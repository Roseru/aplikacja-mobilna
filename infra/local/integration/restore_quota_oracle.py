"""Post-backup mock IO witness; lost quota stays unavailable after real restore.

This is an isolated synthetic fixture, not human consent or real Google usage.
No usage is invented in the restored database, no clock is changed, and the
336-hour hold is tested only at its real current age, where reopening must fail.
"""

import hashlib
import io
import json
import os
import re
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from . import native  # isort: skip

from backup import digest, private_directory, private_write
from pydantic import SecretStr
from recovery_o2 import check, envelope, meal
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from calorie_app.core.config import Settings
from calorie_app.core.errors import DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.ai.decisions import confirm
from calorie_app.modules.ai.schemas import ConfirmRequest
from calorie_app.modules.ai.service import create_analysis, read_analysis
from calorie_app.modules.energy.sync import scope as sync_scope
from calorie_app.modules.sync.router import execute_one, preflight
from calorie_app.modules.sync.schemas import preflight_structure
from calorie_app.modules.sync.snapshots import pull
from calorie_app.modules.sync.tokens import validate_checkpoint


def _support():
    # Import functions/classes only; never execute the destructive pytest fixtures.
    for relative in ("backend", "backend/tests/integration"):
        sys.path.insert(0, str(native.ROOT / relative))
    from test_e7_processes import FakeProvider, WorkerProcess
    from test_e7_runtime import METADATA, image, private_root, role_engine

    return FakeProvider, WorkerProcess, METADATA, image, private_root, role_engine


class DurableCounter:
    """Append-only hash-chained neutral observations, fsynced at each IO boundary."""

    def __init__(self, path, *, create=False):
        self.path, self.lock = Path(path), threading.Lock()
        if self.path.is_symlink() or self.path.is_junction():
            raise ValueError("Linked counter refused")
        if create:
            with self.path.open("xb") as output:
                output.flush()
                os.fsync(output.fileno())
        self.rows = self.read()

    def read(self):
        rows, previous = [], "0" * 64
        raw = self.path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise ValueError("Incomplete counter record")
        for line in raw.splitlines():
            row = json.loads(line)
            saved_hash = row.pop("hash")
            encoded = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
            if (
                row["sequence"] != len(rows) + 1
                or row["previous"] != previous
                or saved_hash != hashlib.sha256(encoded).hexdigest()
            ):
                raise ValueError("Counter prefix changed")
            row["hash"] = saved_hash
            rows.append(row)
            previous = saved_hash
        return rows

    def append(self, event, **fields):
        with self.lock:
            if self.read() != self.rows:
                raise ValueError("Counter changed outside its observer")
            row = fields | {
                "event": event,
                "sequence": len(self.rows) + 1,
                "previous": self.rows[-1]["hash"] if self.rows else "0" * 64,
                "at": datetime.now(UTC).isoformat(),
            }
            encoded = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
            row["hash"] = hashlib.sha256(encoded).hexdigest()
            with self.path.open("ab") as output:
                output.write(json.dumps(row, sort_keys=True).encode() + b"\n")
                output.flush()
                os.fsync(output.fileno())
            self.rows.append(row)

    def counts(self):
        rows = self.read()
        return {
            kind: sum(r["event"] == "dispatch" and r["kind"] == kind for r in rows)
            for kind in ("countTokens", "generateContent")
        }


class _Writer:
    def __init__(self, stream):
        self.stream, self.parts = stream, []

    def write(self, value):
        self.parts.append(value)
        return len(value)

    def flush(self):
        pass

    def __getattr__(self, name):
        return getattr(self.stream, name)


def _observed_provider(counter, stage):
    FakeProvider, *_ = _support()
    fake = FakeProvider()
    original = fake.server.RequestHandlerClass

    class Observed(original):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            if not 0 < length <= 8 * 1024 * 1024:
                raise ValueError("Unbounded mock request")
            raw = self.rfile.read(length)
            check(len(raw) == length, "Incomplete mock request")
            kind = self.path.rsplit(":", 1)[-1]
            check(kind in {"countTokens", "generateContent"}, "Unexpected mock method")
            # This durable observation precedes the reused provider's response.
            counter.append(
                "dispatch",
                stage=stage,
                kind=kind,
                request_bytes=len(raw),
                request_sha256=hashlib.sha256(raw).hexdigest(),
            )
            self.rfile = io.BytesIO(raw)
            writer = _Writer(self.wfile)
            self.wfile = writer
            super().do_POST()
            wire = b"".join(writer.parts)
            _, separator, body = wire.partition(b"\r\n\r\n")
            check(bool(separator), "Mock response lacks HTTP headers")
            counter.append(
                "response",
                stage=stage,
                kind=kind,
                response_bytes=len(body),
                response_sha256=hashlib.sha256(body).hexdigest(),
                response_wire_sha256=hashlib.sha256(wire).hexdigest(),
            )
            # Deliver no successful response before its outcome is durable.
            writer.stream.write(wire)
            writer.stream.flush()

    fake.server.RequestHandlerClass = Observed
    return fake


def _folder(state):
    return native.confined(Path(state["witness_directory"]))


def _evidence(state, name, value):
    path = _folder(state) / name
    if path.exists():
        raise FileExistsError("Existing quota evidence preserved")
    private_write(path, json.dumps(value, sort_keys=True, indent=2))
    state["evidence_sha256"][name] = digest(path)


def _principal(state):
    return Principal(state["issuer"], state["subject"], frozenset({"user"}))


def _settings(engine, state):
    return Settings(
        _env_file=None,
        database_url=engine.url.render_as_string(hide_password=False),
        environment="test",
        ai_photo_root=Path(state["photo_root"]),
        ai_provider="mock",
        ai_project_id="local",
        ai_environment_id="local",
        ai_model="mock-food-v1",
        gemini_api_key=None,
        ai_live_confirmation=None,
    )


def _snapshot(engine):
    with engine.connect() as connection:
        return {
            table: connection.scalar(
                text(
                    "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]') "
                    f"FROM app.{table} t"
                )
            )
            for table in (
                "ai_controls",
                "ai_attempts",
                "ai_jobs",
                "ai_analyses",
                "ai_decisions",
                "ai_receipts",
            )
        }


def _sync_context(value):
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != {"checkpoint", "secret"}
        or not isinstance(value["checkpoint"], str)
        or not 1 <= len(value["checkpoint"]) <= 4096
        or not isinstance(value["secret"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["secret"]) is None
    ):
        raise ValueError("Invalid private sync context")
    return dict(value)


def validate_private_sync_context(context, row, epoch, now):
    """Validate an unchanged checkpoint for this ordinary-sync acceptance scope."""
    context = _sync_context(context)
    if context is None:
        raise ValueError("Private sync context required")
    claims = validate_checkpoint(
        context["checkpoint"],
        SecretStr(context["secret"]),
        owner_id=row["id"],
        generation=row["generation"],
        epoch=epoch,
        now=now,
        installation_id=sync_scope(None),
        push=True,
    )
    return context, {
        "protocol": claims["protocol"],
        "installation": claims["installation"],
        "capability": None,
    }


def prepare(engine, witness_directory, *, owner=None, sync_context=None):
    """Queue one synthetic analysis before T0; no provider dispatch has occurred."""
    _, _, metadata, image, private_root, role_engine = _support()
    sync_context = _sync_context(sync_context)
    directory = native.confined(witness_directory)
    private_directory(directory)
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT id,issuer,subject,generation FROM app.user_accounts "
                    "WHERE state='active' "
                    + ("AND id=:owner " if owner is not None else "")
                    + "ORDER BY id LIMIT 1"
                ),
                {"owner": UUID(str(owner))} if owner is not None else {},
            )
            .mappings()
            .one()
        )
        epoch = connection.scalar(text("SELECT sync_epoch FROM app.installation_state"))
        check(
            connection.scalar(text("SELECT dispatch_open FROM app.ai_controls")) is True,
            "Source AI gate must already be open",
        )
        validated_scope = None
        if sync_context is not None:
            sync_context, validated_scope = validate_private_sync_context(
                sync_context,
                row,
                epoch,
                connection.scalar(text("SELECT clock_timestamp()")),
            )
    worker, login = role_engine((engine, None, engine.url), "calorie_app_ai_worker")
    state = {
        "format": "native-postbackup-mock-quota-oracle/v1",
        "witness_directory": str(directory),
        "photo_root": str(private_root(directory / "transient-photos")),
        "owner": str(row["id"]),
        "issuer": row["issuer"],
        "subject": row["subject"],
        "source_epoch": str(epoch),
        "worker_login": login,
        "worker_url_private": worker.url.render_as_string(hide_password=False),
        "secret_private": sync_context["secret"] if sync_context is not None else secrets_token(),
        "evidence_sha256": {},
    }
    if sync_context is not None:
        state["sync_context_private"] = sync_context
        state["validated_sync_scope"] = validated_scope
    counter = DurableCounter(directory / "provider-counter.jsonl", create=True)
    counter.append("created-before-capture", fixture="synthetic-mock-only", source_epoch=str(epoch))
    state["counter_t0_sha256"] = digest(counter.path)
    _evidence(state, "quota-state-before-admission-private.json", state)
    result = create_analysis(
        engine,
        _principal(state),
        epoch,
        uuid4(),
        metadata,
        image(),
        _settings(engine, state),
    )
    check(
        result.status == 202 and result.error is None,
        "Synthetic analysis was not accepted",
    )
    state["analysis"] = result.payload["analysis_id"]
    with engine.connect() as connection:
        state["job"] = str(
            connection.scalar(
                text("SELECT id FROM app.ai_jobs WHERE analysis_id=:id"),
                {"id": UUID(state["analysis"])},
            )
        )
    before = _snapshot(engine)
    check(before["ai_attempts"] == [], "T0 must precede every provider dispatch")
    _evidence(state, "quota-before-capture-private.json", before)
    _evidence(state, "quota-state-before-capture-private.json", state)
    worker.dispose()
    engine.dispose()
    return state


def secrets_token():
    import secrets

    return secrets.token_hex(32)


def _worker(engine, state, fake):
    _, WorkerProcess, *_ = _support()
    source = make_url(state["worker_url_private"])
    worker = create_engine(
        engine.url.set(username=source.username, password=source.password),
        hide_parameters=True,
    )
    process = WorkerProcess(
        {"worker": worker, "root": Path(state["photo_root"])}, fake, UUID(state["job"])
    )
    identity = native.identity(process.process.pid)
    try:
        process.start()
        done = process.finish()
    finally:
        process.close()
        worker.dispose()
    return {
        "identity": identity,
        "exit_code": process.process.returncode,
        "handled": done["handled"],
        "events": process.events,
        "owned_transport_children_closed": len(process.children),
    }


def after_capture(engine, state):
    """Make actual loopback mock IO, confirm a synthetic choice and commit its sync ACK."""
    counter = DurableCounter(_folder(state) / "provider-counter.jsonl")
    check(
        digest(counter.path) == state["counter_t0_sha256"],
        "Pre-capture counter changed",
    )
    with _observed_provider(counter, "source-after-capture") as fake:
        state["source_mock_port"] = fake.server.server_port
        worker = _worker(engine, state, fake)
        check(worker["handled"] is True, "Original worker did not handle its queued job")
        check(
            fake.counts() == {"countTokens": 1, "generateContent": 1},
            "Postbackup mock IO differs",
        )
    check(
        counter.counts() == {"countTokens": 1, "generateContent": 1},
        "Durable mock counts differ",
    )
    responses = [r for r in counter.read() if r["event"] == "response"]
    check(
        len(responses) == 2 and all(r["response_bytes"] > 0 for r in responses),
        "Missing mock outcome hashes",
    )
    _evidence(state, "source-worker-fence-private.json", worker)
    _evidence(state, "quota-state-after-worker-private.json", state)
    factory = sessionmaker(engine, expire_on_commit=False)
    analysis = read_analysis(factory, _principal(state), UUID(state["analysis"]))
    check(analysis["state"] == "succeeded", "Postbackup mock proposal not committed")
    item = analysis["proposal"]["items"][0]
    operation = meal({"sync_epoch": state["source_epoch"]}, "Synthetic postbackup mock estimate")
    operation["payload"]["items"] = [
        {
            "item_id": str(uuid4()),
            "name": item["name"],
            "product": None,
            "quantity": item["quantity"],
            "basis_unit": item["basis_unit"],
            "nutrition_per_100": item["nutrition_per_100"],
            "density_g_per_ml": None,
            "density_source": None,
            "nutrition_origin": "ai_estimate",
            "formula_version": "nutrition_v1",
            "ration_component_position": None,
        }
    ]
    decision = confirm(
        factory,
        _principal(state),
        UUID(state["source_epoch"]),
        uuid4(),
        UUID(state["analysis"]),
        ConfirmRequest.model_validate(
            {
                "expected_revision": analysis["revision"],
                "meal": {
                    "meal_id": operation["entity_id"],
                    "payload": operation["payload"],
                },
                "drafts": [],
            }
        ),
    )
    check(
        decision.status == 200 and decision.error is None,
        "Synthetic confirmation failed",
    )
    operation["payload"] = decision.payload["meal"]["payload"]
    secret = SecretStr(state["secret_private"])
    context = state.get("sync_context_private")
    checkpoint = (
        context["checkpoint"]
        if context is not None
        else pull(factory, UUID(state["owner"]), {}, secret)["checkpoint"]
    )
    data = envelope({"sync_epoch": state["source_epoch"]}, checkpoint, [operation])
    preflight_structure(data)
    owner, generation = preflight(factory, _principal(state), data, secret)
    ack, _ = execute_one(factory, owner, generation, data, operation, secret)
    check(ack["status"] == "accepted", "Postbackup AI meal was not ACKed")
    state["acked_operation"] = operation
    state["sync_ack"] = ack
    state["counter_postbackup_sha256"] = digest(counter.path)
    _evidence(state, "quota-state-after-ack-private.json", state)
    after = pull(factory, owner, {}, secret)
    actual = next(e for e in after["entities"] if e["entity_id"] == operation["entity_id"])
    check(
        actual["payload"] == operation["payload"],
        "Postbackup AI meal read-back differs",
    )
    _evidence(
        state,
        "quota-after-capture-private.json",
        {
            "database": _snapshot(engine),
            "decision": decision.payload,
            "operation": operation,
            "ack": ack,
            "pull": after,
        },
    )
    engine.dispose()
    return state


def verify(engine, state):
    """Lost postbackup attempts remain unavailable through the real restore gate."""
    _, _, metadata, image, _, _ = _support()
    counter = DurableCounter(_folder(state) / "provider-counter.jsonl")
    check(
        digest(counter.path) == state["counter_postbackup_sha256"],
        "Postbackup counter changed",
    )
    before = _snapshot(engine)
    check(before["ai_attempts"] == [], "T0 unexpectedly contains postbackup attempts")
    with engine.connect() as connection:
        current = connection.scalar(text("SELECT sync_epoch FROM app.installation_state"))
        lost = connection.scalar(
            text("SELECT count(*) FROM app.meals WHERE id=:id"),
            {"id": UUID(state["acked_operation"]["entity_id"])},
        )
    check(
        str(current) != state["source_epoch"] and lost == 0,
        "Restore did not lose postbackup state",
    )
    with _observed_provider(counter, "restored-verify") as fake:
        worker = _worker(engine, state, fake)
        check(worker["handled"] is False, "Restored old worker replayed a job")
        check(
            fake.counts() == {"countTokens": 0, "generateContent": 0},
            "Restored worker renewed IO",
        )
    _evidence(state, "restored-worker-private.json", worker)
    try:
        create_analysis(
            engine,
            _principal(state),
            current,
            uuid4(),
            metadata,
            image(),
            _settings(engine, state),
        )
    except DomainError as error:
        check(
            error.code == "ai_pool_or_restore_unavailable",
            "New admission refused at wrong gate",
        )
    else:
        raise RuntimeError("Restored quota allowed a new admission")
    reservations = {}
    for purpose in ("food_photo", "energy_adjustment"):
        for kind in ("count_tokens", "generate"):
            with engine.begin() as connection:
                connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
                result = connection.scalar(
                    text("SELECT app.e7_reserve(:scope,:purpose,:kind,NULL,0,:attempt,:worker)"),
                    {
                        "scope": "mock:local:mock-food-v1:local",
                        "purpose": purpose,
                        "kind": kind,
                        "attempt": uuid4(),
                        "worker": uuid4(),
                    },
                )
            check(
                result == {"error": "ai_restore_pending"},
                "Uncertain pool became available",
            )
            reservations[purpose + "/" + kind] = result["error"]
    fence_hash = state["evidence_sha256"]["source-worker-fence-private.json"]
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
            connection.execute(
                text("SELECT app.e7_reconcile(:epoch,:evidence,true)"),
                {"epoch": current, "evidence": fence_hash},
            )
    except DBAPIError as error:
        check(error.orig.sqlstate == "23514", "Reconciliation refused unexpectedly")
    else:
        raise RuntimeError("Unelapsed real hold allowed reconciliation")
    after = _snapshot(engine)
    check(after["ai_attempts"] == [], "Denied quota created a replacement attempt")
    control = after["ai_controls"][0]
    check(
        control["dispatch_open"] is False and control["reconciled_at"] is None,
        "Restore gate reopened",
    )
    with engine.connect() as connection:
        age = float(
            connection.scalar(
                text("SELECT extract(epoch FROM clock_timestamp()-closed_at) FROM app.ai_controls")
            )
        )
    check(0 <= age < 336 * 3600, "Unexpected actual restore hold age")
    check(
        counter.counts() == {"countTokens": 1, "generateContent": 1},
        "External usage counter reset or renewed",
    )
    check(
        digest(counter.path) == state["counter_postbackup_sha256"],
        "Restored run changed external IO witness",
    )
    _evidence(state, "quota-restored-before-private.json", before)
    _evidence(state, "quota-restored-after-private.json", after)
    engine.dispose()
    return {
        "result": "PASS",
        "scope": "postbackup-mock-io-and-conservative-restore-quota-gate",
        "source_mock_dispatches": counter.counts(),
        "postrestore_mock_dispatches": {"countTokens": 0, "generateContent": 0},
        "restored_attempt_rows": 0,
        "external_counter_preserved": True,
        "old_worker_handled": False,
        "new_admission_refused": "ai_pool_or_restore_unavailable",
        "both_purposes_and_kinds_refused": reservations,
        "reconcile_sqlstate": "23514",
        "actual_closed_age_seconds": age,
        "hold_required_hours": 336,
        "clock_shift_or_closed_at_backdating": False,
        "lost_usage_rows_invented": False,
        "quota_reopened": False,
        "google_io": 0,
        "full_ko32": False,
        "validated_sync_scope": state.get("validated_sync_scope"),
        "provider_counter_sha256": digest(counter.path),
        "private_evidence_sha256": state["evidence_sha256"],
    }
