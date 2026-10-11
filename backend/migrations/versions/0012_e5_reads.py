"""Private read materializations, narrow ACL and bounded worker retention."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0012_e5_reads"
down_revision = "0011_e4_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "read_admissions",
        sa.Column(
            "owner_id",
            UUID(),
            sa.ForeignKey("app.user_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema="app",
    )
    op.execute(
        "REVOKE ALL ON app.read_admissions FROM PUBLIC,calorie_app_api,"
        "calorie_app_worker,calorie_app_deletion_operator"
    )
    op.execute("""
    CREATE FUNCTION app.admit_read_session(p_owner uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE v_state text;
    BEGIN
      SELECT state INTO v_state FROM app.user_accounts WHERE id=p_owner FOR UPDATE;
      IF NOT FOUND OR v_state <> 'active' THEN
        RAISE EXCEPTION 'admission requires active owner' USING ERRCODE='23514';
      END IF;
      -- INSERT and conflict UPDATE both write a tuple. A stale RR waiter gets
      -- 40001 rather than counting sessions from before the preceding commit.
      INSERT INTO app.read_admissions(owner_id) VALUES(p_owner)
        ON CONFLICT(owner_id) DO UPDATE SET owner_id=EXCLUDED.owner_id;
    END $$;
    REVOKE ALL ON FUNCTION app.admit_read_session(uuid)
      FROM PUBLIC,calorie_app_worker,calorie_app_deletion_operator;
    GRANT EXECUTE ON FUNCTION app.admit_read_session(uuid) TO calorie_app_api;
    """)
    op.create_table(
        "read_sessions",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column(
            "owner_id",
            UUID(),
            sa.ForeignKey("app.user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("epoch", UUID(), nullable=False),
        sa.Column("endpoint", sa.String(12), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("page_limit", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context", JSONB(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("id", "owner_id"),
        sa.CheckConstraint("endpoint IN ('meals','weights','diary-days')", name="endpoint"),
        sa.CheckConstraint("page_limit BETWEEN 1 AND 500", name="page_limit"),
        sa.CheckConstraint("expires_at = created_at + interval '60 minutes'", name="fixed_ttl"),
        sa.CheckConstraint("date_to >= date_from AND date_to-date_from < 366", name="date_range"),
        sa.CheckConstraint(
            "item_count BETWEEN 0 AND 100000 AND byte_count BETWEEN 0 AND 67108864",
            name="resource_limits",
        ),
        schema="app",
    )
    op.create_index(
        "ix_read_sessions_owner_expiry", "read_sessions", ["owner_id", "expires_at"], schema="app"
    )
    op.create_table(
        "read_session_items",
        sa.Column("session_id", UUID(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("owner_id", UUID(), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id", "owner_id"],
            ["app.read_sessions.id", "app.read_sessions.owner_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("position BETWEEN 1 AND 100000", name="position"),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 524288", name="byte_size"),
        schema="app",
    )
    for table in ("read_sessions", "read_session_items"):
        op.execute(
            f"REVOKE ALL ON app.{table} FROM PUBLIC,calorie_app_api,"
            "calorie_app_worker,calorie_app_deletion_operator"
        )
        op.execute(f"GRANT SELECT,INSERT ON app.{table} TO calorie_app_api")
    op.execute("GRANT UPDATE(item_count,byte_count) ON app.read_sessions TO calorie_app_api")
    op.execute("""
    CREATE FUNCTION app.discard_unpaged_read(p_owner uuid,p_session uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE v_generation integer;
    BEGIN
      SELECT generation INTO v_generation FROM app.user_accounts
        WHERE id=p_owner AND state='active' FOR UPDATE;
      IF NOT FOUND OR NOT EXISTS (
          SELECT 1 FROM app.read_sessions s WHERE s.id=p_session AND s.owner_id=p_owner
            AND s.generation=v_generation AND s.item_count<=s.page_limit
            AND s.byte_count<=1048576
            AND EXISTS(SELECT 1 FROM app.installation_state e
                       WHERE e.id=1 AND e.sync_epoch=s.epoch)) THEN
        RAISE EXCEPTION 'invalid unpaged read context' USING ERRCODE='23514';
      END IF;
      -- Cascades only the selected technical items; never changes diary or ACKs.
      DELETE FROM app.read_sessions WHERE id=p_session AND owner_id=p_owner;
    END $$;
    REVOKE ALL ON FUNCTION app.discard_unpaged_read(uuid,uuid)
      FROM PUBLIC,calorie_app_worker,calorie_app_deletion_operator;
    GRANT EXECUTE ON FUNCTION app.discard_unpaged_read(uuid,uuid) TO calorie_app_api;
    """)

    op.execute("""
    CREATE FUNCTION app.prune_read_sessions(p_owner uuid,p_batch integer DEFAULT 1000) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE v_state text; v_now timestamptz; v_items integer; v_sessions integer;
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
        SELECT i.session_id,i.position FROM app.read_session_items i
        JOIN app.read_sessions s ON s.id=i.session_id AND s.owner_id=i.owner_id
        WHERE i.owner_id=p_owner AND s.expires_at <= v_now
        ORDER BY s.expires_at,i.session_id,i.position LIMIT p_batch
      ) DELETE FROM app.read_session_items i USING candidates x
        WHERE i.owner_id=p_owner AND i.session_id=x.session_id AND i.position=x.position;
      GET DIAGNOSTICS v_items=ROW_COUNT;
      WITH candidates AS (
        SELECT s.id FROM app.read_sessions s WHERE s.owner_id=p_owner AND s.expires_at <= v_now
          AND NOT EXISTS (SELECT 1 FROM app.read_session_items i WHERE i.session_id=s.id)
        ORDER BY s.expires_at,s.id LIMIT p_batch
      ) DELETE FROM app.read_sessions s USING candidates x WHERE s.id=x.id AND s.owner_id=p_owner;
      GET DIAGNOSTICS v_sessions=ROW_COUNT;
      RETURN jsonb_build_object('read_items',v_items,'read_sessions',v_sessions);
    END $$;
    REVOKE ALL ON FUNCTION app.prune_read_sessions(uuid,integer)
      FROM PUBLIC,calorie_app_api,calorie_app_deletion_operator;
    GRANT EXECUTE ON FUNCTION app.prune_read_sessions(uuid,integer) TO calorie_app_worker;
    """)


def downgrade():
    # Only technical copies are removed. Existing E4 purge cascades through account FK.
    op.execute("DROP FUNCTION app.prune_read_sessions(uuid,integer)")
    op.execute("DROP FUNCTION app.discard_unpaged_read(uuid,uuid)")
    op.drop_table("read_session_items", schema="app")
    op.drop_table("read_sessions", schema="app")
    op.execute("DROP FUNCTION app.admit_read_session(uuid)")
    op.drop_table("read_admissions", schema="app")
