"""E8 frozen upgrade, restartable history and atomic downgrade on real PG17."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


@pytest.fixture
def e8_empty(database):
    engine, migrate, _ = database
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
    yield database
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
    migrate("upgrade", "head")


@pytest.fixture
def historical_e8_empty(historical_database):
    yield from e8_empty.__wrapped__(historical_database)


def graph(engine, names=None):
    with engine.connect() as connection:
        names = names or [
            name
            for name in inspect(connection).get_table_names(schema="app")
            if name != "alembic_version"
        ]
        return {
            name: list(
                connection.scalars(
                    text(
                        'SELECT to_jsonb(t)::text FROM app."'
                        + name
                        + '" t ORDER BY to_jsonb(t)::text'
                    )
                )
            )
            for name in names
        }


def seed_owner(connection):
    owner = uuid4()
    connection.execute(
        text(
            "INSERT INTO app.user_accounts(id,issuer,subject) VALUES(:owner,'https://e8.example.test',:subject)"
        ),
        {"owner": owner, "subject": str(uuid4())},
    )
    connection.execute(
        text("INSERT INTO app.sync_counters(owner_id) VALUES(:owner)"), {"owner": owner}
    )
    connection.execute(
        text("INSERT INTO app.user_consents(owner_id) VALUES(:owner)"), {"owner": owner}
    )
    connection.execute(
        text("INSERT INTO app.goal_timelines(owner_id) VALUES(:owner)"), {"owner": owner}
    )
    return owner


def test_e8_empty_roundtrip_preserves_complete_e0_e7_rowsets(historical_e8_empty):
    engine, migrate, _ = historical_e8_empty
    migrate("downgrade", "0015_e7_ai")
    before = graph(engine)
    migrate("upgrade", "head")
    assert graph(engine, list(before)) == before
    migrate("downgrade", "0015_e7_ai")
    assert graph(engine) == before
    migrate("upgrade", "head")
    assert graph(engine, list(before)) == before


def test_filled_upgrade_pending_and_bounded_restart_preserves_sources(historical_e8_empty):
    engine, migrate, _ = historical_e8_empty
    migrate("downgrade", "0015_e7_ai")
    with engine.begin() as connection:
        owner = seed_owner(connection)
        for offset in range(14):
            day = date(2020, 1, 1) + timedelta(days=offset)
            connection.execute(
                text(
                    "INSERT INTO app.weights "
                    "(id,owner_id,revision,weight_kg,occurred_at,local_date,time_zone) "
                    "VALUES(:id,:owner,1,75,:occurred,:day,'UTC')"
                ),
                {
                    "id": uuid4(),
                    "owner": owner,
                    "day": day,
                    "occurred": day.isoformat() + "T12:00:00Z",
                },
            )
    before = graph(engine)
    migrate("upgrade", "head")
    assert graph(engine, list(before)) == before
    with engine.begin() as connection:
        state = connection.execute(
            text(
                "SELECT backfill_state,total_points,backfill_after "
                "FROM app.motivation_accounts WHERE owner_id=:owner"
            ),
            {"owner": owner},
        ).one()
        assert tuple(state) == ("pending", 0, None)
        first = connection.scalar(text("SELECT app.e8_process(:owner,4)"), {"owner": owner})
        assert first == {"processed": 4, "backfill_state": "pending", "total_points": 0}
    # Resume in fresh transactions, as after worker/process restart.
    for expected in ("pending", "pending", "ready"):
        with engine.begin() as connection:
            result = connection.scalar(text("SELECT app.e8_process(:owner,4)"), {"owner": owner})
            assert result["backfill_state"] == expected
    with engine.begin() as connection:
        revision = connection.scalar(
            text("SELECT revision FROM app.motivation_accounts WHERE owner_id=:owner"),
            {"owner": owner},
        )
        result = connection.scalar(text("SELECT app.e8_process(:owner,4)"), {"owner": owner})
        assert result == {"processed": 0, "backfill_state": "ready", "total_points": 0}
        assert (
            connection.scalar(
                text("SELECT revision FROM app.motivation_accounts WHERE owner_id=:owner"),
                {"owner": owner},
            )
            == revision
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.diary_days WHERE owner_id=:owner"), {"owner": owner}
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT active_badges FROM app.motivation_accounts WHERE owner_id=:owner"),
                {"owner": owner},
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.motivation_days WHERE owner_id=:owner"),
                {"owner": owner},
            )
            == 14
        )
    assert graph(engine, list(before)) == before


@pytest.mark.parametrize("artifact", ["projection", "affirmation", "session"])
def test_nonempty_e8_downgrade_refuses_atomically_before_ddl(historical_e8_empty, artifact):
    engine, migrate, _ = historical_e8_empty
    with engine.begin() as connection:
        owner = seed_owner(connection)
        if artifact == "projection":
            connection.execute(
                text("SELECT app.e8_refresh(:owner,ARRAY[]::date[],256)"), {"owner": owner}
            )
        elif artifact == "affirmation":
            connection.execute(
                text(
                    "INSERT INTO app.ranking_affirmations SELECT :owner,sync_epoch,1 "
                    "FROM app.installation_state WHERE id=1"
                ),
                {"owner": owner},
            )
        else:
            connection.execute(
                text(
                    "INSERT INTO app.ranking_sessions "
                    "SELECT :id,:owner,1,sync_epoch,10,'ranking_v1',"
                    "TIMESTAMPTZ '2026-01-01T00:10:00Z',TIMESTAMPTZ '2026-01-01T00:00:00Z' "
                    "FROM app.installation_state WHERE id=1"
                ),
                {"id": uuid4(), "owner": owner},
            )
    before = graph(engine)
    with pytest.raises(DBAPIError) as error:
        migrate("downgrade", "0015_e7_ai")
    assert error.value.orig.sqlstate == "23514"
    assert graph(engine) == before


@pytest.mark.parametrize(
    "target",
    [
        "SELECT(energy_kcal) ON app.meal_items",
        "UPDATE(revision) ON app.weights",
        "MAINTAIN ON app.diary_days",
        "EXECUTE ON FUNCTION app.begin_account_deletion(uuid,uuid,integer)",
    ],
)
@pytest.mark.parametrize("grantee", ["PUBLIC", "calorie_app_motivation_worker"])
def test_hostile_effective_e8_acl_refuses_upgrade_atomically(historical_e8_empty, target, grantee):
    engine, migrate, _ = historical_e8_empty
    migrate("downgrade", "0015_e7_ai")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("GRANT " + target + " TO " + grantee)
        before = graph(engine)
        with pytest.raises(DBAPIError) as error:
            migrate("upgrade", "head")
        assert error.value.orig.sqlstate == "23514"
        assert graph(engine) == before
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM app.alembic_version"))
                == "0015_e7_ai"
            )
            assert "motivation_accounts" not in inspect(connection).get_table_names(schema="app")
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("REVOKE " + target + " FROM " + grantee)
        migrate("upgrade", "head")


@pytest.mark.parametrize("member", ["calorie_app_ai_worker", "calorie_app_api"])
def test_shared_runtime_membership_cannot_acquire_e8_worker_authority(historical_e8_empty, member):
    engine, migrate, _ = historical_e8_empty
    migrate("downgrade", "0015_e7_ai")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("GRANT calorie_app_motivation_worker TO " + member)
        before = graph(engine)
        with pytest.raises(DBAPIError) as error:
            migrate("upgrade", "head")
        assert error.value.orig.sqlstate == "23514"
        assert graph(engine) == before
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("REVOKE calorie_app_motivation_worker FROM " + member)
        migrate("upgrade", "head")


@pytest.mark.parametrize(
    "amount,energy,density,expected",
    [
        ("1234.123456", "9876.123456", None, "121883.55611401383936"),
        ("9999.999998", "0.000001", "0.000003", "33.33333332666666666667"),
    ],
)
def test_frozen_source_facts_preserve_exact_nutrition_scale(
    e8_empty, amount, energy, density, expected
):
    # Independent Decimal literals include fractional places beyond PostgreSQL's
    # automatic division scale. Only reverse-density conversion rounds at12.
    from decimal import Decimal

    engine, _, _ = e8_empty
    with engine.begin() as connection:
        owner = seed_owner(connection)
        meal = uuid4()
        connection.execute(
            text(
                "INSERT INTO app.diary_days "
                "(id,owner_id,revision,local_date,time_zone,declared_complete) "
                "VALUES(:id,:owner,1,DATE '2020-01-01','UTC',true)"
            ),
            {"id": uuid4(), "owner": owner},
        )
        connection.execute(
            text(
                "INSERT INTO app.meals "
                "(id,owner_id,revision,title,occurred_at,local_date,time_zone) "
                "VALUES(:id,:owner,1,'oracle',TIMESTAMPTZ '2020-01-01T12:00:00Z',"
                "DATE '2020-01-01','UTC')"
            ),
            {"id": meal, "owner": owner},
        )
        connection.execute(
            text(
                "INSERT INTO app.meal_items(owner_id,meal_id,item_id,position,name,"
                "quantity_amount,quantity_unit,basis_unit,energy_kcal,density_g_per_ml,"
                "density_source,nutrition_origin,formula_version) "
                "VALUES(:owner,:meal,:item,1,'oracle',:amount,'g',:basis,:energy,:density,"
                ":source,'manual','nutrition_v1')"
            ),
            {
                "owner": owner,
                "meal": meal,
                "item": uuid4(),
                "amount": amount,
                "basis": "ml" if density else "g",
                "energy": energy,
                "density": density,
                "source": "oracle" if density else None,
            },
        )
        row = connection.execute(
            text("SELECT * FROM app.e8_day_facts(:owner,ARRAY[DATE '2020-01-01'])"),
            {"owner": owner},
        ).one()
        assert row.energy_sum == Decimal(expected)
        assert row.energy_complete and row.effective_complete
        assert row.in_goal is None
