"""Stop persistent cursor issuance and retain exact legacy expiry semantics."""

import sqlalchemy as sa
from alembic import op

revision = "0005_ration_cursors"
down_revision = "0004_catalog_timestamp"
branch_labels = None
depends_on = None


def upgrade():
    # Existing UUID cursors remain valid until their original expiry. Closing
    # issuance makes the sum of legacy rows + tombstones bounded by this backlog.
    op.create_table(
        "ration_page_token_tombstones",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "package_id",
            sa.Uuid(),
            sa.ForeignKey("app.offline_channels.package_id"),
            nullable=False,
        ),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.CheckConstraint('"limit" BETWEEN 1 AND 500', name="page_limit"),
        schema="app",
    )
    op.create_index(
        "ix_ration_page_tokens_expires_at", "ration_page_tokens", ["expires_at"], schema="app"
    )
    op.execute("REVOKE INSERT ON app.ration_page_tokens FROM calorie_app_api")
    op.execute("""
    CREATE OR REPLACE FUNCTION app.catalog_page_token_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'legacy page token issuance is closed' USING ERRCODE='23514';
    END $$
    """)
    op.execute("""
    CREATE FUNCTION app.prune_ration_page_tokens() RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    DECLARE removed_count integer;
    BEGIN
        WITH expired AS (
            SELECT id FROM app.ration_page_tokens
            WHERE expires_at <= clock_timestamp()
            ORDER BY expires_at, id LIMIT 1000 FOR UPDATE SKIP LOCKED
        ), removed AS (
            DELETE FROM app.ration_page_tokens t USING expired e WHERE t.id=e.id
            RETURNING t.id, t.package_id, t."limit"
        )
        INSERT INTO app.ration_page_token_tombstones (id, package_id, "limit")
        SELECT id, package_id, "limit" FROM removed;
        GET DIAGNOSTICS removed_count = ROW_COUNT;
        RETURN removed_count;
    END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.prune_ration_page_tokens() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.prune_ration_page_tokens() TO calorie_app_api")
    op.execute(
        "REVOKE ALL ON app.ration_page_token_tombstones FROM calorie_app_api, calorie_app_worker"
    )
    op.execute("GRANT SELECT ON app.ration_page_token_tombstones TO calorie_app_api")


def downgrade():
    # Dropping tombstones would silently change known expired UUIDs from410 to422.
    op.execute("""
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM app.ration_page_token_tombstones) THEN
            RAISE EXCEPTION 'cannot remove legacy page expiry evidence' USING ERRCODE='23514';
        END IF;
    END $$
    """)
    op.execute("DROP FUNCTION app.prune_ration_page_tokens()")
    op.drop_index("ix_ration_page_tokens_expires_at", table_name="ration_page_tokens", schema="app")
    op.drop_table("ration_page_token_tombstones", schema="app")
    op.execute("""
    CREATE OR REPLACE FUNCTION app.catalog_page_token_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM app.offline_packages WHERE package_id=NEW.package_id
                       AND release=NEW.release AND state='published') THEN
            RAISE EXCEPTION 'page token requires a published snapshot' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$
    """)
    op.execute("GRANT INSERT ON app.ration_page_tokens TO calorie_app_api")
