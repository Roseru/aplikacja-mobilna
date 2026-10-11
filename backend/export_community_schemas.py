"""Derive structural E6 JSON Schema from the normative generated OpenAPI."""

import argparse
import json
from pathlib import Path

ROOTS = (
    "PublishProductRequest",
    "PublishProductResult",
    "MatchProductRequest",
    "MatchProductResponse",
    "CommunityProductDTO",
    "CommunityProductPage",
    "FeedbackDTO",
    "VoteRequest",
    "VoteResultDTO",
    "ReportRequest",
    "ReportResultDTO",
    "ModerateProductRequest",
    "ModerationProductResultDTO",
    "MergeProductRequest",
    "MergeProductResultDTO",
    "ReportResolutionRequest",
    "ModerationReportDTO",
    "ModerationReportPage",
)


def generate(openapi):
    schemas = openapi["components"]["schemas"]
    selected = {}

    def visit(value):
        if isinstance(value, dict):
            if "$ref" in value and value["$ref"].startswith("#/components/schemas/"):
                name = value["$ref"].split("/")[-1]
                if name not in selected:
                    selected[name] = schemas[name]
                    visit(schemas[name])
            for part in value.values():
                visit(part)
        elif isinstance(value, list):
            for part in value:
                visit(part)

    for name in ROOTS:
        selected[name] = schemas[name]
        visit(schemas[name])
    data = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://calorie.invalid/schemas/community.schema.json",
        "description": (
            "Generated structural E6 contracts; runtime also enforces semantic validators."
        ),
        "$defs": {name: selected[name] for name in sorted(selected)},
    }
    return (
        json.dumps(data, ensure_ascii=False, indent=2).replace("#/components/schemas/", "#/$defs/")
        + "\n"
    ).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    backend = Path(__file__).resolve().parent
    expected = generate(json.loads((backend / "openapi.json").read_text(encoding="utf-8")))
    target = backend.parent / "contracts/schemas/community.schema.json"
    if args.check:
        # Git may check text out as CRLF on Windows. Keep the generated text
        # (including indentation/order/final newline) strict, allowing only EOL.
        if not target.exists() or target.read_text(encoding="utf-8") != expected.decode("utf-8"):
            parser.error("Stale generated community schema")
    else:
        target.write_bytes(expected)
    print("PASS generated community structural schema")


if __name__ == "__main__":
    main()
