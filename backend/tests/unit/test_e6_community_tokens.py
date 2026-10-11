"""Independent signed cursor abuse probes and semantic request hash regression."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import SecretStr

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.community.idempotency import semantic_hash
from calorie_app.modules.catalog.community.tokens import decode_page, encode_page
from calorie_app.modules.catalog.product_pages import expiry_integer

SECRET = SecretStr("e6" * 32)
NOW = datetime(2026, 10, 11, 10, tzinfo=UTC)


def claims():
    return {
        "owner": str(uuid4()),
        "generation": 1,
        "epoch": str(uuid4()),
        "query": "rosół",
        "filter": None,
        "sort": "id",
        "limit": 10,
        "after": str(uuid4()),
        "version": 1,
        "expiry": expiry_integer(NOW + timedelta(hours=1)),
    }


def decode(value, token=None, secret=SECRET, **changes):
    context = {
        "owner": value["owner"],
        "generation": value["generation"],
        "epoch": value["epoch"],
        "query": value["query"],
        "limit": value["limit"],
        "now": NOW,
    }
    return decode_page(token or encode_page(value, SECRET), secret, **(context | changes))


def test_cursor_preserves_original_expiry_after_reencoding():
    value = claims()
    decoded = decode(value)
    assert decoded == value
    assert decode(value, encode_page(decoded, SECRET), now=NOW + timedelta(minutes=59)) == value
    with pytest.raises(DomainError) as failure:
        decode(value, now=NOW + timedelta(hours=1))
    assert (failure.value.status, failure.value.code) == (410, "page_expired")


@pytest.mark.parametrize(
    "field,changed",
    [
        ("owner", str(uuid4())),
        ("generation", 2),
        ("epoch", str(uuid4())),
        ("query", "inny"),
        ("limit", 9),
        ("filter", "open"),
        ("sort", "votes"),
    ],
)
def test_cursor_rejects_context_drift(field, changed):
    value = claims()
    with pytest.raises(DomainError) as failure:
        decode(value, **{field: changed})
    assert failure.value.status == 422


@pytest.mark.parametrize(
    "alteration",
    [
        {"generation": True},
        {"limit": True},
        {"version": True},
        {"version": 0},
        {"expiry": True},
        {"expiry": -1},
        {"after": "bad"},
        {"extra": "spoof"},
    ],
)
def test_even_valid_signature_requires_strict_claim_shape(alteration):
    value = claims()
    altered = value | alteration
    with pytest.raises(DomainError) as failure:
        decode(value, encode_page(altered, SECRET))
    assert failure.value.status == 422


@pytest.mark.parametrize("token", ["bad", "cp1.a.b", "cp1...", "x" * 4097])
def test_invalid_cursor_is_safe422(token):
    with pytest.raises(DomainError) as failure:
        decode(claims(), token)
    assert failure.value.status == 422


def test_cursor_domain_and_key_rotation():
    value = claims()
    with pytest.raises(DomainError):
        decode(value, encode_page(value, SECRET, kind="reports"))
    with pytest.raises(DomainError):
        decode(value, secret=SecretStr("e7" * 32))
    token = encode_page(value, SECRET, kind="reports")
    assert decode(value, token, kind="reports") == value


def test_hash_normalizes_decimal_and_binds_path_versions_content():
    baseline = semantic_hash("PUT", "/a", {"value": Decimal("1.000")}, versions={"vote": 1})
    assert baseline == semantic_hash("PUT", "/a", {"value": Decimal("1")}, versions={"vote": 1})
    assert baseline != semantic_hash("PUT", "/b", {"value": Decimal("1")}, versions={"vote": 1})
    assert baseline != semantic_hash("DELETE", "/a", {"value": Decimal("1")}, versions={"vote": 1})
    assert baseline != semantic_hash("PUT", "/a", {"value": Decimal("2")}, versions={"vote": 1})
    assert baseline != semantic_hash("PUT", "/a", {"value": Decimal("1")}, versions={"vote": 2})
