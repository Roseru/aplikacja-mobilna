"""Offline service and contract-ledger oracle for an owned paired PG restore.

No HTTP server, issuer, provider adapter or mobile client is created. Returned
state contains synthetic identities and signing material and must stay private.
The caller owns capture/restore and commits the new epoch before ``verify``.
"""

import hmac
import json
import secrets
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

from infra.local.integration import native  # isort: skip
from infra.local.integration import restore_trust  # isort: skip

from backup import digest as file_digest
from backup import private_directory, private_write
from pydantic import SecretStr
from recovery_o2 import (
    check,
    envelope,
    meal,
    verify_recovered_state,
    verify_recovery_result,
)
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from calorie_app.core.errors import DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.identity.deletion import begin
from calorie_app.modules.identity.ledger_contract import (
    SOURCE_DOMAIN,
    FencePin,
    LedgerInvalid,
    make_cutoff,
)
from calorie_app.modules.identity.ledger_restore import reconcile_restore
from calorie_app.modules.identity.service import bootstrap
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.router import execute_one, preflight
from calorie_app.modules.sync.schemas import preflight_structure
from calorie_app.modules.sync.snapshots import pull


def _ledger(engine, directory, issuer):
    # This is the existing contract-test receiver, never a production service.
    sys.path.insert(0, str(native.ROOT / "backend"))
    from tests.support.ledger import LedgerHarness

    return LedgerHarness(engine, directory, issuer)


def _save(directory, name, value):
    path = directory / name
    if path.exists():
        raise FileExistsError("Existing witness is preserved")
    private_write(path, json.dumps(value, sort_keys=True, indent=2))
    return file_digest(path)


def _read(state, name):
    return restore_trust.read_witness(state, name)


def _evidence(state, name, value):
    directory = native.confined(Path(state["witness_directory"]))
    state["witness_files"][name] = _save(directory, name, value)


def _principal(state):
    return Principal(state["issuer"], state["subject"], frozenset({"user"}))


def _push(engine, state, boot, checkpoint, operations):
    factory = sessionmaker(engine, expire_on_commit=False)
    secret = SecretStr(state["secret"])
    data = envelope(boot, checkpoint, operations)
    preflight_structure(data)
    owner, generation = preflight(factory, _principal(state), data, secret)
    return [execute_one(factory, owner, generation, data, op, secret)[0] for op in operations]


def _refused(call, code, kind=SyncFailure):
    try:
        call()
    except kind as error:
        check(error.code == code, "Unexpected offline refusal")
    else:
        raise RuntimeError("Expected offline refusal did not occur")


def _checkpoint(ledger):
    ledger.deliver()
    envelopes = ledger.sink.envelopes()
    check(bool(envelopes), "Missing independent ledger anchor")
    # deliver returns an ACK only after the durable receiver's own commit.
    ack = ledger.sink.deliver(envelopes[-1])
    return envelopes, ack


def prepare(engine, issuer, subject, *, deleted_subject=None, witness_directory, secret=None):
    """Create a real committed baseline and independent contract-test witness.

    ``subject`` and optional ``deleted_subject`` must come from the caller's own
    imported synthetic Keycloak database. No consent or provider result is made.
    """
    UUID(subject)
    if deleted_subject is not None:
        UUID(deleted_subject)
        check(deleted_subject != subject, "Distinct synthetic subjects required")
    directory = native.confined(witness_directory)
    private_directory(directory)
    key = uuid4()
    state = {
        "format": "native-offline-restore-oracle/v1",
        "issuer": issuer,
        "subject": subject,
        "secret": secret or secrets.token_hex(32),
        "bootstrap_key": str(key),
        "witness_directory": str(directory),
        "witness_files": {},
    }
    with Session(engine) as session, session.begin():
        state["boot"] = bootstrap(session, _principal(state), key)
        if deleted_subject is not None:
            state["deleted_boot"] = bootstrap(
                session,
                Principal(issuer, deleted_subject, frozenset({"user"})),
                uuid4(),
            )
    factory = sessionmaker(engine, expire_on_commit=False)
    owner = UUID(state["boot"]["account_id"])
    first_page = pull(factory, owner, {}, SecretStr(state["secret"]))
    state["baseline"] = meal(state["boot"], "Synthetic baseline before paired backup")
    accepted = _push(engine, state, state["boot"], first_page["checkpoint"], [state["baseline"]])
    check(accepted[0]["status"] == "accepted", "Baseline was not committed")
    page = pull(factory, owner, {}, SecretStr(state["secret"]))
    check(page["page_token"] is None, "Baseline snapshot is incomplete")
    state["checkpoint"] = page["checkpoint"]
    ledger = _ledger(engine, directory, issuer)
    try:
        _, ack = _checkpoint(ledger)
        trust = ledger.trust
        raw = trust.identity() | {
            "issuer": trust.issuer,
            "source_key": trust.source_key.hex(),
            "ack_key": trust.ack_key.hex(),
        }
        state["witness_files"]["trust-private.json"] = _save(directory, "trust-private.json", raw)
        state["witness_files"]["backup-point.json"] = _save(directory, "backup-point.json", ack)
    finally:
        ledger.close()
    _evidence(
        state,
        "baseline-before-capture-private.json",
        {"graph": _sync_snapshot(engine), "pull": page},
    )
    engine.dispose()
    return state


def after_capture(engine, state, *, push=None, fence_observation=None):
    """Commit a post-backup meal and optional pending deletion, then close writers.

    The witness covers the synchronous owned service writes only. It does not
    attest production processes, provider deletion, or provider session fencing.
    """
    state["lost"] = meal(state["boot"], "Synthetic ACKed meal after paired backup")
    accepted = (
        push([state["lost"]])
        if push
        else _push(engine, state, state["boot"], state["checkpoint"], [state["lost"]])
    )
    check(accepted[0]["status"] == "accepted", "Post-backup meal was not committed")
    factory = sessionmaker(engine, expire_on_commit=False)
    owner = UUID(state["boot"]["account_id"])
    page = pull(factory, owner, {}, SecretStr(state["secret"]))
    actual = next(e for e in page["entities"] if e["entity_id"] == state["lost"]["entity_id"])
    check(actual["payload"] == state["lost"]["payload"], "Post-backup read-back differs")
    if "deleted_boot" in state:
        state["deletion_operation"] = str(uuid4())
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
            result = begin(
                connection,
                UUID(state["deleted_boot"]["account_id"]),
                UUID(state["deletion_operation"]),
                state["deleted_boot"]["account_generation"],
            )
        check(result["identity_confirmed_at"] is None, "Unexpected provider confirmation")
    directory = native.confined(Path(state["witness_directory"]))
    ledger = _ledger(engine, directory, state["issuer"])
    try:
        # Independently supplied controller fact, before inspecting received tail.
        observed = fence_observation or {
            "scope": "contract-test",
            "synchronous_owned_writes_finished": True,
            "network_issuer_api_workers_created": False,
            "observation_id": str(uuid4()),
        }
        observed_hash = _save(directory, "fence-observation.json", observed)
        pin = FencePin(
            **ledger.trust.identity(),
            fence_id=observed["observation_id"],
            fence_sha256=observed_hash,
            scope="contract-test",
        )
        envelopes, ack = _checkpoint(ledger)
        artifacts = {
            "fence-observation.json": observed_hash,
            "fence-pin.json": _save(directory, "fence-pin.json", pin.fields()),
            "cutoff.json": _save(directory, "cutoff.json", make_cutoff(ledger.trust, ack, pin)),
            "prefix-private.json": _save(directory, "prefix-private.json", envelopes),
        }
        state["witness_files"].update(artifacts)
    finally:
        ledger.close()
    _evidence(
        state,
        "source-after-capture-private.json",
        {"graph": _sync_snapshot(engine), "pull": page},
    )
    engine.dispose()
    return state


def _ledger_snapshot(engine):
    with engine.connect() as connection:
        return connection.scalar(
            text(
                "SELECT json_build_object('source',"
                "(SELECT row_to_json(s) FROM (SELECT enabled,next_sequence,head_hash "
                "FROM app.deletion_ledger_source) s),'accounts',"
                "(SELECT json_agg(a ORDER BY a.id) FROM "
                "(SELECT id,state,generation FROM app.user_accounts) a),'receipts',"
                "(SELECT count(*) FROM app.deletion_ledger_restore_receipts))"
            )
        )


def _sync_snapshot(engine):
    with engine.connect() as connection:
        return {
            name: connection.scalar(
                text(
                    "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]') "
                    f"FROM app.{name} t"
                )
            )
            for name in (
                "meals",
                "sync_receipts",
                "sync_recovery_mappings",
                "sync_changes",
            )
        }


def _verify_ledger(engine, state):
    evidence = restore_trust.load_evidence(state)
    trust, pin, _ = restore_trust.validate_evidence(evidence)
    backup, cutoff, envelopes = (
        evidence["backup_point"],
        evidence["cutoff"],
        evidence["envelopes"],
    )
    before = _ledger_snapshot(engine)

    def reconcile(batch, fence=pin):
        return reconcile_restore(
            engine, trust, batch, backup_point=backup, cutoff=cutoff, fence_pin=fence
        )

    first = json.loads(envelopes[0]["body"])
    events = [event for batch in envelopes for event in json.loads(batch["body"])["events"]]
    first["events"] = events[1:]
    gap_body = json.dumps(first)
    gap = [
        {
            "body": gap_body,
            "mac": hmac.digest(trust.source_key, SOURCE_DOMAIN + gap_body.encode(), "sha256").hex(),
        }
    ]
    refused = []
    for name, batch, fence, expected_error in (
        ("missing_prefix", [], pin, "backup_anchor_missing"),
        (
            "changed_mac",
            [envelopes[0] | {"mac": "0" * 64}],
            pin,
            "unauthenticated_source",
        ),
        (
            "authenticated_prefix_gap",
            gap,
            pin,
            "prefix_gap_or_rollback" if len(events) > 1 else "invalid_batch_size",
        ),
        (
            "wrong_independent_fence",
            envelopes,
            replace(pin, fence_id=str(uuid4())),
            "cutoff_fence_mismatch",
        ),
    ):
        try:
            reconcile(batch, fence)
        except LedgerInvalid as error:
            check(str(error) == expected_error, "Ledger refused at an unexpected boundary")
            refused.append(name)
        else:
            raise RuntimeError("Invalid ledger witness was accepted")
        check(_ledger_snapshot(engine) == before, "Invalid ledger mutated restored state")
    result = reconcile(envelopes)
    check(result["reopen_authorized"] is False, "Ledger authorized reopening")
    with engine.connect() as connection:
        check(
            connection.scalar(text("SELECT enabled FROM app.deletion_ledger_source")) is False,
            "Restored ledger source is not frozen",
        )
        if "deleted_boot" in state:
            account = connection.execute(
                text("SELECT state,generation FROM app.user_accounts WHERE id=:id"),
                {"id": UUID(state["deleted_boot"]["account_id"])},
            ).one()
            check(
                account == ("deleting", state["deleted_boot"]["account_generation"] + 1),
                "Pending deletion target was resurrected",
            )
            check(len(result["targets"]) == 1, "Wrong ledger target count")
    return refused


def verify_ledger(engine, state):
    """Reuse the same independent prefix/fence oracle before controlled HTTP reopen."""
    return _verify_ledger(engine, state)


def verify(engine, state):
    """Check the actual restored database through existing offline service oracles."""
    boot, baseline, lost = state["boot"], state["baseline"], state["lost"]
    owner, secret = UUID(boot["account_id"]), SecretStr(state["secret"])
    with engine.connect() as connection:
        epoch = str(connection.scalar(text("SELECT sync_epoch FROM app.installation_state")))
        check(epoch != boot["sync_epoch"], "Restore reused the source epoch")
        check(
            connection.scalar(text("SELECT count(*) FROM app.sync_sessions")) == 0,
            "Old sessions remain",
        )
        check(
            connection.scalar(text("SELECT dispatch_open FROM app.ai_controls")) is False,
            "AI reopened",
        )
        check(
            connection.scalar(text("SELECT enabled FROM app.nemesis_control")) is False,
            "Nemesis reopened",
        )
    refused_ledger = _verify_ledger(engine, state)
    factory = sessionmaker(engine, expire_on_commit=False)
    page = pull(
        factory,
        owner,
        {"recovery_operation_ids": [baseline["operation_id"], lost["operation_id"]]},
        secret,
    )
    check(page["sync_epoch"] == epoch, "Pull epoch mismatch")
    check(
        {r["operation_id"] for r in page["operation_receipts"]} == {baseline["operation_id"]},
        "Restored receipt graph differs",
    )
    check(
        lost["entity_id"] not in {e["entity_id"] for e in page["entities"]},
        "Lost meal survived backup",
    )
    before_stale = _sync_snapshot(engine)
    _evidence(
        state,
        "restored-before-recovery-private.json",
        {"graph": before_stale, "pull": page},
    )
    _evidence(state, "stale-requests-before-private.json", before_stale)
    _refused(
        lambda: _push(engine, state, boot, page["checkpoint"], [lost]),
        "sync_epoch_changed",
    )
    current_boot = boot | {"sync_epoch": epoch}
    _refused(
        lambda: _push(
            engine,
            state,
            current_boot,
            state["checkpoint"],
            [lost | {"sync_epoch": epoch}],
        ),
        "sync_epoch_changed",
    )
    _refused(
        lambda: pull(
            factory,
            owner,
            {"sync_epoch": epoch, "checkpoint": state["checkpoint"]},
            secret,
        ),
        "sync_epoch_changed",
    )
    with Session(engine) as session:
        _refused(
            lambda: bootstrap(session, _principal(state), UUID(state["bootstrap_key"])),
            "sync_epoch_changed",
            DomainError,
        )
    after_stale = _sync_snapshot(engine)
    check(after_stale == before_stale, "Stale request changed the restored graph")
    _evidence(state, "stale-requests-after-private.json", after_stale)
    with Session(engine) as session, session.begin():
        fresh_boot = bootstrap(session, _principal(state), uuid4())
    check(fresh_boot["account_id"] == boot["account_id"], "Restored ownership changed")
    recovery = meal(current_boot, lost["payload"]["title"])
    recovery["payload"] = lost["payload"]
    recovery["recovery"] = {
        "source_epoch": boot["sync_epoch"],
        "source_entity_id": lost["entity_id"],
        "source_revision": 1,
        "source_operation_id": lost["operation_id"],
        "decision": "recreate_missing",
    }
    result = _push(engine, state, current_boot, page["checkpoint"], [recovery])[0]
    verify_recovery_result(result, recovery, recovery["entity_id"], "accepted")
    second = recovery | {"operation_id": str(uuid4()), "entity_id": str(uuid4())}
    replay = _push(engine, state, current_boot, page["checkpoint"], [second])[0]
    verify_recovery_result(replay, second, recovery["entity_id"], "already_applied")
    final = pull(factory, owner, {}, secret)
    check(final["page_token"] is None, "Final pull is incomplete")
    with engine.connect() as connection:
        stored = connection.scalar(
            text(
                "SELECT json_build_object('meals',"
                "(SELECT coalesce(json_agg(json_build_object('id',id,'owner',owner_id,"
                "'revision',revision,'deleted',deleted_at IS NOT NULL)), '[]') FROM app.meals),"
                "'mappings',(SELECT coalesce(json_agg(json_build_object('owner',owner_id,"
                "'source_epoch',source_epoch,'source_entity_id',source_entity_id,"
                "'entity_type',entity_type,'target_entity_id',target_entity_id,"
                "'target_revision',target_revision)), '[]') FROM app.sync_recovery_mappings))"
            )
        )
    verify_recovered_state(recovery, second, baseline, str(owner), final["entities"], stored)
    _evidence(
        state,
        "restored-after-recovery-private.json",
        {
            "graph": _sync_snapshot(engine),
            "pull": final,
            "stored": stored,
            "recovery_operation": recovery,
            "second_operation": second,
            "accepted": result,
            "replayed": replay,
        },
    )
    engine.dispose()
    return {
        "result": "PASS",
        "scope": "offline-backend-services-and-contract-ledger",
        "baseline_receipt_retained": True,
        "post_backup_acked_meal_absent_before_recovery": True,
        "old_epoch_checkpoint_bootstrap_refused": True,
        "explicit_new_uuid_recovery": True,
        "cross_device_mapping_count": 1,
        "independent_ledger_refusals": refused_ledger,
        "pending_deletion_blocked": "deleted_boot" in state,
        "ledger_reopen_authorized": False,
        "network_api_issuer_opened": False,
        "jwt_refresh_pkce_tested": False,
        "uncertain_quota_retention_tested": False,
        "room27_tested": False,
        "full_ko32": False,
        "google_io": 0,
        "private_evidence_sha256": state["witness_files"],
    }
