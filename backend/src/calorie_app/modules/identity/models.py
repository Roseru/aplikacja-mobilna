from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class UserAccount(Base):
    __tablename__ = "user_accounts"
    __table_args__ = (
        UniqueConstraint("issuer", "subject"),
        CheckConstraint("generation >= 1", name="positive_generation"),
        CheckConstraint("generation <= 2147483647", name="generation_range"),
        CheckConstraint("state IN ('active', 'deleting')", name="account_state"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    issuer: Mapped[str] = mapped_column(String(2048))
    subject: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    generation: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InstallationState(Base):
    __tablename__ = "installation_state"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_epoch: Mapped[UUID] = mapped_column()


class OnlineReceipt(Base):
    __tablename__ = "online_receipts"
    __table_args__ = (
        CheckConstraint("operation IN ('bootstrap', 'consents')", name="receipt_operation"),
        CheckConstraint("generation BETWEEN 1 AND 2147483647", name="generation_range"),
        CheckConstraint("length(request_hash) = 64", name="request_hash_length"),
        CheckConstraint(
            "(operation='bootstrap' AND accepted_revision IS NULL "
            "AND response IS NOT NULL) OR (operation='consents' "
            "AND accepted_revision IS NOT NULL "
            "AND accepted_revision BETWEEN 1 AND 2147483647)",
            name="receipt_result",
        ),
        Index(
            "ix_online_receipts_retention",
            "created_at",
            postgresql_where=text("operation='consents' AND response IS NOT NULL"),
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    operation: Mapped[str] = mapped_column(String(20), primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column()
    sync_epoch: Mapped[UUID] = mapped_column()
    response: Mapped[dict | None] = mapped_column(JSONB)
    accepted_revision: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
