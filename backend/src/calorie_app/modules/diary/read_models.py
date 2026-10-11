"""Durable read copies, separate from synchronization receipts/checkpoints."""

from datetime import date, datetime
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


class ReadSession(Base):
    __tablename__ = "read_sessions"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        CheckConstraint("endpoint IN ('meals','weights','diary-days')", name="endpoint"),
        CheckConstraint("page_limit BETWEEN 1 AND 500", name="page_limit"),
        CheckConstraint("expires_at = created_at + interval '60 minutes'", name="fixed_ttl"),
        CheckConstraint("date_to >= date_from AND date_to-date_from < 366", name="date_range"),
        CheckConstraint(
            "item_count BETWEEN 0 AND 100000 AND byte_count BETWEEN 0 AND 67108864",
            name="resource_limits",
        ),
        Index("ix_read_sessions_owner_expiry", "owner_id", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id", ondelete="CASCADE"))
    generation: Mapped[int] = mapped_column()
    epoch: Mapped[UUID] = mapped_column()
    endpoint: Mapped[str] = mapped_column(String(12))
    date_from: Mapped[date] = mapped_column()
    date_to: Mapped[date] = mapped_column()
    page_limit: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    context: Mapped[dict] = mapped_column(JSONB)
    item_count: Mapped[int] = mapped_column(default=0)
    byte_count: Mapped[int] = mapped_column(BigInteger, default=0)


class ReadSessionItem(Base):
    __tablename__ = "read_session_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "owner_id"],
            ["app.read_sessions.id", "app.read_sessions.owner_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("position BETWEEN 1 AND 100000", name="position"),
        CheckConstraint("byte_size BETWEEN 1 AND 524288", name="byte_size"),
    )
    session_id: Mapped[UUID] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column()
    value: Mapped[dict] = mapped_column(JSONB)
    byte_size: Mapped[int] = mapped_column()


class ReadAdmission(Base):
    """A tuple write serializes concurrent RR admission without editing account state."""

    __tablename__ = "read_admissions"
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.user_accounts.id", ondelete="CASCADE"), primary_key=True
    )
