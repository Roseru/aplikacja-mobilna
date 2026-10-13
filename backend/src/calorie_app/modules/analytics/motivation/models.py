"""Durable private projections; source-derived SQL functions own their writes."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class MotivationAccount(Base):
    __tablename__ = "motivation_accounts"
    __table_args__ = (
        Index(
            "ix_motivation_accounts_due",
            "next_matures_at",
            "owner_id",
            postgresql_where=text("next_matures_at IS NOT NULL"),
        ),
        Index(
            "ix_motivation_accounts_backfill",
            "owner_id",
            postgresql_where=text("backfill_state='pending'"),
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text)
    total_points: Mapped[int] = mapped_column(BigInteger)
    active_badges: Mapped[int] = mapped_column()
    revision: Mapped[int] = mapped_column(BigInteger)
    source_position: Mapped[int] = mapped_column(BigInteger)
    sync_epoch: Mapped[UUID] = mapped_column()
    backfill_state: Mapped[str] = mapped_column(Text)
    backfill_after: Mapped[date | None] = mapped_column()
    next_matures_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict] = mapped_column(JSONB)


class MotivationDay(Base):
    __tablename__ = "motivation_days"
    __table_args__ = (Index("ix_motivation_days_mature", "owner_id", "matures_at", "local_date"),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    local_date: Mapped[date] = mapped_column(primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text, primary_key=True)
    time_zone: Mapped[str | None] = mapped_column(String(100))
    matures_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    source_revisions: Mapped[dict] = mapped_column(JSONB)
    effective_complete: Mapped[bool] = mapped_column()
    in_goal: Mapped[bool | None] = mapped_column()
    candidate_points: Mapped[int] = mapped_column(SmallInteger)
    materialized_points: Mapped[int] = mapped_column(SmallInteger)
    weight_matures_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ration_matures_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weight_confirmed: Mapped[bool] = mapped_column()
    ration_confirmed: Mapped[bool] = mapped_column()
    day_confirmed: Mapped[bool] = mapped_column()
    qualified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MotivationBadge(Base):
    __tablename__ = "motivation_badges"
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    badge_code: Mapped[str] = mapped_column(Text, primary_key=True)
    rule_version: Mapped[str] = mapped_column(Text, primary_key=True)
    active: Mapped[bool] = mapped_column()
    first_awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    witness: Mapped[list] = mapped_column(JSONB)


class RankingAffirmation(Base):
    __tablename__ = "ranking_affirmations"
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.user_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    ranking_consent_epoch: Mapped[UUID] = mapped_column()
    source_revision: Mapped[int] = mapped_column()


class RankingSession(Base):
    __tablename__ = "ranking_sessions"
    __table_args__ = (
        Index("ix_ranking_sessions_requester", "requester_id", "expires_at"),
        Index("ix_ranking_sessions_expiry", "expires_at"),
    )
    session_id: Mapped[UUID] = mapped_column(primary_key=True)
    requester_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.user_accounts.id", ondelete="CASCADE")
    )
    generation: Mapped[int] = mapped_column()
    sync_epoch: Mapped[UUID] = mapped_column()
    page_limit: Mapped[int] = mapped_column()
    purpose: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RankingCursor(Base):
    __tablename__ = "ranking_cursors"
    __table_args__ = (
        Index("ix_ranking_cursors_anchor", "anchor_id"),
        UniqueConstraint("session_id", "step", name="ranking_cursors_session_id_step_key"),
    )
    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.ranking_sessions.session_id", ondelete="CASCADE")
    )
    seek_points: Mapped[int] = mapped_column(BigInteger)
    seek_pseudonym: Mapped[str] = mapped_column(Text(collation="C"))
    anchor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("app.user_accounts.id", ondelete="SET NULL")
    )
    step: Mapped[int] = mapped_column(BigInteger)
    next_token: Mapped[str | None] = mapped_column(Text)
