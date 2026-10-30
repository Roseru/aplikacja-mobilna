"""Real native backend evidence; deliberately cannot certify APK or a full release."""

import argparse
import copy
import hashlib
import importlib
import json
import secrets
import socket
import ssl
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from infra.local.integration.native import ROOT, Native, source, write_json

# The existing script imports sibling run.py. Native establishes that script
# directory first; do not depend on import sorting or earlier test imports.
integration_verify = importlib.import_module("verify")
MOBILE_CALLBACK = integration_verify.MOBILE_CALLBACK
VALIDATION_CALLBACK = integration_verify.VALIDATION_CALLBACK
Probe = integration_verify.Probe
expect = integration_verify.expect


def sanitized(value):
    if isinstance(value, dict):
        return {
            k: (
                "[memory-only]"
                if k in {"checkpoint", "snapshot_token", "page_token", "next_page_token"} and v
                else sanitized(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    return value


def fixture(epoch):
    """Contract examples plus two independently calculated quantities:130.5+105=235.5."""
    operations = []
    for kind in ("profile", "goal", "diary_day", "meal", "weight", "product_draft"):
        filename = kind.replace("_", "-")
        payload = json.loads(
            (ROOT / f"contracts/examples/valid/{filename}.json").read_text(encoding="utf-8")
        )
        operations.append(
            {
                "operation_id": str(uuid4()),
                "entity_type": kind,
                "entity_id": str(uuid4()),
                "action": "upsert",
                "base_revision": None,
                "sync_epoch": epoch,
                "payload": payload,
            }
        )
    meal = next(op for op in operations if op["entity_type"] == "meal")
    drink = copy.deepcopy(meal["payload"]["items"][0])
    drink.update(
        item_id=str(uuid4()),
        name="Synthetic drink 250ml",
        basis_unit="ml",
        quantity={"amount": "250", "unit": "ml"},
        nutrition_per_100={"energy_kcal": "42", "protein_g": None, "fat_g": None, "carbs_g": None},
    )
    meal["payload"]["items"].append(drink)
    meal["payload"]["goal_id"] = next(
        op["entity_id"] for op in operations if op["entity_type"] == "goal"
    )
    return operations


def lost_response(probe, token, body, committed):
    """Send the complete request, then disconnect without reading any HTTP ACK."""
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    config = probe.stack.config
    with socket.create_connection((config["host"], config["port"]), timeout=15) as connection:
        with probe.trust.wrap_socket(connection, server_hostname=config["host"]) as tls:
            header = (
                f"POST /api/v1/sync/push HTTP/1.1\r\nHost: {config['host']}:{config['port']}\r\n"
                f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
            ).encode()
            tls.sendall(header + raw)
            # Wait for the independent DB witness, never recv/read the response.
            # Cutting earlier tests request cancellation instead of a lost ACK.
            deadline = time.monotonic() + 15
            while not committed():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Lost-response push did not commit all six operations")
                time.sleep(0.2)


def verify(stack, scope):
    evidence = (
        stack.state
        / "evidence"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4))
    )
    evidence.mkdir(parents=True)
    report = {
        "format": "calorie-native-verification/v1",
        "scope": scope,
        "result": "RUNNING",
        "started_at": datetime.now(UTC).isoformat(),
        "origin": stack.origin,
        "source": source(stack.config["source"]["commit"]),
        "checks": [],
        "android": "WAITING_ANDROID_LEASE",
        "full_user_flow": False,
        "ai_provider": "mock",
        "release_authorized": False,
    }
    write_json(evidence / "receipt.json", report)

    def passed(name, details=None):
        report["checks"].append({"name": name, "result": "PASS", "details": details})
        write_json(evidence / "receipt.json", report)
        print("PASS " + name, flush=True)

    try:
        binding = stack.require_running()
        report["runtime_generation"] = binding["generation"]
        probe = Probe(stack)
        probe.ready()
        passed("verified_https_discovery_exact_issuer_readiness")
        for host, cafile in (
            (stack.config["host"], None),
            ("127.0.0.1", stack.state / "tls/ca.pem"),
        ):
            context = ssl.create_default_context(cafile=cafile)
            try:
                with httpx.Client(verify=context, trust_env=False, timeout=5) as client:
                    client.get(f"https://{host}:{stack.config['port']}/health/live")
            except httpx.ConnectError as error:
                if "CERTIFICATE_VERIFY_FAILED" not in str(error):
                    raise RuntimeError("TLS negative failed for another reason") from None
            else:
                raise RuntimeError("Invalid TLS trust or hostname was accepted")
        passed("unknown_ca_and_wrong_hostname_rejected")
        probe.fresh_accounts()
        pairs = [
            probe.login("a", callback=MOBILE_CALLBACK),
            probe.login("b", callback=VALIDATION_CALLBACK),
        ]
        passed("real_code_pkce_both_android_callbacks_signed_nonce")
        code, verifier, _ = probe.code()
        expect(probe.exchange(code, secrets.token_urlsafe(48)), 400)
        code, verifier, _ = probe.code()
        expect(probe.exchange(code, verifier), 200)
        expect(probe.exchange(code, verifier), 400)
        expect(probe.api("GET", "/api/v1/me", token=pairs[0]["id_token"]), 401)
        passed("wrong_pkce_code_replay_id_token_rejected")
        boots, snapshots = [], []
        for pair in pairs:
            key = str(uuid4())
            first = expect(
                probe.api(
                    "POST",
                    "/api/v1/me/bootstrap",
                    token=pair["access_token"],
                    headers={"Idempotency-Key": key},
                ),
                200,
            ).json()
            again = expect(
                probe.api(
                    "POST",
                    "/api/v1/me/bootstrap",
                    token=pair["access_token"],
                    headers={"Idempotency-Key": key},
                ),
                200,
            ).json()
            if first != again:
                raise RuntimeError("Bootstrap replay differed")
            boots.append(first)
            snapshots.append(
                expect(
                    probe.api("GET", "/api/v1/sync/pull", token=pair["access_token"]), 200
                ).json()
            )
        if boots[0]["account_id"] == boots[1]["account_id"]:
            raise RuntimeError("Account isolation failed")
        passed("bootstrap_idempotency_distinct_accounts_initial_pull")
        revision = stack.sql("calorie_app", "SELECT version_num FROM app.alembic_version;")
        from calorie_app.health import EXPECTED_REVISION

        if revision != EXPECTED_REVISION:
            raise RuntimeError("Schema mismatch")
        report["migration"] = revision
        report["runtime"] = {
            "postgres": stack.sql("calorie_app", "SELECT version();"),
            "java": stack.run(
                [Path(stack.config["java_home"]) / "bin/java.exe", "--version"],
                label="java-version",
            ).strip(),
            "keycloak": (stack.state / "keycloak/version.txt").read_text().strip(),
            "python": sys.version,
            "binary_sha256": {
                name: hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in {
                    "postgres": stack.pg / "postgres.exe",
                    "java": Path(stack.config["java_home"]) / "bin/java.exe",
                    "python": Path(sys.executable),
                    "keycloak_bootstrap": stack.state / "keycloak/lib/quarkus-run.jar",
                }.items()
            },
        }
        passed("real_postgresql_migration", revision)
        if scope == "bootstrap":
            report["result"] = "BACKEND_BOOTSTRAP_PASS"
        else:
            operations = fixture(boots[0]["sync_epoch"])
            write_json(
                evidence / "fixture.json",
                {
                    "operations": operations,
                    "oracle": {
                        "meal_energy": "235.5",
                        "drink_energy": "105",
                        "null_macros": 1,
                        "local_date": "2026-10-09",
                        "expected_receipts": 6,
                    },
                },
            )
            body = {
                "protocol_version": 1,
                "sync_epoch": boots[0]["sync_epoch"],
                "checkpoint": snapshots[0]["checkpoint"],
                "operations": operations,
            }
            owner = boots[0]["account_id"]
            query = (
                "SELECT count(*) FROM app.sync_receipts "
                f"WHERE owner_id='{owner}' AND status='accepted';"
            )
            lost_response(
                probe,
                pairs[0]["access_token"],
                body,
                lambda: stack.sql("calorie_app", query) == "6",
            )
            passed("six_domains_committed_without_reading_http_ack")
            retry = expect(
                probe.api("POST", "/api/v1/sync/push", token=pairs[0]["access_token"], json=body),
                200,
            ).json()
            if [row["status"] for row in retry["results"]] != ["already_applied"] * 6:
                write_json(evidence / "unexpected-retry.json", sanitized(retry))
                raise RuntimeError("Retry duplicated or changed an operation")
            write_json(evidence / "retry.json", sanitized(retry))
            passed("identical_retry_six_already_applied")
            witness_sql = (
                "SELECT json_agg(row_to_json(q)) FROM (SELECT operation_id, "
                "entity_type, entity_id, request_hash, source_epoch, status, revision "
                f"FROM app.sync_receipts WHERE owner_id='{owner}' ORDER BY entity_type) q;"
            )
            witness = json.loads(stack.sql("calorie_app", witness_sql))
            if len(witness) != 6 or {r["operation_id"] for r in witness} != {
                op["operation_id"] for op in operations
            }:
                raise RuntimeError("PostgreSQL witness differs from the six-operation fixture")
            write_json(evidence / "postgres-receipts.json", witness)
            pull = expect(
                probe.api(
                    "GET",
                    "/api/v1/sync/pull",
                    token=pairs[0]["access_token"],
                    params={
                        "sync_epoch": boots[0]["sync_epoch"],
                        "checkpoint": snapshots[0]["checkpoint"],
                    },
                ),
                200,
            ).json()
            write_json(evidence / "separate-pull.json", sanitized(pull))
            by_id = {row["entity_id"]: row for row in pull["entities"]}
            for op in operations:
                entity = by_id.get(op["entity_id"])
                if (
                    not entity
                    or entity["entity_type"] != op["entity_type"]
                    or entity["payload"] != op["payload"]
                ):
                    raise RuntimeError(
                        "Separate PULL failed to preserve fixture IDs/dates/null/payload"
                    )
            bpull = expect(
                probe.api(
                    "GET",
                    "/api/v1/sync/pull",
                    token=pairs[1]["access_token"],
                    params={
                        "sync_epoch": boots[1]["sync_epoch"],
                        "checkpoint": snapshots[1]["checkpoint"],
                    },
                ),
                200,
            ).json()
            if bpull["entities"]:
                raise RuntimeError("Account B received A entities")
            expect(
                probe.api("POST", "/api/v1/sync/push", token=pairs[1]["access_token"], json=body),
                422,
            )
            passed("separate_pull_six_domains_exact_payload_and_owner_isolation")
            numeric = stack.sql(
                "calorie_app",
                "SELECT sum(quantity_amount*energy_kcal/100)::numeric(20,1), "
                "count(*) FILTER (WHERE protein_g IS NULL) FROM app.meal_items "
                f"WHERE owner_id='{owner}';",
            )
            if numeric != "235.5|1":
                raise RuntimeError("Independent numeric/null oracle failed")
            passed("postgres_independent_235_5_and_null_oracle", numeric)
            # Save a canonical payload projection before restart, excluding expiring cursors.
            before = sorted(pull["entities"], key=lambda e: e["entity_id"])
            ca = hashlib.sha256((stack.state / "tls/ca.pem").read_bytes()).hexdigest()
            stack.down()
            stack.up()
            report["restart_generation"] = stack.require_running()["generation"]
            probe.ready()
            fresh = probe.login("a")
            after = expect(
                probe.api("GET", "/api/v1/sync/pull", token=fresh["access_token"]), 200
            ).json()
            if sorted(after["entities"], key=lambda e: e["entity_id"]) != before:
                raise RuntimeError("Restart changed the full data projection")
            if after["sync_epoch"] != boots[0]["sync_epoch"]:
                raise RuntimeError("Restart changed the synchronization epoch")
            if (
                stack.sql("calorie_app", query) != "6"
                or hashlib.sha256((stack.state / "tls/ca.pem").read_bytes()).hexdigest() != ca
            ):
                raise RuntimeError("Restart changed receipts or CA")
            write_json(evidence / "restart-pull.json", sanitized(after))
            if json.loads(stack.sql("calorie_app", witness_sql)) != witness:
                raise RuntimeError("Restart changed the exact PostgreSQL receipts")
            write_json(evidence / "restart-postgres-receipts.json", witness)
            passed("down_up_real_oidc_pg_pull_preserves_ids_data_receipts_ca_epoch")
            report["result"] = "BACKEND_SIX_DOMAIN_PASS"
        stack.require_running()
        report["completed_at"] = datetime.now(UTC).isoformat()
    except Exception as error:
        report["result"] = "FAIL"
        # Unexpected upstream text, credentials and JWT never enter evidence or console.
        report["failure_type"] = type(error).__name__
        report["failure_stage"] = len(report["checks"])
        raise
    finally:
        write_json(evidence / "receipt.json", report)
        print(
            json.dumps(
                {
                    "result": report["result"],
                    "evidence": str(evidence),
                    "android": report["android"],
                    "full_user_flow": False,
                }
            ),
            flush=True,
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--scope", choices=("bootstrap", "sync"), default="bootstrap")
    args = parser.parse_args()
    verify(Native(args.state), args.scope)


if __name__ == "__main__":
    main()
