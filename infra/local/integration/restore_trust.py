"""Pure pre-restore authentication, rooted in the controller's external SHA pin."""

import hashlib
import json
import re
from pathlib import Path

from . import native  # isort: skip

from backup import private_write

from calorie_app.modules.identity.ledger_contract import (
    FencePin,
    Trust,
    validate_restore,
)

FORMAT = "native-external-restore-checkpoint/v1"


def read_witness(state, name):
    folder = native.confined(Path(state["witness_directory"]))
    path = native.confined(folder / name)
    if path.is_symlink() or path.is_junction():
        raise ValueError("Linked independent witness")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != state["witness_files"][name]:
        raise ValueError("Independent witness changed")
    return json.loads(raw)


def load_evidence(state):
    # These controller inputs are kept outside the rollback set. Never load them
    # from a restored DB or derive an expected fence from the received tail.
    raw = read_witness(state, "trust-private.json")
    observation = read_witness(state, "fence-observation.json")
    fence = read_witness(state, "fence-pin.json")
    expected = state["witness_files"]["fence-observation.json"]
    if fence["fence_sha256"] != expected or fence["fence_id"] != observation["observation_id"]:
        raise ValueError("Independent fence observation mismatch")
    return {
        "trust": raw,
        "backup_point": read_witness(state, "backup-point.json"),
        "cutoff": read_witness(state, "cutoff.json"),
        "fence_pin": fence,
        "envelopes": read_witness(state, "prefix-private.json"),
    }


def validate_evidence(evidence):
    raw = evidence["trust"]
    trust = Trust(**(raw | {k: bytes.fromhex(raw[k]) for k in ("source_key", "ack_key")}))
    fence = FencePin(**evidence["fence_pin"])
    result = validate_restore(
        trust,
        evidence["envelopes"],
        backup_point=evidence["backup_point"],
        cutoff=evidence["cutoff"],
        fence_pin=fence,
    )
    return trust, fence, result


def bind_capture(captured, evidence):
    trust, _, _ = validate_evidence(evidence)
    backup = evidence["backup_point"]
    expected = trust.identity() | {
        "issuer": trust.issuer,
        "sequence": backup["sequence"],
        "chain_hash": backup["chain_hash"],
    }
    if captured.get("ledger_backup") != expected:
        raise ValueError("Captured database differs from trusted ledger backup point")


def write_checkpoint(path, captured, ledger_state):
    """Called by the trusted controller using capture's already-held return value.

    The manifest pin was taken during OWNED capture, before later source writes.
    This function never reads the archive to manufacture a new expected pin.
    The returned SHA must be supplied independently to public restore().
    """
    path = native.confined(path)
    if path.exists():
        raise FileExistsError("Existing trusted checkpoint preserved")
    evidence = load_evidence(ledger_state)
    bind_capture(captured, evidence)
    value = {
        "format": FORMAT,
        "archive_manifest_sha256": captured["trusted_manifest_sha256"],
        "source_owner": captured["source_owner"],
        "ledger": evidence,
    }
    encoded = json.dumps(value, sort_keys=True, indent=2) + "\n"
    private_write(path, encoded)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preflight(archive, checkpoint, expected_sha256):
    """No DB/process calls: refuse every untrusted input before target creation."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Independent checkpoint SHA256 required")
    path = native.confined(checkpoint)
    if path.is_symlink() or path.is_junction():
        raise ValueError("Linked trusted checkpoint")
    checkpoint_bytes = path.read_bytes()
    if hashlib.sha256(checkpoint_bytes).hexdigest() != expected_sha256:
        raise ValueError("Trusted checkpoint checksum mismatch")
    value = json.loads(checkpoint_bytes)
    if value.get("format") != FORMAT:
        raise ValueError("Unsupported trusted checkpoint")
    validate_evidence(value["ledger"])
    manifest_path = native.confined(archive / "manifest.json")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != value["archive_manifest_sha256"]:
        raise ValueError("Archive differs from independently captured pin")
    manifest = json.loads(manifest_bytes)
    bind_capture(manifest, value["ledger"])
    return value | {"_manifest_bytes": manifest_bytes, "_manifest": manifest}
