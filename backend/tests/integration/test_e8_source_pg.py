"""Accepted-source atomicity and all-history motivation on PostgreSQL17."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_e4_push import operation, send
from test_e4_push import synced as synced_fixture
from test_e5_statistics import example

from calorie_app.modules.analytics.motivation import service
from calorie_app.modules.analytics.motivation.rules import evaluate_day
from calorie_app.modules.analytics.motivation.time import day_matures_at
from calorie_app.modules.diary.repository import day_for_date
from calorie_app.modules.diary.service import save_diary_day, save_meal

pytestmark = pytest.mark.integration
synced = synced_fixture


@pytest.fixture(autouse=True)
def isolate_e8_accounts(database):
    with database[0].begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
    yield
    with database[0].begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))


def matured(engine, owner):
    with Session(engine) as session, session.begin():
        return session.scalar(text("SELECT app.e8_process(:owner,256)"), {"owner": owner})


def complete_meal(synced, day="2024-01-01", energy="100", ration=False):
    engine, _, _, owner, boot, *_ = synced
    payload = example("meal")
    payload.update(
        local_date=day, occurred_at=day + "T12:00:00Z", time_zone="UTC", goal_id=None, ration=None
    )
    item = payload["items"][0]
    item.update(product=None, ration_component_position=1 if ration else None)
    item["quantity"] = {"amount": "100", "unit": "g"}
    item["basis_unit"] = "g"
    item["nutrition_per_100"].update(energy_kcal=energy, protein_g=None, fat_g=None, carbs_g=None)
    if ration:
        payload["ration"] = {"ration_id": str(uuid4()), "revision": 1, "name": "Snapshot"}
    op = operation(boot, "meal", payload=payload)
    if ration:
        op["payload"]["ration"] = {"ration_id": str(uuid4()), "revision": 1, "name": "Snapshot"}
    assert send(synced, [op])[0]["status"] == "accepted"
    with Session(engine) as session:
        day_row = day_for_date(session, owner, date.fromisoformat(day))
        day_id, revision = day_row.id, day_row.revision
    declaration = operation(
        boot,
        "diary_day",
        entity_id=day_id,
        base=revision,
        payload={
            "local_date": day,
            "time_zone": "UTC",
            "declared_complete": True,
        },
    )
    assert send(synced, [declaration])[0]["status"] == "accepted"
    return op


def project(engine, owner):
    with engine.connect() as connection:
        return (
            connection.execute(
                text("SELECT * FROM app.motivation_accounts WHERE owner_id=:owner"),
                {"owner": owner},
            )
            .mappings()
            .one()
        )


def test_source_receipt_replay_and_six_wire_entities_unchanged(synced):
    engine, _, _, owner, *_ = synced
    op = complete_meal(synced)
    matured(engine, owner)
    before = project(engine, owner)
    assert before["total_points"] == 1
    assert send(synced, [op])[0]["status"] == "already_applied"
    after = project(engine, owner)
    assert (after["total_points"], after["revision"], after["source_position"]) == (
        before["total_points"],
        before["revision"],
        before["source_position"],
    )
    with engine.connect() as connection:
        assert set(
            connection.scalars(
                text(
                    "SELECT DISTINCT entity->>'entity_type' FROM app.sync_changes "
                    "WHERE owner_id=:owner"
                ),
                {"owner": owner},
            )
        ) == {"meal", "diary_day"}
        assert (
            connection.scalar(
                text(
                    "SELECT sum(materialized_points) FROM app.motivation_days WHERE owner_id=:owner"
                ),
                {"owner": owner},
            )
            == after["total_points"]
        )


def test_projection_failure_rolls_back_source_append_and_receipt(synced, monkeypatch):
    engine, _, _, owner, boot, *_ = synced
    original = service.source_mutated

    def fail_after_projection(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected projection failure")

    monkeypatch.setattr(service, "source_mutated", fail_after_projection)
    op = operation(boot, "weight")
    with pytest.raises(RuntimeError, match="injected"):
        send(synced, [op])
    with engine.connect() as c:
        for table in (
            "weights",
            "sync_changes",
            "sync_receipts",
            "motivation_accounts",
            "motivation_days",
            "motivation_badges",
        ):
            assert (
                c.scalar(
                    text(f"SELECT count(*) FROM app.{table} WHERE owner_id=:owner"),
                    {"owner": owner},
                )
                == 0
            )
    monkeypatch.setattr(service, "source_mutated", original)
    assert send(synced, [op])[0]["status"] == "accepted"


def test_meal_move_and_remove_last_recalculate_both_dates(synced):
    engine, _, _, owner, boot, *_ = synced
    op = complete_meal(synced)
    matured(engine, owner)
    moved_payload = op["payload"] | {
        "local_date": "2024-01-02",
        "occurred_at": "2024-01-02T12:00:00Z",
    }
    moved = operation(boot, "meal", entity_id=op["entity_id"], base=1, payload=moved_payload)
    assert send(synced, [moved])[0]["status"] == "accepted"
    assert project(engine, owner)["total_points"] == 0
    with engine.connect() as c:
        rows = list(
            c.execute(
                text(
                    "SELECT local_date,candidate_points,materialized_points FROM "
                    "app.motivation_days WHERE owner_id=:owner ORDER BY local_date"
                ),
                {"owner": owner},
            )
        )
        assert rows == [(date(2024, 1, 1), 0, 0), (date(2024, 1, 2), 0, 0)]
    deleted = operation(boot, "meal", entity_id=op["entity_id"], base=2, action="delete")
    assert send(synced, [deleted])[0]["status"] == "accepted"
    assert project(engine, owner)["total_points"] == 0


def test_badges_alternative_witness_revoke_and_same_identity_reactivation(synced):
    engine, _, _, owner, boot, *_ = synced
    meals = []
    for offset in range(21):
        meals.append(
            complete_meal(
                synced, (date(2020, 1, 1) + timedelta(days=offset)).isoformat(), ration=offset < 5
            )
        )
    matured(engine, owner)
    with engine.connect() as c:
        first = c.execute(
            text(
                "SELECT first_awarded_at FROM app.motivation_badges WHERE "
                "owner_id=:owner AND badge_code='complete_streak_10'"
            ),
            {"owner": owner},
        ).scalar_one()
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.motivation_badges WHERE owner_id=:owner AND active"),
                {"owner": owner},
            )
            == 2
        )
    # Remove first witness, leaving eleven consecutive alternatives.
    for op in meals[:10]:
        assert (
            send(
                synced,
                [operation(boot, "meal", entity_id=op["entity_id"], base=1, action="delete")],
            )[0]["status"]
            == "accepted"
        )
    with engine.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT active FROM app.motivation_badges WHERE owner_id=:owner "
                    "AND badge_code='complete_streak_10'"
                ),
                {"owner": owner},
            )
            is True
        )
    bridge = meals[15]
    assert (
        send(
            synced,
            [operation(boot, "meal", entity_id=bridge["entity_id"], base=1, action="delete")],
        )[0]["status"]
        == "accepted"
    )
    with engine.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT active FROM app.motivation_badges WHERE owner_id=:owner "
                    "AND badge_code='complete_streak_10'"
                ),
                {"owner": owner},
            )
            is False
        )
    complete_meal(synced, "2020-01-16")
    with engine.connect() as c:
        assert c.execute(
            text(
                "SELECT first_awarded_at,active FROM app.motivation_badges WHERE "
                "owner_id=:owner AND badge_code='complete_streak_10'"
            ),
            {"owner": owner},
        ).one() == (first, True)
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM app.motivation_badges WHERE owner_id=:owner "
                    "AND badge_code='complete_streak_10'"
                ),
                {"owner": owner},
            )
            == 1
        )


@pytest.mark.parametrize(
    "day,zone,oracle",
    [
        ("2026-03-29", "Europe/Warsaw", "2026-03-29T22:00:00+00:00"),
        ("2026-10-25", "Europe/Warsaw", "2026-10-25T23:00:00+00:00"),
        ("2018-11-03", "America/Sao_Paulo", "2018-11-04T03:00:00+00:00"),
        ("2020-10-31", "America/Havana", "2020-11-01T04:00:00+00:00"),
        ("2011-12-29", "Pacific/Apia", "2011-12-30T10:00:00+00:00"),
        ("1919-03-30", "America/Toronto", "1919-03-31T04:30:00+00:00"),
    ],
)
def test_sql_python_independent_utc_closure_oracles(database, day, zone, oracle):
    engine, _, _ = database
    expected = datetime.fromisoformat(oracle)
    with engine.connect() as c:
        actual = c.scalar(
            text("SELECT app.e8_day_end(CAST(:day AS date),:zone)"), {"day": day, "zone": zone}
        )
    assert actual == expected
    assert day_matures_at(date.fromisoformat(day), zone) == expected


@pytest.mark.parametrize(
    "energy,amount,unit,basis,density",
    [
        ("0.000001", "0.000001", "g", "g", None),
        ("27", "100", "g", "g", None),
        ("100", "0.000001", "g", "ml", "3"),
        ("123.123456", "1.123456", "ml", "g", "0.333333"),
        (None, "100", "g", "g", None),
        ("0", "100", "g", "g", None),
    ],
)
def test_sql_source_nutrition_matches_decimal_oracle(synced, energy, amount, unit, basis, density):
    engine, _, _, owner, *_ = synced
    payload = example("meal")
    payload.update(
        local_date="2024-01-01",
        occurred_at="2024-01-01T12:00:00Z",
        time_zone="UTC",
        goal_id=None,
        ration=None,
    )
    item = payload["items"][0]
    item.update(
        product=None,
        basis_unit=basis,
        density_g_per_ml=density,
        density_source="oracle" if density else None,
    )
    item["quantity"] = {"amount": amount, "unit": unit}
    item["nutrition_per_100"].update(energy_kcal=energy, protein_g=None, fat_g=None, carbs_g=None)
    with Session(engine) as s, s.begin():
        save_meal(s, owner, uuid4(), payload)
        row = day_for_date(s, owner, date(2024, 1, 1))
        save_diary_day(
            s,
            owner,
            row.id,
            {"local_date": "2024-01-01", "time_zone": "UTC", "declared_complete": True},
            base_revision=row.revision,
        )
        facts = (
            s.execute(
                text("SELECT * FROM app.e8_day_facts(:owner,ARRAY[DATE '2024-01-01'])"),
                {"owner": owner},
            )
            .mappings()
            .one()
        )
        expected = evaluate_day(True, [payload], None)
        assert facts["effective_complete"] is expected.effective_complete
        assert facts["in_goal"] is expected.in_goal
        from calorie_app.modules.diary.validation import meal_totals

        assert (
            facts["energy_sum"]
            == Decimal(meal_totals(payload["items"])["energy_kcal"]["known_sum"])
            if energy is not None
            else facts["energy_sum"] is None
        )
