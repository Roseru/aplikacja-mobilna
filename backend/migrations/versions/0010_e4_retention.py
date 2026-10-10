"""Durable materialized synchronization pages and bounded technical retention."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0010_e4_retention"
down_revision = "0009_e4_sync"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sync_sessions",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("owner_id", UUID(), sa.ForeignKey("app.user_accounts.id"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("epoch", UUID(), nullable=False),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("page_limit", sa.Integer(), nullable=False),
        sa.Column("high_position", sa.BigInteger(), nullable=False),
        sa.Column("base_position", sa.BigInteger(), nullable=False),
        sa.Column("base_issued_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timeline_revision", sa.Integer(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("final_offset", sa.Integer()),
        sa.Column("final_response", JSONB()),
        sa.UniqueConstraint("id", "owner_id"),
        sa.CheckConstraint("mode IN ('snapshot','incremental')", name="mode"),
        sa.CheckConstraint("page_limit BETWEEN 1 AND 500", name="page_limit"),
        sa.CheckConstraint("expires_at = created_at + interval '60 minutes'", name="fixed_ttl"),
        sa.CheckConstraint(
            "high_position >= 0 AND base_position >= 0 AND high_position >= base_position",
            name="position_range",
        ),
        sa.CheckConstraint(
            "item_count BETWEEN 0 AND 100000 AND byte_count BETWEEN 0 AND 67108864",
            name="resource_limits",
        ),
        schema="app",
    )
    op.create_index(
        "ix_sync_sessions_owner_expiry", "sync_sessions", ["owner_id", "expires_at"], schema="app"
    )
    op.create_table(
        "sync_session_items",
        sa.Column("session_id", UUID(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("owner_id", UUID(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id", "owner_id"],
            ["app.sync_sessions.id", "app.sync_sessions.owner_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("position BETWEEN 1 AND 100000", name="position"),
        sa.CheckConstraint(
            "kind IN ('entities','recovery_mappings','operation_receipts')", name="kind"
        ),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 524288", name="byte_size"),
        schema="app",
    )
    for table in ("sync_sessions", "sync_session_items"):
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE ON app.{table} TO calorie_app_api, calorie_app_worker"
        )
        op.execute(
            f"REVOKE DELETE, TRUNCATE ON app.{table} "
            "FROM PUBLIC, calorie_app_api, calorie_app_worker"
        )
    op.execute("""
    CREATE FUNCTION app.prune_sync(p_owner uuid,p_batch integer DEFAULT 1000) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE v_state text; v_now timestamptz; v_changes integer; v_receipts integer;
            v_items integer; v_sessions integer;
    BEGIN
      IF p_owner IS NULL OR p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'invalid retention arguments' USING ERRCODE='22023';
      END IF;
      SELECT state INTO v_state FROM app.user_accounts WHERE id=p_owner FOR UPDATE;
      IF NOT FOUND OR v_state <> 'active' THEN
        RAISE EXCEPTION 'retention requires active owner' USING ERRCODE='23514';
      END IF;
      PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
      v_now := clock_timestamp();
      WITH candidates AS (
        SELECT c.position FROM app.sync_changes c
        WHERE c.owner_id=p_owner AND c.created_at < v_now-interval '60 days'
          AND NOT EXISTS (SELECT 1 FROM app.sync_sessions s WHERE s.owner_id=p_owner
              AND s.expires_at > v_now AND s.mode='incremental'
              AND c.position > s.base_position AND c.position <= s.high_position)
        ORDER BY c.position LIMIT p_batch
      ) DELETE FROM app.sync_changes c USING candidates x
        WHERE c.owner_id=p_owner AND c.position=x.position;
      GET DIAGNOSTICS v_changes=ROW_COUNT;
      WITH candidates AS (
        SELECT operation_id FROM app.sync_receipts WHERE owner_id=p_owner
          AND created_at < v_now-interval '60 days' AND response IS NOT NULL
        ORDER BY created_at,operation_id LIMIT p_batch
      ) UPDATE app.sync_receipts r SET response=NULL FROM candidates x
        WHERE r.owner_id=p_owner AND r.operation_id=x.operation_id;
      GET DIAGNOSTICS v_receipts=ROW_COUNT;
      WITH candidates AS (
        SELECT i.session_id,i.position FROM app.sync_session_items i
        JOIN app.sync_sessions s ON s.id=i.session_id AND s.owner_id=i.owner_id
        WHERE i.owner_id=p_owner AND s.expires_at <= v_now
        ORDER BY s.expires_at,i.session_id,i.position LIMIT p_batch
      ) DELETE FROM app.sync_session_items i USING candidates x
        WHERE i.owner_id=p_owner AND i.session_id=x.session_id AND i.position=x.position;
      GET DIAGNOSTICS v_items=ROW_COUNT;
      WITH candidates AS (
        SELECT s.id FROM app.sync_sessions s WHERE s.owner_id=p_owner AND s.expires_at <= v_now
          AND NOT EXISTS (SELECT 1 FROM app.sync_session_items i WHERE i.session_id=s.id)
        ORDER BY s.expires_at,s.id LIMIT p_batch
      ) DELETE FROM app.sync_sessions s USING candidates x WHERE s.id=x.id AND s.owner_id=p_owner;
      GET DIAGNOSTICS v_sessions=ROW_COUNT;
      RETURN jsonb_build_object('changes',v_changes,'receipts',v_receipts,
                               'items',v_items,'sessions',v_sessions);
    END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.prune_sync(uuid,integer) FROM PUBLIC,calorie_app_api")
    op.execute("GRANT EXECUTE ON FUNCTION app.prune_sync(uuid,integer) TO calorie_app_worker")


def downgrade():
    # These tables are technical copies only; private graph and minimal sync
    # evidence from 0009 retain their identity/revision/deletion protection.
    op.execute("DROP FUNCTION app.prune_sync(uuid,integer)")
    op.drop_table("sync_session_items", schema="app")
    op.drop_table("sync_sessions", schema="app")
