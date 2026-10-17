"""Real scoped Python deletion/CLI and PG17 archive/new-epoch privacy fences."""

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from tests.integration.test_e8_4_migration import snapshot
from tests.integration.test_e8_4_projections import instant
from tests.support.deletion_regression import begin, resume
from tests.support.e8_3_archive import archive_environment, pg_command
from tests.support.e8_3_ci import provision_operator
from tests.support.e8_3_jwt import ISSUER
from tests.support.e8_4_postgres import (
    ROOT,
    SECRET,
    activate,
    challenge,
    clock,
    complete_day,
    finalize,
    finalizer_login,
    fresh_database,
    headers,
    operation,
    push,
    runtime,
    statistics,
)
from tests.support.e8_4_postgres import e8_4_services as e8_4_services

pytestmark = pytest.mark.integration


def operator(rt, folder):
    credential = provision_operator(rt["private"], folder)
    value = json.loads(Path(credential).read_text(encoding="utf-8"))
    return create_engine(value["operator_url"], hide_parameters=True)


@pytest.mark.parametrize("final", [False, True])
def test_actual_minimal_scram_python_resume_and_cli_purge_private_projections(final, tmp_path):
    with runtime() as rt:
        activate(rt)
        metadata = challenge(rt, metrics=True)
        day = date.fromisoformat(metadata["start_date"])
        complete_day(rt, "a", day, "100")
        complete_day(rt, "b", day, "200")
        clock(rt, instant(metadata["end_at"]))
        if final:
            clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
            finalize(rt, metadata["id"])
        assert statistics(rt, metadata["id"], "b").status_code == 200
        minimal = operator(rt, tmp_path)
        owner, operation_id = rt["actors"]["a"]["owner"], uuid4()
        try:
            with minimal.begin() as connection:
                assert connection.scalar(text("SELECT current_user=session_user"))
                for table in (
                    "meals",
                    "goal_versions",
                    "nemesis_day_projections",
                    "nemesis_final_results",
                ):
                    assert not connection.scalar(
                        text(
                            "SELECT has_any_column_privilege(current_user,:table,"
                            "'SELECT,INSERT,UPDATE,REFERENCES')"
                        ),
                        {"table": "app." + table},
                    )
                begin(connection, owner, operation_id, 1)
            assert statistics(rt, metadata["id"], "b").status_code == 404
            called = []

            class Provider:
                def delete_and_confirm(self, issuer, subject):
                    called.append((issuer, subject))

            def crash(stage):
                if stage == "confirmation_committed":
                    raise RuntimeError("synthetic process loss after confirmation COMMIT")

            with pytest.raises(RuntimeError):
                resume(minimal, operation_id, Provider(), barrier=crash)
            before = snapshot(rt["admin"])
            assert any(str(owner) in row for row in before["meals"])
            completed = resume(minimal, operation_id, Provider())
            assert completed["purged_at"] is not None
            assert called == [(ISSUER, rt["actors"]["a"]["subject"])]
            assert resume(minimal, operation_id, Provider())["purged_at"] == completed["purged_at"]
            with rt["admin"].connect() as connection:
                for table in (
                    "nemesis_projection_seeds",
                    "nemesis_day_projections",
                    "nemesis_final_results",
                ):
                    assert (
                        connection.scalar(
                            text(f"SELECT count(*) FROM app.{table} WHERE challenge_id=:id"),
                            {"id": metadata["id"]},
                        )
                        == 0
                    )
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM app.meals WHERE owner_id=:id"), {"id": owner}
                    )
                    == 0
                )
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM app.meals WHERE owner_id=:id"),
                        {"id": rt["actors"]["b"]["owner"]},
                    )
                    == 1
                )
                assert (
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM app.nemesis_receipts "
                            "WHERE entity_id=:id AND response IS NOT NULL"
                        ),
                        {"id": metadata["id"]},
                    )
                    == 0
                )
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM app.deleted_subjects WHERE operation_id=:id"),
                        {"id": operation_id},
                    )
                    == 1
                )
            environment = os.environ | {
                "DELETION_DATABASE_URL": minimal.url.render_as_string(hide_password=False)
            }
            # Actual hardened operator CLI uses the same minimal SCRAM login.
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "calorie_app.modules.identity.deletion",
                    "status",
                    "--operation-id",
                    str(operation_id),
                ],
                env=environment,
                cwd=ROOT / "backend",
                capture_output=True,
                text=True,
                timeout=20,
            )
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout)["purged_at"] is not None
        finally:
            minimal.dispose()


@pytest.mark.parametrize("final", [False, True])
def test_actual_pg17_archive_restore_cannot_resurrect_shared_result(final, tmp_path):
    with runtime() as rt:
        activate(rt)
        metadata = challenge(rt, metrics=True)
        day = date.fromisoformat(metadata["start_date"])
        complete_day(rt, "a", day, "100")
        clock(rt, instant(metadata["end_at"]))
        if final:
            clock(rt, instant(metadata["deadline"]) + timedelta(seconds=1))
            finalize(rt, metadata["id"])
        parsed = make_url(rt["private"].migrator_url)
        environment = archive_environment(parsed)
        archive = tmp_path / "before-withdrawal.dump"
        with archive.open("wb") as output:
            dumped = subprocess.run(
                pg_command(
                    "pg_dump", ["--format=custom", "--dbname", parsed.database], environment
                ),
                stdout=output,
                stderr=subprocess.PIPE,
                env=environment,
                timeout=30,
            )
        assert dumped.returncode == 0 and archive.stat().st_size > 0
        current = rt["client"].get("/api/v1/nemesis/" + metadata["id"], headers=headers(rt)).json()
        response = rt["client"].post(
            "/api/v1/nemesis/" + metadata["id"] + "/cancel",
            headers=headers(rt, revision=current["revision"]),
            json={"reason": "sharing_revoked"},
        )
        assert response.status_code == 200
        with fresh_database(initialize=False) as restored:
            name = make_url(restored.migrator_url).database
            with archive.open("rb") as source:
                copied = subprocess.run(
                    pg_command(
                        "pg_restore",
                        ["--exit-on-error", "--dbname", name],
                        environment,
                        interactive=True,
                    ),
                    stdin=source,
                    capture_output=True,
                    env=environment,
                    timeout=30,
                )
            assert copied.returncode == 0, "actual PG17 archive restoration failed"
            migrator, api = restored.engine(), restored.engine("api")
            try:
                with migrator.begin() as connection:
                    new_epoch = uuid4()
                    connection.execute(
                        text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
                        {"epoch": new_epoch},
                    )
                with api.begin() as connection:
                    result = connection.scalar(
                        text("SELECT app.e8n_statistics(:issuer,:subject,:epoch,:id)"),
                        {
                            "issuer": ISSUER,
                            "subject": rt["actors"]["b"]["subject"],
                            "epoch": new_epoch,
                            "id": metadata["id"],
                        },
                    )
                    assert result["http_status"] == 404
                with finalizer_login(restored) as finalizer:
                    with finalizer.begin() as connection:
                        assert (
                            connection.scalar(
                                text("SELECT app.e8n_finalize(:id)"), {"id": metadata["id"]}
                            )["status"]
                            == "unavailable"
                        )
                with migrator.begin() as connection:
                    assert not connection.scalar(text("SELECT app.e8n_gate()"))
                    connection.execute(text("UPDATE app.nemesis_control SET enabled=false"))
                remaining = None
                while remaining != 0:
                    with migrator.begin() as connection:
                        result = connection.scalar(text("SELECT app.e8n_restore_maintain(1)"))
                        if remaining is not None:
                            assert result["pending"] < remaining
                        remaining = result["pending"]
                with migrator.connect() as connection:
                    assert (
                        connection.scalar(
                            text("SELECT status FROM app.nemesis_challenges WHERE id=:id"),
                            {"id": metadata["id"]},
                        )
                        == "cancelled"
                    )
                app = create_app(
                    Settings(
                        database_url=restored.api_url,
                        environment="test",
                        catalog_page_token_secret=SecretStr(SECRET),
                        oidc_issuer=ISSUER,
                        oidc_jwks_url=ISSUER + "/certs",
                        _env_file=None,
                    ),
                    engine=api,
                )
                app.state.oidc_verifier = rt["signed"].verifier
                with TestClient(app) as client:
                    pull = client.get("/api/v1/sync/pull", headers=rt["actors"]["a"]["headers"])
                    assert pull.status_code == 200, pull.text
                    recovered = {
                        "client": client,
                        "epoch": new_epoch,
                        "actors": {
                            "a": rt["actors"]["a"] | {"checkpoint": pull.json()["checkpoint"]}
                        },
                    }
                    assert (
                        push(recovered, "a", operation(recovered, "weight"))["status"] == "accepted"
                    )
                with migrator.connect() as connection:
                    assert (
                        connection.scalar(
                            text(
                                "SELECT sync_epoch FROM app.motivation_accounts WHERE owner_id=:id"
                            ),
                            {"id": rt["actors"]["a"]["owner"]},
                        )
                        == new_epoch
                    )
            finally:
                api.dispose()
                migrator.dispose()
