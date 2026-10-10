"""Owner-constrained private aggregates and independently stored nutrition snapshots."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base

REVISION = "revision BETWEEN 1 AND 2147483647"
RATION_SNAPSHOT = """
ration IS NULL OR COALESCE((
    jsonb_typeof(ration) = 'object' AND
    ration ?& ARRAY['ration_id','revision','name'] AND
    jsonb_typeof(ration->'ration_id') = 'string' AND
    ration->>'ration_id' ~ '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' AND
    jsonb_typeof(ration->'revision') = 'number' AND
    ration->>'revision' ~ '^[1-9][0-9]{0,9}$' AND
    (ration->>'revision')::numeric BETWEEN 1 AND 2147483647 AND
    jsonb_typeof(ration->'name') = 'string' AND length(ration->>'name') BETWEEN 1 AND 200
), false)
"""


def number_check(field: str, *, positive: bool = False, maximum="999999.999999"):
    comparison = ">" if positive else ">="
    return (
        f"{field} IS NULL OR ({field}::text NOT IN ('NaN','Infinity','-Infinity') "
        f"AND {field} {comparison} 0 AND {field} <= {maximum})"
    )


class DiaryDay(Base):
    __tablename__ = "diary_days"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        UniqueConstraint("owner_id", "local_date", name="uq_diary_days_owner_date"),
        UniqueConstraint("owner_id", "local_date", "time_zone", name="uq_diary_days_owner_zone"),
        CheckConstraint(REVISION, name="revision_range"),
        CheckConstraint("length(time_zone) BETWEEN 1 AND 100", name="time_zone_length"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"))
    revision: Mapped[int] = mapped_column()
    local_date: Mapped[date] = mapped_column()
    time_zone: Mapped[str] = mapped_column(String(100))
    declared_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Meal(Base):
    __tablename__ = "meals"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        ForeignKeyConstraint(
            ["owner_id", "goal_id"], ["app.goal_versions.owner_id", "app.goal_versions.id"]
        ),
        ForeignKeyConstraint(
            ["owner_id", "local_date", "time_zone"],
            ["app.diary_days.owner_id", "app.diary_days.local_date", "app.diary_days.time_zone"],
        ),
        CheckConstraint(REVISION, name="revision_range"),
        CheckConstraint("length(title) BETWEEN 1 AND 200", name="title_length"),
        CheckConstraint(RATION_SNAPSHOT, name="ration_snapshot"),
        CheckConstraint(
            "meal_type IS NULL OR meal_type IN ('breakfast','lunch','dinner','snack')",
            name="meal_type",
        ),
        CheckConstraint(
            "(occurred_at AT TIME ZONE time_zone)::date = local_date", name="local_date_matches"
        ),
        Index("ix_meals_owner_date", "owner_id", "local_date"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"))
    revision: Mapped[int] = mapped_column()
    title: Mapped[str] = mapped_column(String(200))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_date: Mapped[date] = mapped_column()
    time_zone: Mapped[str] = mapped_column(String(100))
    meal_type: Mapped[str | None] = mapped_column(String(20))
    goal_id: Mapped[UUID | None] = mapped_column()
    ration: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MealItem(Base):
    __tablename__ = "meal_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "meal_id"], ["app.meals.owner_id", "app.meals.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["product_id", "product_revision"],
            ["app.product_versions.product_id", "app.product_versions.revision"],
        ),
        UniqueConstraint("owner_id", "meal_id", "position"),
        CheckConstraint("position BETWEEN 1 AND 100", name="position_range"),
        CheckConstraint("length(name) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint(
            "(product_id IS NULL) = (product_revision IS NULL)", name="exact_product_ref"
        ),
        CheckConstraint(
            "product_revision IS NULL OR product_revision BETWEEN 1 AND 2147483647",
            name="product_revision",
        ),
        CheckConstraint(
            number_check("quantity_amount", positive=True, maximum="10000"), name="quantity_range"
        ),
        CheckConstraint("quantity_unit IN ('g','ml') AND basis_unit IN ('g','ml')", name="units"),
        CheckConstraint(
            "(density_g_per_ml IS NULL) = (density_source IS NULL)", name="density_source"
        ),
        CheckConstraint(number_check("density_g_per_ml", positive=True), name="density_range"),
        CheckConstraint(
            "quantity_unit = basis_unit OR density_g_per_ml IS NOT NULL", name="conversion_density"
        ),
        CheckConstraint(
            "density_source IS NULL OR length(density_source) BETWEEN 1 AND 500",
            name="density_source_length",
        ),
        CheckConstraint(
            "nutrition_origin IN ('catalog_snapshot','manual','ai_estimate')",
            name="nutrition_origin",
        ),
        CheckConstraint("formula_version = 'nutrition_v1'", name="formula_version"),
        CheckConstraint(
            "ration_component_position IS NULL OR ration_component_position BETWEEN 1 AND 100000",
            name="ration_position",
        ),
        *[
            CheckConstraint(number_check(field), name=field + "_range")
            for field in ("energy_kcal", "protein_g", "fat_g", "carbs_g")
        ],
    )
    owner_id: Mapped[UUID] = mapped_column(primary_key=True)
    meal_id: Mapped[UUID] = mapped_column(primary_key=True)
    item_id: Mapped[UUID] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column(String(200))
    product_id: Mapped[UUID | None] = mapped_column()
    product_revision: Mapped[int | None] = mapped_column()
    quantity_amount: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    quantity_unit: Mapped[str] = mapped_column(String(2))
    basis_unit: Mapped[str] = mapped_column(String(2))
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    density_g_per_ml: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    density_source: Mapped[str | None] = mapped_column(String(500))
    nutrition_origin: Mapped[str] = mapped_column(String(20))
    formula_version: Mapped[str] = mapped_column(String(20))
    ration_component_position: Mapped[int | None] = mapped_column()


class Weight(Base):
    __tablename__ = "weights"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        CheckConstraint(REVISION, name="revision_range"),
        CheckConstraint(
            number_check("weight_kg", positive=True, maximum="1000"), name="weight_range"
        ),
        CheckConstraint("length(time_zone) BETWEEN 1 AND 100", name="time_zone_length"),
        CheckConstraint(
            "(occurred_at AT TIME ZONE time_zone)::date = local_date", name="local_date_matches"
        ),
        Index("ix_weights_owner_date", "owner_id", "local_date"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"))
    revision: Mapped[int] = mapped_column()
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_date: Mapped[date] = mapped_column()
    time_zone: Mapped[str] = mapped_column(String(100))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductDraft(Base):
    __tablename__ = "product_drafts"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        CheckConstraint(REVISION, name="revision_range"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        CheckConstraint("app.private_draft_valid(payload)", name="strict_payload"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"))
    revision: Mapped[int] = mapped_column()
    payload: Mapped[dict] = mapped_column(JSONB)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
