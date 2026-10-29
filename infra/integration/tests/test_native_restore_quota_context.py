"""Synthetic signed checkpoint scope tests; no DB, network or live tokens."""

from datetime import UTC, datetime
from uuid import uuid4

from infra.local.integration import restore_quota_oracle as quota  # isort: skip

import pytest
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.tokens import context_claims, micros, sign_token
from pydantic import SecretStr


@pytest.fixture
def signed_context():
    now, epoch = datetime.now(UTC), uuid4()
    row, secret = {"id": uuid4(), "generation": 1}, "e4" * 32
    claims = context_claims(owner_id=row["id"], generation=1, epoch=epoch) | {
        "kind": "checkpoint",
        "position": 0,
        "issued": micros(now),
    }
    context = {"checkpoint": sign_token(claims, SecretStr(secret)), "secret": secret}
    return context, row, epoch, now, claims


def test_valid_checkpoint_retains_exact_bytes_and_neutral_ordinary_scope(
    signed_context,
):
    context, row, epoch, now, _ = signed_context
    original = context["checkpoint"]
    copied, scope = quota.validate_private_sync_context(context, row, epoch, now)
    assert copied == context and copied is not context
    assert copied["checkpoint"].encode() == original.encode()
    assert scope == {"protocol": 1, "installation": "calorie-app", "capability": None}
    context["checkpoint"] = "synthetic-mutation-after-validation"
    assert copied["checkpoint"] == original


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("protocol", 2, "invalid_sync_token"),
        ("installation", "calorie-app:energy_estimates_v1", "invalid_sync_token"),
        ("installation", "another-installation", "invalid_sync_token"),
        ("owner", str(uuid4()), "invalid_sync_token"),
        ("generation", 2, "account_generation_changed"),
        ("epoch", str(uuid4()), "sync_epoch_changed"),
    ],
)
def test_valid_mac_foreign_signed_context_refuses(signed_context, field, value, code):
    context, row, epoch, now, claims = signed_context
    # Only newly generated synthetic fixture claims are signed here.
    foreign = context | {
        "checkpoint": sign_token(claims | {field: value}, SecretStr(context["secret"]))
    }
    with pytest.raises(SyncFailure) as caught:
        quota.validate_private_sync_context(foreign, row, epoch, now)
    assert caught.value.code == code


def test_wrong_secret_refuses_without_changing_checkpoint(signed_context):
    context, row, epoch, now, _ = signed_context
    foreign = context | {"secret": "ab" * 32}
    with pytest.raises(SyncFailure) as caught:
        quota.validate_private_sync_context(foreign, row, epoch, now)
    assert caught.value.code == "invalid_sync_token"
    assert foreign["checkpoint"] == context["checkpoint"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"checkpoint": "synthetic"},
        {"checkpoint": "synthetic", "secret": "bad"},
        {
            "checkpoint": "synthetic",
            "secret": "e4" * 32,
            "capability": "energy_estimates_v1",
        },
    ],
)
def test_shape_cannot_introduce_an_unsigned_capability(value):
    with pytest.raises(ValueError):
        quota.validate_private_sync_context(value, {}, None, None)
