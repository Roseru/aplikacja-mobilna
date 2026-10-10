import json
import re
from importlib.resources import files
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.catalog.schemas import ManifestDTO, ProductDTO, RationDTO, RationPage

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
PUBLIC_ROUTES = {
    "/rations": ("list_rations", "ration-page.json", "domain.schema.json", "RationPage"),
    "/rations/{id}": ("read_ration", "ration.json", "catalog.schema.json", "Ration"),
    "/offline-package/manifest": (
        "read_manifest",
        "catalog-manifest.json",
        "catalog.schema.json",
        "Manifest",
    ),
    "/offline-package/{filename}": ("download_package", None, None, None),
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def expand(value, document):
    if isinstance(value, dict):
        if "$ref" in value:
            assert value["$ref"].startswith("#/")
            nested = document
            for key in value["$ref"][2:].split("/"):
                nested = nested[key.replace("~1", "/").replace("~0", "~")]
            return {
                **expand(nested, document),
                **{key: expand(item, document) for key, item in value.items() if key != "$ref"},
            }
        return {key: expand(item, document) for key, item in value.items()}
    if isinstance(value, list):
        return [expand(item, document) for item in value]
    return value


def normative(schema, definition):
    registry = Registry().with_resources(
        (path.as_uri(), Resource.from_contents(read(path)))
        for path in (CONTRACTS / "schemas").glob("*.json")
    )
    uri = (CONTRACTS / "schemas" / schema).as_uri()
    return Draft202012Validator(
        {"$ref": uri + "#/$defs/" + definition}, registry=registry, format_checker=FormatChecker()
    )


@pytest.fixture
def app():
    application = create_app(
        Settings(
            database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        )
    )
    yield application
    application.state.engine.dispose()


def test_resources_and_demo_are_exact_normative_copies():
    resources = files("calorie_app.modules.catalog.resources")
    for filename in ("common.schema.json", "catalog.schema.json"):
        assert (
            resources.joinpath(filename).read_bytes()
            == (CONTRACTS / "schemas" / filename).read_bytes()
        )
    assert (ROOT / "backend/data/demo/seed.json").read_bytes() == (
        CONTRACTS / "examples/valid/catalog-demo.json"
    ).read_bytes()


def test_active_contracts_have_no_duplicate_operations_and_keep_real_auth_for_e3(app):
    generated = app.openapi()
    design = (CONTRACTS / "openapi/design-v1.yaml").read_text("utf-8")
    draft_paths = set(re.findall(r"^  (/[^\s:]+):$", design, re.MULTILINE))
    assert generated["openapi"] == "3.1.0"
    for path, (operation_id, *_rest) in PUBLIC_ROUTES.items():
        assert path not in draft_paths
        operation = generated["paths"]["/api/v1" + path]["get"]
        assert operation["operationId"] == operation_id
        assert operation["security"] == []
    for path in ("/products", "/products/{id}"):
        assert path in draft_paths and "/api/v1" + path not in generated["paths"]
        block = re.search(
            r"^  " + re.escape(path) + r":\n(.*?)(?=^  /|^components:)",
            design,
            re.MULTILINE | re.DOTALL,
        ).group(1)
        assert "x-implementation-stage: E3" in block
        assert "security:\n      - bearerAuth: []" in block
    operation_ids = re.findall(r"^      operationId: (\S+)$", design, re.MULTILINE)
    operation_ids.extend(
        method["operationId"]
        for route in generated["paths"].values()
        for method in route.values()
        if "operationId" in method
    )
    assert len(operation_ids) == len(set(operation_ids))


def test_committed_api_is_generated_from_current_application(app):
    assert read(ROOT / "backend/openapi.json") == app.openapi()


@pytest.mark.parametrize("route", list(PUBLIC_ROUTES)[:-1])
def test_generated_responses_and_normative_schemas_accept_retained_shapes(app, route):
    document = app.openapi()
    _, filename, schema_name, definition = PUBLIC_ROUTES[route]
    value = read(CONTRACTS / "examples/valid" / filename)
    schema = document["paths"]["/api/v1" + route]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    expanded_schema = expand(schema, document)
    Draft202012Validator.check_schema(expanded_schema)
    Draft202012Validator(expanded_schema, format_checker=FormatChecker()).validate(value)
    normative(schema_name, definition).validate(value)
    # Nullable means an explicit null. The required property cannot disappear.
    invalid = dict(value)
    del invalid[
        "next_page_token"
        if definition == "RationPage"
        else "manufacturer"
        if definition == "Ration"
        else "published_at"
    ]
    assert not Draft202012Validator(expanded_schema).is_valid(invalid)
    assert not normative(schema_name, definition).is_valid(invalid)


def test_current_dtos_serialize_to_e0_schemas():
    package = read(CONTRACTS / "examples/valid/catalog-demo.json")
    fixtures = [
        (ProductDTO, package["products"][0], "catalog.schema.json", "Product"),
        (RationDTO, package["rations"][0], "catalog.schema.json", "Ration"),
        (
            RationPage,
            {"items": package["rations"], "next_page_token": None},
            "domain.schema.json",
            "RationPage",
        ),
        (
            ManifestDTO,
            read(CONTRACTS / "examples/valid/catalog-manifest.json"),
            "catalog.schema.json",
            "Manifest",
        ),
    ]
    for model, value, schema, definition in fixtures:
        serialized = model.model_validate(value).model_dump(mode="json")
        normative(schema, definition).validate(serialized)
        assert serialized == value


def test_download_contract_has_exact_gzip_media_size_and_constrained_filename(app):
    operation = app.openapi()["paths"]["/api/v1/offline-package/{filename}"]["get"]
    success = operation["responses"]["200"]
    assert success["content"] == {
        "application/gzip": {"schema": {"type": "string", "format": "binary"}},
    }
    assert "Content-Encoding" not in success.get("headers", {})
    size = success["headers"]["Content-Length"]["schema"]
    assert size == {"type": "integer", "minimum": 1, "maximum": 10485760}
    manifest = read(CONTRACTS / "examples/valid/catalog-manifest.json")
    Draft202012Validator(size).validate(manifest["compressed_bytes"])
    filename = next(
        parameter for parameter in operation["parameters"] if parameter["name"] == "filename"
    )
    assert filename["in"] == "path" and filename["required"]
    validator = Draft202012Validator(filename["schema"])
    assert validator.is_valid(manifest["path"])
    for invalid in ("../base-pl.1.json.gz", "base-pl.0.json.gz", "demo.json.gz"):
        assert not validator.is_valid(invalid)


@pytest.mark.parametrize("route", list(PUBLIC_ROUTES))
def test_public_error_schemas_accept_e0_error_examples(app, route):
    document = app.openapi()
    responses = document["paths"]["/api/v1" + route]["get"]["responses"]
    for status in ("404", "422", "503", *(("410",) if route == "/rations" else ())):
        schema = expand(responses[status]["content"]["application/json"]["schema"], document)
        value = read(CONTRACTS / f"examples/valid/error-{status}.json")
        Draft202012Validator(schema).validate(value)
        normative("domain.schema.json", "Error").validate(value)


@pytest.mark.parametrize(
    "url,status",
    [
        ("/api/v1/rations?limit=0", 422),
        ("/api/v1/rations?include_demo=true", 422),
        ("/api/v1/rations/not-a-uuid", 422),
        ("/api/v1/offline-package/base-pl.0.json.gz", 422),
        ("/api/v1/products", 404),
    ],
)
def test_public_errors_from_real_handlers_match_e0(app, url, status):
    with TestClient(app) as client:
        response = client.get(url)
    assert response.status_code == status
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    normative("domain.schema.json", "Error").validate(response.json())
