"""Author acceptance: accepted goal branches and source axes beyond 10,000 rows."""

from datetime import date, timedelta
from time import monotonic
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_e4_push import operation, send
from test_e4_push import synced as synced_fixture
from test_e5_statistics import example
from test_e8_source_pg import complete_meal, matured, project

from calorie_app.modules.diary.repository import day_for_date

pytestmark = pytest.mark.integration
synced = synced_fixture


@pytest.fixture(autouse=True)
def isolate_accounts(database):
    with database[0].begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
    yield
    with database[0].begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))


def accepted_goal(synced, base, *, day="2000-01-01", energy="100", correction=None):
    payload = example("goal") | {
        "effective_from": day,
        "decided_at": day + "T00:00:00Z",
        "time_zone": "UTC",
        "energy_kcal": energy,
        "timeline_base_revision": base,
        "reason": "history_correction" if correction else "user_decision",
        "correction_of": str(correction) if correction else None,
    }
    op = operation(synced[4], "goal", payload=payload)
    result = send(synced, [op])[0]
    assert result["status"] == "accepted", result
    return op


def facts(engine, owner, days):
    with engine.connect() as connection:
        return {
            row["local_date"]: dict(row)
            for row in connection.execute(
                text("SELECT * FROM app.e8_day_facts(:owner,CAST(:dates AS date[]))"),
                {"owner": owner, "dates": days},
            ).mappings()
        }


def complete_meal_with_reference(synced, day, energy, reference):
    engine, _, _, owner, boot, *_ = synced
    payload = example("meal") | {
        "local_date": day,
        "occurred_at": day + "T12:00:00Z",
        "time_zone": "UTC",
        "ration": None,
    }
    item = payload["items"][0]
    item.update(product=None, basis_unit="g", density_g_per_ml=None, density_source=None)
    item["quantity"] = {"amount": "100", "unit": "g"}
    item["nutrition_per_100"].update(energy_kcal=energy, protein_g=None, fat_g=None, carbs_g=None)
    op = operation(boot, "meal", payload=payload)
    # operation() deliberately strips examples' dependencies; set this explicit
    # accepted historical reference afterwards to prove it does not select goal.
    op["payload"]["goal_id"] = reference
    assert send(synced, [op])[0]["status"] == "accepted"
    with Session(engine) as session:
        row = day_for_date(session, owner, date.fromisoformat(day))
        day_id, revision = row.id, row.revision
    declared = operation(
        boot,
        "diary_day",
        entity_id=day_id,
        base=revision,
        payload={"local_date": day, "time_zone": "UTC", "declared_complete": True},
    )
    assert send(synced, [declared])[0]["status"] == "accepted"
    return op


def test_accepted_branched_moved_goal_correction_never_revives_old_head(synced):
    engine, _, _, owner, *_ = synced
    root = accepted_goal(synced, 0)
    first = complete_meal_with_reference(synced, "2000-01-01", "90", root["entity_id"])
    second = complete_meal_with_reference(synced, "2000-01-02", "110", root["entity_id"])
    matured(engine, owner)
    assert project(engine, owner)["total_points"] == 4
    left = accepted_goal(synced, 1, day="2000-01-03", energy="200", correction=root["entity_id"])
    right = accepted_goal(synced, 2, day="2000-01-04", energy="300", correction=root["entity_id"])
    head = accepted_goal(synced, 3, day="2000-01-02", energy="400", correction=left["entity_id"])
    dates = [date(2000, 1, 1) + timedelta(days=i) for i in range(4)]
    actual = facts(engine, owner, dates)
    assert actual[dates[0]]["goal_id"] is None
    assert all(actual[day]["goal_id"] == UUID(head["entity_id"]) for day in dates[1:])
    assert project(engine, owner)["total_points"] == 2
    # Move latest surviving descendant past both source dates. Neither root,
    # left, nor the other branch becomes the selected fallback again.
    moved = accepted_goal(synced, 4, day="2000-01-05", energy="100", correction=head["entity_id"])
    actual = facts(engine, owner, dates + [date(2000, 1, 5)])
    assert all(actual[day]["goal_id"] is None for day in dates)
    assert actual[date(2000, 1, 5)]["goal_id"] == UUID(moved["entity_id"])
    assert project(engine, owner)["total_points"] == 2
    with engine.connect() as connection:
        references = list(
            connection.execute(
                text("SELECT id,goal_id FROM app.meals WHERE owner_id=:owner ORDER BY local_date"),
                {"owner": owner},
            )
        )
        assert references == [
            (UUID(first["entity_id"]), UUID(root["entity_id"])),
            (UUID(second["entity_id"]), UUID(root["entity_id"])),
        ]
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.e8_goal_heads(:owner)"), {"owner": owner}
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.goal_versions WHERE owner_id=:owner AND id=:right"),
                {"owner": owner, "right": UUID(right["entity_id"])},
            )
            == 1
        )
    assert send(synced, [moved])[0]["status"] == "already_applied"
    assert project(engine, owner)["total_points"] == 2


@pytest.mark.parametrize(
    "energy,expected", [("1800", 2), ("2200", 2), ("1799.999999", 1), ("2200.000001", 1)]
)
def test_accepted_decimal_goal_band_inclusive_without_macro_requirement(synced, energy, expected):
    engine, _, _, owner, *_ = synced
    goal = accepted_goal(synced, 0, day="2020-01-01", energy="2000")
    source = complete_meal_with_reference(synced, "2020-01-01", energy, goal["entity_id"])
    matured(engine, owner)
    day = facts(engine, owner, [date(2020, 1, 1)])[date(2020, 1, 1)]
    assert day["effective_complete"]
    assert day["in_goal"] is (expected == 2)
    assert project(engine, owner)["total_points"] == expected
    before = project(engine, owner)
    assert send(synced, [source])[0]["status"] == "already_applied"
    after = project(engine, owner)
    assert (after["total_points"], after["revision"]) == (
        before["total_points"],
        before["revision"],
    )


def seed_goal_axis(engine, owner, count):
    """Known-valid large source fixture; no E8 projection is supplied by tests.

    Three legacy per-row guards otherwise repeatedly enumerate IANA zones and
    scan the entire prefix/axis. Bypass only those guards during this one seed,
    validate their UTC/payload/contiguous-axis preconditions once in SQL, and
    reenable them before the new decision traverses the normal sync path.
    Owner/account, immutability, FK, unique, numeric and all E8 checks stay on.
    """
    with engine.begin() as connection:
        for guard in ("private_time_zone", "goal_axis_insert", "goal_axis_complete"):
            connection.exec_driver_sql("ALTER TABLE app.goal_versions DISABLE TRIGGER " + guard)
        connection.exec_driver_sql(
            "ALTER TABLE app.goal_timelines DISABLE TRIGGER goal_axis_complete"
        )
        connection.execute(
            text("INSERT INTO app.goal_timelines(owner_id,revision) VALUES(:owner,:count)"),
            {"owner": owner, "count": count},
        )
        connection.execute(
            text("""
            INSERT INTO app.goal_versions(
              id,owner_id,revision,timeline_revision,timeline_base_revision,
              effective_from,decided_at,time_zone,goal_type,energy_kcal,activity_class,reason,payload)
            SELECT md5(:owner_text||':'||i::text)::uuid,:owner,1,i,i-1,DATE '2000-01-01',
              TIMESTAMPTZ '2000-01-01T00:00:00Z','UTC','maintain',100,'line','user_decision',
              jsonb_build_object('effective_from','2000-01-01','decided_at','2000-01-01T00:00:00Z',
                'time_zone','UTC','goal_type','maintain','energy_kcal','100','protein_g',NULL,
                'fat_g',NULL,'carbs_g',NULL,'activity_class','line','estimate',NULL,
                'timeline_base_revision',i-1,'reason','user_decision','correction_of',NULL)
            FROM generate_series(1,:count) i
        """),
            {"owner": owner, "owner_text": str(owner), "count": count},
        )
        validated = connection.execute(
            text("""
            SELECT count(*),min(timeline_revision),max(timeline_revision),
              bool_and(revision=1 AND timeline_base_revision=timeline_revision-1 AND time_zone='UTC'
                AND effective_from=DATE '2000-01-01'
                AND decided_at=TIMESTAMPTZ '2000-01-01T00:00:00Z'
                AND correction_of IS NULL AND reason='user_decision' AND energy_kcal=100
                AND payload=jsonb_build_object('effective_from','2000-01-01',
                  'decided_at','2000-01-01T00:00:00Z','time_zone','UTC','goal_type','maintain',
                  'energy_kcal','100','protein_g',NULL,'fat_g',NULL,'carbs_g',NULL,
                  'activity_class','line','estimate',NULL,'timeline_base_revision',timeline_revision-1,
                  'reason','user_decision','correction_of',NULL))
            FROM app.goal_versions WHERE owner_id=:owner
        """),
            {"owner": owner},
        ).one()
        assert validated == (count, 1, count, True)
        assert (
            connection.scalar(
                text("SELECT revision FROM app.goal_timelines WHERE owner_id=:owner"),
                {"owner": owner},
            )
            == count
        )
        for guard in ("private_time_zone", "goal_axis_insert", "goal_axis_complete"):
            connection.exec_driver_sql("ALTER TABLE app.goal_versions ENABLE TRIGGER " + guard)
        connection.exec_driver_sql(
            "ALTER TABLE app.goal_timelines ENABLE TRIGGER goal_axis_complete"
        )


def test_new_accepted_goal_over_10001_source_versions_has_no_python_cap(synced, record_property):
    engine, _, _, owner, *_ = synced
    count = 10001
    started = monotonic()
    seed_goal_axis(engine, owner, count)
    meal = complete_meal(synced, "2001-01-01", energy="90")
    matured(engine, owner)
    assert project(engine, owner)["total_points"] == 2
    new = accepted_goal(synced, count, energy="200")
    assert project(engine, owner)["total_points"] == 1
    actual = facts(engine, owner, [date(2001, 1, 1)])[date(2001, 1, 1)]
    assert actual["goal_id"] == UUID(new["entity_id"])
    assert actual["in_goal"] is False and actual["effective_complete"] is True
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.goal_versions WHERE owner_id=:owner"),
                {"owner": owner},
            )
            == count + 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.e8_goal_heads(:owner)"), {"owner": owner}
            )
            == count + 1
        )
        assert (
            connection.scalar(
                text("SELECT revision FROM app.goal_timelines WHERE owner_id=:owner"),
                {"owner": owner},
            )
            == count + 1
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM app.sync_receipts WHERE owner_id=:owner "
                    "AND operation_id=:operation AND status='accepted'"
                ),
                {"owner": owner, "operation": UUID(new["operation_id"])},
            )
            == 1
        )
        source = connection.execute(
            text(
                "SELECT revision,local_date,goal_id FROM app.meals "
                "WHERE owner_id=:owner AND id=:meal"
            ),
            {"owner": owner, "meal": UUID(meal["entity_id"])},
        ).one()
        assert source == (1, date(2001, 1, 1), None)
    snapshot = project(engine, owner)
    assert send(synced, [new])[0]["status"] == "already_applied"
    assert project(engine, owner)["revision"] == snapshot["revision"]
    record_property("source_goal_versions", count + 1)
    record_property("surviving_heads", count + 1)
    record_property("accepted_goal_timeline_revision", count + 1)
    record_property("goal_history_seconds", round(monotonic() - started, 3))
