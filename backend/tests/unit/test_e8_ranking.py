import base64
from uuid import uuid4

import pytest
from pydantic import ValidationError

from calorie_app.core.errors import DomainError
from calorie_app.modules.analytics.motivation.ranking import cursor_digest, new_cursor_token
from calorie_app.modules.analytics.motivation.schemas import RankingEntry, RankingQuery


@pytest.mark.parametrize("bad", [0, 101, True, "01", "1000", "1.0", "+1", " 1", 1.1])
def test_ranking_strict_bounded_limit(bad):
    with pytest.raises(ValidationError):
        RankingQuery(limit=bad)


@pytest.mark.parametrize("limit", [1, 50, 100, "1", "50", "100"])
def test_ranking_legal_limits(limit):
    assert RankingQuery(limit=limit).limit == int(limit)


def test_random_cursor_has_no_encoded_seek_or_identity():
    tokens = {new_cursor_token() for _ in range(100)}
    assert len(tokens) == 100
    owner = str(uuid4()).encode()
    for token in tokens:
        decoded = base64.urlsafe_b64decode(token[4:] + "=")
        assert len(decoded) == 32
        assert owner not in decoded and b"pseudonym" not in decoded and b"points" not in decoded
        assert len(cursor_digest(token)) == 64


@pytest.mark.parametrize(
    "bad", ["", "rk1.abc", "rp1." + "a" * 43, "rk1." + "a" * 44, "rk1." + "!" * 43, None]
)
def test_cursor_malformed_no_private_details(bad):
    with pytest.raises(DomainError) as error:
        cursor_digest(bad)
    assert error.value.status == 422 and error.value.details == []


def test_ranking_cannot_accept_identity_authority():
    row = dict(position=1, pseudonym="Żołnierz", points=10, rank="Rekrut", active_badges=0)
    assert RankingEntry(**row).pseudonym == "Żołnierz"
    with pytest.raises(ValidationError):
        RankingEntry(**row, account_id=str(uuid4()))
    with pytest.raises(ValidationError):
        RankingQuery(owner=str(uuid4()))


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_generated_motivation_schema_checks_windows_line_endings(tmp_path, monkeypatch, eol):
    import importlib.util
    import json
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "e8_export_test", backend / "export_motivation_schema.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Uses the frozen normative generated OpenAPI from the integration checkout.
    source = json.loads(backend.joinpath("openapi.json").read_text(encoding="utf-8"))
    from calorie_app.core.config import Settings
    from calorie_app.main import create_app

    app = create_app(
        Settings(
            database_url="postgresql+psycopg://unused@localhost/unused",
            catalog_page_token_secret="e2" * 32,
        )
    )
    try:
        source.update(components=app.openapi()["components"])
    finally:
        app.state.engine.dispose()
    expected = module.generate(source)
    output_backend = tmp_path / "backend"
    output_backend.mkdir()
    output_backend.joinpath("openapi.json").write_text(json.dumps(source), encoding="utf-8")
    target = tmp_path / "contracts/schemas/motivation.schema.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(expected.replace("\n", eol).encode("utf-8"))
    monkeypatch.setattr(module, "__file__", str(output_backend / "export_motivation_schema.py"))
    monkeypatch.setattr(sys, "argv", [module.__file__, "--check"])
    before = target.read_bytes()
    module.main()
    assert target.read_bytes() == before
    target.write_bytes(before.replace(b"regularity_v1", b"regularity_wrong", 1))
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


def test_registered_e8_examples_match_generated_json_schema():
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    root = Path(__file__).resolve().parents[3] / "contracts"
    schema = json.loads(root.joinpath("schemas/motivation.schema.json").read_text(encoding="utf-8"))
    index = json.loads(root.joinpath("examples/index.json").read_text(encoding="utf-8"))
    for item in index["examples"]:
        if item["server"]["stage"] != "E8":
            continue
        definition = item["schema"].split("#/$defs/")[1]
        validator = Draft202012Validator(schema | {"$ref": "#/$defs/" + definition})
        value = json.loads(root.joinpath("examples", item["path"]).read_text(encoding="utf-8"))
        errors = list(validator.iter_errors(value))
        if item["local"]["result"] == "valid":
            assert not errors, (item["id"], errors)
        else:
            assert item["local"]["reason"] in {error.validator for error in errors}


@pytest.mark.parametrize(
    "code,retry_after", [("ranking_cursor_limit", "600"), ("ai_daily_quota", "86400")]
)
def test_cursor_retry_after_and_legacy_daily_quota_preserved(code, retry_after):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from calorie_app.core.errors import install_error_handlers

    app = FastAPI()

    @app.middleware("http")
    async def context(request, call_next):
        request.state.request_id = str(uuid4())
        return await call_next(request)

    @app.get("/probe")
    def probe():
        raise DomainError(429, code)

    install_error_handlers(app)
    with TestClient(app) as client:
        response = client.get("/probe")
    assert response.status_code == 429
    assert response.headers["retry-after"] == retry_after
