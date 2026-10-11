"""Required private page metadata and normative E3 payload DTOs."""

from typing import ClassVar

from pydantic import Field, RootModel, model_validator

from calorie_app.modules.catalog.schemas import Revision, Timestamp, Uuid
from calorie_app.modules.diary.validation import validate_payload
from calorie_app.modules.profiles.schemas import DTO, LocalDate, TimelineRevision, TimeZone
from calorie_app.modules.sync.schemas import resources


class DomainPayload(RootModel[dict]):
    definition: ClassVar[str]

    @model_validator(mode="after")
    def valid(self):
        validate_payload(self.root, self.definition)
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        def resolve(value, document):
            if isinstance(value, list):
                return [resolve(part, document) for part in value]
            if not isinstance(value, dict):
                return value
            if "$ref" in value:
                file, pointer = value["$ref"].split("#", 1)
                file = file or document
                target = resources()[file]
                for key in pointer.strip("/").split("/"):
                    target = target[key]
                return resolve(target, file)
            return {key: resolve(part, document) for key, part in value.items()}

        return resolve(
            resources()["domain.schema.json"]["$defs"][cls.definition], "domain.schema.json"
        )


class MealPayload(DomainPayload):
    definition = "Meal"


class WeightPayload(DomainPayload):
    definition = "Weight"


class DiaryDayPayload(DomainPayload):
    definition = "DiaryDay"


class MealRecord(DTO):
    entity_id: Uuid
    revision: Revision
    payload: MealPayload


class WeightRecord(DTO):
    entity_id: Uuid
    revision: Revision
    payload: WeightPayload


class DiaryDayRecord(DTO):
    entity_id: Uuid
    revision: Revision
    payload: DiaryDayPayload
    effective_complete: bool = Field(strict=True)


class ReadPage(DTO):
    account_id: Uuid
    account_generation: Revision
    sync_epoch: Uuid
    as_of: Timestamp
    time_zone: TimeZone | None
    profile_revision: Revision | None
    goal_timeline_revision: TimelineRevision
    server_position: int = Field(strict=True, ge=0, le=9223372036854775807)
    date_from: LocalDate = Field(alias="from")
    date_to: LocalDate = Field(alias="to")
    next_page_token: str | None = Field(min_length=1, max_length=4096)


class MealPage(ReadPage):
    items: list[MealRecord] = Field(max_length=500)


class WeightPage(ReadPage):
    items: list[WeightRecord] = Field(max_length=500)


class DiaryDayPage(ReadPage):
    items: list[DiaryDayRecord] = Field(max_length=500)
