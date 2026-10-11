"""Deletion evidence survives the private account graph and is visible to Alembic.

These models describe the existing 0011 schema; runtime must still use the
restricted SQL functions rather than writing the jobs/context through the ORM.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv

from calorie_app.db.base import Base


class AccountDeletionJob(Base):
    __tablename__ = "account_deletion_jobs"
    __table_args__ = (
        PrimaryKeyConstraint("operation_id", name="account_deletion_jobs_pkey"),
        UniqueConstraint("account_id", name="account_deletion_jobs_account_id_key"),
        UniqueConstraint("issuer", "subject", name="account_deletion_jobs_issuer_subject_key"),
        CheckConstraint(
            "expected_generation BETWEEN 1 AND 2147483646",
            name=conv("account_deletion_jobs_expected_generation_check"),
        ),
        CheckConstraint(
            "deleting_generation=expected_generation+1",
            name=conv("account_deletion_jobs_check"),
        ),
        CheckConstraint(
            "(identity_confirmed_at IS NULL AND block_until IS NULL AND purged_at IS NULL) "
            "OR (identity_confirmed_at IS NOT NULL "
            "AND block_until >= identity_confirmed_at + interval '420 seconds')",
            name=conv("account_deletion_jobs_check1"),
        ),
    )
    operation_id: Mapped[UUID] = mapped_column()
    account_id: Mapped[UUID] = mapped_column()
    issuer: Mapped[str] = mapped_column(String(2048))
    subject: Mapped[str] = mapped_column(String(255))
    expected_generation: Mapped[int] = mapped_column()
    deleting_generation: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    identity_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    block_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeletedSubject(Base):
    __tablename__ = "deleted_subjects"
    __table_args__ = (PrimaryKeyConstraint("issuer", "subject", name="deleted_subjects_pkey"),)
    issuer: Mapped[str] = mapped_column(String(2048))
    subject: Mapped[str] = mapped_column(String(255))
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "app.account_deletion_jobs.operation_id", name="deleted_subjects_operation_id_fkey"
        )
    )


class DeletionContext(Base):
    __tablename__ = "_deletion_context"
    __table_args__ = (PrimaryKeyConstraint("transaction_id", name="_deletion_context_pkey"),)
    transaction_id: Mapped[int] = mapped_column(BigInteger, autoincrement=False)
    owner_id: Mapped[UUID] = mapped_column()
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "app.account_deletion_jobs.operation_id", name="_deletion_context_operation_id_fkey"
        )
    )
