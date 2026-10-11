from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from calorie_app.db.base import Base


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (CheckConstraint("revision BETWEEN 1 AND 2147483647", name="revision_range"),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    ranking: Mapped[bool] = mapped_column(default=False, server_default="false")
    automatic_energy_adjustment: Mapped[bool] = mapped_column(default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Profile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        Index(
            "uq_user_profiles_live_owner",
            "owner_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("revision BETWEEN 1 AND 2147483647", name="revision_range"),
        CheckConstraint("length(pseudonym) BETWEEN 1 AND 80", name="pseudonym_length"),
        CheckConstraint(
            "height_cm IS NULL OR (height_cm > 0 AND height_cm <= 300 "
            "AND height_cm::text NOT IN ('NaN','Infinity','-Infinity'))",
            name="height_range",
        ),
        CheckConstraint(
            "activity_class IN ('stationary','line','commando')", name="activity_class"
        ),
        CheckConstraint("length(time_zone) BETWEEN 1 AND 100", name="time_zone_length"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"))
    revision: Mapped[int] = mapped_column(default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pseudonym: Mapped[str] = mapped_column(String(80))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    activity_class: Mapped[str] = mapped_column(String(16))
    time_zone: Mapped[str] = mapped_column(String(100))


class GoalTimeline(Base):
    __tablename__ = "goal_timelines"
    __table_args__ = (CheckConstraint("revision BETWEEN 0 AND 2147483647", name="revision_range"),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(default=0, server_default="0")


class GoalVersion(Base):
    __tablename__ = "goal_versions"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        UniqueConstraint("owner_id", "timeline_revision", name="uq_goal_versions_owner_timeline"),
        ForeignKeyConstraint(
            ["owner_id", "correction_of"], ["app.goal_versions.owner_id", "app.goal_versions.id"]
        ),
        CheckConstraint("revision = 1", name="immutable_revision"),
        CheckConstraint("timeline_revision BETWEEN 1 AND 2147483647", name="timeline_range"),
        CheckConstraint("timeline_base_revision = timeline_revision - 1", name="timeline_base"),
        CheckConstraint(
            "energy_kcal > 0 AND energy_kcal <= 20000 "
            "AND energy_kcal::text NOT IN ('NaN','Infinity','-Infinity')",
            name="energy_range",
        ),
        *[
            CheckConstraint(
                f"{field} IS NULL OR ({field} >= 0 AND {field} <= 5000 "
                f"AND {field}::text NOT IN ('NaN','Infinity','-Infinity'))",
                name=f"{field}_range",
            )
            for field in ("protein_g", "fat_g", "carbs_g")
        ],
        CheckConstraint(
            "activity_class IN ('stationary','line','commando')", name="activity_class"
        ),
        CheckConstraint("goal_type IN ('reduce','maintain','gain')", name="goal_type"),
        CheckConstraint(
            "(reason='user_decision' AND correction_of IS NULL) OR "
            "(reason='history_correction' AND correction_of IS NOT NULL)",
            name="correction_audit",
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        CheckConstraint("correction_of IS NULL OR correction_of <> id", name="no_self_correction"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.user_accounts.id"))
    revision: Mapped[int] = mapped_column(default=1, server_default="1")
    timeline_revision: Mapped[int] = mapped_column()
    timeline_base_revision: Mapped[int] = mapped_column()
    effective_from: Mapped[date] = mapped_column(Date)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    time_zone: Mapped[str] = mapped_column(String(100))
    goal_type: Mapped[str] = mapped_column(String(16))
    energy_kcal: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    activity_class: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(20))
    correction_of: Mapped[UUID | None] = mapped_column()
    payload: Mapped[dict] = mapped_column(JSONB)
