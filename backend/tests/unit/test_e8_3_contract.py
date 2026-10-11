"""Strict DTO and cryptographic addressing tests, without fake database evidence."""

import base64
import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from calorie_app.modules.nemesis.addressing import (
    canonical_request_hash,
    generate_share_code,
    share_code_digest,
    validate_share_code,
)
from calorie_app.modules.nemesis.schemas import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    AcceptNemesis,
    CancelNemesis,
    CreateNemesis,
    EmptyNemesisOperation,
    NemesisMetadata,
    NemesisScope,
    NemesisTerms,
    ShareCodeReceipt,
    validate_body_size,
    validate_response_size,
)


def terms(**changes):
    return {"rule_version": "regularity_v1", "scope": {"regularity": True}, **changes}


@pytest.mark.parametrize("duration", [7, 30, 90])
def test_all_duration_options_and_defaults(duration):
    model = NemesisTerms.model_validate(terms(duration_days=duration))
    assert model.duration_days == duration
    assert model.time_zone == "Europe/Warsaw"
    assert model.scope.model_dump() == {
        "regularity": True,
        "weight_change": False,
        "mean_deficit": False,
    }


@pytest.mark.parametrize("duration", [True, False, "7", 7.0, 0, 1, 6, 8, 29, 31, 91])
def test_duration_is_strict_and_bounded(duration):
    with pytest.raises(ValidationError):
        NemesisTerms.model_validate(terms(duration_days=duration))


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_regularity_requires_exact_true(value):
    with pytest.raises(ValidationError):
        NemesisScope.model_validate({"regularity": value})


def test_regularity_is_required():
    with pytest.raises(ValidationError):
        NemesisScope.model_validate({})


@pytest.mark.parametrize("name", ["weight_change", "mean_deficit"])
@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_optional_scopes_are_strict_booleans(name, value):
    with pytest.raises(ValidationError):
        NemesisScope.model_validate({"regularity": True, name: value})


@pytest.mark.parametrize("scope", ["raw_weight", "meals", "account_id", "anything"])
def test_unrecognized_scopes_are_forbidden(scope):
    with pytest.raises(ValidationError):
        NemesisTerms.model_validate(terms(scope={"regularity": True, scope: True}))


@pytest.mark.parametrize(
    "model,body",
    [
        (EmptyNemesisOperation, {"owner_id": str(uuid4())}),
        (CancelNemesis, {"reason": "sharing_revoked", "note": "medical text"}),
        (AcceptNemesis, {"terms": terms(), "participant_id": str(uuid4())}),
        (CreateNemesis, {"destination_code": "A" * 43, "terms": terms(), "start_at": "now"}),
        (NemesisTerms, terms(score=2)),
    ],
)
def test_operation_authority_and_unknown_fields_rejected(model, body):
    with pytest.raises(ValidationError):
        model.model_validate(body)


@pytest.mark.parametrize("reason", ["withdrawn", "declined", "sharing_revoked"])
def test_narrow_cancel_reasons(reason):
    assert CancelNemesis(reason=reason).reason == reason


@pytest.mark.parametrize("reason", ["expired", "deleted", "restore", "other", "", 1])
def test_caller_cannot_choose_maintenance_reasons(reason):
    with pytest.raises(ValidationError):
        CancelNemesis(reason=reason)


@pytest.mark.parametrize("zone", ["", "../../Europe/Warsaw", "No/Such_Zone", "a" * 101, 1])
def test_invalid_zone_rejected(zone):
    with pytest.raises(ValidationError):
        NemesisTerms.model_validate(terms(time_zone=zone))


@pytest.mark.parametrize("value", ["\x00", "\ud800", "\udfff"])
def test_unicode_invalid_scalar_is_rejected_without_repair(value):
    with pytest.raises(ValidationError):
        CancelNemesis.model_validate({"reason": value})


def test_actual_body_byte_limit_including_whitespace():
    validate_body_size(b" " * MAX_REQUEST_BYTES)
    with pytest.raises(ValueError, match="nemesis_payload_too_large"):
        validate_body_size(b" " * (MAX_REQUEST_BYTES + 1))
    with pytest.raises(ValueError):
        validate_response_size({"items": "x" * MAX_RESPONSE_BYTES})


def test_share_code_uses_32_fresh_csprng_bytes(monkeypatch):
    seen = []

    def entropy(size):
        seen.append(size)
        return bytes(range(size))

    monkeypatch.setattr("calorie_app.modules.nemesis.addressing.secrets.token_bytes", entropy)
    code = generate_share_code()
    assert seen == [32]
    assert len(code) == 43
    assert base64.urlsafe_b64decode(code + "=") == bytes(range(32))
    assert share_code_digest(code) == hashlib.sha256(code.encode("ascii")).hexdigest()
    assert code not in share_code_digest(code)


def test_real_codes_are_distinct_and_roundtrip():
    codes = {generate_share_code() for _ in range(100)}
    assert len(codes) == 100
    assert all(validate_share_code(code) == code for code in codes)


@pytest.mark.parametrize(
    "code", ["A" * 42, "A" * 44, "A" * 42 + "=", "A" * 42 + "+", "A" * 42 + "B", 123, "😃" * 43]
)
def test_code_is_exact_canonical_base64url(code):
    with pytest.raises(ValueError, match="invalid_destination_code_format"):
        validate_share_code(code)
    with pytest.raises(ValidationError):
        CreateNemesis.model_validate({"destination_code": code, "terms": terms()})


def test_code_not_in_model_repr():
    code = generate_share_code()
    model = CreateNemesis(destination_code=code, terms=NemesisTerms.model_validate(terms()))
    assert code not in repr(model)


def test_semantic_hash_normalizes_defaults_and_dictionary_order():
    epoch = uuid4()
    model = AcceptNemesis.model_validate({"terms": terms()})
    explicit = AcceptNemesis.model_validate(
        {
            "terms": terms(
                duration_days=30,
                time_zone="Europe/Warsaw",
                scope={"mean_deficit": False, "regularity": True, "weight_change": False},
            )
        }
    )
    left = canonical_request_hash("accept", model, epoch, 1, UUID(int=1))
    assert left == canonical_request_hash("accept", explicit, epoch, 1, UUID(int=1))
    for changed in [
        canonical_request_hash("cancel", model, epoch, 1, UUID(int=1)),
        canonical_request_hash("accept", model, uuid4(), 1, UUID(int=1)),
        canonical_request_hash("accept", model, epoch, 2, UUID(int=1)),
        canonical_request_hash("accept", model, epoch, 1, UUID(int=2)),
        canonical_request_hash("accept", {"terms": terms(duration_days=7)}, epoch, 1, UUID(int=1)),
    ]:
        assert left != changed


def test_metadata_has_no_partner_account_or_sources():
    fields = NemesisMetadata.model_fields
    assert "partner_pseudonym" in fields
    assert not (
        {"account_id", "partner_id", "owner_id", "email", "weight", "meals"} & fields.keys()
    )
    assert set(fields["status"].annotation.__args__) == {
        "invited",
        "active",
        "finished",
        "cancelled",
    }


def test_receipt_timestamps_are_canonical_utc():
    model = ShareCodeReceipt(
        destination_code=generate_share_code(),
        issued_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at="2026-01-02T00:00:00Z",
    )
    assert model.issued_at == "2026-01-01T00:00:00Z"
    with pytest.raises(ValidationError):
        ShareCodeReceipt(destination_code="A" * 43, issued_at="2026-01-01", expires_at="bad")
