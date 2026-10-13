"""Further worker, consent, recovery and immutable history evidence on PG17."""

from datetime import timedelta
from time import sleep
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from calorie_app.integrations.gemini.protocol import ProviderOutcome
from calorie_app.integrations.gemini.transport import execute
from calorie_app.modules.profiles.schemas import ConsentInput
from calorie_app.modules.profiles.service import put_consents
from tests.integration.test_e7_runtime import e7 as e7_fixture
from tests.integration.test_e9_energy import (
    body,
    create,
    create_photo,
    decision,
    owner,
    post,
    read,
    run,
    seed,
)

e7 = e7_fixture
pytestmark = pytest.mark.integration


def consent(rt, automatic):
    with Session(rt["api"]) as s, s.begin():
        revision = s.scalar(
            text("SELECT revision FROM app.user_consents WHERE owner_id=:owner"),
            {"owner": owner(rt)},
        )
        return put_consents(
            s,
            owner(rt),
            ConsentInput(ranking=False, automatic_energy_adjustment=automatic),
            revision,
            uuid4(),
        )


def affirm(rt, version_id):
    c = consent(rt, True)
    response = post(
        rt, "affirm", body(rt) | {"id": str(version_id), "consent_revision": c["revision"]}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_auto_requires_current_online_baseline_and_does_not_rebaseline(e7):
    version, _, today = seed(e7)
    consent(e7, True)
    assert run(e7) == 0
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT baseline_id IS NULL FROM app.energy_axes")) is True
    affirm(e7, version)
    assert run(e7) == 1
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT baseline_id FROM app.energy_axes")) == version
        assert (
            c.scalar(
                text("SELECT maintenance_kcal FROM app.energy_versions WHERE source='automatic'")
            )
            == 2700
        )
        assert c.scalar(text("SELECT last_applied_at IS NOT NULL FROM app.energy_axes")) is True
    assert run(e7) == 0


def test_consent_off_on_fences_queued_automatic_job_before_io(e7):
    version, _, _ = seed(e7)
    affirm(e7, version)

    def hook(boundary, claim):
        if boundary == "before_dispatch":
            consent(e7, False)
            consent(e7, True)

    assert run(e7, hook=hook) == 1
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 0
        assert c.scalar(text("SELECT baseline_id IS NULL FROM app.energy_axes")) is True
        assert (
            c.scalar(text("SELECT error_code FROM app.energy_analyses"))
            == "analysis_context_changed"
        )
    assert run(e7) == 0


@pytest.mark.parametrize("code", ["unknown", "invalid", "429_daily", "429_unknown", "injection"])
def test_provider_failure_never_produces_energy(e7, code):
    e7["settings"] = e7["settings"].model_copy(update={"ai_mock_scenario": code})
    seed(e7)
    a = create(e7)
    run(e7)
    result = read(e7, a["id"]).json()
    assert result["state"] == "failed", result
    assert result["explanation"] is None
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.energy_versions")) == 1
    assert run(e7) == 0


@pytest.mark.parametrize("kind", ["minute", "before_send"])
def test_allowed_new_provider_attempt_reserves_again_but_client_retry_does_not(e7, kind):
    seed(e7)
    key = uuid4()
    original = body(e7)
    created = post(e7, "analyses", original, key).json()
    assert post(e7, "analyses", original, key).json() == created
    seen = 0

    def transport(provider, call_kind, payload, config, timeout):
        nonlocal seen
        if call_kind == "generateContent":
            seen += 1
            if seen == 1:
                return (
                    ProviderOutcome(
                        "provider_rate_limited", retry_kind="minute", retry_after_seconds=1
                    )
                    if kind == "minute"
                    else ProviderOutcome("provider_unavailable", sent=False)
                )
        return execute(provider, call_kind, payload, config, timeout)

    run(e7, transport=transport)
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 2
    sleep(1.05)
    run(e7, transport=transport)
    ready = read(e7, created["id"]).json()
    assert ready["state"] == "ready", ready
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 3
        assert c.scalar(text("SELECT count(*) FROM app.energy_analyses")) == 1


def test_dispatch_crash_reclaim_never_repeats_outbound_and_preserves_permit(e7):
    seed(e7)
    a = create(e7)

    def hook(boundary, claim):
        if boundary == "after_dispatch":
            raise RuntimeError("synthetic crash after committed dispatch")

    with pytest.raises(RuntimeError):
        run(e7, hook=hook)
    with e7["admin"].begin() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 1
        c.execute(text("UPDATE app.ai_jobs SET lease_until=clock_timestamp()-interval '1 second'"))
    assert run(e7) == 0
    result = read(e7, a["id"]).json()
    assert result["state"] == "failed" and result["error_code"] == "provider_result_unknown"
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 1
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.ai_transport_permits WHERE attempt_id IS NOT NULL")
            )
            == 1
        )


def test_gate_and_epoch_block_queued_job_without_io(e7):
    seed(e7)
    create(e7)
    with e7["admin"].begin() as c:
        c.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
            {"epoch": uuid4()},
        )
    assert run(e7) == 0
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 0
        assert c.scalar(text("SELECT NOT dispatch_open FROM app.ai_controls")) is True


def test_revert_replaces_acknowledged_plan_preserves_today_and_has_no_model_call(e7):
    original, _, today = seed(e7)
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    applied = post(e7, "analyses/accept", decision(e7, ready)).json()
    before = body(e7)
    wrong = post(e7, "revert", before | {"id": str(original), "replace_id": None})
    assert wrong.status_code == 409 and wrong.json()["code"] == "energy_scheduled_conflict"
    key = uuid4()
    data = body(e7) | {"id": str(original), "replace_id": applied["entity_id"]}
    restored = post(e7, "revert", data, key)
    assert restored.status_code == 200, restored.text
    assert post(e7, "revert", data, key).json() == restored.json()
    assert restored.json()["payload"]["maintenance_kcal"] == "2595"
    assert restored.json()["payload"]["supersedes"] == applied["entity_id"]
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 2
        assert (
            c.scalar(
                text("SELECT (app.e9_resolve(:owner,:day)).maintenance_kcal"),
                {"owner": owner(e7), "day": today + timedelta(days=1)},
            )
            == 2595
        )
        assert c.scalar(text("SELECT count(*) FROM app.energy_versions")) == 3


@pytest.mark.parametrize("hours,expected", [(335, 429), (336, 200)])
def test_application_cooldown_independent_of_analysis_cooldown(e7, hours, expected):
    seed(e7)
    with e7["admin"].begin() as c:
        c.execute(
            text(
                "UPDATE app.energy_axes SET last_applied_at=clock_timestamp()"
                "-make_interval(hours=>:hours)"
            ),
            {"hours": hours},
        )
    a = create(e7)
    run(e7)
    ready = read(e7, a["id"]).json()
    result = post(e7, "analyses/accept", decision(e7, ready))
    assert result.status_code == expected, result.text
    if expected == 429:
        assert result.json()["code"] == "energy_apply_cooldown"


def test_minimal_receipt_retention_prevents_reexecution(e7):
    seed(e7)
    key = uuid4()
    data = body(e7)
    created = post(e7, "analyses", data, key)
    assert created.status_code == 200
    with e7["admin"].begin() as c:
        c.execute(
            text(
                "UPDATE app.energy_receipts SET created_at=clock_timestamp()-interval '1441 hours'"
            )
        )
    with Session(e7["worker"]) as s, s.begin():
        assert (
            s.scalar(text("SELECT app.e7_prune_receipts(:owner,1000)"), {"owner": owner(e7)}) == 1
        )
    result = post(e7, "analyses", data, key)
    assert result.status_code == 409 and result.json()["code"] == "idempotency_result_expired"
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.energy_receipts")) == 1
        assert c.scalar(text("SELECT count(*) FROM app.energy_analyses")) == 1


def test_oversized_auto_owner_does_not_block_photo_job(e7):
    version, _, today = seed(e7)
    affirm(e7, version)
    # Populate only this disposable fixture without executing 100001 maturity
    # hooks. Constraints stay active; replication mode is local to setup txn.
    with e7["admin"].begin() as c:
        c.execute(text("SET LOCAL session_replication_role=replica"))
        c.execute(
            text(
                "INSERT INTO app.weights(id,owner_id,revision,weight_kg,occurred_at,"
                "local_date,time_zone) SELECT gen_random_uuid(),:o,1,80,"
                "CAST(:d AS date)+interval '12 hours',CAST(:d AS date),'UTC' "
                "FROM generate_series(1,100001)"
            ),
            {"o": owner(e7), "d": today - timedelta(days=1)},
        )
    photo = create_photo(e7 | {"boots": [e7["boots"][1]], "principals": [e7["principals"][1]]})
    assert run(e7) == 1
    with e7["admin"].connect() as c:
        assert (
            c.scalar(
                text("SELECT last_auto_state FROM app.energy_axes WHERE owner_id=:o"),
                {"o": owner(e7)},
            )
            == "resource_exhausted"
        )
        assert (
            c.scalar(
                text("SELECT last_auto_checked_date FROM app.energy_axes WHERE owner_id=:o"),
                {"o": owner(e7)},
            )
            == today
        )
        assert c.scalar(text("SELECT count(*) FROM app.energy_analyses")) == 0
        assert (
            c.scalar(
                text("SELECT state FROM app.ai_analyses WHERE id=:id"), {"id": photo["analysis_id"]}
            )
            == "succeeded"
        )
        assert (
            c.scalar(text("SELECT count(*) FROM app.ai_attempts WHERE purpose='energy_adjustment'"))
            == 0
        )
    assert run(e7) == 0
