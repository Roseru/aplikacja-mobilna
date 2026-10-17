"""Synthetic predecessor restore rehearsal, using exact archived historical source."""

import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import time
from uuid import uuid4

from backup import private_directory, private_write, verify_archive
from recovery_o2 import (
    admin,
    check,
    envelope,
    maintenance,
    meal,
    quiet_sql,
    restore_owned,
    wait_maintenance,
)
from run import ROOT, Stack
from verify import Probe, expect

PREDECESSOR = "a522471140150271d853d66aa06f11d868699e49"
REVISION = "0021_e8_nemesis_results"
PYTHON_IMAGE = (
    "docker.io/library/python:3.13-slim@sha256:"
    "70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f"
)


def command(root, arguments, *, env=None):
    with (root / "experiment-private.log").open("ab") as log:
        subprocess.run(
            arguments, cwd=ROOT, env=env, stdout=log, stderr=log, check=True, timeout=600
        )


def inspect(image, template):
    return subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", template], text=True
    ).strip()


def verify_meals(stack, probe, fixtures, tokens):
    rows = json.loads(
        quiet_sql(
            stack,
            "calorie_app",
            """
        SELECT coalesce(json_agg(json_build_object('id',id,'owner',owner_id,
            'revision',revision,'deleted',deleted_at IS NOT NULL)), '[]') FROM app.meals;
    """,
        )
    )
    expected = [
        {"id": op["entity_id"], "owner": boot["account_id"], "revision": 1, "deleted": False}
        for boot, op in fixtures.values()
    ]
    check(
        sorted(rows, key=lambda r: r["id"]) == sorted(expected, key=lambda r: r["id"]),
        "Rollback data/ownership/count mismatch",
    )
    for who, (_, op) in fixtures.items():
        page = expect(probe.api("GET", "/api/v1/sync/pull", token=tokens[who]), 200).json()
        check(page["page_token"] is None, "Incomplete rollback snapshot")
        meals = [entry for entry in page["entities"] if entry["entity_type"] == "meal"]
        check(
            meals
            == [
                {
                    "entity_type": "meal",
                    "entity_id": op["entity_id"],
                    "revision": 1,
                    "deleted": False,
                    "payload": op["payload"],
                }
            ],
            "Rollback API payload/isolation mismatch",
        )
        status = expect(
            probe.api(
                "POST",
                "/api/v1/sync/push",
                token=tokens[who],
                json=envelope(fixtures[who][0], page["checkpoint"], [op]),
            ),
            200,
        ).json()["results"][0]["status"]
        check(status == "already_applied", "Rollback receipt/idempotency lost")


def rehearse_predecessor(root, commit, current_image):
    check(not root.exists(), "Existing predecessor state refused")
    private_directory(root)
    source = root / "historical-source"
    source.mkdir()
    # Checkout is shallow in CI. Fetch only the named immutable predecessor, never merge it.
    command(root, ["git", "fetch", "--no-tags", "origin", PREDECESSOR])
    archive = root / "source.tar"
    command(
        root,
        [
            "git",
            "archive",
            "--format=tar",
            "--output",
            str(archive),
            PREDECESSOR,
            "backend",
            "infra",
        ],
    )
    with tarfile.open(archive) as stream:
        stream.extractall(source, filter="data")
    spec = importlib.util.spec_from_file_location(
        "o2_historical_run", source / "infra/integration/run.py"
    )
    historical = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(historical)
    state = root / "owned-stack"
    project = "o2-rollback-" + uuid4().hex[:12]
    historical.initialize(state, port=20443, project=project)
    stack = historical.Stack(state)
    stage = "build_exact_predecessor"
    receipt = {
        "result": "FAIL",
        "commit": commit,
        "for_revision": "0024_e9_history_graph",
        "strategy": "restore",
        "scope": "synthetic predecessor 0021 -> upgrade0024 -> paired restore0021",
        "predecessor_commit": PREDECESSOR,
        "predecessor_schema": REVISION,
        "production_rollback": "WAITING_EXTERNAL O3 accepted deployed image and coherent backups",
        "google_calls": 0,
    }
    try:
        tag = project + "-backend:local"
        command(
            root,
            [
                "docker",
                "build",
                "--build-arg",
                "PYTHON_IMAGE=" + PYTHON_IMAGE,
                "--label",
                "org.opencontainers.image.revision=" + PREDECESSOR,
                "-t",
                tag,
                str(source / "backend"),
            ],
        )
        old_image = inspect(tag, "{{.Id}}")
        check(
            inspect(old_image, '{{index .Config.Labels "org.opencontainers.image.revision"}}')
            == PREDECESSOR,
            "Historical image source label mismatch",
        )
        receipt["predecessor_image"] = old_image
        stack.compose("build", "keycloak")
        stack.compose("up", "--detach", "--no-build", "--wait", "--wait-timeout", "360")
        probe = Probe(stack)
        probe.ready()
        check(
            quiet_sql(stack, "calorie_app", "SELECT version_num FROM app.alembic_version;")
            == REVISION,
            "Predecessor did not start at0021",
        )
        quiet_sql(
            stack,
            "calorie_app",
            "UPDATE app.ai_controls SET dispatch_open=false,"
            "closed_at=coalesce(closed_at,clock_timestamp()); "
            "UPDATE app.nemesis_control SET enabled=false;",
        )
        fixtures, sessions = {}, {}
        for who in ("a", "b"):
            sessions[who] = probe.login(who)
            token = sessions[who]["access_token"]
            boot = expect(
                probe.api(
                    "POST",
                    "/api/v1/me/bootstrap",
                    token=token,
                    headers={"Idempotency-Key": str(uuid4())},
                ),
                200,
            ).json()
            page = expect(probe.api("GET", "/api/v1/sync/pull", token=token), 200).json()
            op = meal(boot, "Synthetic predecessor meal " + who)
            result = expect(
                probe.api(
                    "POST",
                    "/api/v1/sync/push",
                    token=token,
                    json=envelope(boot, page["checkpoint"], [op]),
                ),
                200,
            ).json()["results"][0]
            check(result["status"] == "accepted", "Predecessor write failed")
            fixtures[who] = boot, op
        tokens = {who: session["access_token"] for who, session in sessions.items()}
        verify_meals(stack, probe, fixtures, tokens)
        stage = "historical_capture_and_globals_rehearsal"
        environment = os.environ | {"PYTHONPATH": str(source / "backend/src")}
        backup = root / "paired-predecessor"
        for action in ("capture", "rehearse"):
            args = [
                sys.executable,
                str(source / "infra/integration/backup.py"),
                action,
                "--backup",
                str(backup),
            ]
            if action == "capture":
                args += ["--state", str(state)]
            command(root, args, env=environment)
        manifest = verify_archive(backup)
        check(manifest["revision"] == REVISION, "Wrong predecessor backup")
        receipt["backup_revision"] = manifest["revision"]
        receipt["paired_globals_rehearsal"] = "PASS"
        stage = "upgrade_to0024"
        current = Stack(state)
        # Use the actual already-tested C2 image, preserving historical Keycloak26.8.0.
        command(root, ["docker", "image", "tag", current_image, tag])
        current.compose("run", "--rm", "--no-deps", "migrate")
        current.compose(
            "up", "--detach", "--no-deps", "--force-recreate", "api", "keycloak", "gateway"
        )
        probe.ready()
        check(
            quiet_sql(stack, "calorie_app", "SELECT version_num FROM app.alembic_version;")
            == "0024_e9_history_graph",
            "Upgrade did not reach0024",
        )
        verify_meals(stack, probe, fixtures, tokens)
        receipt["upgrade_data_preserved"] = True
        # Old image against0024 must refuse readiness, without running its migrator.
        stage = "old_image_on0024_denied"
        override = root / "old-image.json"
        private_write(
            override,
            json.dumps(
                {
                    "services": {
                        name: {"image": old_image}
                        for name in ("api", "migrate", "storage-init", "retention")
                    }
                }
            ),
        )
        stack.compose("-f", str(override), "up", "--detach", "--no-deps", "--force-recreate", "api")
        deadline = time.monotonic() + 60
        while True:
            try:
                with probe.client() as client:
                    response = client.get(stack.origin + "/health/ready")
                if response.status_code == 503:
                    break
                check(
                    response.status_code == 502 and time.monotonic() < deadline,
                    "Old image unexpectedly ready on0024",
                )
            except OSError:
                check(time.monotonic() < deadline, "Old image readiness probe timed out")
            time.sleep(0.25)
        receipt["old_image_on0024"] = "readiness503"
        stage = "restore_paired0021"
        restore_owned(stack, backup)
        check(
            quiet_sql(stack, "calorie_app", "SELECT version_num FROM app.alembic_version;")
            == REVISION,
            "Restore did not return0021",
        )
        epoch = str(uuid4())
        quiet_sql(
            stack,
            "calorie_app",
            f"BEGIN; UPDATE app.installation_state SET sync_epoch='{epoch}'; "
            "DELETE FROM app.sync_sessions; UPDATE app.ai_controls SET dispatch_open=false,"
            "closed_at=coalesce(closed_at,clock_timestamp()); "
            "UPDATE app.nemesis_control SET enabled=false; COMMIT;",
        )
        for _ in range(10000):
            result = json.loads(
                quiet_sql(
                    stack,
                    "calorie_app",
                    "SET ROLE calorie_app_migrator; SELECT app.e8n_restore_maintain(100);",
                )
            )
            if result["pending"] == 0:
                break
        else:
            raise RuntimeError("Predecessor cleanup incomplete")
        # Correct source/image, not a retagged current image. Keep ingress/issuance closed.
        command(root, ["docker", "image", "tag", old_image, tag])
        stack.compose("up", "--detach", "--no-deps", "--wait", "keycloak")
        maintenance(stack)
        wait_maintenance(probe)
        logout = admin(probe, "POST", "/logout-all", expected=200).json()
        check(not logout.get("failedRequests"), "Predecessor logout failed")
        stage = "restored_sessions_fenced"
        closed = time.monotonic()
        while time.monotonic() - closed < 421:
            time.sleep(1)
        receipt["issuance_closed_wait_seconds"] = round(time.monotonic() - closed, 3)
        stack.compose("-f", str(override), "up", "--detach", "--no-deps", "--force-recreate", "api")
        stack.compose("up", "--detach", "--no-deps", "--force-recreate", "gateway")
        probe.ready()
        for session in sessions.values():
            expect(probe.api("GET", "/api/v1/me", token=session["access_token"]), 401)
            with probe.client() as client:
                response = expect(
                    client.post(
                        probe.issuer + "/protocol/openid-connect/token",
                        data={
                            "grant_type": "refresh_token",
                            "client_id": "calorie-android",
                            "refresh_token": session["refresh_token"],
                        },
                    ),
                    400,
                )
                check(response.json()["error"] == "invalid_grant", "Old predecessor refresh valid")
        fresh_fixtures, tokens = {}, {}
        for who, (boot, op) in fixtures.items():
            tokens[who] = probe.login(who)["access_token"]
            new = expect(
                probe.api(
                    "POST",
                    "/api/v1/me/bootstrap",
                    token=tokens[who],
                    headers={"Idempotency-Key": str(uuid4())},
                ),
                200,
            ).json()
            check(
                new["account_id"] == boot["account_id"] and new["sync_epoch"] == epoch,
                "Rollback bootstrap ownership/epoch changed",
            )
            # Preserve original operation/epoch; use the new boot only for reads and fresh writes.
            fresh_fixtures[who] = new, op
        # Read data after new epoch; keep old receipts and reject old-epoch operations.
        verify_meals_after_restore(stack, probe, fresh_fixtures, tokens)
        check(
            quiet_sql(stack, "calorie_app", "SELECT NOT dispatch_open FROM app.ai_controls;") == "t"
            and quiet_sql(stack, "calorie_app", "SELECT NOT enabled FROM app.nemesis_control;")
            == "t",
            "Rollback capabilities reopened",
        )
        command(
            root,
            [
                "docker",
                "image",
                "save",
                "--output",
                str(root.parent / "predecessor-image.tar"),
                old_image,
            ],
        )
        receipt.update(
            result="PASS",
            stage="complete",
            data_preserved=True,
            before_restore_post_backup_business_writes=0,
            post_restore_acceptance_meals=2,
            traffic_reopened="owned_scratch_only",
            ai_nemesis_reopened=False,
            image_source=(
                "git archive exact predecessor; unmodified historical Dockerfile; "
                "truthful build label"
            ),
        )
        return receipt
    except Exception as error:
        receipt.update(stage=stage, error_kind=type(error).__name__)
        raise
    finally:
        try:
            stack.compose("down")
        except Exception:
            receipt.update(result="FAIL", cleanup_failed=True)
            raise
        finally:
            private_write(root.parent / "rollback.json", json.dumps(receipt, indent=2))


def verify_meals_after_restore(stack, probe, fixtures, tokens):
    # Reuse exact independent data checks, but no replay of old-epoch operations.
    for who, (boot, op) in fixtures.items():
        page = expect(probe.api("GET", "/api/v1/sync/pull", token=tokens[who]), 200).json()
        meals = [entry for entry in page["entities"] if entry["entity_type"] == "meal"]
        check(
            page["page_token"] is None
            and meals
            == [
                {
                    "entity_type": "meal",
                    "entity_id": op["entity_id"],
                    "revision": 1,
                    "deleted": False,
                    "payload": op["payload"],
                }
            ],
            "Restored API data/isolation mismatch",
        )
        response = expect(
            probe.api(
                "POST",
                "/api/v1/sync/push",
                token=tokens[who],
                json=envelope(boot, page["checkpoint"], [op]),
            ),
            409,
        )
        check(response.json()["code"] == "sync_epoch_changed", "Old operation epoch not fenced")
        # Fresh post-restore write and replay proves service operation on real0021.
        fresh = meal(boot, "Fresh synthetic rollback acceptance " + who)
        data = envelope(boot, page["checkpoint"], [fresh])
        for status in ("accepted", "already_applied"):
            check(
                expect(
                    probe.api("POST", "/api/v1/sync/push", token=tokens[who], json=data), 200
                ).json()["results"][0]["status"]
                == status,
                "Restored API write/replay failed",
            )
        check(
            quiet_sql(
                stack,
                "calorie_app",
                f"SELECT count(*) FROM app.meals WHERE owner_id='{boot['account_id']}' "
                f"AND id='{fresh['entity_id']}';",
            )
            == "1",
            "Restored write missing",
        )
    check(
        quiet_sql(stack, "calorie_app", "SELECT count(*) FROM app.meals;") == "4",
        "Restored meal count mismatch",
    )
