"""Jobs and anonymous attempt/physical transport permit metadata."""

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from calorie_app.modules.ai.models import col, table

AIJob = table(
    "ai_jobs",
    col("id", UUID, pk=True),
    col("owner_id", UUID),
    col("analysis_id", UUID),
    col("purpose", Text),
    col("generation", Integer),
    col("sync_epoch", UUID),
    col("pool_scope", Text, fk="app.ai_pools.scope"),
    col("state", Text),
    col("phase", Text),
    col("queue_deadline", DateTime(timezone=True)),
    col("next_attempt_at", DateTime(timezone=True)),
    col("started_at", DateTime(timezone=True), nullable=True),
    col("processing_deadline", DateTime(timezone=True), nullable=True),
    col("lease_until", DateTime(timezone=True), nullable=True),
    col("fence", UUID, nullable=True),
    col("generate_attempts", Integer),
    col("preflight_done", Boolean),
    col("input_tokens", Integer, nullable=True),
    UniqueConstraint("analysis_id", name="ai_jobs_analysis_id_key"),
    ForeignKeyConstraint(
        ["owner_id", "analysis_id"], ["app.ai_analyses.owner_id", "app.ai_analyses.id"]
    ),
)
Index(
    "uq_ai_one_active_account",
    AIJob.c.owner_id,
    unique=True,
    postgresql_where=text("state IN ('queued','running')"),
)
Index(
    "ix_ai_jobs_ready", AIJob.c.next_attempt_at, AIJob.c.id, postgresql_where=text("state='queued'")
)
AIAttempt = table(
    "ai_attempts",
    col("id", UUID, pk=True),
    col("job_id", UUID, nullable=True),
    col("pool_scope", Text, fk="app.ai_pools.scope"),
    col("purpose", Text),
    col("kind", Text),
    col("ordinal", Integer),
    col("dispatched_at", DateTime(timezone=True)),
    col("pacific_day", Date),
    col("reserved_tokens", Integer),
    col("input_tokens", Integer, nullable=True),
    col("output_tokens", Integer, nullable=True),
    col("thoughts_tokens", Integer, nullable=True),
    col("status", Text),
    col("io_finished_at", DateTime(timezone=True), nullable=True),
    col("worker_token_hash", Text),
    col("fenced_at", DateTime(timezone=True), nullable=True),
    col("fencing_evidence_hash", Text, nullable=True),
    ForeignKeyConstraint(["job_id"], ["app.ai_jobs.id"], ondelete="SET NULL"),
)
Index("ix_ai_attempts_window", AIAttempt.c.pool_scope, AIAttempt.c.dispatched_at)
Index("ix_ai_attempts_day", AIAttempt.c.pool_scope, AIAttempt.c.pacific_day)
AITransportPermit = table(
    "ai_transport_permits",
    col("environment", Text, pk=True),
    col("slot", Integer, pk=True),
    col("attempt_id", UUID, nullable=True, fk="app.ai_attempts.id"),
    UniqueConstraint("attempt_id", name="ai_transport_permits_attempt_id_key"),
)
