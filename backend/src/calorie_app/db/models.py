from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class UserAccount(Base):
    __tablename__ = "user_accounts"
    __table_args__ = (
        UniqueConstraint("issuer", "subject"),
        CheckConstraint("generation >= 1", name="positive_generation"),
        CheckConstraint("state IN ('active', 'deleting')", name="account_state"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    issuer: Mapped[str] = mapped_column(String(2048))
    subject: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    generation: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductSource(Base):
    __tablename__ = "product_sources"
    __table_args__ = (
        CheckConstraint("status IN ('unverified', 'verified')", name="source_status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(16), default="unverified")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[UUID] = mapped_column(primary_key=True)


class ProductVersion(Base):
    __tablename__ = "product_versions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("basis_unit IN ('g', 'ml')", name="basis_unit"),
        CheckConstraint(
            "energy_kcal >= 0 AND protein_g >= 0 AND fat_g >= 0 AND carbs_g >= 0",
            name="nonnegative_nutrition",
        ),
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("app.products.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("app.product_sources.id"))
    name: Mapped[str] = mapped_column(String(255))
    basis_unit: Mapped[str] = mapped_column(String(2))
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
