"""Strict online community contracts, independent of sync-v1 and official DTOs."""

from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, StrictBool, StrictInt, model_validator

from calorie_app.modules.catalog.schemas import (
    CatalogDTO,
    NutritionDTO,
    PageToken,
    PositiveDecimal,
    ProductRefDTO,
    QuantityDTO,
    Revision,
    Unit,
    Uuid,
)
from calorie_app.modules.catalog.schemas import (
    Text as CatalogText,
)


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text cannot contain only whitespace")
    return value


Text = Annotated[CatalogText, AfterValidator(_nonblank)]
SourceKind = Literal["label", "recipe", "estimate", "ai"]
NutritionField = Literal["energy_kcal", "protein_g", "fat_g", "carbs_g"]
IdentityField = Literal["brand", "variant", "composition", "energy_kcal"]
Count = Annotated[StrictInt, Field(ge=0)]
Aliases = Annotated[list[Text], Field(max_length=50)]
RecipeText = Annotated[str, Field(strict=True, min_length=1, max_length=4000)]
CompositionValue = RecipeText | Annotated[list[Text], Field(min_length=1, max_length=100)]


class IdentityFieldDTO(CatalogDTO):
    state: Literal["known", "unknown", "not_applicable"]
    value: Text | None

    @model_validator(mode="after")
    def state_value(self) -> Self:
        if (self.state == "known") != (self.value is not None):
            raise ValueError("known requires a value; other states require null")
        if self.value is not None and not self.value.strip():
            raise ValueError("identity cannot contain only whitespace")
        return self


class CompositionDTO(CatalogDTO):
    state: Literal["known", "unknown"]
    value: CompositionValue | None

    @model_validator(mode="after")
    def state_value(self) -> Self:
        if (self.state == "known") != (self.value is not None):
            raise ValueError("known composition requires a value; unknown requires null")
        values = [self.value] if isinstance(self.value, str) else self.value or []
        if any(not value.strip() for value in values):
            raise ValueError("composition cannot contain only whitespace")
        return self


class IdentityDTO(CatalogDTO):
    brand: IdentityFieldDTO
    variant: IdentityFieldDTO
    composition: CompositionDTO


class PublicationDensityDTO(CatalogDTO):
    amount: PositiveDecimal
    source_description: Text


class MatchProductRequest(CatalogDTO):
    draft_id: Uuid
    draft_revision: Revision
    source_kind: SourceKind
    source_description: Text
    identity: IdentityDTO
    aliases: Aliases = Field(default_factory=list)
    portion: QuantityDTO | None = None
    density: PublicationDensityDTO | None = None


class PublishProductRequest(MatchProductRequest):
    selected_product: ProductRefDTO | None = None
    confirm_new: StrictBool = False

    @model_validator(mode="after")
    def single_decision(self) -> Self:
        if self.selected_product is not None and self.confirm_new:
            raise ValueError("selected_product and confirm_new are mutually exclusive")
        return self


class PublishProductResult(CatalogDTO):
    decision: Literal["new_product", "existing_variant", "selected_existing"]
    product: ProductRefDTO


PublishProductResponse = PublishProductResult


class MatchCandidateDTO(CatalogDTO):
    product: ProductRefDTO
    provenance: Literal["official", "community"]
    reasons: Annotated[list[Text], Field(min_length=1, max_length=20)]
    high_confidence: StrictBool


class MatchProductResponse(CatalogDTO):
    decision: Literal["existing_variant", "manual_candidates", "new_product"]
    existing_product: ProductRefDTO | None
    candidates: Annotated[list[MatchCandidateDTO], Field(max_length=20)]
    missing_identity_fields: Annotated[list[IdentityField], Field(max_length=4)]
    truncated: StrictBool

    @model_validator(mode="after")
    def coherent_decision(self) -> Self:
        if (self.decision == "existing_variant") != (self.existing_product is not None):
            raise ValueError("existing_variant requires its exact reference")
        if self.decision != "manual_candidates" and self.missing_identity_fields:
            raise ValueError("incomplete matching identity requires manual_candidates")
        return self


class CommunityProductDTO(CatalogDTO):
    product_id: Uuid
    revision: Revision
    canonical_ref: ProductRefDTO
    state_revision: Revision
    name: Text
    aliases: Aliases
    brand: Text | None
    variant: Text | None
    identity: IdentityDTO
    basis_unit: Unit
    nutrition_per_100: NutritionDTO
    portion: QuantityDTO
    density: PublicationDensityDTO | None
    source_id: Uuid
    source_kind: SourceKind
    source_description: Text
    provenance: Literal["community"]
    verification: Literal["unverified", "verified"]
    visibility: Literal["visible", "hidden"]
    complete: StrictBool
    missing_nutrition_fields: Annotated[list[NutritionField], Field(max_length=4)]
    missing_identity_fields: Annotated[list[IdentityField], Field(max_length=4)]
    positive_votes: Count
    negative_votes: Count
    voters: Count
    is_mine: StrictBool

    @model_validator(mode="after")
    def coherent_snapshot(self) -> Self:
        expected = [
            key for key, value in self.nutrition_per_100.model_dump().items() if value is None
        ]
        if self.missing_nutrition_fields != expected or self.complete != (not expected):
            raise ValueError("nutrition completeness must describe exact null fields")
        missing = [
            key
            for key in ("brand", "variant", "composition")
            if getattr(self.identity, key).state == "unknown"
        ]
        if self.nutrition_per_100.energy_kcal is None:
            missing.append("energy_kcal")
        if self.missing_identity_fields != missing:
            raise ValueError("identity completeness must remain separate from nutrition")
        if self.verification == "verified" and not self.complete:
            raise ValueError("verified requires complete nutrition")
        if self.portion.unit != self.basis_unit and self.density is None:
            raise ValueError("cross-unit portion requires documented density")
        if self.voters != self.positive_votes + self.negative_votes:
            raise ValueError("voters must equal separate positive and negative counts")
        for key in ("brand", "variant"):
            field = getattr(self.identity, key)
            if getattr(self, key) != field.value:
                raise ValueError("brand and variant must agree with identity states")
        return self


class CommunityProductPage(CatalogDTO):
    items: Annotated[list[CommunityProductDTO], Field(max_length=500)]
    next_page_token: PageToken | None


class VoteRequest(CatalogDTO):
    value: Annotated[StrictInt, Field(ge=-1, le=1, json_schema_extra={"enum": [-1, 1]})]

    @model_validator(mode="after")
    def nonzero(self) -> Self:
        if self.value == 0:
            raise ValueError("vote must be 1 or -1")
        return self


class VoteResultDTO(CatalogDTO):
    revision: Count
    value: Annotated[StrictInt, Field(ge=-1, le=1, json_schema_extra={"enum": [-1, 1]})] | None

    @model_validator(mode="after")
    def nonzero(self) -> Self:
        if self.value == 0:
            raise ValueError("withdrawn vote is null")
        return self


class FeedbackDTO(CatalogDTO):
    product: ProductRefDTO
    positive_votes: Count
    negative_votes: Count
    voters: Count
    my_value: Annotated[StrictInt, Field(ge=-1, le=1, json_schema_extra={"enum": [-1, 1]})] | None
    my_revision: Count
    is_mine: StrictBool

    @model_validator(mode="after")
    def coherent_votes(self) -> Self:
        if self.my_value == 0 or self.voters != self.positive_votes + self.negative_votes:
            raise ValueError("invalid feedback counts or value")
        return self


ReportStatus = Literal["open", "resolved", "dismissed", "referred_to_admin"]


class ReportRequest(CatalogDTO):
    product: ProductRefDTO
    reason: Text
    description: Text


class ReportResultDTO(CatalogDTO):
    report_id: Uuid
    revision: Revision
    status: ReportStatus
