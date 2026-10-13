"""The new contract is generated from API DTOs and packaged identically."""

import json
from importlib.resources import files
from pathlib import Path

from export_energy_schema import generate

ROOT = Path(__file__).resolve().parents[3]


def test_energy_schema_is_generated_and_installed_resource_matches():
    api = json.loads((ROOT / "backend/openapi.json").read_text(encoding="utf-8"))
    source = (ROOT / "contracts/schemas/energy.schema.json").read_text(encoding="utf-8")
    assert source == generate(api)
    assert (
        files("calorie_app.modules.catalog.resources")
        .joinpath("energy.schema.json")
        .read_text(encoding="utf-8")
        == source
    )
