"""Explicit opt-in, with signed scope and unchanged legacy request bodies."""

from copy import deepcopy

from pydantic import RootModel, model_validator

from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.schemas import expanded_schema, validate_wire

CAPABILITY = "energy_estimates_v1"
SCOPE = "calorie-app:energy_estimates_v1"


def scope(value):
    if value is None:
        return "calorie-app"
    if value != CAPABILITY:
        raise SyncFailure(422, "invalid_request")
    return SCOPE


def entity_schema():
    from calorie_app.modules.energy.schemas import EnergyEntity

    generated = EnergyEntity.model_json_schema()
    definitions = generated.pop("$defs", {})

    def inline(value):
        if isinstance(value, list):
            return [inline(v) for v in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return inline(definitions[value["$ref"].rsplit("/", 1)[-1]])
        return {k: inline(v) for k, v in value.items()}

    return inline(generated)


class EnergyPullResponse(RootModel[dict]):
    @model_validator(mode="after")
    def wire(self):
        from jsonschema import Draft202012Validator

        from calorie_app.modules.catalog.validation import FORMATS

        value = deepcopy(self.root)
        energy = [v for v in value["entities"] if v.get("entity_type") == "energy_estimate"]
        value["entities"] = [
            v for v in value["entities"] if v.get("entity_type") != "energy_estimate"
        ]
        validate_wire(value, "PullResponse")
        validator = Draft202012Validator(entity_schema(), format_checker=FORMATS)
        if any(next(validator.iter_errors(v), None) is not None for v in energy):
            raise ValueError("invalid energy sync entity")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = expanded_schema("PullResponse")
        schema["properties"]["entities"]["items"]["oneOf"].append(entity_schema())
        return schema
