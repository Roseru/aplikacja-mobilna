from datetime import date
from uuid import uuid4

import pytest

from calorie_app.core.errors import DomainError
from calorie_app.modules.diary import read_tokens
from calorie_app.modules.diary.read_service import validate_query
from calorie_app.modules.sync.tokens import context_claims, sign_token


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"from": "2026-01-01"},
        {"from": "2026-1-01", "to": "2026-01-01"},
        {"from": "2026-02-30", "to": "2026-03-01"},
        {"from": "2026-01-02", "to": "2026-01-01"},
        {"from": "2026-01-01", "to": "2027-01-02"},
        {"from": "2026-01-01", "to": "2026-01-01", "owner": "other"},
    ]
    + [
        {"from": "2026-01-01", "to": "2026-01-01", "limit": value}
        for value in [True, 0, 501, "+1", "1.0", "1000", None]
    ]
    + [
        {"from": "2026-01-01", "to": "2026-01-01", "page_token": value}
        for value in ["", "x" * 4097, None]
    ],
)
def test_invalid_queries(query):
    with pytest.raises(DomainError, match="invalid_request"):
        validate_query(query)


def test_inclusive_366_days_and_defaults():
    result = validate_query({"from": "2024-01-01", "to": "2024-12-31"})
    assert result == {"from": date(2024, 1, 1), "to": date(2024, 12, 31), "limit": 100}
    assert (
        validate_query({"from": "2026-01-01", "to": "2026-01-01", "limit": "500"})["limit"] == 500
    )


@pytest.mark.parametrize("case", ["owner", "generation", "epoch", "purpose", "tamper", "sync"])
def test_read_token_bindings_and_domain(case):
    owner, epoch = uuid4(), uuid4()
    context = {"owner_id": owner, "generation": 1, "epoch": epoch}
    claims = context_claims(**context) | {"kind": "read_page"}
    token = read_tokens.sign(claims, "e2" * 32)
    assert read_tokens.verify(token, "e2" * 32, **context) == claims
    if case in context:
        context[case] = uuid4() if case != "generation" else 2
    elif case == "owner":
        context["owner_id"] = uuid4()
    elif case == "purpose":
        token = read_tokens.sign(claims | {"kind": "page"}, "e2" * 32)
    elif case == "tamper":
        token = token[:-1] + ("A" if token[-1] != "A" else "B")
    elif case == "sync":
        token = sign_token(claims, "e2" * 32)
    with pytest.raises(DomainError):
        read_tokens.verify(token, "e2" * 32, **context)
