"""Materialized private synchronization sessions, never stateless table cursors."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class SyncSession(Base):
    __tablename__ = "sync_sessions"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        CheckConstraint("mode IN ('snapshot','incremental')", name="mode"),
        CheckConstraint("page_limit BETWEEN 1 AND 500", name="page_limit"),
        CheckConstraint("expires_at = created_at + interval '60 minutes'", name="fixed_ttl"),
        CheckConstraint(
            "high_position >= 0 AND base_position >= 0 AND high_position >= base_position",
            name="position_range",
        ),
        CheckConstraint(
            "item_count BETWEEN 0 AND 100000 AND byte_count BETWEEN 0 AND 67108864",
            name="resource_limits",
        ),
        Index("ix_sync_sessions_owner_expiry", "owner_id", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"))
    generation: Mapped[int] = mapped_column()
    epoch: Mapped[UUID] = mapped_column()
    mode: Mapped[str] = mapped_column(String(12))
    page_limit: Mapped[int] = mapped_column()
    high_position: Mapped[int] = mapped_column(BigInteger)
    base_position: Mapped[int] = mapped_column(BigInteger)
    base_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timeline_revision: Mapped[int] = mapped_column()
    item_count: Mapped[int] = mapped_column(default=0)
    byte_count: Mapped[int] = mapped_column(BigInteger, default=0)
    final_offset: Mapped[int | None] = mapped_column()
    final_response: Mapped[dict | None] = mapped_column(JSONB)


class SyncSessionItem(Base):
    __tablename__ = "sync_session_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "owner_id"],
            ["app.sync_sessions.id", "app.sync_sessions.owner_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("position BETWEEN 1 AND 100000", name="position"),
        CheckConstraint(
            "kind IN ('entities','recovery_mappings','operation_receipts')", name="kind"
        ),
        CheckConstraint("byte_size BETWEEN 1 AND 524288", name="byte_size"),
    )
    session_id: Mapped[UUID] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(24))
    value: Mapped[dict] = mapped_column(JSONB)
    byte_size: Mapped[int] = mapped_column()
