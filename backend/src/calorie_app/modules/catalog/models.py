"""Relational catalog snapshots and their exact offline package membership."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class ProductSource(Base):
    __tablename__ = "product_sources"
    __table_args__ = (
        CheckConstraint("status IN ('unverified', 'verified')", name="source_status"),
        CheckConstraint(
            "basis IS NULL OR basis IN ('assumed_listed_quantity', 'per_100_g', "
            "'per_100_ml', 'label_serving', 'mixed_labels')",
            name="source_basis",
        ),
        CheckConstraint(
            "content_hash IS NULL OR (content_hash ~ '^[0-9a-f]{64}$' "
            "AND document_id IS NOT NULL AND basis IS NOT NULL "
            "AND missing_data IS NOT NULL AND notes IS NOT NULL)",
            name="sealed_metadata",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(16), default="unverified")
    document_id: Mapped[str | None] = mapped_column(String(2000))
    url: Mapped[str | None] = mapped_column(String())
    checked_on: Mapped[date | None] = mapped_column(Date())
    market: Mapped[str | None] = mapped_column(String(2000))
    manufacturer: Mapped[str | None] = mapped_column(String(2000))
    variant: Mapped[str | None] = mapped_column(String(2000))
    basis: Mapped[str | None] = mapped_column(String(32))
    missing_data: Mapped[list[str] | None] = mapped_column(JSONB)
    notes: Mapped[list[str] | None] = mapped_column(JSONB)
    content_hash: Mapped[str | None] = mapped_column(String(64))


class Product(Base):
    __tablename__ = "products"
    id: Mapped[UUID] = mapped_column(primary_key=True)


class ProductVersion(Base):
    __tablename__ = "product_versions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("basis_unit IN ('g', 'ml')", name="basis_unit"),
        CheckConstraint(
            "(energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal <= 999999.999999)) "
            "AND (protein_g IS NULL OR (protein_g >= 0 AND protein_g <= 999999.999999)) "
            "AND (fat_g IS NULL OR (fat_g >= 0 AND fat_g <= 999999.999999)) "
            "AND (carbs_g IS NULL OR (carbs_g >= 0 AND carbs_g <= 999999.999999))",
            name="finite_nutrition",
        ),
        CheckConstraint(
            "package_amount IS NULL OR (package_amount > 0 AND package_amount <= 999999.999999)",
            name="finite_package_amount",
        ),
        CheckConstraint(
            "(package_amount IS NULL AND package_unit IS NULL) OR "
            "(package_amount IS NOT NULL AND package_unit IS NOT NULL "
            "AND package_unit IN ('g', 'ml'))",
            name="package_quantity",
        ),
        CheckConstraint(
            "(density_amount IS NULL AND density_source_id IS NULL) OR "
            "(density_amount IS NOT NULL AND density_source_id IS NOT NULL "
            "AND density_amount > 0 AND density_amount <= 999999.999999)",
            name="finite_density",
        ),
        CheckConstraint("status IS NULL OR status IN ('unverified', 'verified')", name="status"),
        CheckConstraint(
            "content_hash IS NULL OR (content_hash ~ '^[0-9a-f]{64}$' "
            "AND aliases IS NOT NULL AND package_amount IS NOT NULL "
            "AND source_locator IS NOT NULL AND status IS NOT NULL)",
            name="sealed_metadata",
        ),
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("app.products.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("app.product_sources.id"))
    name: Mapped[str] = mapped_column(String(2000))
    basis_unit: Mapped[str] = mapped_column(String(2))
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    aliases: Mapped[list[str] | None] = mapped_column(JSONB)
    brand: Mapped[str | None] = mapped_column(String(2000))
    variant: Mapped[str | None] = mapped_column(String(2000))
    package_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    package_unit: Mapped[str | None] = mapped_column(String(2))
    density_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    density_source_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.product_sources.id"))
    source_locator: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str | None] = mapped_column(String(16))
    preparation: Mapped[str | None] = mapped_column(String(2000))
    content_hash: Mapped[str | None] = mapped_column(String(64))


class Ration(Base):
    __tablename__ = "rations"
    id: Mapped[UUID] = mapped_column(primary_key=True)


class RationVersion(Base):
    __tablename__ = "ration_versions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("status IN ('unverified', 'verified')", name="status"),
        CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'", name="content_hash"
        ),
    )
    ration_id: Mapped[UUID] = mapped_column(ForeignKey("app.rations.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(2000))
    manufacturer: Mapped[str | None] = mapped_column(String(2000))
    variant: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[UUID] = mapped_column(ForeignKey("app.product_sources.id"))
    complete: Mapped[bool] = mapped_column(Boolean)
    excluded_items: Mapped[list[dict]] = mapped_column(JSONB)
    content_hash: Mapped[str | None] = mapped_column(String(64))


class RationComponent(Base):
    __tablename__ = "ration_components"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ration_id", "ration_revision"],
            ["app.ration_versions.ration_id", "app.ration_versions.revision"],
        ),
        ForeignKeyConstraint(
            ["product_id", "product_revision"],
            ["app.product_versions.product_id", "app.product_versions.revision"],
        ),
        CheckConstraint("position >= 1 AND position <= 100000", name="position"),
        CheckConstraint("amount > 0 AND amount <= 999999.999999", name="finite_amount"),
        CheckConstraint("unit IN ('g', 'ml')", name="unit"),
    )
    ration_id: Mapped[UUID] = mapped_column(primary_key=True)
    ration_revision: Mapped[int] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    group_name: Mapped[str] = mapped_column(String(2000))
    product_id: Mapped[UUID] = mapped_column()
    product_revision: Mapped[int] = mapped_column()
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    unit: Mapped[str] = mapped_column(String(2))
    optional: Mapped[bool] = mapped_column(Boolean)


class OfflineChannel(Base):
    __tablename__ = "offline_channels"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "active_release"],
            ["app.offline_packages.package_id", "app.offline_packages.release"],
            name="fk_offline_channels_active_package",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        CheckConstraint("kind IN ('demo', 'official')", name="kind"),
        CheckConstraint("active_release IS NULL OR active_release >= 1", name="active_release"),
    )
    package_id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    active_release: Mapped[int | None] = mapped_column()


class OfflinePackage(Base):
    __tablename__ = "offline_packages"
    __table_args__ = (
        CheckConstraint("release >= 1", name="positive_release"),
        CheckConstraint("schema_version = 1 AND min_reader_version = 1", name="reader_version"),
        CheckConstraint("state IN ('draft', 'published')", name="state"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash"),
        CheckConstraint(
            "product_count BETWEEN 1 AND 10000 AND ration_count BETWEEN 1 AND 1000 "
            "AND component_count BETWEEN 1 AND 100000 AND source_count BETWEEN 1 AND 10000",
            name="counts",
        ),
        CheckConstraint(
            "(sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$') AND "
            "(compressed_bytes IS NULL OR compressed_bytes BETWEEN 1 AND 10485760) AND "
            "(uncompressed_bytes IS NULL OR uncompressed_bytes BETWEEN 1 AND 52428800)",
            name="artifact_limits",
        ),
        CheckConstraint(
            "state != 'published' OR (sealed AND sha256 IS NOT NULL "
            "AND compressed_bytes IS NOT NULL AND uncompressed_bytes IS NOT NULL "
            "AND artifact_path IS NOT NULL)",
            name="published_artifact",
        ),
        CheckConstraint(
            "state != 'draft' OR (sha256 IS NULL AND compressed_bytes IS NULL "
            "AND uncompressed_bytes IS NULL AND artifact_path IS NULL)",
            name="draft_artifact",
        ),
    )
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.offline_channels.package_id"), primary_key=True
    )
    release: Mapped[int] = mapped_column(primary_key=True)
    schema_version: Mapped[int] = mapped_column()
    min_reader_version: Mapped[int] = mapped_column()
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16))
    sealed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    content_hash: Mapped[str] = mapped_column(String(64))
    product_count: Mapped[int] = mapped_column()
    ration_count: Mapped[int] = mapped_column()
    component_count: Mapped[int] = mapped_column()
    source_count: Mapped[int] = mapped_column()
    sha256: Mapped[str | None] = mapped_column(String(64))
    compressed_bytes: Mapped[int | None] = mapped_column()
    uncompressed_bytes: Mapped[int | None] = mapped_column()
    artifact_path: Mapped[str | None] = mapped_column(String(4096))


class OfflinePackageProduct(Base):
    __tablename__ = "offline_package_products"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "release"],
            ["app.offline_packages.package_id", "app.offline_packages.release"],
        ),
        ForeignKeyConstraint(
            ["product_id", "product_revision"],
            ["app.product_versions.product_id", "app.product_versions.revision"],
        ),
    )
    package_id: Mapped[UUID] = mapped_column(primary_key=True)
    release: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[UUID] = mapped_column(primary_key=True)
    product_revision: Mapped[int] = mapped_column(primary_key=True)


class OfflinePackageRation(Base):
    __tablename__ = "offline_package_rations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "release"],
            ["app.offline_packages.package_id", "app.offline_packages.release"],
        ),
        ForeignKeyConstraint(
            ["ration_id", "ration_revision"],
            ["app.ration_versions.ration_id", "app.ration_versions.revision"],
        ),
    )
    package_id: Mapped[UUID] = mapped_column(primary_key=True)
    release: Mapped[int] = mapped_column(primary_key=True)
    ration_id: Mapped[UUID] = mapped_column(primary_key=True)
    ration_revision: Mapped[int] = mapped_column(primary_key=True)


class OfflinePackageSource(Base):
    __tablename__ = "offline_package_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "release"],
            ["app.offline_packages.package_id", "app.offline_packages.release"],
        ),
    )
    package_id: Mapped[UUID] = mapped_column(primary_key=True)
    release: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("app.product_sources.id"), primary_key=True)


class RationPageToken(Base):
    __tablename__ = "ration_page_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["package_id", "release"],
            ["app.offline_packages.package_id", "app.offline_packages.release"],
        ),
        CheckConstraint('"limit" BETWEEN 1 AND 500', name="page_limit"),
        CheckConstraint("after_revision >= 1", name="after_revision"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    package_id: Mapped[UUID] = mapped_column()
    release: Mapped[int] = mapped_column()
    after_id: Mapped[UUID] = mapped_column()
    after_revision: Mapped[int] = mapped_column()
    limit: Mapped[int] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
