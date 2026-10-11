"""Explicit versioned correction, state, report and merge contracts."""

from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, model_validator

from calorie_app.modules.catalog.community.schemas import (
    Aliases,
    IdentityDTO,
    PublicationDensityDTO,
    ReportStatus,
    SourceKind,
    Text,
)
from calorie_app.modules.catalog.schemas import (
    CatalogDTO,
    NutritionDTO,
    PageToken,
    ProductRefDTO,
    QuantityDTO,
    Revision,
    Unit,
    Uuid,
)


class ProductCorrectionDTO(CatalogDTO):
    name: Text
    aliases: Aliases
    identity: IdentityDTO
    basis_unit: Unit
    nutrition_per_100: NutritionDTO
    portion: QuantityDTO
    density: PublicationDensityDTO | None
    source_kind: SourceKind
    source_description: Text

    @model_validator(mode="after")
    def quantity_basis(self) -> Self:
        if not self.name.strip():
            raise ValueError("name cannot contain only whitespace")
        if self.portion.unit != self.basis_unit and self.density is None:
            raise ValueError("cross-unit portion requires documented density")
        return self


class ModerateProductRequest(CatalogDTO):
    expected_state_revision: Revision
    reason: Text
    correction: ProductCorrectionDTO | None = None
    verification: Literal["unverified", "verified"] | None = None
    visibility: Literal["visible", "hidden"] | None = None
    source_confirmed: StrictBool = False

    @model_validator(mode="after")
    def actual_change(self) -> Self:
        if self.correction is None and self.verification is None and self.visibility is None:
            raise ValueError("moderation requires a correction or state decision")
        if self.verification == "verified" and not self.source_confirmed:
            raise ValueError("verification requires explicit source confirmation")
        return self


class MergeProductRequest(CatalogDTO):
    target: ProductRefDTO
    expected_source_state_revision: Revision
    expected_target_state_revision: Revision
    identity_confirmed: StrictBool
    reason: Text

    @model_validator(mode="after")
    def confirmation(self) -> Self:
        if not self.identity_confirmed:
            raise ValueError("merge requires explicit identity confirmation")
        return self


class ModerationProductResultDTO(CatalogDTO):
    product: ProductRefDTO
    canonical_ref: ProductRefDTO
    state_revision: Revision


class MergeProductResultDTO(CatalogDTO):
    source: ProductRefDTO
    target: ProductRefDTO
    source_state_revision: Revision
    target_state_revision: Revision


class ReportResolutionRequest(CatalogDTO):
    expected_revision: Revision
    status: Literal["resolved", "dismissed", "referred_to_admin"]
    reason: Text


class ModerationReportDTO(CatalogDTO):
    report_id: Uuid
    product: ProductRefDTO
    canonical_ref: ProductRefDTO
    revision: Revision
    status: ReportStatus
    reason: Text
    description: Text
    resolution_reason: Text | None


class ModerationReportPage(CatalogDTO):
    items: Annotated[list[ModerationReportDTO], Field(max_length=500)]
    next_page_token: PageToken | None
