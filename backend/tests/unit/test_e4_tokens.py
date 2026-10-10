from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr

from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.snapshots import validate_query
from calorie_app.modules.sync.tokens import (
    context_claims,
    sign_checkpoint,
    sign_token,
    validate_checkpoint,
)

SECRET = SecretStr("13" * 32)


@pytest.fixture
def context():
    return {
        "owner_id": uuid4(),
        "generation": 1,
        "epoch": uuid4(),
        "installation_id": "isolated-e4",
    }


def test_checkpoint_exact_30_days_and_next_microsecond(context):
    issued = datetime(2026, 10, 10, tzinfo=UTC)
    token = sign_checkpoint(SECRET, position=7, now=issued, **context)
    assert (
        validate_checkpoint(token, SECRET, now=issued + timedelta(days=30), **context)["position"]
        == 7
    )
    for push, code, status in (
        (False, "sync_cursor_expired", 410),
        (True, "sync_reconciliation_required", 409),
    ):
        with pytest.raises(SyncFailure) as error:
            validate_checkpoint(
                token, SECRET, now=issued + timedelta(days=30, microseconds=1), push=push, **context
            )
        assert (error.value.code, error.value.status) == (code, status)
        assert error.value.details["recovery_required"] == "full_snapshot"


@pytest.mark.parametrize(
    "field,value",
    [("owner_id", uuid4()), ("generation", 2), ("epoch", uuid4()), ("installation_id", "other")],
)
def test_binding_rejects_other_context(context, field, value):
    now = datetime(2026, 10, 10, tzinfo=UTC)
    token = sign_checkpoint(SECRET, position=7, now=now, **context)
    expected = {"generation": "account_generation_changed", "epoch": "sync_epoch_changed"}.get(
        field, "invalid_sync_token"
    )
    with pytest.raises(SyncFailure, match=expected):
        validate_checkpoint(token, SECRET, now=now, **(context | {field: value}))


@pytest.mark.parametrize("kind", ["snapshot", "page"])
def test_non_checkpoint_token_never_authorizes_push(context, kind):
    now = datetime(2026, 10, 10, tzinfo=UTC)
    token = sign_token(
        context_claims(**context) | {"kind": kind, "session": str(uuid4()), "offset": 1}, SECRET
    )
    with pytest.raises(SyncFailure, match="invalid_sync_token"):
        validate_checkpoint(token, SECRET, now=now, push=True, **context)


def test_signature_canonicalization_and_future_issuance(context):
    now = datetime(2026, 10, 10, tzinfo=UTC)
    token = sign_checkpoint(SECRET, position=0, now=now, **context)
    with pytest.raises(SyncFailure, match="invalid_sync_token"):
        validate_checkpoint(token, SECRET, now=now - timedelta(microseconds=1), **context)
    for altered in (token[:-2] + "xx", token + "=", token.replace("sync1", "rp1")):
        with pytest.raises(SyncFailure, match="invalid_sync_token"):
            validate_checkpoint(altered, SECRET, now=now, **context)
    with pytest.raises(SyncFailure, match="invalid_sync_token"):
        validate_checkpoint(token, SecretStr("14" * 32), now=now, **context)


@pytest.mark.parametrize(
    "query",
    [
        {"page_token": "p"},
        {"checkpoint": "c"},
        {"snapshot_token": "s"},
        {"checkpoint": "c", "sync_epoch": str(uuid4()), "snapshot_token": "s"},
        {"checkpoint": "c", "sync_epoch": str(uuid4()), "recovery_operation_ids": [str(uuid4())]},
        {"limit": 0},
        {"limit": 501},
        {"limit": True},
        {"limit": "1.0"},
        {"limit": "²"},
        {"sync_epoch": "NOTUUID"},
        {"recovery_operation_ids": []},
        {"recovery_operation_ids": [str(uuid4())] * 2},
        {"unknown": 1},
    ],
)
def test_pull_query_rejects_mixed_modes_and_invalid_structure(query):
    with pytest.raises(SyncFailure, match="invalid_request"):
        validate_query(query)


def test_pull_query_valid_modes():
    epoch = str(uuid4())
    assert validate_query({}) == {"limit": 500}
    assert validate_query({"limit": "1"})["limit"] == 1
    assert (
        validate_query({"checkpoint": "c", "sync_epoch": epoch, "page_token": "p"})["limit"] == 500
    )
    assert (
        validate_query({"snapshot_token": "s", "sync_epoch": epoch, "page_token": "p"})["limit"]
        == 500
    )
