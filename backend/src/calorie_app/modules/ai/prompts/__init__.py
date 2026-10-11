"""Immutable request profile bundled in both wheel and sdist."""

from importlib.resources import files

MODEL = "gemini-3.5-flash-lite"
PROMPT_VERSION = "food-photo-prompt-v1"
SCHEMA_VERSION = "food-photo-schema-v1"
REST_PROFILE_VERSION = "gemini-rest-v1beta-2026-10-11"
INPUT_TOKEN_LIMIT = 8192
OUTPUT_TOKEN_LIMIT = 2048


def system_prompt() -> str:
    return files(__package__).joinpath("food_photo_v1.txt").read_text(encoding="utf-8")


def provider_schema() -> dict:
    """Google's supported JSON Schema subset, deliberately separate from DTO.

    Decimal syntax, Unicode/text limits, identity state/value coherence and
    unit coherence remain enforced by the strict backend parser.
    """
    text = {"type": "string"}
    decimal = {"type": ["string", "null"]}

    def obj(properties):
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    def identity(states):
        return obj({"state": {"type": "string", "enum": states}, "value": decimal.copy()})

    item = obj(
        {
            "name": text.copy(),
            "quantity": obj(
                {"amount": text.copy(), "unit": {"type": "string", "enum": ["g", "ml"]}}
            ),
            "basis_unit": {"type": "string", "enum": ["g", "ml"]},
            "nutrition_per_100": obj(
                {key: decimal.copy() for key in ("energy_kcal", "protein_g", "fat_g", "carbs_g")}
            ),
            "identity": obj(
                {
                    "brand": identity(["known", "unknown", "not_applicable"]),
                    "variant": identity(["known", "unknown", "not_applicable"]),
                    # A recipe string is an E6 CompositionValue. Choosing this
                    # subset avoids unsupported anyOf/string-or-array schema.
                    "composition": identity(["known", "unknown"]),
                }
            ),
            "density": {"type": "null"},
            "uncertainty": {"type": "string", "enum": ["low", "medium", "high"]},
            "notes": {"type": "array", "items": text.copy(), "maxItems": 5},
        }
    )
    return obj(
        {
            "items": {"type": "array", "items": item, "maxItems": 30},
            "notes": {"type": "array", "items": text.copy(), "maxItems": 10},
        }
    )
