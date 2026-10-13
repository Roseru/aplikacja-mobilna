"""Metadata for migration drift; privileged functions own every energy write."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from calorie_app.modules.ai.models import col, table

EnergyAxis = table(
    "energy_axes",
    col("owner_id", UUID, pk=True, fk="app.user_accounts.id"),
    col("revision", Integer),
    col("baseline_id", UUID, nullable=True),
    col("baseline_epoch", UUID, nullable=True),
    col("baseline_consent_revision", Integer, nullable=True),
    col("baseline_notice", JSONB, nullable=True),
    col("last_applied_at", DateTime(timezone=True), nullable=True),
    col("last_auto_checked_date", Date, nullable=True),
    col("last_auto_state", Text, nullable=True),
)
EnergyVersion = table(
    "energy_versions",
    col("id", UUID, pk=True),
    col("owner_id", UUID, fk="app.user_accounts.id"),
    col("revision", Integer),
    col("effective_from", Date),
    col("maintenance_kcal", Numeric),
    col("method", Text),
    col("source", Text),
    col("source_id", UUID),
    col("supersedes", UUID, nullable=True),
    col("decided_at", DateTime(timezone=True)),
    col("audit", JSONB),
    UniqueConstraint("owner_id", "id", name="energy_versions_owner_id_id_key"),
    UniqueConstraint("owner_id", "revision", name="energy_versions_owner_id_revision_key"),
    UniqueConstraint(
        "owner_id", "source", "source_id", name="energy_versions_owner_id_source_source_id_key"
    ),
    ForeignKeyConstraint(
        ["owner_id", "supersedes"], ["app.energy_versions.owner_id", "app.energy_versions.id"]
    ),
)
Index(
    "ix_energy_versions_date",
    EnergyVersion.c.owner_id,
    EnergyVersion.c.effective_from,
    EnergyVersion.c.revision,
)
EnergyAnalysis = table(
    "energy_analyses",
    col("id", UUID, pk=True),
    col("owner_id", UUID, fk="app.user_accounts.id"),
    col("generation", Integer),
    col("sync_epoch", UUID),
    col("revision", Integer),
    col("automatic", Boolean),
    col("accepted_at", DateTime(timezone=True)),
    col("date_from", Date),
    col("date_to", Date),
    col("context", JSONB),
    col("fingerprint", Text),
    col("profile", JSONB),
    col("notice", JSONB),
    col("result", JSONB),
    col("state", Text),
    col("created_at", DateTime(timezone=True), nullable=True),
    col("expires_at", DateTime(timezone=True), nullable=True),
    col("explanation", JSONB, nullable=True),
    col("error_code", Text, nullable=True),
    UniqueConstraint("owner_id", "id", name="energy_analyses_owner_id_id_key"),
)
Index(
    "ix_energy_analyses_owner",
    EnergyAnalysis.c.owner_id,
    EnergyAnalysis.c.accepted_at,
    EnergyAnalysis.c.id,
)
EnergyReceipt = table(
    "energy_receipts",
    col("owner_id", UUID, pk=True, fk="app.user_accounts.id"),
    col("key", UUID, pk=True),
    col("request_hash", Text),
    col("generation", Integer),
    col("sync_epoch", UUID),
    col("response", JSONB, nullable=True),
    col("result_minimal", JSONB),
    col("created_at", DateTime(timezone=True)),
)

EnergyChange = table(
    "energy_changes",
    col("owner_id", UUID, pk=True),
    col("position", BigInteger, pk=True),
    col("version_id", UUID),
    ForeignKeyConstraint(
        ["owner_id", "position"],
        ["app.sync_changes.owner_id", "app.sync_changes.position"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["owner_id", "version_id"], ["app.energy_versions.owner_id", "app.energy_versions.id"]
    ),
)
