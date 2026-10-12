"""Opaque, single-use addressing material and semantic receipt fingerprints."""

import base64
import hashlib
import re
import secrets
from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel

from calorie_app.core.wire import validate_json_strings
from calorie_app.modules.catalog.validation import canonical_json

SHARE_CODE_BYTES = 32
SHARE_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def generate_share_code() -> str:
    """256 fresh CSPRNG bits; caller retains plaintext only in a bounded own receipt."""
    raw = secrets.token_bytes(SHARE_CODE_BYTES)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def validate_share_code(value) -> str:
    if not isinstance(value, str) or SHARE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid_destination_code_format")
    raw = base64.urlsafe_b64decode(value + "=")
    if len(raw) != SHARE_CODE_BYTES or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value:
        raise ValueError("invalid_destination_code_format")
    return value


def share_code_digest(code: str) -> str:
    validate_share_code(code)
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def canonical_request_hash(
    operation: str,
    body: Mapping | BaseModel,
    epoch: UUID,
    if_match: int | None = None,
    entity_id: UUID | None = None,
) -> str:
    """Hash normalized DTO body and all headers/target that change mutation semantics."""
    if isinstance(body, BaseModel):
        body = body.model_dump(mode="json")
    semantic = {
        "operation": operation,
        "body": dict(body),
        "sync_epoch": str(epoch),
        "if_match": if_match,
        "entity_id": None if entity_id is None else str(entity_id),
    }
    validate_json_strings(semantic)
    return hashlib.sha256(canonical_json(semantic)).hexdigest()
