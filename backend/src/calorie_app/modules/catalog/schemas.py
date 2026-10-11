"""Typed catalog responses. Required nullable fields preserve unknown values."""

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictBool,
    StrictInt,
    WithJsonSchema,
    model_validator,
)

from calorie_app.core.wire import validate_json_strings
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.catalog.validation import (
    DECIMAL_PATTERN,
    canonical,
    validate_definition,
    validate_manifest,
    wire_decimal,
)

DecimalValue = Annotated[
    Decimal,
    BeforeValidator(wire_decimal),
    PlainSerializer(canonical, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": DECIMAL_PATTERN}),
]
PositiveDecimal = Annotated[
    DecimalValue,
    Field(gt=0),
    WithJsonSchema(
        {
            "allOf": [
                {"type": "string", "pattern": DECIMAL_PATTERN},
                {"not": {"const": "0"}},
            ]
        }
    ),
]
Revision = Annotated[StrictInt, Field(ge=1, le=2147483647)]
Text = Annotated[str, Field(strict=True, min_length=1, max_length=2000)]
Status = Literal["unverified", "verified"]
Unit = Literal["g", "ml"]


def _uuid(value):
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("UUID must use lowercase canonical text")
    return UUID(value)


Uuid = Annotated[UUID, BeforeValidator(_uuid)]
TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.[0-9]{1,6})?Z$"


def _timestamp(value):
    if isinstance(value, str):
        if re.fullmatch(TIMESTAMP_PATTERN, value) is None:
            raise ValueError("Timestamp must use UTC Z")
        datetime.fromisoformat(value)  # Reject invalid calendar/time, retain valid wire spelling.
        return value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("Timestamp must be timezone-aware UTC")
    return utc_text(value)


Timestamp = Annotated[
    str,
    BeforeValidator(_timestamp),
    WithJsonSchema({"type": "string", "format": "date-time", "pattern": TIMESTAMP_PATTERN}),
]


class CatalogDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def safe_text(cls, value):
        validate_json_strings(value)
        return value


class NutritionDTO(CatalogDTO):
    energy_kcal: DecimalValue | None
    protein_g: DecimalValue | None
    fat_g: DecimalValue | None
    carbs_g: DecimalValue | None


class QuantityDTO(CatalogDTO):
    amount: PositiveDecimal
    unit: Unit


class DensityDTO(CatalogDTO):
    amount: PositiveDecimal
    source_id: Uuid


class ProductRefDTO(CatalogDTO):
    product_id: Uuid
    revision: Revision


class ProductDTO(CatalogDTO):
    product_id: Uuid
    revision: Revision
    name: Text
    aliases: Annotated[list[Text], Field(max_length=100)]
    brand: Text | None
    variant: Text | None
    basis_unit: Unit
    nutrition_per_100: NutritionDTO
    package_quantity: QuantityDTO
    density_g_per_ml: DensityDTO | None
    source_id: Uuid
    source_locator: Text
    status: Status
    preparation: Text | None

    @model_validator(mode="after")
    def wire_contract(self) -> Self:
        validate_definition(self.model_dump(mode="json"), "Product")
        return self


class ComponentDTO(CatalogDTO):
    position: Annotated[StrictInt, Field(ge=1, le=100000)]
    group: Text
    product: ProductRefDTO
    quantity: QuantityDTO
    optional: StrictBool


class ExcludedItemDTO(CatalogDTO):
    source_locator: Text
    name: Text
    classification: Literal["food", "seasoning", "equipment"]
    source_amount: PositiveDecimal | None
    source_unit: Text | None
    reasons: Annotated[list[Text], Field(min_length=1, max_length=20)]


class RationDTO(CatalogDTO):
    ration_id: Uuid
    revision: Revision
    name: Text
    manufacturer: Text | None
    variant: Text | None
    status: Status
    source_id: Uuid
    complete: StrictBool
    components: Annotated[list[ComponentDTO], Field(min_length=1, max_length=100000)]
    excluded_items: Annotated[list[ExcludedItemDTO], Field(max_length=1000)]

    @model_validator(mode="after")
    def wire_contract(self) -> Self:
        validate_definition(self.model_dump(mode="json"), "Ration")
        return self


class CountsDTO(CatalogDTO):
    products: Annotated[StrictInt, Field(ge=0, le=10000)]
    rations: Annotated[StrictInt, Field(ge=0, le=1000)]
    components: Annotated[StrictInt, Field(ge=0, le=100000)]
    sources: Annotated[StrictInt, Field(ge=0, le=10000)]


class ManifestDTO(CatalogDTO):
    package_id: Uuid
    release: Revision
    schema_version: Literal[1]
    min_reader_version: Literal[1]
    published_at: Timestamp
    kind: Literal["demo", "official"]
    counts: CountsDTO
    path: str
    compressed_bytes: Annotated[StrictInt, Field(ge=1, le=10485760)]
    uncompressed_bytes: Annotated[StrictInt, Field(ge=1, le=52428800)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_ids: Annotated[list[Uuid], Field(min_length=1, max_length=10000)]

    @model_validator(mode="before")
    @classmethod
    def strict_versions(cls, value):
        if isinstance(value, dict):
            for field in ("schema_version", "min_reader_version"):
                if field in value and type(value[field]) is not int:
                    raise ValueError(f"{field} must be an integer")
        return value

    @model_validator(mode="after")
    def wire_contract(self) -> Self:
        validate_manifest(self.model_dump(mode="json"))
        return self


PageToken = Annotated[str, Field(strict=True, min_length=1, max_length=4096)]


class RationPage(CatalogDTO):
    items: Annotated[list[RationDTO], Field(max_length=500)]
    next_page_token: PageToken | None


class ProductPage(CatalogDTO):
    items: Annotated[list[ProductDTO], Field(max_length=500)]
    next_page_token: PageToken | None
