"""Wire DTOs use the normative bundled schemas, including required nulls."""

import json
from functools import cache
from importlib.resources import files

from jsonschema import Draft202012Validator
from pydantic import RootModel, model_validator
from referencing import Registry, Resource

from calorie_app.modules.catalog.validation import FORMATS
from calorie_app.modules.diary.validation import validate_payload
from calorie_app.modules.profiles.schemas import GoalPayload, ProfilePayload
from calorie_app.modules.sync.errors import SyncFailure

BASE = "https://calorie.invalid/schemas/"
DEFINITIONS = {
    "profile": "Profile",
    "goal": "Goal",
    "meal": "Meal",
    "weight": "Weight",
    "diary_day": "DiaryDay",
    "product_draft": "ProductDraft",
}


@cache
def resources():
    root = files("calorie_app.modules.catalog.resources")
    return {
        name: json.loads(root.joinpath(name).read_text(encoding="utf-8"))
        for name in ("sync.schema.json", "common.schema.json", "domain.schema.json")
    }


@cache
def validator(definition):
    registry = Registry().with_resources(
        (BASE + name, Resource.from_contents(schema)) for name, schema in resources().items()
    )
    return Draft202012Validator(
        {"$ref": BASE + "sync.schema.json#/$defs/" + definition},
        registry=registry,
        format_checker=FORMATS,
    )


def validate_wire(value, definition):
    def exact(part):
        if isinstance(part, float):
            raise ValueError("fractional_wire_number")
        if isinstance(part, dict):
            for item in part.values():
                exact(item)
        if isinstance(part, list):
            for item in part:
                exact(item)

    exact(value)
    if next(validator(definition).iter_errors(value), None) is not None:
        raise ValueError("invalid_sync_wire")


def expanded_schema(definition):
    def resolve(value, document):
        if isinstance(value, list):
            return [resolve(v, document) for v in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            file, pointer = value["$ref"].split("#", 1)
            file = file or document
            target = resources()[file]
            for key in pointer.strip("/").split("/"):
                target = target[key]
            return resolve(target, file)
        return {key: resolve(item, document) for key, item in value.items()}

    return resolve(resources()["sync.schema.json"]["$defs"][definition], "sync.schema.json")


class WireDTO(RootModel[dict]):
    @model_validator(mode="after")
    def wire(self):
        validate_wire(self.root, type(self).__name__)
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        return expanded_schema(cls.__name__)


class PushRequest(WireDTO):
    pass


class PushResponse(WireDTO):
    pass


class PullResponse(WireDTO):
    pass


class SyncError(WireDTO):
    pass


def preflight_structure(data):
    try:
        validate_wire(data, "PushRequest")
        if type(data["protocol_version"]) is not int:
            raise ValueError
        ids, entities = set(), set()
        for operation in data["operations"]:
            key = (operation["entity_type"], operation["entity_id"])
            if operation["operation_id"] in ids or key in entities:
                raise ValueError
            ids.add(operation["operation_id"])
            entities.add(key)
            if operation["action"] == "upsert":
                kind, payload = operation["entity_type"], operation["payload"]
                if kind in {"profile", "goal"}:
                    (ProfilePayload if kind == "profile" else GoalPayload).model_validate(payload)
                else:
                    validate_payload(payload, DEFINITIONS[kind])
    except ValueError:
        raise SyncFailure(422, "invalid_request") from None
