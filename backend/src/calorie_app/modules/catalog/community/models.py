"""Exact public snapshots, private attribution and durable online operation evidence."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class CatalogState(Base):
    __tablename__ = "community_catalog_state"
    __table_args__ = (
        CheckConstraint("id=1", name="singleton"),
        CheckConstraint("revision>=1 AND queue_revision>=1", name="revision_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, server_default="1")
    queue_revision: Mapped[int] = mapped_column(BigInteger, server_default="1")


class CommunityProduct(Base):
    __tablename__ = "community_products"
    __table_args__ = (
        CheckConstraint("current_revision>=1 AND state_revision>=1", name="revision_range"),
        CheckConstraint("verification IN ('unverified','verified')", name="verification"),
        CheckConstraint("visibility IN ('visible','hidden')", name="visibility"),
        CheckConstraint("canonical_id IS NULL OR canonical_id<>product_id", name="not_self_merge"),
        Index(
            "ix_community_products_roots",
            "product_id",
            postgresql_where=text("canonical_id IS NULL AND visibility='visible'"),
        ),
    )
    product_id: Mapped[UUID] = mapped_column(ForeignKey("app.products.id"), primary_key=True)
    current_revision: Mapped[int] = mapped_column(Integer, server_default="1")
    state_revision: Mapped[int] = mapped_column(Integer, server_default="1")
    verification: Mapped[str] = mapped_column(String(16), server_default="unverified")
    visibility: Mapped[str] = mapped_column(String(16), server_default="visible")
    canonical_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("app.community_products.product_id")
    )


class CommunityVersion(Base):
    __tablename__ = "community_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "revision"],
            ["app.product_versions.product_id", "app.product_versions.revision"],
        ),
        CheckConstraint("source_kind IN ('label','recipe','estimate','ai')", name="source_kind"),
        CheckConstraint("cardinality(normalized_names) BETWEEN 1 AND 51", name="names_limit"),
        CheckConstraint(
            "ingredients IS NULL OR (jsonb_typeof(ingredients)='array' "
            "AND jsonb_array_length(ingredients)<=100)",
            name="ingredients_limit",
        ),
        CheckConstraint(
            "octet_length(identity::text)<=1048576 "
            "AND octet_length(normalized_identity::text)<=1048576",
            name="identity_limit",
        ),
        Index("ix_community_versions_names", "normalized_name_hashes", postgresql_using="gin"),
        Index("ix_community_versions_identity", "identity_key"),
        Index(
            "ix_community_versions_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.community_products.product_id"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(16))
    source_description: Mapped[str] = mapped_column(String(2000))
    ingredients: Mapped[list[str] | None] = mapped_column(JSONB)
    recipe: Mapped[str | None] = mapped_column(String(4000))
    identity: Mapped[dict] = mapped_column(JSONB)
    normalized_names: Mapped[list[str]] = mapped_column(ARRAY(Text))
    normalized_name_hashes: Mapped[list[str]] = mapped_column(ARRAY(String(64)))
    normalized_identity: Mapped[dict] = mapped_column(JSONB)
    identity_key: Mapped[str] = mapped_column(String(64))
    search_text: Mapped[str] = mapped_column(Text)


class CommunityAuthor(Base):
    __tablename__ = "community_authors"
    # Remove attribution on purge; shared snapshots never cascade from accounts.
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.community_products.product_id"), primary_key=True
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)


class PublicationBinding(Base):
    __tablename__ = "community_publication_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "product_revision"],
            ["app.product_versions.product_id", "app.product_versions.revision"],
        ),
        CheckConstraint("draft_revision>=1", name="draft_revision"),
        CheckConstraint("metadata_hash ~ '^[0-9a-f]{64}$'", name="metadata_hash"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    draft_id: Mapped[UUID] = mapped_column(primary_key=True)
    draft_revision: Mapped[int] = mapped_column(primary_key=True)
    metadata_hash: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[UUID] = mapped_column()
    product_revision: Mapped[int] = mapped_column()
    result_minimal: Mapped[dict] = mapped_column(JSONB)


class CommunityVote(Base):
    __tablename__ = "community_votes"
    __table_args__ = (
        CheckConstraint("value IS NULL OR value IN (-1,1)", name="value"),
        CheckConstraint("revision BETWEEN 1 AND 2147483647", name="revision"),
        CheckConstraint("NOT active OR value IS NOT NULL", name="active_value"),
        Index("ix_community_votes_product_active", "product_id", "active"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("app.products.id"), primary_key=True)
    value: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class CommunityReport(Base):
    __tablename__ = "community_reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "product_revision"],
            ["app.product_versions.product_id", "app.product_versions.revision"],
        ),
        CheckConstraint(
            "status IN ('open','resolved','dismissed','referred_to_admin')", name="status"
        ),
        CheckConstraint("revision BETWEEN 1 AND 2147483647", name="revision"),
        Index("ix_community_reports_queue", "status", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.user_accounts.id"))
    product_id: Mapped[UUID] = mapped_column()
    product_revision: Mapped[int] = mapped_column()
    canonical_id: Mapped[UUID] = mapped_column(ForeignKey("app.products.id"))
    reason: Mapped[str] = mapped_column(String(2000))
    description: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(24), server_default="open")
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    resolution_reason: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )


class CommunityAudit(Base):
    __tablename__ = "community_audit"
    __table_args__ = (Index("ix_community_audit_operation", "operation_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.user_accounts.id"))
    operation_id: Mapped[UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(2000))
    old_ref: Mapped[dict | None] = mapped_column(JSONB)
    new_ref: Mapped[dict | None] = mapped_column(JSONB)
    old_state: Mapped[int | None] = mapped_column(Integer)
    new_state: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.products.id"))
    target_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.products.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )


class CommunityReceipt(Base):
    __tablename__ = "community_receipts"
    __table_args__ = (
        CheckConstraint("generation>=1", name="generation"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash"),
        CheckConstraint("status_code BETWEEN 200 AND 499", name="status_code"),
        CheckConstraint(
            "octet_length(result_minimal::text)<=8192 AND (response_payload IS NULL "
            "OR octet_length(response_payload::text)<=1048576)",
            name="bounded_response",
        ),
        Index(
            "ix_community_receipts_retention",
            "owner_id",
            "created_at",
            postgresql_where=text("response_payload IS NOT NULL"),
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    operation_kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer)
    sync_epoch: Mapped[UUID] = mapped_column()
    status_code: Mapped[int] = mapped_column(Integer)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    result_minimal: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )


class CommunityQuota(Base):
    __tablename__ = "community_quotas"
    __table_args__ = (
        CheckConstraint(
            "receipts BETWEEN 0 AND 1000 AND products BETWEEN 0 AND 20 "
            "AND reports BETWEEN 0 AND 50 AND votes BETWEEN 0 AND 200",
            name="limits",
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    receipts: Mapped[int] = mapped_column(Integer, server_default="0")
    products: Mapped[int] = mapped_column(Integer, server_default="0")
    reports: Mapped[int] = mapped_column(Integer, server_default="0")
    votes: Mapped[int] = mapped_column(Integer, server_default="0")
