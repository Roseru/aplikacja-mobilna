"""Photo consent and explicit corrections; sync-v1 payloads stay unchanged."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from calorie_app.modules.ai.configuration import NOTICE_VERSION
from calorie_app.modules.ai.result import ProviderFoodItem
from calorie_app.modules.catalog.community.schemas import MatchProductResponse
from calorie_app.modules.catalog.schemas import CatalogDTO, Revision, Timestamp, Uuid
from calorie_app.modules.diary.validation import validate_payload
from calorie_app.modules.sync.schemas import expanded_schema


class PhotoConsent(CatalogDTO):
    accepted: Annotated[StrictBool, Field(json_schema_extra={"const": True})]
    notice_version: Literal["food-photo-notice-v1"]
    provider: Literal["mock", "gemini"]
    scope: Literal["this_photo"]

    @model_validator(mode="after")
    def explicit(self):
        if self.accepted is not True or self.notice_version != NOTICE_VERSION:
            raise ValueError("photo consent required")
        return self


class CreateMetadata(CatalogDTO):
    consent: PhotoConsent


class CancelRequest(CatalogDTO):
    expected_revision: Revision


class MealTemplate(CatalogDTO):
    meal_id: Uuid
    payload: dict

    @model_validator(mode="after")
    def wire(self):
        validate_payload(self.payload, "Meal")
        if len(self.payload["items"]) > 30:
            raise ValueError("too many photo items")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        schema["properties"]["payload"] = expanded_schema("Meal", "domain.schema.json")
        schema["properties"]["payload"]["properties"]["items"]["maxItems"] = 30
        return schema


class DraftTemplate(CatalogDTO):
    draft_id: Uuid
    payload: dict

    @model_validator(mode="after")
    def wire(self):
        validate_payload(self.payload, "ProductDraft")
        if "AI" not in self.payload["source_description"]:
            raise ValueError("AI source description required")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        schema["properties"]["payload"] = expanded_schema("ProductDraft", "domain.schema.json")
        return schema


class ConfirmRequest(CatalogDTO):
    expected_revision: Revision
    meal: MealTemplate
    drafts: Annotated[list[DraftTemplate], Field(max_length=30)] = Field(default_factory=list)

    @model_validator(mode="after")
    def single_ids(self):
        if len({draft.draft_id for draft in self.drafts}) != len(self.drafts):
            raise ValueError("duplicate draft ids")
        return self


class AnalysisProfile(CatalogDTO):
    provider: Literal["mock", "gemini"]
    model: Annotated[str, Field(min_length=1, max_length=100)]
    prompt_version: str
    schema_version: str
    preparation_version: str
    rest_profile_version: str
    mock_scenario: str | None


class CreateResponse(CatalogDTO):
    analysis_id: Uuid
    revision: Revision
    state: Literal["queued", "running", "succeeded", "failed"]
    queue_deadline: Timestamp
    profile: AnalysisProfile


class ProposalItem(ProviderFoodItem):
    component_id: Uuid
    matches: MatchProductResponse


class NutritionTotal(CatalogDTO):
    known_sum: Annotated[str, Field(strict=True, pattern=r"^(0|[1-9][0-9]{0,12})(\.[0-9]{1,12})?$")]
    missing_count: Annotated[StrictInt, Field(ge=0, le=30)]
    complete: StrictBool
    display: Annotated[str, Field(strict=True, pattern=r"^(0|[1-9][0-9]{0,12})(\.[0-9])?$")]

    @model_validator(mode="after")
    def completeness(self):
        if self.complete != (self.missing_count == 0):
            raise ValueError("incoherent totals")
        return self


class NutritionTotals(CatalogDTO):
    energy_kcal: NutritionTotal
    protein_g: NutritionTotal
    fat_g: NutritionTotal
    carbs_g: NutritionTotal


class Proposal(CatalogDTO):
    items: Annotated[list[ProposalItem], Field(min_length=1, max_length=30)]
    notes: Annotated[list[str], Field(max_length=10)]
    totals: NutritionTotals
    model_version: Annotated[str, Field(max_length=200)] | None
    formula_version: Literal["nutrition_v1"]


class AnalysisResponse(CatalogDTO):
    analysis_id: Uuid
    revision: Revision
    state: Literal["queued", "running", "succeeded", "failed"]
    decision_state: Literal["pending", "confirmed", "cancelled"]
    queue_deadline: Timestamp
    photo_expires_at: Timestamp
    profile: AnalysisProfile
    proposal: Proposal | None
    error_code: str | None


class CancelResponse(CatalogDTO):
    analysis_id: Uuid
    revision: Revision
    state: Literal["failed"]
    decision_state: Literal["cancelled"]
    error_code: Literal["analysis_cancelled"]


class ConfirmResponse(CatalogDTO):
    analysis_id: Uuid
    meal: MealTemplate
    drafts: Annotated[list[DraftTemplate], Field(max_length=30)]
    provenance: dict


class Capabilities(CatalogDTO):
    provider: Literal["mock", "gemini"]
    profile: AnalysisProfile
    notice_version: Literal["food-photo-notice-v1"]
    available: StrictBool
    unavailable_reason: str | None
    image_bytes: StrictInt = 5 * 1024 * 1024
    body_bytes: StrictInt = 6 * 1024 * 1024
    ingredients: StrictInt = 30
    daily_photos: StrictInt = 10
    queue_seconds: StrictInt = 300
    attempt_seconds: StrictInt = 45
    total_seconds: StrictInt = 120
    max_generate_attempts: StrictInt = 2
    max_outbound_calls: StrictInt = 2
    active_jobs_per_account: StrictInt = 1
    manual_entry_available: Literal[True] = True


# Included by the proposal schema exporter; this references the existing E6 contract.
MatchingResponse = MatchProductResponse
