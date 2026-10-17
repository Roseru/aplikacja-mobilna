"""Owned HTTPS/PG17/Keycloak recovery rehearsal; never accepts an existing state.

This is an operator acceptance scenario, not a production ledger importer.
All identities, ledger and archives stay in a newly created private directory.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from backup import capture, digest, execute, private_write, rehearse, verify_archive
from run import ROOT, Stack, initialize
from verify import Probe, expect

from calorie_app.health import EXPECTED_REVISION


def check(condition, label):
    if not condition:
        raise RuntimeError(label)


def meal(boot, title):
    payload = json.loads((ROOT / "contracts/examples/valid/meal.json").read_text(encoding="utf-8"))
    payload["title"] = title
    payload["items"][0]["item_id"] = str(uuid4())
    return {
        "operation_id": str(uuid4()),
        "entity_id": str(uuid4()),
        "entity_type": "meal",
        "action": "upsert",
        "base_revision": None,
        "sync_epoch": boot["sync_epoch"],
        "payload": payload,
    }


def envelope(boot, checkpoint, operations):
    return {
        "protocol_version": 1,
        "sync_epoch": boot["sync_epoch"],
        "checkpoint": checkpoint,
        "operations": operations,
    }


def admin(probe, method, path, *, expected=200):
    # Short-lived admin token in memory only. Actual provider admin API, never its DB.
    credentials = json.loads((probe.stack.state / "credentials.json").read_text())
    with probe.client() as client:
        token = expect(
            client.post(
                probe.stack.origin + "/realms/master/protocol/openid-connect/token",
                data={"grant_type": "password", "client_id": "admin-cli", **credentials["admin"]},
            ),
            200,
        ).json()["access_token"]
        return expect(
            client.request(
                method,
                probe.stack.origin + "/admin/realms/calorie-dev" + path,
                headers={"Authorization": "Bearer " + token},
            ),
            expected,
        )


def quiet_sql(stack, database, statement):
    return stack.compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-qAt",
        input_text=statement,
    ).strip()


def sql_uuid(value):
    return str(UUID(str(value)))


def deletion(stack, probe, target, operation):
    account = sql_uuid(target["account_id"])
    operation = sql_uuid(operation)
    subject = sql_uuid(target["subject"])
    generation = target["account_generation"]
    check(type(generation) is int and generation >= 1, "Invalid deletion generation")
    # The expected exact issuer is derived from this owned installation, not ledger input.
    check(target["issuer"] == probe.issuer, "Deletion issuer mismatch")
    actual = json.loads(
        quiet_sql(
            stack,
            "calorie_app",
            f"SELECT row_to_json(t) FROM "
            f"(SELECT id,issuer,subject,generation FROM app.user_accounts WHERE id='{account}') t;",
        )
    )
    check(
        actual
        == {"id": account, "issuer": probe.issuer, "subject": subject, "generation": generation},
        "Deletion identity/generation mismatch",
    )
    quiet_sql(
        stack,
        "calorie_app",
        "SET ROLE calorie_app_deletion_operator; "
        f"SELECT app.begin_account_deletion('{account}','{operation}',{generation});",
    )
    admin(probe, "DELETE", "/users/" + subject, expected=204)
    admin(probe, "GET", "/users/" + subject, expected=404)
    quiet_sql(
        stack,
        "calorie_app",
        "SET ROLE calorie_app_deletion_operator; "
        f"SELECT app.confirm_account_deletion('{operation}'); "
        f"SELECT app.purge_deleted_account('{operation}');",
    )
    check(
        quiet_sql(
            stack,
            "calorie_app",
            f"SELECT purged_at IS NOT NULL FROM "
            f"app.account_deletion_jobs WHERE operation_id='{operation}';",
        )
        == "t",
        "Deletion not completed",
    )
    check(
        quiet_sql(
            stack, "calorie_app", f"SELECT count(*) FROM app.user_accounts WHERE id='{account}';"
        )
        == "0",
        "Deleted app account remains",
    )
    check(
        quiet_sql(
            stack, "calorie_app", f"SELECT app.subject_blocked('{probe.issuer}','{subject}');"
        )
        == "t",
        "Permanent subject fence missing",
    )


def verify_fixture_ledger(path, pinned_hash, *, expected, cutoff):
    """A pinned *local fixture*, not authentication of a production authority.

    The runner pins this hash only after observing the complete own deletion.
    Production requires O3's independent authenticated complete stream/coverage.
    """
    check(path.is_file() and not path.is_symlink(), "Missing independent ledger")
    check(digest(path) == pinned_hash, "Ledger integrity mismatch")
    entry = json.loads(path.read_text(encoding="utf-8"))
    check(entry["source"] == "owned-live-deletion-observation-v1", "Ledger origin mismatch")
    check(entry["target"] == expected, "Ledger target mismatch")
    check(entry["complete_through"] >= cutoff, "Ledger stale coverage")
    check(entry["completed"] is True, "Ledger incomplete")
    return entry


def restore_owned(stack, archive):
    """Restore only the cluster created in this invocation; callers cannot supply a state."""
    verify_archive(archive)
    stack.compose("stop", "gateway", "api", "retention", "keycloak")
    check(
        quiet_sql(
            stack,
            "postgres",
            "SELECT count(*) FROM pg_stat_activity WHERE "
            "backend_type='client backend' AND pid<>pg_backend_pid();",
        )
        == "0",
        "Writers remain",
    )
    container = stack.compose("ps", "-q", "postgres").strip()
    for database in ("calorie_app", "keycloak"):
        quiet_sql(stack, "postgres", f'DROP DATABASE "{database}";')
        execute(
            archive,
            [
                "docker",
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "--create",
                "--exit-on-error",
            ],
            input_path=archive / (database + ".dump"),
            output_path=archive / (database + "-restore-private.log"),
        )


def maintenance(stack):
    # Only provider administration and JWKS. User issuance and all API remain 503.
    config = stack.state / "recovery-Caddyfile"
    private_write(
        config,
        """{
    admin off
    auto_https off
    persist_config off
}
https://:8443 {
    tls /run/tls/server.pem /run/tls/server.key
    header Cache-Control "no-store"
    @operator path /admin/* /realms/master/* /realms/calorie-dev/protocol/openid-connect/certs
    handle @operator {
        reverse_proxy keycloak:8080
    }
    respond "Recovery maintenance" 503
}
""",
        public=True,
    )
    override = stack.state / "maintenance.json"
    private_write(
        override,
        json.dumps(
            {
                "services": {
                    "gateway": {
                        "volumes": [
                            {
                                "type": "bind",
                                "source": config.as_posix(),
                                "target": "/etc/caddy/Caddyfile",
                                "read_only": True,
                            }
                        ]
                    }
                }
            }
        ),
    )
    stack.compose("-f", str(override), "up", "--detach", "--no-deps", "--force-recreate", "gateway")


def wait_maintenance(probe, timeout=30):
    """Bounded listener startup; an open route is an immediate failure, never retried."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with probe.client() as client:
                expect(client.get(probe.stack.origin + "/api/v1/me"), 503)
                expect(client.post(probe.issuer + "/protocol/openid-connect/token"), 503)
            return
        except httpx.TransportError:
            time.sleep(0.25)
    raise RuntimeError("Maintenance HTTPS listener did not start within bound")


def run(state, port):
    check(not state.exists(), "Refusing existing state; fresh owned scratch required")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    check(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT, text=True
        ).strip(),
        "Committed source required",
    )
    project = "o2-recovery-" + uuid4().hex[:12]
    initialize(state, port=port, project=project)
    stack, checks = Stack(state), []
    receipt = {
        "result": "FAIL",
        "commit": commit,
        "scope": "O2-server-meal-recovery",
        "checks": checks,
        "full_ko32": "WAITING_EXTERNAL",
        "google_calls": 0,
    }
    try:
        with (state / "migration-private.log").open("wb") as log:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "backend/tests/integration/test_e9_migration.py",
                    "-k",
                    "o2_populated",
                    "--basetemp",
                    str(state / "migration-tests"),
                    "-q",
                    "--tb=short",
                ],
                cwd=ROOT,
                stdout=log,
                stderr=log,
                check=True,
                timeout=300,
            )
        checks.append("populated 0021 to 0024 migration and legacy replay passed on owned PG17")
        # Compose does not currently forward VCS_REF. Build this exact clean source explicitly.
        stack.compose("build", "--build-arg", "VCS_REF=" + commit)
        stack.compose("up", "--detach", "--wait", "--wait-timeout", "360")
        probe = Probe(stack)
        probe.ready()
        sessions = {who: probe.login(who) for who in ("a", "b")}
        boots, keys = {}, {}
        for who in ("a", "b"):
            keys[who] = str(uuid4())
            boots[who] = expect(
                probe.api(
                    "POST",
                    "/api/v1/me/bootstrap",
                    token=sessions[who]["access_token"],
                    headers={"Idempotency-Key": keys[who]},
                ),
                200,
            ).json()
        token = sessions["a"]["access_token"]
        page = expect(probe.api("GET", "/api/v1/sync/pull", token=token), 200).json()
        checkpoint = page["checkpoint"]
        first = meal(boots["a"], "Synthetic confirmed meal before backup")
        accepted = expect(
            probe.api(
                "POST",
                "/api/v1/sync/push",
                token=token,
                json=envelope(boots["a"], checkpoint, [first]),
            ),
            200,
        ).json()
        check(accepted["results"][0]["status"] == "accepted", "Initial meal not accepted")
        capture(stack.state, state / "paired-backup")
        rehearsal = rehearse(state / "paired-backup")
        check(rehearsal["result"] == "PASS", "Existing paired rehearsal failed")
        checks.append("backup.py capture/verify/rehearse: actual paired archives/globals/catalog")
        stack.compose("up", "--detach", "--no-deps", "keycloak", "api", "retention", "gateway")
        probe.ready()
        # The state starts closed by procedure; close dispatch explicitly before any AI worker.
        quiet_sql(
            stack,
            "calorie_app",
            "UPDATE app.ai_controls SET dispatch_open=false, "
            "closed_at=coalesce(closed_at,clock_timestamp());",
        )
        lost = meal(boots["a"], "Synthetic confirmed meal after backup")
        acknowledgement = expect(
            probe.api(
                "POST",
                "/api/v1/sync/push",
                token=token,
                json=envelope(boots["a"], checkpoint, [lost]),
            ),
            200,
        ).json()
        check(acknowledgement["results"][0]["status"] == "accepted", "Post-backup meal rejected")
        after = expect(probe.api("GET", "/api/v1/sync/pull", token=token), 200).json()
        entity = next(e for e in after["entities"] if e["entity_id"] == lost["entity_id"])
        check(entity["payload"] == lost["payload"], "Post-backup meal read-back differs")
        b = boots["b"]
        target = json.loads(
            quiet_sql(
                stack,
                "calorie_app",
                f"SELECT row_to_json(t) FROM (SELECT "
                f"id AS account_id,issuer,subject,generation AS account_generation "
                f"FROM app.user_accounts WHERE id='{sql_uuid(b['account_id'])}') t;",
            )
        )
        deletion_id = str(uuid4())
        deletion(stack, probe, target, deletion_id)
        cutoff = datetime.now(UTC).isoformat()
        ledger = state / "external-deletions.json"
        private_write(
            ledger,
            json.dumps(
                {
                    "source": "owned-live-deletion-observation-v1",
                    "target": target,
                    "operation_id": deletion_id,
                    "completed": True,
                    "complete_through": cutoff,
                }
            ),
        )
        pinned = digest(ledger)
        checks.append("post-backup meal accepted; B provider DELETE/404 and begin/confirm/purge")
        restore_owned(stack, state / "paired-backup")
        # Counterfactual: the backup resurrects B and omits an acknowledged meal.
        check(
            quiet_sql(
                stack,
                "calorie_app",
                f"SELECT count(*) FROM app.user_accounts WHERE id='{sql_uuid(b['account_id'])}';",
            )
            == "1",
            "B not restored",
        )
        check(
            quiet_sql(
                stack,
                "calorie_app",
                f"SELECT count(*) FROM app.meals WHERE id='{sql_uuid(lost['entity_id'])}';",
            )
            == "0",
            "Lost meal unexpectedly present",
        )
        check(
            quiet_sql(
                stack,
                "calorie_app",
                f"SELECT title FROM app.meals WHERE id='{sql_uuid(first['entity_id'])}';",
            )
            == first["payload"]["title"],
            "Confirmed baseline meal corrupted",
        )
        checks.append("actual pg_restore reproduces resurrection and lost acknowledged meal")
        receipt["stage"] = "commit_epoch_and_cleanup"
        epoch = str(uuid4())
        quiet_sql(
            stack,
            "calorie_app",
            f"BEGIN; UPDATE app.installation_state SET sync_epoch='{epoch}'; "
            "UPDATE app.nemesis_control SET enabled=false; DELETE FROM app.sync_sessions; "
            "UPDATE app.ai_controls SET dispatch_open=false, "
            "closed_at=coalesce(closed_at,clock_timestamp()); COMMIT;",
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
            raise RuntimeError("Bounded cleanup incomplete")
        receipt["stage"] = "start_restored_keycloak"
        stack.compose("up", "--detach", "--no-deps", "--wait", "keycloak")
        receipt["stage"] = "maintenance_gateway"
        maintenance(stack)
        wait_maintenance(probe)
        receipt["stage"] = "reconcile_external_fixture"
        entry = verify_fixture_ledger(ledger, pinned, expected=target, cutoff=cutoff)
        deletion(stack, probe, target, entry["operation_id"])
        logout = admin(probe, "POST", "/logout-all", expected=200).json()
        check(
            isinstance(logout, dict) and not logout.get("failedRequests"),
            "Provider logout-all partially failed",
        )
        admin(probe, "GET", "/users/" + target["subject"], expected=404)
        # Since restore, user issuance has been inaccessible. Observe the full conservative
        # unknown-token bound; no fake clocks, skew changes or shortened lifetime.
        receipt["stage"] = "real_issuance_wait"
        closed = time.monotonic()
        deadline = closed + 421
        while time.monotonic() < deadline:
            time.sleep(max(0, min(1, deadline - time.monotonic())))
        receipt["issuance_closed_wait_seconds"] = round(time.monotonic() - closed, 3)
        checks.append(
            "independent pinned fixture reconciled; API/issuance 503 for >=420 real seconds"
        )
        receipt["stage"] = "old_token_and_meal_recovery_checks"
        stack.compose("up", "--detach", "--no-deps", "--wait", "api")
        stack.compose("up", "--detach", "--no-deps", "--force-recreate", "gateway")
        probe.ready()
        for session in sessions.values():
            expect(probe.api("GET", "/api/v1/me", token=session["access_token"]), 401)
            with probe.client() as client:
                refresh = expect(
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
                check(refresh.json()["error"] == "invalid_grant", "Refresh unexpectedly valid")
        token = probe.login("a")["access_token"]
        expect(
            probe.api(
                "POST", "/api/v1/me/bootstrap", token=token, headers={"Idempotency-Key": keys["a"]}
            ),
            409,
        )
        boot = expect(
            probe.api(
                "POST",
                "/api/v1/me/bootstrap",
                token=token,
                headers={"Idempotency-Key": str(uuid4())},
            ),
            200,
        ).json()
        check(
            boot["account_id"] == boots["a"]["account_id"] and boot["sync_epoch"] == epoch,
            "Fresh PKCE/bootstrap changed ownership",
        )
        for path, kwargs in (
            ("/api/v1/sync/pull", {"params": {"sync_epoch": epoch, "checkpoint": checkpoint}}),
        ):
            response = expect(probe.api("GET", path, token=token, **kwargs), 409)
            check(response.json()["code"] == "sync_epoch_changed", "Old checkpoint not fenced")
        rewritten = lost | {"sync_epoch": epoch}
        expect(
            probe.api(
                "POST",
                "/api/v1/sync/push",
                token=token,
                json=envelope(boot, checkpoint, [rewritten]),
            ),
            409,
        )
        page = expect(probe.api("GET", "/api/v1/sync/pull", token=token), 200).json()
        check(lost["entity_id"] not in {e["entity_id"] for e in page["entities"]}, "Silent replay")
        recovery = meal(boot, lost["payload"]["title"])
        recovery["payload"] = lost["payload"]
        recovery["recovery"] = {
            "source_epoch": boots["a"]["sync_epoch"],
            "source_entity_id": lost["entity_id"],
            "source_revision": 1,
            "source_operation_id": lost["operation_id"],
            "decision": "recreate_missing",
        }
        result = expect(
            probe.api(
                "POST",
                "/api/v1/sync/push",
                token=token,
                json=envelope(boot, page["checkpoint"], [recovery]),
            ),
            200,
        ).json()["results"][0]
        check(result["status"] == "accepted", "Conscious recovery failed")
        second = recovery | {"operation_id": str(uuid4()), "entity_id": str(uuid4())}
        replay = expect(
            probe.api(
                "POST",
                "/api/v1/sync/push",
                token=token,
                json=envelope(boot, page["checkpoint"], [second]),
            ),
            200,
        ).json()["results"][0]
        check(
            replay["recovery_mapping"] == result["recovery_mapping"],
            "Second device duplicated recovery",
        )
        check(
            quiet_sql(stack, "calorie_app", "SELECT dispatch_open FROM app.ai_controls;") == "f"
            and quiet_sql(stack, "calorie_app", "SELECT enabled FROM app.nemesis_control;") == "f",
            "Capabilities reopened",
        )
        checks.append(
            "real old access/refresh denied, fresh PKCE, old keys/checkpoint fenced, "
            "meal recovery mapping"
        )
        image = subprocess.check_output(
            ["docker", "image", "inspect", project + "-backend:local", "--format", "{{.Id}}"],
            text=True,
        ).strip()
        revision = subprocess.check_output(
            [
                "docker",
                "image",
                "inspect",
                image,
                "--format",
                '{{index .Config.Labels "org.opencontainers.image.revision"}}',
            ],
            text=True,
        ).strip()
        check(revision == commit, "Image OCI revision does not match tested clean source")
        subprocess.run(
            ["docker", "image", "save", "--output", str(state / "backend-image.tar"), image],
            check=True,
            capture_output=True,
            timeout=120,
        )
        for name, extra in {
            "backend_acceptance": {
                "image": image,
                "schema_revision": EXPECTED_REVISION,
                "scope": "owned HTTPS meal recovery; see recovery-o2.json and compatibility matrix",
                "android_acceptance": "NOT_RUN",
                "full_ko32": "WAITING_EXTERNAL",
            },
            "migration": {
                "from_revision": "0021_e8_nemesis_results",
                "to_revision": EXPECTED_REVISION,
                "data_preserved": True,
                "predecessor_commit": "a522471140150271d853d66aa06f11d868699e49",
            },
            "rollback": {
                "for_revision": EXPECTED_REVISION,
                "strategy": "restore",
                "scope": "actual paired own 0024->0024 pg_restore only",
                "result": "BLOCKED",
                "waiting_external": "O3/O2: accepted 0021 image and coherent predecessor backup",
                "predecessor_rollback": "NOT_RUN",
            },
        }.items():
            private_write(
                state / (name + ".json"),
                json.dumps({"result": "PASS", "commit": commit, **extra}, indent=2),
            )
        receipt.update(
            result="PASS",
            image=image,
            schema_revision=EXPECTED_REVISION,
            checks=checks,
            production_ledger=False,
            client_recovery=False,
            offsite_verified=False,
            traffic_reopened="owned_scratch_only",
            ai_nemesis_reopened=False,
        )
        return receipt
    except Exception as error:
        receipt["error_kind"] = type(error).__name__
        http_failure = re.fullmatch(
            r"Integration HTTP check expected (\d{3}), got (\d{3})", str(error)
        )
        if http_failure:
            receipt["http_expected"], receipt["http_actual"] = map(int, http_failure.groups())
        receipt["failure_locations"] = [
            {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(error.__traceback__)
        ]
        private_write(state / "failure-private.log", traceback.format_exc())
        raise
    finally:
        # Only resources created by this invocation. A cleanup error is also FAIL.
        try:
            stack.compose("down")
        except Exception:
            receipt.update(result="FAIL", cleanup_failed=True)
            raise
        finally:
            private_write(state / "recovery-o2.json", json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--port", type=int, default=19443)
    args = parser.parse_args()
    try:
        receipt = run(args.state.resolve(), args.port)
    except Exception:
        parser.exit(1, "Owned O2 recovery failed; inspect private logs; no production reopen\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
