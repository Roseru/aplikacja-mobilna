"""Metadata for the immutable lifecycle tables; privileged SQL owns their writes."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class NemesisControl(Base):
    __tablename__ = "nemesis_control"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    sync_epoch: Mapped[UUID] = mapped_column()
    enabled: Mapped[bool] = mapped_column(server_default=text("false"))
    schema_revision: Mapped[str | None] = mapped_column(Text)
    initializer_revision: Mapped[str | None] = mapped_column(Text)
    projector_revision: Mapped[str | None] = mapped_column(Text)
    finalizer_revision: Mapped[str | None] = mapped_column(Text)


class NemesisRelease(Base):
    __tablename__ = "nemesis_releases"
    schema_revision: Mapped[str | None] = mapped_column(Text)
    initializer_revision: Mapped[str | None] = mapped_column(Text)
    projector_revision: Mapped[str] = mapped_column(Text, primary_key=True)
    finalizer_revision: Mapped[str] = mapped_column(Text, primary_key=True)


class NemesisChallenge(Base):
    __tablename__ = "nemesis_challenges"
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    inviter_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.user_accounts.id"))
    invitee_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.user_accounts.id"))
    inviter_generation: Mapped[int] = mapped_column()
    invitee_generation: Mapped[int] = mapped_column()
    sync_epoch: Mapped[UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(BigInteger, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text)
    terms: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_date: Mapped[date | None] = mapped_column()
    end_date: Mapped[date | None] = mapped_column()
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_status: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)


Index(
    "ix_nemesis_inviter_history",
    NemesisChallenge.inviter_id,
    NemesisChallenge.created_at.desc(),
    NemesisChallenge.id.desc(),
)
Index(
    "ix_nemesis_invitee_history",
    NemesisChallenge.invitee_id,
    NemesisChallenge.created_at.desc(),
    NemesisChallenge.id.desc(),
)
Index(
    "ix_nemesis_due",
    NemesisChallenge.status,
    NemesisChallenge.expires_at,
    NemesisChallenge.end_at,
    NemesisChallenge.id,
    postgresql_where=text("status IN ('invited','active')"),
)


class NemesisSlot(Base):
    __tablename__ = "nemesis_slots"
    __table_args__ = (
        UniqueConstraint(
            "challenge_id", "owner_id", name="nemesis_slots_challenge_id_owner_id_key"
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    challenge_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.nemesis_challenges.id", ondelete="CASCADE")
    )


class NemesisShareCode(Base):
    __tablename__ = "nemesis_share_codes"
    __table_args__ = (UniqueConstraint("digest", name="nemesis_share_codes_digest_key"),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column()
    sync_epoch: Mapped[UUID] = mapped_column()
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NemesisReceipt(Base):
    __tablename__ = "nemesis_receipts"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    operation: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column()
    sync_epoch: Mapped[UUID] = mapped_column()
    entity_id: Mapped[UUID | None] = mapped_column()
    accepted_revision: Mapped[int | None] = mapped_column(BigInteger)
    http_status: Mapped[int] = mapped_column()
    code: Mapped[str] = mapped_column(Text)
    response: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index(
    "ix_nemesis_receipt_cleanup",
    NemesisReceipt.response_expires_at,
    NemesisReceipt.owner_id,
    NemesisReceipt.operation,
    NemesisReceipt.key,
    postgresql_where=text("response IS NOT NULL"),
)


class NemesisAdmission(Base):
    __tablename__ = "nemesis_admissions"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index(
    "ix_nemesis_admission_window",
    NemesisAdmission.owner_id,
    NemesisAdmission.kind,
    NemesisAdmission.admitted_at,
)


class NemesisCursor(Base):
    __tablename__ = "nemesis_cursors"
    token: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    requester_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"))
    generation: Mapped[int] = mapped_column()
    sync_epoch: Mapped[UUID] = mapped_column()
    purpose: Mapped[str] = mapped_column(Text, server_default=text("'own_metadata'"))
    anchor_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    anchor_id: Mapped[UUID] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index("ix_nemesis_cursor_cleanup", NemesisCursor.expires_at, NemesisCursor.token)


class NemesisProjectionSeed(Base):
    __tablename__ = "nemesis_projection_seeds"
    challenge_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.nemesis_challenges.id", ondelete="CASCADE"), primary_key=True
    )
    initializer_revision: Mapped[str] = mapped_column(Text)
    resolver_revision: Mapped[str] = mapped_column(Text)
    initialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_revision: Mapped[int] = mapped_column(BigInteger, server_default=text("1"))
    final_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NemesisDayProjection(Base):
    __tablename__ = "nemesis_day_projections"
    challenge_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.nemesis_challenges.id", ondelete="CASCADE"), primary_key=True
    )
    participant_role: Mapped[str] = mapped_column(Text, primary_key=True)
    local_date: Mapped[date] = mapped_column(primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text, primary_key=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    matures_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    candidate_points: Mapped[int] = mapped_column(SmallInteger)
    effective_complete: Mapped[bool] = mapped_column()
    in_goal: Mapped[bool | None] = mapped_column()
    intake_kcal: Mapped[Decimal | None] = mapped_column(Numeric)
    maintenance_kcal: Mapped[Decimal | None] = mapped_column(Numeric)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric)
    weight_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weight_id: Mapped[UUID | None] = mapped_column()
    weight_revision: Mapped[int | None] = mapped_column()
    source_revisions: Mapped[dict] = mapped_column(JSONB)
    source_position: Mapped[int] = mapped_column(BigInteger)
    qualified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(BigInteger, server_default=text("1"))


class NemesisFinalResult(Base):
    __tablename__ = "nemesis_final_results"
    challenge_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.nemesis_challenges.id", ondelete="CASCADE"), primary_key=True
    )
    participant_role: Mapped[str] = mapped_column(Text, primary_key=True)
    aggregates: Mapped[dict] = mapped_column(JSONB)
    read_revision: Mapped[int] = mapped_column(BigInteger)
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NemesisRuntimeContract(Base):
    __tablename__ = "nemesis_runtime_contract"
    signature: Mapped[str] = mapped_column(Text, primary_key=True)
    body_sha256: Mapped[str] = mapped_column(Text)
