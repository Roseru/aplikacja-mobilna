"""Catalog snapshots, exact package membership and immutable publication."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_catalog_offline"
down_revision = "0002_finite_nutrition"
branch_labels = None
depends_on = None


def _check(table, name, predicate):
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, predicate, schema="app")


def _package_fk():
    return sa.ForeignKeyConstraint(
        ["package_id", "release"],
        ["app.offline_packages.package_id", "app.offline_packages.release"],
    )


def upgrade():
    for column in (
        sa.Column("document_id", sa.String(2000)),
        sa.Column("url", sa.String()),
        sa.Column("checked_on", sa.Date()),
        sa.Column("market", sa.String(2000)),
        sa.Column("manufacturer", sa.String(2000)),
        sa.Column("variant", sa.String(2000)),
        sa.Column("basis", sa.String(32)),
        sa.Column("missing_data", JSONB),
        sa.Column("notes", JSONB),
        sa.Column("content_hash", sa.String(64)),
    ):
        op.add_column("product_sources", column, schema="app")
    _check(
        "product_sources",
        "source_basis",
        "basis IS NULL OR basis IN "
        "('assumed_listed_quantity', 'per_100_g', 'per_100_ml', "
        "'label_serving', 'mixed_labels')",
    )
    _check(
        "product_sources",
        "sealed_metadata",
        "content_hash IS NULL OR (content_hash ~ '^[0-9a-f]{64}$' "
        "AND document_id IS NOT NULL AND basis IS NOT NULL "
        "AND missing_data IS NOT NULL AND notes IS NOT NULL)",
    )
    op.alter_column(
        "product_versions",
        "name",
        type_=sa.String(2000),
        existing_type=sa.String(255),
        existing_nullable=False,
        schema="app",
    )
    for column in (
        sa.Column("aliases", JSONB),
        sa.Column("brand", sa.String(2000)),
        sa.Column("variant", sa.String(2000)),
        sa.Column("package_amount", sa.Numeric(12, 6)),
        sa.Column("package_unit", sa.String(2)),
        sa.Column("density_amount", sa.Numeric(12, 6)),
        sa.Column("density_source_id", sa.Uuid()),
        sa.Column("source_locator", sa.String(2000)),
        sa.Column("status", sa.String(16)),
        sa.Column("preparation", sa.String(2000)),
        sa.Column("content_hash", sa.String(64)),
    ):
        op.add_column("product_versions", column, schema="app")
    op.create_foreign_key(
        op.f("fk_product_versions_density_source_id_product_sources"),
        "product_versions",
        "product_sources",
        ["density_source_id"],
        ["id"],
        source_schema="app",
        referent_schema="app",
    )
    _check(
        "product_versions",
        "finite_package_amount",
        "package_amount IS NULL OR (package_amount > 0 AND package_amount <= 999999.999999)",
    )
    _check(
        "product_versions",
        "package_quantity",
        "(package_amount IS NULL AND package_unit IS NULL) OR "
        "(package_amount IS NOT NULL AND package_unit IS NOT NULL "
        "AND package_unit IN ('g', 'ml'))",
    )
    _check(
        "product_versions",
        "finite_density",
        "(density_amount IS NULL AND density_source_id IS NULL) OR "
        "(density_amount IS NOT NULL AND density_source_id IS NOT NULL "
        "AND density_amount > 0 AND density_amount <= 999999.999999)",
    )
    _check("product_versions", "status", "status IS NULL OR status IN ('unverified', 'verified')")
    _check(
        "product_versions",
        "sealed_metadata",
        "content_hash IS NULL OR (content_hash ~ '^[0-9a-f]{64}$' "
        "AND aliases IS NOT NULL AND package_amount IS NOT NULL "
        "AND source_locator IS NOT NULL AND status IS NOT NULL)",
    )
    op.create_table("rations", sa.Column("id", sa.Uuid(), primary_key=True), schema="app")
    op.create_table(
        "ration_versions",
        sa.Column("ration_id", sa.Uuid(), sa.ForeignKey("app.rations.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(2000), nullable=False),
        sa.Column("manufacturer", sa.String(2000)),
        sa.Column("variant", sa.String(2000)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("app.product_sources.id"), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("excluded_items", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
        sa.CheckConstraint("status IN ('unverified', 'verified')", name="status"),
        sa.CheckConstraint(
            "content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'", name="content_hash"
        ),
        schema="app",
    )
    op.create_table(
        "ration_components",
        sa.Column("ration_id", sa.Uuid(), primary_key=True),
        sa.Column("ration_revision", sa.Integer(), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("group_name", sa.String(2000), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_revision", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 6), nullable=False),
        sa.Column("unit", sa.String(2), nullable=False),
        sa.Column("optional", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ration_id", "ration_revision"],
            ["app.ration_versions.ration_id", "app.ration_versions.revision"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "product_revision"],
            ["app.product_versions.product_id", "app.product_versions.revision"],
        ),
        sa.CheckConstraint("position >= 1 AND position <= 100000", name="position"),
        sa.CheckConstraint("amount > 0 AND amount <= 999999.999999", name="finite_amount"),
        sa.CheckConstraint("unit IN ('g', 'ml')", name="unit"),
        schema="app",
    )
    op.create_table(
        "offline_channels",
        sa.Column("package_id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("active_release", sa.Integer()),
        sa.CheckConstraint("kind IN ('demo', 'official')", name="kind"),
        sa.CheckConstraint("active_release IS NULL OR active_release >= 1", name="active_release"),
        schema="app",
    )
    op.create_table(
        "offline_packages",
        sa.Column(
            "package_id",
            sa.Uuid(),
            sa.ForeignKey("app.offline_channels.package_id"),
            primary_key=True,
        ),
        sa.Column("release", sa.Integer(), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("min_reader_version", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("sealed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("product_count", sa.Integer(), nullable=False),
        sa.Column("ration_count", sa.Integer(), nullable=False),
        sa.Column("component_count", sa.Integer(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("compressed_bytes", sa.Integer()),
        sa.Column("uncompressed_bytes", sa.Integer()),
        sa.Column("artifact_path", sa.String(4096)),
        sa.CheckConstraint("release >= 1", name="positive_release"),
        sa.CheckConstraint("schema_version = 1 AND min_reader_version = 1", name="reader_version"),
        sa.CheckConstraint("state IN ('draft', 'published')", name="state"),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash"),
        sa.CheckConstraint(
            "product_count BETWEEN 1 AND 10000 AND ration_count BETWEEN 1 AND 1000 "
            "AND component_count BETWEEN 1 AND 100000 AND source_count BETWEEN 1 AND 10000",
            name="counts",
        ),
        sa.CheckConstraint(
            "(sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$') AND "
            "(compressed_bytes IS NULL OR compressed_bytes BETWEEN 1 AND 10485760) AND "
            "(uncompressed_bytes IS NULL OR uncompressed_bytes BETWEEN 1 AND 52428800)",
            name="artifact_limits",
        ),
        sa.CheckConstraint(
            "state != 'published' OR (sealed AND sha256 IS NOT NULL "
            "AND compressed_bytes IS NOT NULL AND uncompressed_bytes IS NOT NULL "
            "AND artifact_path IS NOT NULL)",
            name="published_artifact",
        ),
        sa.CheckConstraint(
            "state != 'draft' OR (sha256 IS NULL AND compressed_bytes IS NULL "
            "AND uncompressed_bytes IS NULL AND artifact_path IS NULL)",
            name="draft_artifact",
        ),
        schema="app",
    )
    op.create_foreign_key(
        "fk_offline_channels_active_package",
        "offline_channels",
        "offline_packages",
        ["package_id", "active_release"],
        ["package_id", "release"],
        source_schema="app",
        referent_schema="app",
        deferrable=True,
        initially="DEFERRED",
    )
    for table, entity in (
        ("offline_package_products", "product"),
        ("offline_package_rations", "ration"),
    ):
        op.create_table(
            table,
            sa.Column("package_id", sa.Uuid(), primary_key=True),
            sa.Column("release", sa.Integer(), primary_key=True),
            sa.Column(f"{entity}_id", sa.Uuid(), primary_key=True),
            sa.Column(f"{entity}_revision", sa.Integer(), primary_key=True),
            _package_fk(),
            sa.ForeignKeyConstraint(
                [f"{entity}_id", f"{entity}_revision"],
                [f"app.{entity}_versions.{entity}_id", f"app.{entity}_versions.revision"],
            ),
            schema="app",
        )
    op.create_table(
        "offline_package_sources",
        sa.Column("package_id", sa.Uuid(), primary_key=True),
        sa.Column("release", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id", sa.Uuid(), sa.ForeignKey("app.product_sources.id"), primary_key=True
        ),
        _package_fk(),
        schema="app",
    )
    op.create_table(
        "ration_page_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("release", sa.Integer(), nullable=False),
        sa.Column("after_id", sa.Uuid(), nullable=False),
        sa.Column("after_revision", sa.Integer(), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _package_fk(),
        sa.CheckConstraint('"limit" BETWEEN 1 AND 500', name="page_limit"),
        sa.CheckConstraint("after_revision >= 1", name="after_revision"),
        schema="app",
    )
    _install_guards()
    # E1 runtime writes remain available on the original skeleton only. Explicit
    # revocation overrides bootstrap's permissive default grants on new tables.
    for table in (
        "rations",
        "ration_versions",
        "ration_components",
        "offline_channels",
        "offline_packages",
        "offline_package_products",
        "offline_package_rations",
        "offline_package_sources",
        "ration_page_tokens",
    ):
        op.execute(f"REVOKE ALL ON TABLE app.{table} FROM calorie_app_api, calorie_app_worker")
        op.execute(f"GRANT SELECT ON TABLE app.{table} TO calorie_app_api, calorie_app_worker")
    op.execute("GRANT INSERT ON TABLE app.ration_page_tokens TO calorie_app_api")
    for table, columns in (
        ("product_sources", "id, description, status"),
        (
            "product_versions",
            "product_id, revision, source_id, name, basis_unit, "
            "energy_kcal, protein_g, fat_g, carbs_g",
        ),
    ):
        op.execute(f"REVOKE INSERT, UPDATE ON app.{table} FROM calorie_app_api, calorie_app_worker")
        op.execute(
            f"GRANT INSERT ({columns}), UPDATE ({columns}) ON app.{table} "
            "TO calorie_app_api, calorie_app_worker"
        )


def _install_guards():
    op.execute("""
    CREATE FUNCTION app.catalog_snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.content_hash IS NOT NULL THEN
            RAISE EXCEPTION 'sealed catalog snapshot is immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END $$
    """)
    for table in ("product_sources", "product_versions", "ration_versions"):
        op.execute(
            f"CREATE TRIGGER catalog_snapshot_guard BEFORE UPDATE OR DELETE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.catalog_snapshot_guard()"
        )
    op.execute("""
    CREATE FUNCTION app.catalog_component_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent record;
    BEGIN
        -- Lock both parents for UPDATE, including moves between revisions.
        FOR parent IN
            SELECT ration_id, revision, content_hash FROM app.ration_versions
            WHERE (TG_OP <> 'INSERT' AND ration_id = OLD.ration_id
                   AND revision = OLD.ration_revision)
               OR (TG_OP <> 'DELETE' AND ration_id = NEW.ration_id
                   AND revision = NEW.ration_revision)
            ORDER BY ration_id, revision FOR UPDATE
        LOOP
            IF parent.content_hash IS NOT NULL THEN
                RAISE EXCEPTION 'sealed ration components are immutable' USING ERRCODE = '23514';
            END IF;
        END LOOP;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER catalog_component_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON app.ration_components FOR EACH ROW EXECUTE FUNCTION app.catalog_component_guard()"
    )
    op.execute("""
    CREATE FUNCTION app.catalog_membership_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent record;
    BEGIN
        FOR parent IN
            SELECT package_id, release, sealed FROM app.offline_packages
            WHERE (TG_OP <> 'INSERT' AND package_id = OLD.package_id AND release = OLD.release)
               OR (TG_OP <> 'DELETE' AND package_id = NEW.package_id AND release = NEW.release)
            ORDER BY package_id, release FOR UPDATE
        LOOP
            IF parent.sealed THEN
                RAISE EXCEPTION 'sealed package membership is immutable' USING ERRCODE = '23514';
            END IF;
        END LOOP;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END $$
    """)
    for table in ("offline_package_products", "offline_package_rations", "offline_package_sources"):
        op.execute(
            f"CREATE TRIGGER catalog_membership_guard BEFORE INSERT OR UPDATE OR DELETE "
            f"ON app.{table} FOR EACH ROW EXECUTE FUNCTION app.catalog_membership_guard()"
        )
    op.execute("""
    CREATE FUNCTION app.catalog_package_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'INSERT' THEN
            IF NEW.sealed OR NEW.state <> 'draft' THEN
                RAISE EXCEPTION 'package must begin as an unsealed draft' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END IF;
        IF TG_OP = 'DELETE' OR OLD.state = 'published' THEN
            RAISE EXCEPTION 'package is immutable' USING ERRCODE = '23514';
        END IF;
        IF (to_jsonb(NEW) - ARRAY['sealed','state','sha256','compressed_bytes',
                                   'uncompressed_bytes','artifact_path']) IS DISTINCT FROM
           (to_jsonb(OLD) - ARRAY['sealed','state','sha256','compressed_bytes',
                                   'uncompressed_bytes','artifact_path'])
           OR (OLD.sealed AND NOT NEW.sealed) THEN
            RAISE EXCEPTION 'package header is immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.sealed AND NOT OLD.sealed THEN
            IF NEW.product_count <> (SELECT count(*) FROM app.offline_package_products
                 WHERE package_id=NEW.package_id AND release=NEW.release)
               OR NEW.ration_count <> (SELECT count(*) FROM app.offline_package_rations
                 WHERE package_id=NEW.package_id AND release=NEW.release)
               OR NEW.source_count <> (SELECT count(*) FROM app.offline_package_sources
                 WHERE package_id=NEW.package_id AND release=NEW.release)
               OR NEW.component_count <> (SELECT count(*) FROM app.ration_components c
                 JOIN app.offline_package_rations r ON r.ration_id=c.ration_id
                   AND r.ration_revision=c.ration_revision
                 WHERE r.package_id=NEW.package_id AND r.release=NEW.release) THEN
                RAISE EXCEPTION 'package membership counts differ' USING ERRCODE = '23514';
            END IF;
            IF EXISTS (SELECT 1 FROM app.offline_package_products m
                       JOIN app.product_versions v ON v.product_id=m.product_id
                         AND v.revision=m.product_revision
                       WHERE m.package_id=NEW.package_id AND m.release=NEW.release
                         AND v.content_hash IS NULL)
               OR EXISTS (SELECT 1 FROM app.offline_package_rations m
                       JOIN app.ration_versions v ON v.ration_id=m.ration_id
                         AND v.revision=m.ration_revision
                       WHERE m.package_id=NEW.package_id AND m.release=NEW.release
                         AND v.content_hash IS NULL)
               OR EXISTS (SELECT 1 FROM app.offline_package_sources m
                       JOIN app.product_sources s ON s.id=m.source_id
                       WHERE m.package_id=NEW.package_id AND m.release=NEW.release
                         AND s.content_hash IS NULL) THEN
                RAISE EXCEPTION 'legacy or unsealed snapshot cannot enter a package'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER catalog_package_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON app.offline_packages FOR EACH ROW EXECUTE FUNCTION app.catalog_package_guard()"
    )
    op.execute("""
    CREATE FUNCTION app.catalog_channel_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'channel identity is immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (NEW.package_id IS DISTINCT FROM OLD.package_id
           OR NEW.kind IS DISTINCT FROM OLD.kind OR
           (OLD.active_release IS NOT NULL AND
             (NEW.active_release IS NULL OR NEW.active_release < OLD.active_release))) THEN
            RAISE EXCEPTION 'channel identity or active release cannot regress'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.active_release IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM app.offline_packages WHERE package_id=NEW.package_id
            AND release=NEW.active_release AND state='published'
        ) THEN
            RAISE EXCEPTION 'active release must be published' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER catalog_channel_guard BEFORE INSERT OR UPDATE OR DELETE "
        "ON app.offline_channels FOR EACH ROW EXECUTE FUNCTION app.catalog_channel_guard()"
    )
    op.execute("""
    CREATE FUNCTION app.catalog_page_token_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM app.offline_packages WHERE package_id=NEW.package_id
                       AND release=NEW.release AND state='published') THEN
            RAISE EXCEPTION 'page token requires a published snapshot' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER catalog_page_token_guard BEFORE INSERT OR UPDATE "
        "ON app.ration_page_tokens FOR EACH ROW EXECUTE FUNCTION app.catalog_page_token_guard()"
    )


def downgrade():
    # Disposable test databases only: published artifacts need a production plan.
    op.execute(
        "GRANT INSERT, UPDATE ON app.product_sources, app.product_versions "
        "TO calorie_app_api, calorie_app_worker"
    )
    for table in ("product_sources", "product_versions", "ration_versions"):
        op.execute(f"DROP TRIGGER catalog_snapshot_guard ON app.{table}")
    op.drop_constraint(
        "fk_offline_channels_active_package", "offline_channels", schema="app", type_="foreignkey"
    )
    for table in (
        "ration_page_tokens",
        "offline_package_sources",
        "offline_package_rations",
        "offline_package_products",
        "offline_packages",
        "offline_channels",
        "ration_components",
        "ration_versions",
        "rations",
    ):
        op.drop_table(table, schema="app")
    for function in (
        "catalog_snapshot_guard",
        "catalog_component_guard",
        "catalog_membership_guard",
        "catalog_package_guard",
        "catalog_channel_guard",
        "catalog_page_token_guard",
    ):
        op.execute(f"DROP FUNCTION app.{function}()")
    for name in (
        "finite_package_amount",
        "package_quantity",
        "finite_density",
        "status",
        "sealed_metadata",
    ):
        op.drop_constraint(
            op.f(f"ck_product_versions_{name}"), "product_versions", schema="app", type_="check"
        )
    op.drop_constraint(
        op.f("fk_product_versions_density_source_id_product_sources"),
        "product_versions",
        schema="app",
        type_="foreignkey",
    )
    for name in (
        "aliases",
        "brand",
        "variant",
        "package_amount",
        "package_unit",
        "density_amount",
        "density_source_id",
        "source_locator",
        "status",
        "preparation",
        "content_hash",
    ):
        op.drop_column("product_versions", name, schema="app")
    op.alter_column(
        "product_versions",
        "name",
        type_=sa.String(255),
        existing_type=sa.String(2000),
        existing_nullable=False,
        schema="app",
    )
    for name in ("source_basis", "sealed_metadata"):
        op.drop_constraint(
            op.f(f"ck_product_sources_{name}"), "product_sources", schema="app", type_="check"
        )
    for name in (
        "document_id",
        "url",
        "checked_on",
        "market",
        "manufacturer",
        "variant",
        "basis",
        "missing_data",
        "notes",
        "content_hash",
    ):
        op.drop_column("product_sources", name, schema="app")
