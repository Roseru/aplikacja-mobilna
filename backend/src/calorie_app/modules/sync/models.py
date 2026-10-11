from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class SyncCounter(Base):
    __tablename__ = "sync_counters"
    __table_args__ = (CheckConstraint("position >= 0", name="position_range"),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    position: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class SyncReceipt(Base):
    __tablename__ = "sync_receipts"
    __table_args__ = (
        CheckConstraint("status IN ('accepted','conflict','rejected')", name="status"),
        CheckConstraint("length(request_hash)=64", name="hash"),
        Index("ix_sync_receipts_created", "owner_id", "created_at"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    source_epoch: Mapped[UUID] = mapped_column()
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[UUID] = mapped_column()
    action: Mapped[str] = mapped_column(String(10), default="upsert", server_default="upsert")
    status: Mapped[str] = mapped_column(String(20))
    code: Mapped[str | None] = mapped_column(String(60))
    revision: Mapped[int | None] = mapped_column()
    recovery_epoch: Mapped[UUID | None] = mapped_column()
    recovery_entity_id: Mapped[UUID | None] = mapped_column()
    response: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncChange(Base):
    __tablename__ = "sync_changes"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    position: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncReservation(Base):
    __tablename__ = "sync_reservations"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    entity_id: Mapped[UUID] = mapped_column(primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecoveryMapping(Base):
    __tablename__ = "sync_recovery_mappings"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    source_epoch: Mapped[UUID] = mapped_column(primary_key=True)
    source_entity_id: Mapped[UUID] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    target_entity_id: Mapped[UUID] = mapped_column()
    target_revision: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
