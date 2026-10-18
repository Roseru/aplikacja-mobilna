"""Versioned authenticated deletion stream; no provider or transport dependency."""

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from uuid import UUID

ZERO = "0" * 64
SOURCE_DOMAIN = b"deletion-ledger-source-v1\n"
ACK_DOMAIN = "deletion-ledger-ack-v1"
CUTOFF_DOMAIN = "deletion-ledger-cutoff-v1"
MAX_BATCH_BYTES = 1024 * 1024


class LedgerInvalid(ValueError):
    """Stable diagnostic; never include identity, key, or raw body."""


def require(condition, code):
    if not condition:
        raise LedgerInvalid(code)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def uuid_text(value):
    require(isinstance(value, str) and str(UUID(value)) == value, "invalid_uuid")
    return value


@dataclass(frozen=True)
class Trust:
    installation_id: str
    stream_id: str
    anchor_id: str
    receiver_id: str
    issuer: str
    source_key: bytes = field(repr=False)
    ack_key: bytes = field(repr=False)

    def __post_init__(self):
        for value in (self.installation_id, self.stream_id, self.anchor_id, self.receiver_id):
            uuid_text(value)
        require(bool(self.issuer), "invalid_issuer")
        require(len(self.source_key) == len(self.ack_key) == 32, "invalid_key")
        require(self.source_key != self.ack_key, "distinct_keys_required")

    def identity(self):
        return {
            key: getattr(self, key)
            for key in ("installation_id", "stream_id", "anchor_id", "receiver_id")
        }


def ack_frame(ack):
    return "\n".join(
        str(ack[key])
        for key in (
            "domain",
            "installation_id",
            "stream_id",
            "anchor_id",
            "receiver_id",
            "sequence",
            "chain_hash",
        )
    ).encode("ascii")


def make_ack(trust, sequence, chain_hash):
    ack = trust.identity() | {"domain": ACK_DOMAIN, "sequence": sequence, "chain_hash": chain_hash}
    ack["mac"] = hmac.digest(trust.ack_key, ack_frame(ack), "sha256").hex()
    return ack


def verify_ack(trust, ack):
    require(
        isinstance(ack, dict)
        and set(ack)
        == {
            "domain",
            "installation_id",
            "stream_id",
            "anchor_id",
            "receiver_id",
            "sequence",
            "chain_hash",
            "mac",
        },
        "invalid_ack",
    )
    require(ack["domain"] == ACK_DOMAIN, "invalid_ack_domain")
    require(all(ack[k] == v for k, v in trust.identity().items()), "ack_target_mismatch")
    require(type(ack["sequence"]) is int and 1 <= ack["sequence"] < 2**63, "invalid_ack_sequence")
    require(isinstance(ack["chain_hash"], str) and len(ack["chain_hash"]) == 64, "invalid_ack_hash")
    require(
        isinstance(ack["mac"], str)
        and hmac.compare_digest(
            hmac.digest(trust.ack_key, ack_frame(ack), "sha256").hex(), ack["mac"]
        ),
        "unauthenticated_ack",
    )
    return ack


@dataclass(frozen=True)
class FencePin:
    """Independent controller input; never infer this pin from an exported cutoff."""

    installation_id: str
    stream_id: str
    anchor_id: str
    receiver_id: str
    fence_id: str
    fence_sha256: str
    scope: str

    def __post_init__(self):
        for name in ("installation_id", "stream_id", "anchor_id", "receiver_id", "fence_id"):
            uuid_text(getattr(self, name))
        require(
            isinstance(self.fence_sha256, str)
            and len(self.fence_sha256) == 64
            and all(c in "0123456789abcdef" for c in self.fence_sha256),
            "invalid_fence_hash",
        )
        require(self.scope in {"contract-test", "production"}, "invalid_fence_scope")

    def fields(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def cutoff_frame(cutoff):
    return (
        ack_frame(cutoff)
        + b"\n"
        + "\n".join(cutoff[key] for key in ("fence_id", "fence_sha256", "scope")).encode("ascii")
    )


def make_cutoff(trust, ack, fence_pin):
    """Trusted receiver/controller only, after independently observing the fence."""
    verify_ack(trust, ack)
    require(isinstance(fence_pin, FencePin), "independent_fence_pin_required")
    require(
        all(fence_pin.fields()[k] == v for k, v in trust.identity().items()),
        "fence_target_mismatch",
    )
    cutoff = ack | fence_pin.fields() | {"domain": CUTOFF_DOMAIN}
    cutoff["mac"] = hmac.digest(trust.ack_key, cutoff_frame(cutoff), "sha256").hex()
    return cutoff


def verify_cutoff(trust, cutoff, fence_pin):
    require(isinstance(fence_pin, FencePin), "independent_fence_pin_required")
    require(
        all(fence_pin.fields()[k] == v for k, v in trust.identity().items()),
        "fence_target_mismatch",
    )
    require(
        isinstance(cutoff, dict)
        and set(cutoff) == set(fence_pin.fields()) | {"domain", "sequence", "chain_hash", "mac"},
        "invalid_cutoff",
    )
    require(cutoff["domain"] == CUTOFF_DOMAIN, "invalid_cutoff_domain")
    require(all(cutoff[k] == v for k, v in fence_pin.fields().items()), "cutoff_fence_mismatch")
    require(
        type(cutoff["sequence"]) is int and 1 <= cutoff["sequence"] < 2**63,
        "invalid_cutoff_sequence",
    )
    require(
        isinstance(cutoff["chain_hash"], str)
        and len(cutoff["chain_hash"]) == 64
        and all(c in "0123456789abcdef" for c in cutoff["chain_hash"]),
        "invalid_cutoff_hash",
    )
    require(
        isinstance(cutoff["mac"], str)
        and hmac.compare_digest(
            hmac.digest(trust.ack_key, cutoff_frame(cutoff), "sha256").hex(), cutoff["mac"]
        ),
        "unauthenticated_cutoff",
    )
    return cutoff


def authenticated_batch(trust, envelope):
    require(isinstance(envelope, dict) and set(envelope) == {"body", "mac"}, "invalid_envelope")
    body, mac = envelope["body"], envelope["mac"]
    require(
        isinstance(body, str) and len(body.encode("utf-8")) <= MAX_BATCH_BYTES, "batch_too_large"
    )
    require(
        isinstance(mac, str)
        and hmac.compare_digest(
            hmac.digest(trust.source_key, SOURCE_DOMAIN + body.encode("utf-8"), "sha256").hex(), mac
        ),
        "unauthenticated_source",
    )
    batch = json.loads(body)
    require(
        isinstance(batch, dict) and type(batch.get("version")) is int and batch["version"] == 1,
        "invalid_batch_version",
    )
    require(all(batch.get(k) == v for k, v in trust.identity().items()), "source_target_mismatch")
    require(
        isinstance(batch.get("events"), list) and 1 <= len(batch["events"]) <= 128,
        "invalid_batch_size",
    )
    return batch["events"]


def verify_event(trust, event, sequence, previous):
    require(
        isinstance(event, dict)
        and set(event)
        == {
            "sequence",
            "event_id",
            "operation_id",
            "stage",
            "outcome",
            "attempt",
            "content",
            "content_hash",
            "previous_hash",
            "chain_hash",
        },
        "invalid_event_fields",
    )
    require(
        type(event.get("sequence")) is int and event["sequence"] == sequence,
        "prefix_gap_or_rollback",
    )
    require(event.get("previous_hash") == previous, "chain_fork")
    content = event.get("content")
    require(
        isinstance(content, str) and len(content.encode("utf-8")) <= 16384, "invalid_event_content"
    )
    require(event.get("content_hash") == digest(content.encode("utf-8")), "content_changed")
    require(
        event.get("chain_hash")
        == digest(bytes.fromhex(previous) + bytes.fromhex(event["content_hash"])),
        "chain_changed",
    )
    entry = json.loads(content)
    require(
        isinstance(entry, dict) and type(entry.get("version")) is int and entry["version"] == 1,
        "invalid_event_version",
    )
    for key in ("installation_id", "stream_id", "anchor_id"):
        require(entry.get(key) == getattr(trust, key), "event_target_mismatch")
    for key in ("sequence", "event_id", "operation_id", "stage", "outcome", "attempt"):
        require(entry.get(key) == event.get(key), "event_envelope_mismatch")
    uuid_text(entry["event_id"])
    require(isinstance(entry.get("issuer"), str) and bool(entry["issuer"]), "event_issuer_missing")
    if sequence == 1:
        require(entry["issuer"] == trust.issuer, "anchor_issuer_mismatch")
        require(
            entry["stage"] == "anchor" and entry["outcome"] == "cutover_unknown_history",
            "anchor_required",
        )
        require(
            all(
                entry.get(k) is None
                for k in (
                    "operation_id",
                    "account_id",
                    "subject",
                    "expected_generation",
                    "deleting_generation",
                    "attempt",
                )
            ),
            "invalid_anchor",
        )
    else:
        uuid_text(entry["operation_id"])
        uuid_text(entry["account_id"])
        require(
            isinstance(entry.get("subject"), str) and 1 <= len(entry["subject"]) <= 255,
            "invalid_subject",
        )
        generation = entry.get("expected_generation")
        require(type(generation) is int and 1 <= generation < 2147483647, "invalid_generation")
        require(
            type(entry.get("deleting_generation")) is int
            and entry["deleting_generation"] == generation + 1,
            "generation_mismatch",
        )
        require(
            (entry["stage"], entry["outcome"])
            in {
                ("legacy", "unknown"),
                ("begin", "intent"),
                ("provider", "intent"),
                ("provider", "confirmed"),
                ("provider", "failed"),
                ("provider", "uncertain"),
                ("confirm", "confirmed"),
                ("purge", "intent"),
                ("purge", "confirmed"),
            },
            "invalid_transition_kind",
        )
        if entry["stage"] == "provider":
            uuid_text(entry["attempt"])
        else:
            require(entry["attempt"] is None, "invalid_attempt")
    return entry


def validate_restore(trust, envelopes, *, backup_point, cutoff, fence_pin=None):
    """Return blocked targets from a full authenticated prefix; never authorize reopen.

    Checkpoints and the independent fence pin are trusted controller inputs.
    A caller must obtain cutoff from O3's physically fenced last-write evidence.
    No clock value or highest received sequence is substituted for that evidence.
    """
    verify_ack(trust, backup_point)
    verify_cutoff(trust, cutoff, fence_pin)
    require(backup_point["sequence"] <= cutoff["sequence"], "cutoff_before_backup")
    sequence, previous, entries, operations = 1, ZERO, [], {}
    seen_backup = False
    seen = {}
    phases = {}
    for envelope in envelopes:
        for event in authenticated_batch(trust, envelope):
            number = event.get("sequence")
            if type(number) is int and number < sequence:
                require(seen.get(number) == event, "prefix_replay_conflict")
                continue
            seen[number] = event
            entry = verify_event(trust, event, sequence, previous)
            previous = event["chain_hash"]
            if sequence == backup_point["sequence"]:
                require(previous == backup_point["chain_hash"], "backup_point_conflict")
                seen_backup = True
            if entry["operation_id"] is not None:
                operation = entry["operation_id"]
                identity = tuple(
                    entry[k]
                    for k in (
                        "account_id",
                        "issuer",
                        "subject",
                        "expected_generation",
                        "deleting_generation",
                    )
                )
                require(
                    operation not in operations or operations[operation] == identity,
                    "operation_target_changed",
                )
                operations[operation] = identity
                phase, attempt = phases.get(operation, (None, None))
                kind = (entry["stage"], entry["outcome"])
                if kind == ("legacy", "unknown"):
                    require(phase is None, "legacy_observation_conflict")
                    phase = "legacy_unknown"
                elif kind == ("begin", "intent"):
                    require(phase is None, "duplicate_begin")
                    phase = "begin"
                elif kind == ("provider", "intent"):
                    require(
                        phase
                        in {"begin", "provider_intent", "provider_failed", "provider_uncertain"},
                        "provider_before_begin_or_after_confirm",
                    )
                    phase, attempt = "provider_intent", entry["attempt"]
                elif entry["stage"] == "provider":
                    require(
                        phase == "provider_intent" and attempt == entry["attempt"],
                        "provider_result_without_attempt",
                    )
                    phase = "provider_" + entry["outcome"]
                elif kind == ("confirm", "confirmed"):
                    require(phase == "provider_confirmed", "confirm_without_provider")
                    phase = "confirm"
                elif kind == ("purge", "intent"):
                    require(phase == "confirm", "purge_without_confirm")
                    phase = "purge_intent"
                elif kind == ("purge", "confirmed"):
                    require(phase == "purge_intent", "purge_without_intent")
                    phase = "purge"
                phases[operation] = phase, attempt
                entries.append(entry)
            sequence += 1
    require(seen_backup, "backup_anchor_missing")
    require(
        sequence - 1 == cutoff["sequence"] and previous == cutoff["chain_hash"],
        "cutoff_missing_or_conflicting",
    )
    # Every operation is fenced, even one still pending or with an uncertain provider.
    return {
        "version": 1,
        "reopen_authorized": False,
        "source_frozen": True,
        "targets": list({entry["operation_id"]: entry for entry in entries}.values()),
    }
