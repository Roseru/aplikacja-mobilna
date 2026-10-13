"""Final integration boundaries: ranking-only consent and second snapshot limit."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.integration.test_e7_runtime import client
from tests.integration.test_e7_runtime import e7 as e7_fixture
from tests.integration.test_e9_energy import body, create_photo, owner, post, run, seed
from tests.integration.test_e9_worker import affirm

e7 = e7_fixture
pytestmark = pytest.mark.integration


def state(rt):
    with client(rt) as http:
        response = http.get("/api/v1/me/energy/state")
    assert response.status_code == 200, response.text
    return response.json()


def test_ranking_only_put_preserves_requested_and_requires_new_energy_affirmation(e7):
    version, _, _ = seed(e7)
    affirm(e7, version)
    old = state(e7)
    assert old["automatic_requested"] and old["automatic_effective"]
    with e7["admin"].connect() as c:
        revision = c.scalar(
            text("SELECT revision FROM app.user_consents WHERE owner_id=:o"), {"o": owner(e7)}
        )
    with client(e7) as http:
        changed = http.put(
            "/api/v1/me/consents",
            json={"ranking": True, "automatic_energy_adjustment": True},
            headers={"Idempotency-Key": str(uuid4()), "If-Match": f'"{revision}"'},
        )
    assert changed.status_code == 200, changed.text
    assert changed.json()["automatic_energy_adjustment"] is True
    current = state(e7)
    assert current["automatic_requested"] is True
    assert current["automatic_effective"] is False
    assert current["baseline_id"] is None and current["automatic_notice"] is None
    assert run(e7) == 0
    old_affirm = post(e7, "affirm", body(e7) | {"id": str(version), "consent_revision": revision})
    assert old_affirm.status_code == 409, old_affirm.text
    fresh = post(
        e7,
        "affirm",
        body(e7) | {"id": str(version), "consent_revision": changed.json()["revision"]},
    )
    assert fresh.status_code == 200, fresh.text
    assert state(e7)["automatic_effective"] is True
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 0


def test_second_snapshot_resource_limit_is_scoped_and_photo_continues(e7):
    version, _, _ = seed(e7)
    affirm(e7, version)
    # Reproduce the documented 54000 at the second build after axis metadata grew.
    # Injection affects only this disposable DB and the actual producer/runner run.
    with e7["admin"].begin() as c:
        c.execute(
            text("ALTER FUNCTION app.e9_context(uuid,date,date) RENAME TO e9_context_edge_original")
        )
        c.execute(
            text("""CREATE FUNCTION app.e9_context(p_owner uuid,p_from date,p_to date)
            RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
            SET search_path=pg_catalog,pg_temp AS $$ BEGIN
            IF EXISTS(SELECT 1 FROM app.energy_axes WHERE owner_id=p_owner
                AND last_auto_checked_date IS NOT NULL) THEN
                RAISE EXCEPTION 'synthetic second context limit' USING ERRCODE='54000';END IF;
            RETURN app.e9_context_edge_original(p_owner,p_from,p_to);END $$""")
        )
        c.execute(
            text("ALTER FUNCTION app.e9_context(uuid,date,date) OWNER TO calorie_app_migrator")
        )
        c.execute(text("REVOKE ALL ON FUNCTION app.e9_context(uuid,date,date) FROM PUBLIC"))
    try:
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
            assert c.scalar(text("SELECT count(*) FROM app.ai_energy_admissions")) == 0
            assert c.scalar(text("SELECT count(*) FROM app.energy_analyses")) == 0
            assert (
                c.scalar(
                    text("SELECT state FROM app.ai_analyses WHERE id=:id"),
                    {"id": photo["analysis_id"]},
                )
                == "succeeded"
            )
        assert run(e7) == 0
    finally:
        with e7["admin"].begin() as c:
            c.execute(text("DROP FUNCTION app.e9_context(uuid,date,date)"))
            c.execute(
                text(
                    "ALTER FUNCTION app.e9_context_edge_original(uuid,date,date) "
                    "RENAME TO e9_context"
                )
            )
