"""Relational metadata for migration drift checks; SQL functions own narrow writes."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from calorie_app.db.base import Base


def table(name, *columns, **kwargs):
    return Table(name, Base.metadata, *columns, schema="app", **kwargs)


def col(name, type_, *, pk=False, nullable=False, fk=None):
    args = [ForeignKey(fk)] if fk else []
    return Column(name, type_, *args, primary_key=pk, nullable=nullable)


AIControl = table(
    "ai_controls",
    col("id", Integer, pk=True),
    col("sync_epoch", UUID),
    col("dispatch_open", Boolean),
    col("closed_at", DateTime(timezone=True), nullable=True),
    col("reconciled_at", DateTime(timezone=True), nullable=True),
    col("reconciliation_hash", Text, nullable=True),
)
AIPool = table(
    "ai_pools",
    col("scope", Text, pk=True),
    col("provider", Text),
    col("project", Text),
    col("model", Text),
    col("environment", Text),
    col("rpm", Integer),
    col("tpm", BigInteger),
    col("rpd", Integer),
    col("confirmed_at", DateTime(timezone=True)),
    col("free_only", Boolean),
    col("enabled", Boolean),
    UniqueConstraint(
        "provider",
        "project",
        "model",
        "environment",
        name="ai_pools_provider_project_model_environment_key",
    ),
)
AIAnalysis = table(
    "ai_analyses",
    col("id", UUID, pk=True),
    col("owner_id", UUID, fk="app.user_accounts.id"),
    col("generation", Integer),
    col("sync_epoch", UUID),
    col("profile", JSONB),
    col("original_hash", Text),
    col("prepared_hash", Text),
    col("width", Integer),
    col("height", Integer),
    col("storage_key", Text, nullable=True),
    col("accepted_at", DateTime(timezone=True)),
    col("photo_expires_at", DateTime(timezone=True)),
    col("state", Text),
    col("revision", Integer),
    col("proposal", JSONB, nullable=True),
    col("error_code", Text, nullable=True),
    col("decision_state", Text),
    UniqueConstraint("owner_id", "id", name="ai_analyses_owner_id_id_key"),
    UniqueConstraint("storage_key", name="ai_analyses_storage_key_key"),
)
Index(
    "ix_ai_analyses_ttl",
    AIAnalysis.c.photo_expires_at,
    AIAnalysis.c.id,
    postgresql_where=text("storage_key IS NOT NULL"),
)
AIPhotoConsent = table(
    "ai_photo_consents",
    col("analysis_id", UUID, pk=True),
    col("owner_id", UUID),
    col("notice_version", Text),
    col("provider", Text),
    col("scope", Text),
    col("accepted_at", DateTime(timezone=True)),
    col("original_hash", Text),
    col("revoked_at", DateTime(timezone=True), nullable=True),
    ForeignKeyConstraint(
        ["owner_id", "analysis_id"], ["app.ai_analyses.owner_id", "app.ai_analyses.id"]
    ),
)
AIDecision = table(
    "ai_decisions",
    col("analysis_id", UUID, pk=True),
    col("owner_id", UUID),
    col("decision_hash", Text),
    col("meal_id", UUID),
    col("response", JSONB),
    col("confirmed_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["owner_id", "analysis_id"], ["app.ai_analyses.owner_id", "app.ai_analyses.id"]
    ),
)
AIReceipt = table(
    "ai_receipts",
    col("owner_id", UUID, pk=True, fk="app.user_accounts.id"),
    col("operation_id", UUID, pk=True),
    col("operation_kind", Text),
    col("request_hash", Text),
    col("generation", Integer),
    col("sync_epoch", UUID),
    col("status_code", Integer),
    col("response_payload", JSONB, nullable=True),
    col("result_minimal", JSONB),
    col("created_at", DateTime(timezone=True)),
)
Index(
    "ix_ai_receipts_retention",
    AIReceipt.c.owner_id,
    AIReceipt.c.created_at,
    AIReceipt.c.operation_id,
    postgresql_where=text("response_payload IS NOT NULL"),
)
AIAdmission = table(
    "ai_admissions",
    col("owner_id", UUID, pk=True, fk="app.user_accounts.id"),
    col("day", Date, pk=True),
    col("receipts", Integer),
    col("photos", Integer),
)
AIEnergyAdmission = table(
    "ai_energy_admissions",
    col("owner_id", UUID, pk=True, fk="app.user_accounts.id"),
    col("accepted_at", DateTime(timezone=True)),
)
AICleanupIntent = table(
    "ai_cleanup_intents",
    col("storage_key", Text, pk=True),
    col("created_at", DateTime(timezone=True)),
)
