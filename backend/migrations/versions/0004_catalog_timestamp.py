"""Immutable evidence for explicit recovery of legacy draft timestamp spelling."""

import sqlalchemy as sa
from alembic import op

revision = "0004_catalog_timestamp"
down_revision = "0003_catalog_offline"
branch_labels = None
depends_on = None


def upgrade():
    # No rewriting or rehashing of existing packages, including publications.
    op.create_table(
        "catalog_timestamp_recoveries",
        sa.Column("package_id", sa.Uuid(), primary_key=True),
        sa.Column("release", sa.Integer(), primary_key=True),
        sa.Column("published_at_text", sa.String(27), nullable=False),
        sa.Column("original_content_hash", sa.String(64), nullable=False),
        sa.Column("original_input", sa.Text(), nullable=False),
        sa.Column(
            "recovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "recovered_by", sa.Text(), nullable=False, server_default=sa.text("current_user")
        ),
        sa.ForeignKeyConstraint(
            ["package_id", "release"],
            ["app.offline_packages.package_id", "app.offline_packages.release"],
        ),
        sa.CheckConstraint("original_content_hash ~ '^[0-9a-f]{64}$'", name="content_hash"),
        sa.CheckConstraint(
            "published_at_text ~ "
            "'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            "([.][0-9]{1,6})?Z$'",
            name="timestamp_text",
        ),
        sa.CheckConstraint(
            "octet_length(original_input) BETWEEN 1 AND 52428800", name="evidence_size"
        ),
        schema="app",
    )
    op.execute("""
    CREATE FUNCTION app.catalog_timestamp_recovery_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE package app.offline_packages%ROWTYPE; evidence jsonb;
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'timestamp recovery audit is immutable' USING ERRCODE='23514';
        END IF;
        SELECT * INTO package FROM app.offline_packages
        WHERE package_id=NEW.package_id AND release=NEW.release FOR UPDATE;
        IF NOT FOUND OR package.state <> 'draft' OR NOT package.sealed
           OR package.content_hash IS DISTINCT FROM NEW.original_content_hash
           OR package.published_at IS DISTINCT FROM NEW.published_at_text::timestamptz THEN
            RAISE EXCEPTION 'timestamp recovery requires proven sealed draft'
                USING ERRCODE='23514';
        END IF;
        evidence := NEW.original_input::jsonb;
        IF evidence->>'published_at' IS DISTINCT FROM NEW.published_at_text
           OR evidence->>'package_id' IS DISTINCT FROM NEW.package_id::text
           OR (evidence->>'release')::integer IS DISTINCT FROM NEW.release
           OR encode(sha256(convert_to(NEW.original_input, 'UTF8')), 'hex')
              IS DISTINCT FROM NEW.original_content_hash
           OR NEW.recovered_by IS DISTINCT FROM current_user::text THEN
            RAISE EXCEPTION 'timestamp recovery evidence differs' USING ERRCODE='23514';
        END IF;
        NEW.recovered_at := clock_timestamp();
        RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER catalog_timestamp_recovery_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON app.catalog_timestamp_recoveries FOR EACH ROW "
        "EXECUTE FUNCTION app.catalog_timestamp_recovery_guard()"
    )
    op.execute(
        "REVOKE ALL ON app.catalog_timestamp_recoveries FROM calorie_app_api, calorie_app_worker"
    )
    op.execute(
        "GRANT SELECT ON app.catalog_timestamp_recoveries TO calorie_app_api, calorie_app_worker"
    )


def downgrade():
    # Removing proof would strand recovered packages: require an explicit
    # migration plan instead of silently breaking existing publications.
    op.execute("""
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM app.catalog_timestamp_recoveries) THEN
            RAISE EXCEPTION 'cannot remove timestamp recovery evidence'
                USING ERRCODE='23514';
        END IF;
    END $$
    """)
    op.drop_table("catalog_timestamp_recoveries", schema="app")
    op.execute("DROP FUNCTION app.catalog_timestamp_recovery_guard()")
