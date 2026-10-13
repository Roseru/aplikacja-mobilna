"""Actual PG17/API LOGIN/worker LOGIN, mock subprocess and independent oracles."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from calorie_app.modules.diary.service import save_diary_day, save_meal, save_weight
from calorie_app.modules.jobs.runner import Runner
from calorie_app.modules.profiles.schemas import EstimateInput, GoalPayload, ProfilePayload
from calorie_app.modules.profiles.service import create_goal, estimate_energy, save_profile
from tests.integration.test_e7_runtime import client
from tests.integration.test_e7_runtime import create as create_photo
from tests.integration.test_e7_runtime import e7 as e7_fixture

e7 = e7_fixture
pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def owner(rt, who=0):
    return UUID(rt["boots"][who]["account_id"])


def sample(name):
    return json.loads((ROOT / "contracts/examples/valid" / (name + ".json")).read_text())


def seed(rt, *, estimate=True, complete=14, kcal="2700", existing_profile=False):
    who = owner(rt)
    with rt["admin"].connect() as c:
        today = c.scalar(text("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date"))
    initial = today - timedelta(days=20)
    with Session(rt["api"]) as s, s.begin():
        if not existing_profile:
            save_profile(
                s,
                who,
                uuid4(),
                ProfilePayload(
                    pseudonym="Synthetic E9",
                    height_cm="180",
                    activity_class="stationary",
                    time_zone="UTC",
                ),
            )
        estimated = estimate_energy(
            EstimateInput(
                age_years=30,
                height_cm="180",
                weight_kg="75",
                equation_variant="plus_5",
                activity_class="stationary",
            ),
            datetime.combine(initial, datetime.min.time(), UTC),
        )
        goal = sample("goal") | {
            "effective_from": initial.isoformat(),
            "decided_at": initial.isoformat() + "T00:00:00Z",
            "time_zone": "UTC",
            "energy_kcal": "2200",
            "timeline_base_revision": 0,
            "reason": "user_decision",
            "correction_of": None,
            "estimate": estimated if estimate else None,
        }
        g = create_goal(s, who, uuid4(), GoalPayload.model_validate(goal))
        for i in range(14):
            d = today - timedelta(days=14 - i)
            meal = sample("meal")
            item = meal["items"][0] | {
                "item_id": str(uuid4()),
                "product": None,
                "quantity": {"amount": "100", "unit": "g"},
                "basis_unit": "g",
                "density_g_per_ml": None,
                "density_source": None,
                "nutrition_per_100": {
                    "energy_kcal": kcal,
                    "protein_g": None,
                    "fat_g": None,
                    "carbs_g": None,
                },
            }
            meal.update(
                local_date=d.isoformat(),
                occurred_at=d.isoformat() + "T12:00:00Z",
                time_zone="UTC",
                goal_id=None,
                ration=None,
                items=[item],
            )
            save_meal(s, who, uuid4(), meal)
            day = s.execute(
                text(
                    "SELECT id,revision FROM app.diary_days WHERE owner_id=:owner AND local_date=:d"
                ),
                {"owner": who, "d": d},
            ).one()
            save_diary_day(
                s,
                who,
                day.id,
                {
                    "local_date": d.isoformat(),
                    "time_zone": "UTC",
                    "declared_complete": i < complete,
                },
                base_revision=day.revision,
            )
            if i in (0, 6, 7, 13):
                save_weight(
                    s,
                    who,
                    uuid4(),
                    {
                        "weight_kg": "80",
                        "occurred_at": d.isoformat() + "T12:00:00Z",
                        "local_date": d.isoformat(),
                        "time_zone": "UTC",
                    },
                )
        return g.id, goal, today


def body(rt):
    with rt["admin"].connect() as c:
        revision = (
            c.scalar(
                text("SELECT revision FROM app.energy_axes WHERE owner_id=:owner"),
                {"owner": owner(rt)},
            )
            or 0
        )
    return {
        "sync_epoch": rt["boots"][0]["sync_epoch"],
        "account_generation": 1,
        "axis_revision": revision,
    }


def notice(provider="mock", automatic=False):
    return {
        "accepted": True,
        "qualified_for_v1": True,
        "notice_version": "energy-aggregates-notice-v1",
        "aggregate_scope": "energy_adjustment_v1_minimal_aggregates",
        "provider": provider,
        "scope": "automatic_energy_adjustment" if automatic else "this_energy_analysis",
    }


def post(rt, path, data, key=None, who=0):
    if path == "analyses" and "notice" not in data:
        data = data | {"notice": notice(rt["settings"].ai_provider)}
    if path == "affirm" and "notice" not in data:
        data = data | {"notice": notice(rt["settings"].ai_provider, True)}
    with client(rt, who) as http:
        return http.post(
            "/api/v1/me/energy/" + path, json=data, headers={"Idempotency-Key": str(key or uuid4())}
        )


def create(rt):
    r = post(rt, "analyses", body(rt))
    assert r.status_code == 200, r.text
    return r.json()


def read(rt, id, who=0):
    with client(rt, who) as http:
        return http.get("/api/v1/me/energy/analyses/" + str(id))


def run(rt, **kw):
    return Runner(rt["worker"], rt["factory"], rt["settings"], **kw).cycle()


def decision(rt, a):
    return body(rt) | {"id": a["id"], "revision": a["revision"]}


def test_full_manual_history_replay_next_day_immutable_goal(e7):
    goal_id, original, today = seed(e7)
    key = uuid4()
    data = body(e7)
    first = post(e7, "analyses", data, key).json()
    assert first["state"] == "queued", first
    assert post(e7, "analyses", data, key).json() == first
    assert run(e7) == 1
    ready = read(e7, first["id"]).json()
    assert ready["state"] == "ready" and ready["result"]["proposed"] == "2700", ready
    accept_key = uuid4()
    accept_data = decision(e7, ready)
    applied = post(e7, "analyses/accept", accept_data, accept_key)
    assert applied.status_code == 200, applied.text
    entity = applied.json()
    assert entity["payload"]["maintenance_kcal"] == "2700"
    assert entity["payload"]["effective_from"] == (today + timedelta(days=1)).isoformat()
    assert post(e7, "analyses/accept", accept_data, accept_key).json() == entity
    conflict = post(
        e7, "analyses/accept", accept_data | {"revision": ready["revision"] + 1}, accept_key
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_key_reused"
    with e7["admin"].connect() as c:
        assert (
            c.scalar(text("SELECT payload FROM app.goal_versions WHERE id=:id"), {"id": goal_id})
            == original
        )
        assert (
            c.scalar(
                text("SELECT (app.e9_resolve(:owner,:today)).maintenance_kcal"),
                {"owner": owner(e7), "today": today},
            )
            == 2595
        )
        assert (
            c.scalar(
                text("SELECT (app.e9_resolve(:owner,:day)).maintenance_kcal"),
                {"owner": owner(e7), "day": today + timedelta(days=1)},
            )
            == 2700
        )
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.energy_versions WHERE owner_id=:owner"),
                {"owner": owner(e7)},
            )
            == 2
        )
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 2


@pytest.mark.parametrize(
    "complete,state",
    [
        (0, "insufficient_data"),
        (9, "insufficient_data"),
        (10, "manual_review_required"),
        (13, "manual_review_required"),
    ],
)
def test_insufficient_minimum_no_model_and_description(e7, complete, state):
    seed(e7, complete=complete)
    created = create(e7)
    if complete < 10:
        assert created["id"] is None and created["state"] == state
        assert run(e7) == 0
    else:
        run(e7)
        result = read(e7, created["id"]).json()
        assert result["state"] == state and result["result"]["proposed"] is None
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == (0 if complete < 10 else 2)
        assert c.scalar(text("SELECT count(*) FROM app.energy_versions")) == 1


def test_manual_goal_without_estimate_never_bootstraps_energy(e7):
    seed(e7, estimate=False)
    result = create(e7)
    assert result["state"] == "energy_history_unavailable"
    assert run(e7) == 0
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.energy_versions")) == 0


def test_private_ids_do_not_reveal_analysis_to_other_owner(e7):
    seed(e7)
    a = create(e7)
    assert read(e7, a["id"], 1).status_code == 404
    with Session(e7["api"]) as s, s.begin():
        save_profile(
            s,
            owner(e7, 1),
            uuid4(),
            ProfilePayload(pseudonym="B", height_cm=None, activity_class="line", time_zone="UTC"),
        )
    b = e7["boots"][1]
    data = {
        "sync_epoch": b["sync_epoch"],
        "account_generation": 1,
        "axis_revision": 0,
        "id": a["id"],
        "revision": 1,
    }
    result = post(e7, "analyses/reject", data, who=1)
    assert result.status_code == 404


@pytest.mark.parametrize("change", ["profile", "weight", "meal", "day", "consent", "delete_weight"])
def test_each_input_category_invalidates_ready_even_equal_sums(e7, change):
    seed(e7)
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    with e7["admin"].begin() as c:
        own = owner(e7)
        table = {
            "profile": "user_profiles",
            "weight": "weights",
            "delete_weight": "weights",
            "meal": "meals",
            "day": "diary_days",
            "consent": "user_consents",
        }[change]
        delta = "deleted_at=clock_timestamp()," if change == "delete_weight" else ""
        predicate = (
            "owner_id=:owner"
            if change in ("profile", "consent")
            else "id=(SELECT id FROM app." + table + " WHERE owner_id=:owner LIMIT 1)"
        )
        c.execute(
            text(
                "UPDATE app." + table + " SET " + delta + "revision=revision+1 WHERE " + predicate
            ),
            {"owner": own},
        )
    response = post(e7, "analyses/accept", decision(e7, ready))
    assert response.status_code == 409 and response.json()["code"] == "analysis_context_changed", (
        response.text
    )


def test_expiry_is_ready_creation_plus_24h_and_inclusive(e7):
    seed(e7)
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    with e7["admin"].begin() as c:
        assert c.scalar(
            text(
                "SELECT expires_at-created_at=interval '24 hours' FROM app.energy_"
                "analyses WHERE id=:id"
            ),
            {"id": a["id"]},
        )
        c.execute(
            text(
                "UPDATE app.energy_analyses SET created_at=transaction_timestamp()"
                "-interval '24 hours',expires_at=transaction_timestamp() WHERE id="
                ":id"
            ),
            {"id": a["id"]},
        )
    result = post(e7, "analyses/accept", decision(e7, ready))
    assert result.status_code == 410, result.text


def test_photo_and_energy_share_active_account_slot(e7):
    seed(e7)
    create_photo(e7)
    response = post(e7, "analyses", body(e7))
    assert response.status_code == 409 and response.json()["code"] == "ai_active_job"
    run(e7)
    assert create(e7)["state"] == "queued"


def test_two_acceptors_apply_once(e7):
    seed(e7)
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    data = decision(e7, ready)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: post(e7, "analyses/accept", data), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.energy_versions WHERE source='manual'")) == 1


def test_minimal_worker_cannot_reserve_or_write_sources(e7):
    for sql in [
        (
            "SELECT app.e7_reserve('mock:local:mock-food-v1:local','energy_adj"
            "ustment','generate',NULL,1,gen_random_uuid(),gen_random_uuid())"
        ),
        "SELECT app.e8n_delete_helper(gen_random_uuid(),gen_random_uuid(),false)",
        "SELECT * FROM app.energy_versions",
        "SELECT * FROM app.weights",
        "UPDATE app.goal_versions SET energy_kcal=1",
        "SELECT app.e9_apply(gen_random_uuid(),gen_random_uuid(),2000,'automatic','{}',NULL)",
    ]:
        with e7["worker"].connect() as c:
            with pytest.raises(DBAPIError):
                c.execute(text(sql))


def test_old_provider_result_cannot_publish_after_source_change(e7):
    seed(e7)
    a = create(e7)

    def hook(boundary, claim):
        if boundary == "after_response":
            with e7["admin"].begin() as c:
                c.execute(
                    text("UPDATE app.user_profiles SET revision=revision+1 WHERE owner_id=:owner"),
                    {"owner": owner(e7)},
                )

    run(e7, hook=hook)
    result = read(e7, a["id"]).json()
    assert result["state"] == "failed" and result["error_code"] == "analysis_context_changed"


def test_same_count_and_same_weight_sum_do_not_hide_replaced_measurement(e7):
    from calorie_app.modules.catalog.timestamps import utc_text
    from calorie_app.modules.diary.models import Weight
    from calorie_app.modules.diary.service import delete_entity, save_weight

    seed(e7)
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    with Session(e7["api"]) as s, s.begin():
        old = (
            s.execute(
                text("SELECT * FROM app.weights WHERE owner_id=:owner ORDER BY id LIMIT 1"),
                {"owner": owner(e7)},
            )
            .mappings()
            .one()
        )
        payload = {
            "weight_kg": "80",
            "local_date": old["local_date"].isoformat(),
            "time_zone": old["time_zone"],
            "occurred_at": utc_text(old["occurred_at"]),
        }
        delete_entity(s, Weight, owner(e7), old["id"], base_revision=old["revision"])
        save_weight(s, owner(e7), uuid4(), payload)
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.weights WHERE deleted_at IS NULL")) == 4
        assert (
            c.scalar(text("SELECT sum(weight_kg) FROM app.weights WHERE deleted_at IS NULL")) == 320
        )
    response = post(e7, "analyses/accept", decision(e7, ready))
    assert response.status_code == 409 and response.json()["code"] == "analysis_context_changed"


def test_changed_goal_revision_blocks_even_identical_energy(e7):
    original, goal, today = seed(e7)
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    with Session(e7["api"]) as s, s.begin():
        create_goal(
            s,
            owner(e7),
            uuid4(),
            GoalPayload.model_validate(
                goal
                | {
                    "effective_from": today.isoformat(),
                    "decided_at": today.isoformat() + "T00:00:00Z",
                    "timeline_base_revision": 1,
                }
            ),
        )
    response = post(e7, "analyses/accept", decision(e7, ready))
    assert response.status_code == 409 and response.json()["code"] == "analysis_context_changed"


def test_timezone_change_does_not_move_source_dates_and_stales_proposal(e7):
    seed(e7)
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    with e7["admin"].begin() as c:
        before = list(c.scalars(text("SELECT local_date FROM app.weights ORDER BY id")))
        c.execute(
            text("UPDATE app.user_profiles SET time_zone='Europe/Warsaw',revision=revision+1")
        )
        assert list(c.scalars(text("SELECT local_date FROM app.weights ORDER BY id"))) == before
    result = post(e7, "analyses/accept", decision(e7, ready))
    assert result.status_code == 409 and result.json()["code"] == "analysis_context_changed"


def test_later_plan_survives_manual_accept_and_revert(e7):
    initial, goal, today = seed(e7)
    with Session(e7["api"]) as s, s.begin():
        estimated = estimate_energy(
            EstimateInput(
                age_years=30,
                height_cm="180",
                weight_kg="76",
                equation_variant="plus_5",
                activity_class="stationary",
            )
        )
        future = create_goal(
            s,
            owner(e7),
            uuid4(),
            GoalPayload.model_validate(
                goal
                | {
                    "effective_from": (today + timedelta(days=5)).isoformat(),
                    "decided_at": today.isoformat() + "T00:00:00Z",
                    "timeline_base_revision": 1,
                    "estimate": estimated,
                }
            ),
        )
        future_id = future.id
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    accepted = post(e7, "analyses/accept", decision(e7, ready))
    assert accepted.status_code == 200, accepted.text
    reverted = post(
        e7, "revert", body(e7) | {"id": str(initial), "replace_id": accepted.json()["entity_id"]}
    )
    assert reverted.status_code == 200, reverted.text
    with e7["admin"].connect() as c:
        assert (
            c.scalar(
                text("SELECT (app.e9_resolve(:owner,:day)).id"),
                {"owner": owner(e7), "day": today + timedelta(days=5)},
            )
            == future_id
        )
        assert (
            c.scalar(
                text("SELECT (app.e9_resolve(:owner,:day)).maintenance_kcal"),
                {"owner": owner(e7), "day": today + timedelta(days=5)},
            )
            == 2610
        )


def test_corrected_legacy_axis_does_not_revive_moved_original(e7):
    initial, goal, today = seed(e7)
    with Session(e7["api"]) as s, s.begin():
        create_goal(
            s,
            owner(e7),
            uuid4(),
            GoalPayload.model_validate(
                goal
                | {
                    "effective_from": (today - timedelta(days=7)).isoformat(),
                    "decided_at": today.isoformat() + "T00:00:00Z",
                    "timeline_base_revision": 1,
                    "correction_of": str(initial),
                    "reason": "history_correction",
                }
            ),
        )
    result = create(e7)
    assert result["state"] == "energy_history_unavailable"
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 0
        assert c.scalar(text("SELECT count(*) FROM app.energy_versions")) == 2


def test_planned_next_day_requires_explicit_conflict_resolution(e7):
    initial, goal, today = seed(e7)
    with Session(e7["api"]) as s, s.begin():
        create_goal(
            s,
            owner(e7),
            uuid4(),
            GoalPayload.model_validate(
                goal
                | {
                    "effective_from": (today + timedelta(days=1)).isoformat(),
                    "decided_at": today.isoformat() + "T00:00:00Z",
                    "timeline_base_revision": 1,
                    "estimate": goal["estimate"]
                    | {"estimated_at": today.isoformat() + "T00:00:00Z"},
                }
            ),
        )
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    result = post(e7, "analyses/accept", decision(e7, ready))
    assert result.status_code == 409 and result.json()["code"] == "energy_scheduled_conflict"
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.energy_versions WHERE source='manual'")) == 0


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"accepted": False},
        {"accepted": 1},
        {"qualified_for_v1": False},
        {"notice_version": "food-photo-notice-v1"},
        {"scope": "this_photo"},
        {"aggregate_scope": "full_diary"},
    ],
)
def test_manual_notice_is_affirmative_and_scope_exact(e7, change):
    seed(e7)
    data = body(e7)
    if change is not None:
        data["notice"] = notice() | change
    with client(e7) as http:
        result = http.post(
            "/api/v1/me/energy/analyses", json=data, headers={"Idempotency-Key": str(uuid4())}
        )
    assert result.status_code == 422, result.text
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 0
        assert c.scalar(text("SELECT count(*) FROM app.energy_analyses")) == 0


def test_manual_notice_provider_must_match_actual_profile(e7):
    seed(e7)
    result = post(e7, "analyses", body(e7) | {"notice": notice("gemini")})
    assert result.status_code == 403 and result.json()["code"] == "energy_notice_provider_mismatch"
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 0


def test_reject_revokes_notice_during_generate_and_blocks_late_result(e7):
    seed(e7)
    a = create(e7)
    stopped = False

    def hook(boundary, claim):
        nonlocal stopped
        if boundary == "before_result_commit" and not stopped:
            stopped = True
            current = read(e7, a["id"]).json()
            result = post(e7, "analyses/reject", decision(e7, current))
            assert result.status_code == 200, result.text

    run(e7, hook=hook)
    result = read(e7, a["id"]).json()
    assert result["state"] == "rejected" and result["notice"]["revoked_at"] is not None
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.energy_versions")) == 1


def test_notice_and_source_context_are_bound_to_same_server_snapshot(e7):
    seed(e7)
    a = create(e7)
    assert a["notice"]["snapshot_hash"] == a["source_context"]["snapshot_hash"]
    assert a["notice"]["profile_revision"] == a["source_context"]["profile_revision"] == 1
    assert a["notice"]["scope"] == "this_energy_analysis"


def test_duplicate_keys_and_oversized_body_rejected_before_mutation(e7):
    with client(e7) as http:
        dup = http.post(
            "/api/v1/me/energy/analyses",
            content='{"axis_revision":1,"axis_revision":2}',
            headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid4())},
        )
        large = http.post(
            "/api/v1/me/energy/analyses",
            content=b" " * 8193,
            headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid4())},
        )
    assert dup.status_code == 422 and large.status_code == 413


def test_goal_reusing_estimate_artifact_preserves_accepted_adjustment(e7):
    _, goal, today = seed(e7)
    analysis = create(e7)
    run(e7)
    accepted = post(e7, "analyses/accept", decision(e7, read(e7, analysis["id"]).json()))
    assert accepted.status_code == 200, accepted.text
    with e7["admin"].connect() as c:
        adjusted = c.execute(
            text("SELECT id,maintenance_kcal FROM app.energy_versions WHERE source='manual'")
        ).one()
        revision = c.scalar(
            text("SELECT revision FROM app.energy_axes WHERE owner_id=:o"), {"o": owner(e7)}
        )
        goal_revision = c.scalar(
            text("SELECT revision FROM app.goal_timelines WHERE owner_id=:o"), {"o": owner(e7)}
        )
    clone = goal | {
        "energy_kcal": "2300",
        "effective_from": (today + timedelta(days=1)).isoformat(),
        "timeline_base_revision": goal_revision,
        "decided_at": today.isoformat() + "T12:00:00Z",
    }
    with Session(e7["api"]) as session, session.begin():
        create_goal(session, owner(e7), uuid4(), GoalPayload.model_validate(clone))
    with e7["admin"].connect() as c:
        resolved = c.execute(
            text("SELECT (app.e9_resolve(:o,:d)).id,(app.e9_resolve(:o,:d)).maintenance_kcal"),
            {"o": owner(e7), "d": today + timedelta(days=1)},
        ).one()
        assert resolved == adjusted
        assert resolved.maintenance_kcal == 2700
        assert (
            c.scalar(
                text("SELECT revision FROM app.energy_axes WHERE owner_id=:o"), {"o": owner(e7)}
            )
            == revision
        )
