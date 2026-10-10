import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.db.models import Product, ProductSource, ProductVersion, UserAccount
from calorie_app.modules.diary.models import DiaryDay, Meal, ProductDraft, Weight
from calorie_app.modules.diary.repository import day_for_date, owned
from calorie_app.modules.diary.service import (
    day_is_complete,
    delete_entity,
    meal_payload,
    remove_meal_item,
    save_diary_day,
    save_meal,
    save_product_draft,
    save_weight,
)
from calorie_app.modules.identity.service import begin_deleting
from calorie_app.modules.profiles.schemas import GoalPayload
from calorie_app.modules.profiles.service import create_goal

pytestmark = pytest.mark.integration
EXAMPLES = Path(__file__).resolve().parents[3] / "contracts/examples/valid"


def example(name):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


@pytest.fixture
def owners(database):
    engine, _, _ = database
    ids = (uuid4(), uuid4())
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                UserAccount(id=value, issuer="https://diary.test", subject=str(value))
                for value in ids
            ]
        )
    try:
        yield (engine, *ids)
    finally:
        # Dedicated *_test database only; fixture bypasses immutable audit
        # DELETE guards to allow the later E1/E2 migration regression probes.
        with engine.begin() as connection:
            connection.exec_driver_sql("TRUNCATE app.user_accounts CASCADE")


def make_meal(engine, owner):
    entity = uuid4()
    with Session(engine) as session, session.begin():
        save_meal(session, owner, entity, example("meal"))
    return entity


@pytest.mark.parametrize(
    "table", ["diary_days", "meals", "meal_items", "weights", "product_drafts"]
)
def test_raw_runtime_mutation_cannot_bypass_deleting(owners, table):
    engine, owner, _ = owners
    make_meal(engine, owner)
    with Session(engine) as session, session.begin():
        save_weight(session, owner, uuid4(), example("weight"))
        save_product_draft(session, owner, uuid4(), example("product-draft"))
        begin_deleting(session, owner)
    mutation = "quantity_amount=quantity_amount" if table == "meal_items" else "revision=revision+1"
    with pytest.raises(IntegrityError, match="active account"), engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_api")
        connection.execute(
            text(f"UPDATE app.{table} SET {mutation} WHERE owner_id=:owner"), {"owner": owner}
        )


def test_owner_reads_writes_and_last_item_tombstone(owners):
    engine, a, b = owners
    entity = make_meal(engine, a)
    with Session(engine) as session, session.begin():
        assert owned(session, Meal, b, entity) is None
        with pytest.raises(DomainError) as error:
            remove_meal_item(
                session, b, entity, UUID(example("meal")["items"][0]["item_id"]), base_revision=1
            )
        assert error.value.code == "not_found"
        row = remove_meal_item(
            session, a, entity, UUID(example("meal")["items"][0]["item_id"]), base_revision=1
        )
        assert row.deleted_at is not None and row.revision == 2
        assert meal_payload(session, row)["items"] == example("meal")["items"]
    with Session(engine) as session, session.begin():
        with pytest.raises(DomainError) as error:
            save_meal(session, a, entity, example("meal"), base_revision=2)
        assert error.value.code == "version_conflict"


def test_foreign_goal_app_and_db_composite_constraint(owners):
    engine, a, b = owners
    goal = uuid4()
    with Session(engine) as session, session.begin():
        create_goal(session, b, goal, GoalPayload.model_validate(example("goal")))
    with Session(engine) as session, session.begin():
        with pytest.raises(DomainError):
            save_meal(session, a, uuid4(), example("meal") | {"goal_id": str(goal)})
        session.rollback()
    meal = make_meal(engine, a)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("UPDATE app.meals SET goal_id=:goal WHERE id=:id"), {"goal": goal, "id": meal}
        )


def test_item_foreign_meal_raw_sql_rejected(owners):
    engine, a, b = owners
    meal = make_meal(engine, a)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("UPDATE app.meal_items SET owner_id=:owner WHERE meal_id=:meal"),
            {"owner": b, "meal": meal},
        )


def test_day_unique_and_immutable_zone_at_domain_and_db(owners):
    engine, a, _ = owners
    meal = make_meal(engine, a)
    with Session(engine) as session, session.begin():
        day = day_for_date(session, a, date(2026, 10, 9))
        day_id = day.id
        with pytest.raises(DomainError):
            save_diary_day(session, a, uuid4(), example("diary-day"))
        with pytest.raises(DomainError):
            save_diary_day(
                session, a, day.id, example("diary-day") | {"time_zone": "UTC"}, base_revision=1
            )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(DiaryDay).values(
                id=uuid4(),
                owner_id=a,
                revision=1,
                local_date=date(2026, 10, 9),
                time_zone="UTC",
                declared_complete=False,
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("UPDATE app.diary_days SET time_zone='UTC' WHERE id=:id"), {"id": day_id}
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE app.meals SET time_zone='UTC' WHERE id=:id"), {"id": meal})


def test_diary_completeness_recomputed_after_meal_mutation(owners):
    engine, a, _ = owners
    meal_id = make_meal(engine, a)
    with Session(engine) as session, session.begin():
        day = day_for_date(session, a, date(2026, 10, 9))
        save_diary_day(session, a, day.id, example("diary-day"), base_revision=1)
        assert day_is_complete(session, a, day.id)
        payload = example("meal")
        payload["items"][0]["nutrition_per_100"]["energy_kcal"] = None
        save_meal(session, a, meal_id, payload, base_revision=1)
        assert not day_is_complete(session, a, day.id)
        payload["items"][0]["nutrition_per_100"]["energy_kcal"] = "0"
        save_meal(session, a, meal_id, payload, base_revision=2)
        assert not day_is_complete(session, a, day.id)
        payload["items"][0]["nutrition_per_100"]["energy_kcal"] = "0.000001"
        save_meal(session, a, meal_id, payload, base_revision=3)
        assert day_is_complete(session, a, day.id)
        delete_entity(session, Meal, a, meal_id, base_revision=4)
        assert not day_is_complete(session, a, day.id)


@pytest.mark.parametrize(
    "value", ["NaN", "Infinity", "-Infinity", "-0.000001", "0", "1000.000001", "1000000"]
)
def test_weight_raw_sql_numeric_bounds(owners, value):
    engine, a, _ = owners
    with pytest.raises((IntegrityError, DataError)), engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO app.weights
            (id,owner_id,revision,weight_kg,occurred_at,local_date,time_zone)
            VALUES (:id,:owner,1,CAST(:weight AS numeric),'2026-10-09T06:00:00Z',
                    '2026-10-09','Europe/Warsaw')"""),
            {"id": uuid4(), "owner": a, "weight": value},
        )


@pytest.mark.parametrize(
    "field", ["energy_kcal", "protein_g", "fat_g", "carbs_g", "quantity_amount", "density_g_per_ml"]
)
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "-0.000001", "1000000"])
def test_item_raw_sql_numeric_bounds(owners, field, value):
    engine, a, _ = owners
    meal = make_meal(engine, a)
    with pytest.raises((IntegrityError, DataError)), engine.begin() as connection:
        # Field names come from fixed parameters, never user data.
        connection.execute(
            text(f"UPDATE app.meal_items SET {field}=CAST(:value AS numeric) WHERE meal_id=:meal"),
            {"value": value, "meal": meal},
        )


def test_dst_weights_exact_multiple_same_date_and_rollback(owners):
    engine, a, b = owners
    ids = (uuid4(), uuid4())
    with Session(engine) as session, session.begin():
        for entity, name in zip(ids, ("weight-dst-first", "weight-dst-second"), strict=True):
            row = save_weight(session, a, entity, example(name) | {"weight_kg": "70.123456"})
            assert row.weight_kg == Decimal("70.123456")
            assert owned(session, Weight, b, entity) is None
    with Session(engine) as session:
        values = list(session.scalars(select(Weight).where(Weight.owner_id == a)))
        assert len(values) == 2 and values[0].local_date == values[1].local_date
        rolled_back = uuid4()
        save_weight(session, a, rolled_back, example("weight"))
        session.rollback()
        assert owned(session, Weight, a, rolled_back) is None


def test_raw_sql_bad_local_date_and_zone_rejected(owners):
    engine, a, _ = owners
    for column, value in (("local_date", "2026-10-08"), ("time_zone", "Invented/Zone")):
        entity = uuid4()
        with Session(engine) as session, session.begin():
            save_weight(session, a, entity, example("weight"))
        with pytest.raises((IntegrityError, DataError)), engine.begin() as connection:
            connection.execute(
                text(f"UPDATE app.weights SET {column}=:value WHERE id=:id"),
                {"value": value, "id": entity},
            )


def test_empty_live_meal_and_final_item_sql_delete_rejected(owners):
    engine, a, _ = owners
    meal = make_meal(engine, a)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM app.meal_items WHERE meal_id=:id"), {"id": meal})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO app.meals
            (id,owner_id,revision,title,occurred_at,time_zone,local_date)
            VALUES (:id,:owner,1,'empty','2026-10-09T06:00:00Z','Europe/Warsaw','2026-10-09')"""),
            {"id": uuid4(), "owner": a},
        )


def test_catalog_revisions_do_not_change_historical_snapshot(owners):
    engine, a, _ = owners
    source, product, meal = uuid4(), uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add_all([Product(id=product), ProductSource(id=source, description="test label")])
        session.flush()
        session.add(
            ProductVersion(
                product_id=product,
                revision=1,
                source_id=source,
                name="original",
                basis_unit="g",
                energy_kcal=Decimal("87"),
            )
        )
        session.flush()
        payload = example("meal")
        payload["items"][0]["product"] = {"product_id": str(product), "revision": 1}
        payload["items"][0]["nutrition_origin"] = "catalog_snapshot"
        save_meal(session, a, meal, payload)
    with Session(engine) as session, session.begin():
        session.add(
            ProductVersion(
                product_id=product,
                revision=2,
                source_id=source,
                name="new label",
                basis_unit="g",
                energy_kcal=Decimal("900"),
            )
        )
    with Session(engine) as session:
        assert meal_payload(session, owned(session, Meal, a, meal)) == payload


@pytest.mark.parametrize(
    "mutation",
    [
        {
            "nutrition_per_100": {
                "energy_kcal": "NaN",
                "protein_g": None,
                "fat_g": None,
                "carbs_g": None,
            }
        },
        {"density_g_per_ml": "1"},
        {"basis_unit": None},
        {"product_id": str(uuid4())},
        {"package_quantity": {"amount": "1", "unit": "ml"}},
    ],
)
def test_draft_strict_schema_also_enforced_on_raw_sql(owners, mutation):
    engine, a, _ = owners
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(ProductDraft).values(
                id=uuid4(), owner_id=a, revision=1, payload=example("product-draft") | mutation
            )
        )


def test_draft_owner_tombstone_and_revision_limit(owners):
    engine, a, b = owners
    entity = uuid4()
    with Session(engine) as session, session.begin():
        save_product_draft(session, a, entity, example("product-draft"))
        assert owned(session, ProductDraft, b, entity) is None
        delete_entity(session, ProductDraft, a, entity, base_revision=1)
        with pytest.raises(DomainError):
            save_product_draft(session, a, entity, example("product-draft"), base_revision=2)
    with pytest.raises((IntegrityError, DataError)), engine.begin() as connection:
        connection.execute(
            text("UPDATE app.product_drafts SET revision=2147483648 WHERE id=:id"), {"id": entity}
        )


def test_exact_owner_goal_ref_and_item_key_constraints(owners):
    engine, a, _ = owners
    goal, meal = uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        create_goal(session, a, goal, GoalPayload.model_validate(example("goal")))
        save_meal(session, a, meal, example("meal") | {"goal_id": str(goal)})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO app.meal_items SELECT * FROM app.meal_items
                                  WHERE meal_id=:id"""),
            {"id": meal},
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("UPDATE app.meal_items SET product_revision=1 WHERE meal_id=:id"), {"id": meal}
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE app.meals SET revision=0 WHERE id=:id"), {"id": meal})


def test_deleting_generation_blocks_domain_mutations(owners):
    engine, a, _ = owners
    with Session(engine) as session, session.begin():
        begin_deleting(session, a)
    for save, payload in (
        (save_meal, "meal"),
        (save_weight, "weight"),
        (save_product_draft, "product-draft"),
        (save_diary_day, "diary-day"),
    ):
        with Session(engine) as session, session.begin():
            with pytest.raises(DomainError) as error:
                save(session, a, uuid4(), example(payload), expected_generation=1)
            assert error.value.code == "account_deleting"


@pytest.mark.parametrize("role", ["calorie_app_api", "calorie_app_worker"])
def test_runtime_private_grants_no_ddl_or_operator_extras(owners, role):
    engine, a, _ = owners
    with engine.begin() as connection:
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        with Session(bind=connection) as session:
            save_weight(session, a, uuid4(), example("weight"))
    with pytest.raises(ProgrammingError), engine.begin() as connection:
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        connection.exec_driver_sql("CREATE TABLE app.forbidden_diary_test(id integer)")
