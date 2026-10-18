"""Independent synthetic inputs for authentication, ordering and coverage refusals."""

import hmac
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from calorie_app.modules.identity.ledger_contract import (
    SOURCE_DOMAIN,
    ZERO,
    FencePin,
    LedgerInvalid,
    Trust,
    digest,
    make_ack,
    make_cutoff,
    validate_restore,
)


def fence_pin(trust):
    return FencePin(
        **trust.identity(),
        fence_id=str(UUID(int=30)),
        fence_sha256=digest(b"independent synthetic fence observation"),
        scope="contract-test",
    )


def cutoff_at(trust, sequence, chain_hash):
    return make_cutoff(trust, make_ack(trust, sequence, chain_hash), fence_pin(trust))


def fixtures():
    trust = Trust(
        *(str(UUID(int=n)) for n in (1, 2, 3, 4)),
        "https://ledger.test/realms/owned",
        b"s" * 32,
        b"a" * 32,
    )
    events = []
    previous = ZERO
    for sequence, (stage, outcome) in enumerate(
        [
            ("anchor", "cutover_unknown_history"),
            ("begin", "intent"),
            ("provider", "intent"),
            ("provider", "confirmed"),
            ("confirm", "confirmed"),
            ("purge", "intent"),
            ("purge", "confirmed"),
        ],
        1,
    ):
        entry = {k: v for k, v in trust.identity().items() if k != "receiver_id"}
        entry |= {
            "version": 1,
            "issuer": trust.issuer,
            "sequence": sequence,
            "event_id": str(UUID(int=100 + sequence)),
            "operation_id": None if sequence == 1 else str(UUID(int=10)),
            "account_id": None if sequence == 1 else str(UUID(int=11)),
            "subject": None if sequence == 1 else str(UUID(int=12)),
            "expected_generation": None if sequence == 1 else 7,
            "deleting_generation": None if sequence == 1 else 8,
            "stage": stage,
            "outcome": outcome,
            "attempt": str(UUID(int=20)) if stage == "provider" else None,
        }
        content = json.dumps(entry, ensure_ascii=False, separators=(", ", ": "), sort_keys=True)
        content_hash = digest(content.encode())
        chain = digest(bytes.fromhex(previous) + bytes.fromhex(content_hash))
        event = {
            k: entry[k]
            for k in ("sequence", "event_id", "operation_id", "stage", "outcome", "attempt")
        }
        event |= {
            "content": content,
            "content_hash": content_hash,
            "previous_hash": previous,
            "chain_hash": chain,
        }
        events.append(event)
        previous = chain
    envelope = sign(trust, events)
    backup = make_ack(trust, 1, events[0]["chain_hash"])
    cutoff = cutoff_at(trust, 7, events[-1]["chain_hash"])
    return trust, envelope, backup, cutoff


def sign(trust, events):
    body = json.dumps(trust.identity() | {"version": 1, "events": events}, sort_keys=True)
    return {
        "body": body,
        "mac": hmac.digest(trust.source_key, SOURCE_DOMAIN + body.encode(), "sha256").hex(),
    }


def test_independent_complete_prefix_and_exact_duplicate_are_idempotent():
    trust, batch, backup, cutoff = fixtures()
    result = validate_restore(
        trust, [batch, batch], backup_point=backup, cutoff=cutoff, fence_pin=fence_pin(trust)
    )
    assert result["reopen_authorized"] is False and result["source_frozen"] is True
    assert result["targets"][0]["expected_generation"] == 7


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "gap",
        "reverse",
        "content",
        "source_mac",
        "foreign_installation",
        "foreign_receiver",
        "foreign_stream",
        "foreign_anchor",
        "ack_mac",
        "ack_rollback",
        "ack_conflict",
        "no_anchor",
        "generation",
        "issuer",
        "account",
        "provider_attempt",
    ],
)
def test_missing_changed_or_untrusted_coverage_is_rejected(change):
    trust, envelope, backup, cutoff = fixtures()
    events = json.loads(envelope["body"])["events"]
    if change == "missing":
        batches = []
    elif change in {"gap", "reverse", "no_anchor"}:
        events = (
            events[:2] + events[3:]
            if change == "gap"
            else list(reversed(events))
            if change == "reverse"
            else events[1:]
        )
        batches = [sign(trust, events)]
    elif change in {"content", "generation", "issuer", "account", "provider_attempt"}:
        event = events[3]
        body = json.loads(event["content"])
        key, value = {
            "content": ("subject", "tampered"),
            "generation": ("deleting_generation", 9),
            "issuer": ("issuer", "https://other.test"),
            "account": ("account_id", str(UUID(int=99))),
            "provider_attempt": ("attempt", str(UUID(int=99))),
        }[change]
        body[key] = value
        event["content"] = json.dumps(body, sort_keys=True)
        # Recompute downstream hashes and valid source MAC: semantic checks,
        # independently pinned cutoff and identity still must detect corruption.
        previous = ZERO
        for event in events:
            event["previous_hash"] = previous
            event["content_hash"] = digest(event["content"].encode())
            event["chain_hash"] = digest(
                bytes.fromhex(previous) + bytes.fromhex(event["content_hash"])
            )
            previous = event["chain_hash"]
        batches = [sign(trust, events)]
    elif change == "source_mac":
        batches = [envelope | {"mac": ZERO}]
    else:
        batches = [envelope]
        if change.startswith("foreign_"):
            field = {
                "foreign_installation": "installation_id",
                "foreign_receiver": "receiver_id",
                "foreign_stream": "stream_id",
                "foreign_anchor": "anchor_id",
            }[change]
            trust = replace(trust, **{field: str(UUID(int=98))})
        elif change == "ack_mac":
            cutoff = cutoff | {"mac": ZERO}
        elif change == "ack_rollback":
            cutoff = cutoff_at(trust, 1, events[0]["chain_hash"])
            backup = make_ack(trust, 7, events[-1]["chain_hash"])
        elif change == "ack_conflict":
            cutoff = cutoff_at(trust, 7, ZERO)
    with pytest.raises((LedgerInvalid, ValueError)):
        validate_restore(
            trust, batches, backup_point=backup, cutoff=cutoff, fence_pin=fence_pin(trust)
        )


def test_pending_and_uncertain_are_fenced_instead_of_ignored():
    trust, batch, backup, _ = fixtures()
    events = json.loads(batch["body"])["events"][:3]
    cutoff = cutoff_at(trust, 3, events[-1]["chain_hash"])
    result = validate_restore(
        trust, [sign(trust, events)], backup_point=backup, cutoff=cutoff, fence_pin=fence_pin(trust)
    )
    assert len(result["targets"]) == 1 and result["targets"][0]["outcome"] == "intent"
    assert result["reopen_authorized"] is False


def test_versioned_examples_use_independent_synthetic_keys():
    trust, batch, backup, cutoff = fixtures()
    root = Path(__file__).resolve().parents[3] / "contracts/examples/valid"
    assert json.loads((root / "deletion-ledger-v1-batch.json").read_text("utf-8")) == batch
    assert json.loads((root / "deletion-ledger-v1-ack.json").read_text("utf-8")) == make_ack(
        trust, cutoff["sequence"], cutoff["chain_hash"]
    )
    assert json.loads((root / "deletion-ledger-v1-cutoff.json").read_text("utf-8")) == cutoff


def test_inner_batch_event_content_match_versioned_schema():
    from jsonschema import Draft202012Validator, FormatChecker

    root = Path(__file__).resolve().parents[3] / "contracts"
    schema = json.loads((root / "schemas/deletion-ledger-v1.schema.json").read_text("utf-8"))
    trust, envelope, _, cutoff = fixtures()
    batch = json.loads(envelope["body"])
    for name, value in [
        ("Batch", batch),
        ("Cutoff", cutoff),
        ("FencePin", fence_pin(trust).fields()),
        *[("Content", json.loads(e["content"])) for e in batch["events"]],
    ]:
        validator = Draft202012Validator(
            schema | {"$ref": "#/$defs/" + name}, format_checker=FormatChecker()
        )
        validator.validate(value)


@pytest.mark.parametrize(
    "change",
    [
        "ordinary_ack",
        "missing_pin",
        "old_fence",
        "foreign_fence",
        "changed_scope",
        "changed_hash",
        "unsigned",
    ],
)
def test_cutoff_requires_independently_pinned_fence(change):
    trust, batch, backup, cutoff = fixtures()
    pin = fence_pin(trust)
    if change == "ordinary_ack":
        cutoff = make_ack(trust, cutoff["sequence"], cutoff["chain_hash"])
    elif change == "missing_pin":
        pin = None
    elif change in {"old_fence", "foreign_fence"}:
        pin = replace(
            pin,
            **(
                {"fence_id": str(UUID(int=31))}
                if change == "old_fence"
                else {"stream_id": str(UUID(int=31))}
            ),
        )
    else:
        cutoff = (
            cutoff
            | {
                "changed_scope": {"scope": "production"},
                "changed_hash": {"fence_sha256": ZERO},
                "unsigned": {"mac": ZERO},
            }[change]
        )
    with pytest.raises(LedgerInvalid):
        validate_restore(trust, [batch], backup_point=backup, cutoff=cutoff, fence_pin=pin)
