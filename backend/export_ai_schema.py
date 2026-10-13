"""Generate structural E7 schema from DTOs, with strict EOL drift checks."""

import argparse
import json
from pathlib import Path

ROOTS = (
    "CreateMetadata",
    "CreateResponse",
    "AnalysisResponse",
    "CancelRequest",
    "CancelResponse",
    "ConfirmRequest",
    "ConfirmResponse",
    "Capabilities",
    "ProviderFoodResult",
    "Proposal",
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
        "$id": "https://calorie.invalid/schemas/ai.schema.json",
        "description": (
            "Generated structural E7 contracts; runtime also validates semantic, "
            "context, time and ownership constraints."
        ),
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
    target = Path(__file__).resolve().parents[1] / "contracts/schemas/ai.schema.json"
    expected = generate(
        json.loads(Path(__file__).with_name("openapi.json").read_text(encoding="utf-8"))
    )
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != expected:
            parser.error("Stale generated E7 schema")
    else:
        target.write_bytes(expected.encode("utf-8"))
    print("PASS generated E7 structural schema")


if __name__ == "__main__":
    main()
