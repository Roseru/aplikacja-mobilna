"""Export strict E9 DTO definitions from the normative FastAPI OpenAPI document."""

import argparse
import json
from pathlib import Path

ROOTS = (
    "AnalysisRequest",
    "DecisionRequest",
    "AffirmRequest",
    "RevertRequest",
    "AnalysisRead",
    "UnavailableRead",
    "AffirmRead",
    "HistoryPage",
    "AnalysisPage",
    "EnergyPullResponse",
    "EnergyState",
)


def generate(openapi):
    schemas = openapi["components"]["schemas"]
    definitions = {}

    def visit(value):
        if isinstance(value, dict):
            if "$ref" in value and value["$ref"].startswith("#/components/schemas/"):
                name = value["$ref"].split("/")[-1]
                if name not in definitions:
                    definitions[name] = schemas[name]
                    visit(schemas[name])
            for part in value.values():
                visit(part)
        elif isinstance(value, list):
            for part in value:
                visit(part)

    for name in ROOTS:
        definitions[name] = schemas[name]
        visit(schemas[name])
    value = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://calorie.invalid/schemas/energy.schema.json",
        "description": ("Generated E9 energy_adjustment_v1, immutable E and opt-in sync DTOs."),
        "$defs": {key: definitions[key] for key in sorted(definitions)},
    }
    return (
        json.dumps(value, ensure_ascii=False, indent=2).replace("#/components/schemas/", "#/$defs/")
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "contracts/schemas/energy.schema.json"
    expected = generate(
        json.loads(Path(__file__).with_name("openapi.json").read_text(encoding="utf-8"))
    )
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != expected:
            parser.error("Stale generated E8 schema")
    else:
        target.write_bytes(expected.encode("utf-8"))
    print("PASS generated E9 structural schema")


if __name__ == "__main__":
    main()
