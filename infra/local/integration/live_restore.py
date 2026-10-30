"""Owned C experiment: real HTTPS/PKCE and post-backup mock IO, never a release."""

import argparse
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from . import native  # isort: skip

import httpx
from backup import digest, private_directory
from pydantic import SecretStr
from recovery_o2 import (
    admin,
    check,
    envelope,
    meal,
    verify_recovered_state,
    verify_recovery_result,
)
from sqlalchemy import create_engine
from starlette.responses import Response
from verify import Probe, expect

from calorie_app.modules.sync.schemas import preflight_structure
from calorie_app.modules.sync.service import fingerprint
from calorie_app.modules.sync.tokens import validate_checkpoint

from . import (
    gateway,
    rehearse_restore,
    restore,
    restore_oracle,
    restore_quota_oracle,
    restore_trust,
)

GUARD = "8638dbcead2b97ac915ae676b85dc99e3ac551e7"


class Maintenance:
    """Operator barrier around the unchanged peer guard; never an auth provider."""

    def __init__(self, guarded, closed):
        self.guarded, self.closed = guarded, closed

    @staticmethod
    def operator_route(scope):
        path, method = scope["path"], scope["method"]
        if scope.get("raw_path", path.encode("ascii")) != path.encode("ascii") or scope.get(
            "query_string", b""
        ):
            return False
        return (method, path) in {
            ("POST", "/realms/master/protocol/openid-connect/token"),
            ("POST", "/admin/realms/calorie-dev/logout-all"),
            ("GET", "/realms/calorie-dev/protocol/openid-connect/certs"),
        } or (
            method == "GET"
            and re.fullmatch(r"/admin/realms/calorie-dev/users/[0-9a-f-]{36}/sessions", path)
            is not None
        )

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http"
            and self.guarded.allowed_client(scope.get("client"))
            and self.closed
            and not self.operator_route(scope)
        ):
            await Response(
                "Recovery maintenance",
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        await self.guarded(scope, receive, send)


def cleanup_owned(stack, source, target, receipt):
    receipt["stopped_services"] = stop_services(stack)
    if source is None and (stack.state / "postgres.process.json").exists():
        stack.down()  # Fresh source only; qualified Native PID/birth/exe/datadir stop.
        receipt["startup_failure_native_down"] = True
    remaining = [
        pg for pg in (source, target) if pg is not None and pg.config["status"] != "STOPPED"
    ]
    if rehearse_restore.stop_owned_clusters(remaining, receipt):
        raise RuntimeError("C own cleanup failed")


def serve():
    import uvicorn

    state = Path(os.environ["CALORIE_NATIVE_STATE"])
    config = json.loads((state / "native.json").read_text())
    gateway._configuration(config)
    app = Maintenance(gateway.application(), os.environ.get("RESTORE_MAINTENANCE") == "1")
    sockets = []
    try:
        for host in {"127.0.0.1", config["host"]}:
            listener = socket.socket()
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((host, config["port"]))
            sockets.append(listener)
        uvicorn.Server(
            uvicorn.Config(
                app,
                access_log=False,
                proxy_headers=False,
                ssl_keyfile=str(state / "tls/server.key"),
                ssl_certfile=str(state / "tls/server.pem"),
            )
        ).run(sockets=sockets)
    finally:
        for listener in sockets:
            listener.close()


def stop_services(stack):
    stopped = {}
    for name in ("gateway", "keycloak"):
        path = stack.state / f"{name}.process.json"
        if path.exists():
            record = json.loads(path.read_text())
            native.terminate(record)  # Existing qualified exact PID/birth/exe/owned-tree lifecycle.
            stopped[name] = record
            path.unlink()
    return stopped


def start_services(stack, *, maintenance=False):
    env = stack.env("keycloak")
    env.update(
        JAVA_HOME=stack.config["java_home"],
        JAVA_OPTS_KC_HEAP="-Xms64m -Xmx512m",
        KC_LOG_LEVEL="info,org.keycloak.events:off,org.keycloak.protocol.oidc.utils.OAuth2CodeParser:off",
    )
    stack.launch(
        "keycloak",
        [
            str(stack.state / "keycloak/bin/kc.bat"),
            "start-dev",
            "--http-host=127.0.0.1",
            f"--http-port={stack.config['keycloak_port']}",
            f"--http-management-port={stack.config['management_port']}",
        ],
        env,
    )
    stack.launch(
        "gateway",
        [sys.executable, "-m", "infra.local.integration.live_restore", "serve"],
        stack.env("api") | {"RESTORE_MAINTENANCE": "1" if maintenance else "0"},
    )


def owned_source(stack):
    """Bind only Native source freshly created by run(), never accept an existing state."""
    check(not (stack.state / "owner.json").exists(), "Unexpected source owner")
    values = dict(
        line.split("=", 1) for line in (stack.state / "postgres.env").read_text().splitlines()
    )
    native.private_write(stack.state / "password.private", values["POSTGRES_PASSWORD"] + "\n")
    binaries = {}
    for name in (
        "initdb",
        "pg_ctl",
        "postgres",
        "psql",
        "pg_dump",
        "pg_dumpall",
        "pg_restore",
    ):
        path = stack.pg / (name + ".exe")
        version = subprocess.check_output([str(path), "--version"], **native.FLAGS).decode().strip()
        check("(PostgreSQL) 17." in version, "PG17 required")
        binaries[path.name] = {"sha256": digest(path), "version": version}
    native.write_json(
        stack.state / "owner.json",
        {
            "format": restore.FORMAT,
            "owner": str(uuid4()),
            "state": str(stack.state),
            "pg_bin": str(stack.pg),
            "port": stack.config["pg_port"],
            "user": "postgres",
            "binaries": binaries,
            "process": json.loads((stack.state / "postgres.process.json").read_text()),
            "status": "RUNNING",
        },
    )
    pg = restore.OwnedPG(stack.state)
    pg.qualify()
    return pg


def allow_roles(pg, *roles):
    pg.qualify()
    check(
        all(re.fullmatch(r"[a-z_][a-z0-9_]*", role) for role in roles),
        "Invalid role allowlist",
    )
    native.private_write(
        pg.data / "pg_hba.conf",
        "".join(f"host all {role} 127.0.0.1/32 scram-sha-256\n" for role in ("postgres", *roles))
        + "host all all 0.0.0.0/0 reject\nhost all all ::0/0 reject\n",
    )
    pg.sql("postgres", "SELECT pg_reload_conf();")


def tls_and_peer(probe):
    with probe.client() as client:
        expect(client.get(probe.stack.origin + "/health/ready"), 200)
    try:
        with httpx.Client(trust_env=False, timeout=5) as untrusted:
            untrusted.get(probe.stack.origin + "/health/live")
    except httpx.ConnectError as error:
        check("CERTIFICATE_VERIFY_FAILED" in str(error), "Unknown CA failed outside TLS")
    else:
        raise RuntimeError("Unknown CA accepted")
    # Real socket peer127.0.0.2, verified certificate for the configured host.
    with socket.socket() as raw:
        raw.settimeout(10)
        raw.bind(("127.0.0.2", 0))
        raw.connect(("127.0.0.1", probe.stack.config["port"]))
        with probe.trust.wrap_socket(raw, server_hostname=probe.stack.config["host"]) as secured:
            secured.sendall(
                (
                    "POST /realms/master/protocol/openid-connect/token HTTP/1.1\r\n"
                    f"Host: {probe.stack.config['host']}\r\n"
                    "Content-Length: 0\r\nConnection: close\r\n\r\n"
                ).encode()
            )
            response = secured.recv(4096)
    check(
        response.startswith(b"HTTP/1.1 403"),
        "Foreign actual peer reached provider route",
    )
    return {
        "trusted_tls": True,
        "unknown_ca_refused": True,
        "actual_foreign_peer": "127.0.0.2",
        "foreign_peer_status": 403,
        "response_sha256": __import__("hashlib").sha256(response).hexdigest(),
    }


def maintenance_ready(probe):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            with probe.client() as client:
                expect(client.get(probe.stack.origin + "/api/v1/me"), 503)
                expect(client.post(probe.issuer + "/protocol/openid-connect/token"), 503)
                keys = client.get(probe.issuer + "/protocol/openid-connect/certs")
            if keys.status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(1)
    raise RuntimeError("Maintenance did not become ready")


def http_recovery(probe, sessions, keys, scenario, pg):
    for session in sessions.values():
        expect(probe.api("GET", "/api/v1/me", token=session["access_token"]), 401)
        with probe.client() as client:
            denied = expect(
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
            check(denied.json()["error"] == "invalid_grant", "Restored refresh valid")
    blocked = probe.login("b")["access_token"]
    check(
        expect(probe.api("GET", "/api/v1/me", token=blocked), 403).json()["code"]
        == "account_deleting",
        "B reopened",
    )
    token = probe.login("a")["access_token"]
    before = json.loads(pg.sql("calorie_app", SNAPSHOT))
    expect(
        probe.api(
            "POST",
            "/api/v1/me/bootstrap",
            token=token,
            headers={"Idempotency-Key": keys["a"]},
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
    epoch = pg.sql("calorie_app", "SELECT sync_epoch FROM app.installation_state;")
    check(
        boot["account_id"] == scenario["boot"]["account_id"] and boot["sync_epoch"] == epoch,
        "Owner or epoch changed",
    )
    denied = expect(
        probe.api(
            "GET",
            "/api/v1/sync/pull",
            token=token,
            params={"sync_epoch": epoch, "checkpoint": scenario["checkpoint"]},
        ),
        409,
    )
    check(denied.json()["code"] == "sync_epoch_changed", "Old checkpoint accepted")
    after = json.loads(pg.sql("calorie_app", SNAPSHOT))
    check(before == after, "Refused old bootstrap/checkpoint mutated sync graph")
    page = expect(probe.api("GET", "/api/v1/sync/pull", token=token), 200).json()
    lost = scenario["lost"]
    check(
        lost["entity_id"] not in {e["entity_id"] for e in page["entities"]},
        "Lost meal silently replayed",
    )
    source = restore_oracle._read(scenario, "source-after-capture-private.json")
    source_receipt = next(
        row
        for row in source["graph"]["sync_receipts"]
        if row["operation_id"] == lost["operation_id"]
    )
    check(source_receipt["owner_id"] == boot["account_id"], "Source receipt owner differs")
    old_operation = old_operation_epoch_probe(
        probe,
        token,
        boot,
        page,
        lost,
        pg,
        expected_source_fingerprint=source_receipt["request_hash"],
    )
    recovery = meal(boot, lost["payload"]["title"])
    recovery["payload"] = lost["payload"]
    recovery["recovery"] = {
        "source_epoch": scenario["boot"]["sync_epoch"],
        "source_entity_id": lost["entity_id"],
        "source_revision": 1,
        "source_operation_id": lost["operation_id"],
        "decision": "recreate_missing",
    }

    def push(op):
        return expect(
            probe.api(
                "POST",
                "/api/v1/sync/push",
                token=token,
                json=envelope(boot, page["checkpoint"], [op]),
            ),
            200,
        ).json()["results"][0]

    accepted = push(recovery)
    verify_recovery_result(accepted, recovery, recovery["entity_id"], "accepted")
    second = recovery | {"operation_id": str(uuid4()), "entity_id": str(uuid4())}
    replayed = push(second)
    verify_recovery_result(replayed, second, recovery["entity_id"], "already_applied")
    final = expect(probe.api("GET", "/api/v1/sync/pull", token=token), 200).json()
    check(final["page_token"] is None, "Final PULL incomplete")
    stored = json.loads(
        pg.sql(
            "calorie_app",
            "SELECT json_build_object('meals',"
            "(SELECT json_agg(json_build_object('id',id,'owner',owner_id,'revision',revision,"
            "'deleted',deleted_at IS NOT NULL)) FROM app.meals),"
            "'mappings',(SELECT json_agg(json_build_object('owner',owner_id,'source_epoch',"
            "source_epoch,'source_entity_id',source_entity_id,"
            "'entity_type',entity_type,'target_entity_id',target_entity_id,"
            "'target_revision',target_revision)) FROM app.sync_recovery_mappings));",
        )
    )
    verify_recovered_state(
        recovery,
        second,
        scenario["baseline"],
        boot["account_id"],
        final["entities"],
        stored,
    )
    native.write_json(
        pg.state / "http-before-after.private.json",
        {
            "before": before,
            "after": after,
            "recovery": recovery,
            "second": second,
            "accepted": accepted,
            "replayed": replayed,
            "final_pull": final,
            "stored": stored,
        },
    )
    return {
        "result": "PASS",
        "old_access_401": 2,
        "old_refresh_invalid_grant": 2,
        "fresh_code_s256": True,
        "old_bootstrap_key_refused": True,
        "old_checkpoint_refused": True,
        "old_operation_epoch_refused": old_operation["refused"],
        "old_operation_epoch_proof": old_operation,
        "refused_sync_graph_equal": True,
        "one_recovery_mapping": True,
        "complete_separate_pull": True,
        "raw_evidence_sha256": digest(pg.state / "http-before-after.private.json"),
    }


SNAPSHOT = (
    "SELECT json_build_object("
    + ",".join(
        f"'{table}',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]') "
        f"FROM app.{table} t)"
        for table in (
            "meals",
            "sync_changes",
            "sync_receipts",
            "sync_recovery_mappings",
        )
    )
    + ");"
)


def full_app_graph(pg):
    """One read-only snapshot of every application table, including sync bookkeeping."""
    names = pg.sql(
        "calorie_app",
        "SELECT tablename FROM pg_tables WHERE schemaname='app' ORDER BY tablename;",
    ).splitlines()
    check(
        names and all(re.fullmatch(r"[a-z_][a-z0-9_]*", name) for name in names),
        "Unexpected graph table",
    )
    # VALUES avoids json_build_object's function-argument limit for the full schema.
    statement = (
        "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; "
        "SELECT jsonb_object_agg(name,rows) FROM (VALUES "
        + ",".join(
            f"('{name}',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]') "
            f"FROM app.{name} t))"
            for name in names
        )
        + ") g(name,rows); COMMIT;"
    )
    return json.loads(pg.sql("calorie_app", statement))


def old_operation_epoch_probe(
    probe,
    token,
    boot,
    page,
    operation,
    pg,
    *,
    expected_source_fingerprint,
):
    """Isolate old-operation refusal from stale checkpoint/authentication failures.

    Reuse the persisted operation unchanged. Its canonical fingerprint must match
    the accepted source receipt. The historical HTTP body need not have been
    archived; only this supplemental request's exact body bytes are captured.
    """
    evidence = pg.state / "old-operation-epoch.private.json"
    pg.qualify()
    check(not evidence.exists(), "Existing epoch-probe evidence preserved")
    check(page["page_token"] is None, "Fresh full snapshot required")
    check(operation["sync_epoch"] != boot["sync_epoch"], "Old operation epoch required")
    original_fingerprint = fingerprint(operation)
    check(
        original_fingerprint == expected_source_fingerprint,
        "Operation differs from accepted source receipt",
    )
    epoch = pg.sql("calorie_app", "SELECT sync_epoch FROM app.installation_state;")
    check(boot["sync_epoch"] == epoch, "Fresh outer epoch required")
    account = json.loads(
        pg.sql(
            "calorie_app",
            "SELECT json_build_object('generation',generation,'now',clock_timestamp()) "
            "FROM app.user_accounts WHERE id='" + str(UUID(boot["account_id"])) + "';",
        )
    )
    claims = validate_checkpoint(
        page["checkpoint"],
        SecretStr(probe.stack.env("api")["CATALOG_PAGE_TOKEN_SECRET"]),
        owner_id=UUID(boot["account_id"]),
        generation=account["generation"],
        epoch=UUID(epoch),
        now=datetime.fromisoformat(account["now"]),
        push=True,
    )
    request = envelope(boot, page["checkpoint"], [operation])
    preflight_structure(request)  # Real minItems=1 contract; no empty-PUSH workaround.
    before = full_app_graph(pg)  # Bootstrap/authentication/PULL precede this baseline.
    response = probe.api("POST", "/api/v1/sync/push", token=token, json=request)
    after = full_app_graph(pg)
    sent = json.loads(response.request.content)
    native.write_json(
        evidence,
        {
            "expected_source_fingerprint": expected_source_fingerprint,
            "validated_checkpoint_claims": claims,
            "request_bytes_utf8": response.request.content.decode("utf-8"),
            "response_status": response.status_code,
            "response_bytes_utf8": response.content.decode("utf-8"),
            "before": before,
            "after": after,
            "authorization_header_excluded": True,
            "historical_raw_HTTP_body_identity_claim": False,
        },
    )
    check(
        sent["operations"] == [operation]
        and fingerprint(sent["operations"][0]) == original_fingerprint
        and sent["checkpoint"] == page["checkpoint"]
        and sent["sync_epoch"] == epoch,
        "Actual wire changed the historical operation or fresh context",
    )
    check(
        response.status_code == 409 and response.json()["code"] == "sync_epoch_changed",
        "Old operation epoch barrier not isolated",
    )
    check(before == after, "Refused old operation mutated application graph")
    return {
        "refused": True,
        "code": "sync_epoch_changed",
        "operation_unchanged": True,
        "fresh_checkpoint_validated_for_push": True,
        "all_app_tables_equal": len(before),
        "evidence_sha256": digest(evidence),
    }


def run(state, pg_bin, keycloak_home, java_home, host):
    check(
        ipaddress.IPv4Address(host).is_private and not ipaddress.IPv4Address(host).is_loopback,
        "RFC1918 host required",
    )
    state = restore.owned_path(state)
    check(not state.exists(), "Fresh C state required")
    check(rehearse_restore.memory_available() >= 2 * 1024**3, "Insufficient resources")
    private_directory(state)
    ports = set()
    while len(ports) < 4:
        ports.add(rehearse_restore.free_port())
    https, pgport, kcport, management = ports
    native.prepare(
        state / "services",
        host=host,
        port=https,
        pg_port=pgport,
        keycloak_port=kcport,
        management_port=management,
        pg_bin=pg_bin,
        java_home=java_home,
        keycloak_home=keycloak_home,
        python=sys.executable,
        pin=GUARD,
    )
    stack = native.Native(state / "services")
    native.private_write(
        stack.state / "keycloak.env",
        (stack.state / "keycloak.env").read_text() + "JAVA_OPTS_KC_HEAP=-Xms64m -Xmx512m\n",
    )
    receipt = {
        "format": "native-live-restore-C/v1",
        "result": "FAIL",
        "google_io": 0,
        "room27": False,
        "full_ko32": False,
        "production_rpo_rto": False,
        "source_binding": native.source(GUARD),
        "started_at": datetime.now(UTC).isoformat(),
    }
    snapshots = state / "executed-source"
    snapshots.mkdir()
    for path in native.HERE.glob("*.py"):
        shutil.copy2(path, snapshots / path.name)
    receipt["head"] = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=native.ROOT, **native.FLAGS)
        .decode()
        .strip()
    )
    source = target = engine = None
    try:
        receipt["stage"] = "new_source_native_up"
        stack.up()  # Fresh source only; never used on the restored target.
        source = owned_source(stack)
        probe = Probe(stack)
        receipt["tls_peer"] = tls_and_peer(probe)
        sessions = {who: probe.login(who) for who in ("a", "b")}
        keys = {who: str(uuid4()) for who in sessions}
        for who, session in sessions.items():
            expect(
                probe.api(
                    "POST",
                    "/api/v1/me/bootstrap",
                    token=session["access_token"],
                    headers={"Idempotency-Key": keys[who]},
                ),
                200,
            )
        native.write_json(state / "old-sessions.private.json", sessions)
        subjects = json.loads(
            source.sql(
                "keycloak",
                "SELECT json_object_agg(username,id) FROM user_entity "
                "WHERE username IN ('integration-a','integration-b');",
            )
        )
        engine = create_engine(source.url(), hide_parameters=True)
        scenario = restore_oracle.prepare(
            engine,
            probe.issuer,
            subjects["integration-a"],
            deleted_subject=subjects["integration-b"],
            witness_directory=state / "ledger-witness",
            secret=stack.env("api")["CATALOG_PAGE_TOKEN_SECRET"],
        )
        native.write_json(state / "scenario-before-T0.private.json", scenario)
        quota = restore_quota_oracle.prepare(
            engine,
            state / "quota-witness",
            owner=scenario["boot"]["account_id"],
            sync_context={
                "checkpoint": scenario["checkpoint"],
                "secret": scenario["secret"],
            },
        )
        native.write_json(state / "quota-before-T0.private.json", quota)
        engine.dispose()
        receipt["stage"] = "capture_T0_before_mock_IO"
        stop_services(stack)
        source.seal()
        captured = restore.capture(source, state / "paired-T0")
        native.write_json(state / "held-capture-pin.private.json", captured)
        allow_roles(source, "calorie_app_api", "keycloak", quota["worker_login"])
        start_services(stack)
        probe.ready()
        receipt["stage"] = "actual_postbackup_mock_IO_and_HTTP_ACK"
        quota = restore_quota_oracle.after_capture(engine, quota)
        native.write_json(state / "quota-after-source-IO.private.json", quota)
        observation = {
            "scope": "contract-test",
            "observation_id": str(uuid4()),
            "network_issuer_api_workers_created": True,
            "synchronous_owned_writes_finished": True,
        }

        def live_push(operations):
            result = expect(
                probe.api(
                    "POST",
                    "/api/v1/sync/push",
                    token=sessions["a"]["access_token"],
                    json=envelope(scenario["boot"], scenario["checkpoint"], operations),
                ),
                200,
            ).json()["results"]
            observation["stopped_source_services"] = stop_services(stack)
            observation["quota_worker_exited"] = True
            return result

        scenario = restore_oracle.after_capture(
            engine, scenario, push=live_push, fence_observation=observation
        )
        engine.dispose()
        native.write_json(state / "scenario.private.json", scenario)
        native.write_json(state / "quota.private.json", quota)
        source.seal()
        source.stop()
        (stack.state / "postgres.process.json").unlink()
        receipt["source_stopped"] = True
        receipt["stage"] = "restore_new_target_offline"
        checkpoint = state / "trusted-checkpoint.private.json"
        checkpoint_sha = restore_trust.write_checkpoint(checkpoint, captured, scenario)
        target, receipt["paired"] = restore.restore(
            state / "paired-T0",
            state / "target",
            pg_bin,
            rehearse_restore.free_port(),
            checkpoint=checkpoint,
            checkpoint_sha256=checkpoint_sha,
        )
        engine = create_engine(target.url(), hide_parameters=True)
        receipt["ledger"] = restore_oracle.verify_ledger(engine, scenario)
        engine.dispose()
        allow_roles(target, "calorie_app_api", "keycloak", quota["worker_login"])
        oldport = stack.config["pg_port"]
        stack.config["pg_port"] = target.port
        native.write_json(stack.state / "native.json", stack.config)
        for name in ("api", "keycloak"):
            path = stack.state / f"{name}.env"
            native.private_write(
                path,
                path.read_text().replace(f"127.0.0.1:{oldport}", f"127.0.0.1:{target.port}"),
            )
        start_services(stack, maintenance=True)
        maintenance_ready(probe)
        logout = admin(probe, "POST", "/logout-all").json()
        check(
            isinstance(logout, dict) and not logout.get("failedRequests"),
            "Partial provider logout-all",
        )
        receipt["provider_user_session_counts"] = {}
        for name in ("a", "b"):
            subject = subjects["integration-" + name]
            remaining_sessions = admin(probe, "GET", f"/users/{subject}/sessions").json()
            check(
                isinstance(remaining_sessions, list) and not remaining_sessions,
                "Provider SSO sessions remain after logout-all",
            )
            receipt["provider_user_session_counts"][name] = len(remaining_sessions)
        closed = time.monotonic()
        receipt["stage"] = "real_421_second_fence"
        native.write_json(
            state / "progress.json",
            {"stage": receipt["stage"], "started_at": datetime.now(UTC).isoformat()},
        )
        receipt["quota"] = restore_quota_oracle.verify(engine, quota)
        engine.dispose()
        while time.monotonic() - closed < 421:
            maintenance_ready(probe)
            print(
                json.dumps(
                    {
                        "stage": "issuance_API_closed",
                        "real_elapsed_seconds": round(time.monotonic() - closed),
                    }
                ),
                flush=True,
            )
            time.sleep(min(30, max(0, 421 - (time.monotonic() - closed))))
        receipt["real_issuance_closed_seconds"] = time.monotonic() - closed
        check(receipt["real_issuance_closed_seconds"] >= 421, "Fence too short")
        # Restart only our gateway; Keycloak remains with actual logout-all applied.
        marker = stack.state / "gateway.process.json"
        native.terminate(json.loads(marker.read_text()))
        marker.unlink()
        stack.launch(
            "gateway",
            [sys.executable, "-m", "infra.local.integration.live_restore", "serve"],
            stack.env("api"),
        )
        probe.ready()
        receipt["stage"] = "HTTP_OIDC_recovery"
        receipt["http"] = http_recovery(probe, sessions, keys, scenario, target)
        check(
            native.source(GUARD) == receipt["source_binding"],
            "C sources changed during execution",
        )
        receipt.update(result="PASS", stage="complete")
    except Exception as error:
        receipt.update(result="FAIL", error_kind=type(error).__name__)
        native.private_write(state / "failure.private.log", traceback.format_exc())
        raise
    finally:
        if engine is not None:
            engine.dispose()
        try:
            cleanup_owned(stack, source, target, receipt)
        except Exception as error:
            receipt.update(result="FAIL", cleanup_error=type(error).__name__)
            raise
        finally:
            receipt["ended_at"] = datetime.now(UTC).isoformat()
            native.write_json(state / "execution.json", receipt)
    return receipt


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "serve":
        serve()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("state", "pg-bin", "keycloak-home", "java-home"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    result = run(args.state, args.pg_bin, args.keycloak_home, args.java_home, args.host)
    print(json.dumps({"result": result["result"], "full_ko32": False, "google_io": 0}))


if __name__ == "__main__":
    main()
