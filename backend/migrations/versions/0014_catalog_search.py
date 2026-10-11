"""Indexed Unicode selectors keyed by immutable exact catalogue versions."""

import hashlib
import unicodedata

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "0014_catalog_search"
down_revision = "0013_e6_community"
branch_labels = None
depends_on = None


def _normalized(value):
    # Frozen migration implementation: future runtime edits cannot rewrite 0014.
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _metadata(row):
    names = sorted({_normalized(row.name), *map(_normalized, row.aliases or [])})
    return {
        "product_id": row.product_id,
        "revision": row.revision,
        "normalized_names": names,
        "normalized_name_hashes": [hashlib.sha256(name.encode()).hexdigest() for name in names],
        "search_text": " ".join(
            names + [_normalized(value) for value in (row.brand, row.variant) if value is not None]
        ),
    }


def upgrade():
    op.create_table(
        "product_search_metadata",
        sa.Column("product_id", UUID(), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("normalized_names", ARRAY(sa.Text()), nullable=False),
        sa.Column("normalized_name_hashes", ARRAY(sa.String(64)), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id", "revision"],
            ["app.product_versions.product_id", "app.product_versions.revision"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("revision>=1", name="revision"),
        sa.CheckConstraint("cardinality(normalized_names) BETWEEN 1 AND 101", name="names_limit"),
        sa.CheckConstraint(
            "cardinality(normalized_names)=cardinality(normalized_name_hashes)", name="hash_count"
        ),
        schema="app",
    )
    # Table and column privileges are independent; no inherited runtime DML.
    op.execute(
        "REVOKE ALL ON app.product_search_metadata "
        "FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_deletion_operator"
    )
    op.execute("GRANT SELECT ON app.product_search_metadata TO calorie_app_api")
    _backfill()
    op.create_index(
        "ix_product_search_metadata_names",
        "product_search_metadata",
        ["normalized_name_hashes"],
        schema="app",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_product_search_metadata_trgm",
        "product_search_metadata",
        ["search_text"],
        schema="app",
        postgresql_using="gin",
        postgresql_ops={"search_text": "public.gin_trgm_ops"},
    )
    op.execute("""
    CREATE FUNCTION app.product_search_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
      -- Only a legitimate parent deletion may cascade technical metadata. Existing
      -- sealed snapshot guards still reject parent DELETE before any cascade.
      IF TG_OP='DELETE' AND NOT EXISTS(SELECT 1 FROM app.product_versions
          WHERE product_id=OLD.product_id AND revision=OLD.revision) THEN RETURN OLD; END IF;
      RAISE EXCEPTION 'exact derived search metadata is immutable' USING ERRCODE='23514';
    END $$;
    REVOKE ALL ON FUNCTION app.product_search_immutable_guard() FROM
      PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_deletion_operator;
    CREATE TRIGGER product_search_immutable BEFORE UPDATE OR DELETE ON app.product_search_metadata
      FOR EACH ROW EXECUTE FUNCTION app.product_search_immutable_guard();
    CREATE FUNCTION app.catalog_search_membership_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
      -- Deferred so the migrator can seal and add every derived row atomically.
      IF NEW.sealed AND EXISTS(
        SELECT 1 FROM app.offline_package_products p
        WHERE p.package_id=NEW.package_id AND p.release=NEW.release
          AND NOT EXISTS(SELECT 1 FROM app.product_search_metadata m
            WHERE m.product_id=p.product_id AND m.revision=p.product_revision)) THEN
        RAISE EXCEPTION 'sealed package requires exact derived search metadata'
          USING ERRCODE='23514';
      END IF;
      RETURN NULL;
    END $$;
    REVOKE ALL ON FUNCTION app.catalog_search_membership_guard() FROM
      PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_deletion_operator;
    CREATE CONSTRAINT TRIGGER catalog_search_membership AFTER INSERT OR UPDATE
      ON app.offline_packages DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION app.catalog_search_membership_guard();
    """)


def _backfill():
    connection = op.get_bind()
    table = sa.table(
        "product_search_metadata",
        sa.column("product_id", UUID()),
        sa.column("revision", sa.Integer()),
        sa.column("normalized_names", ARRAY(sa.Text())),
        sa.column("normalized_name_hashes", ARRAY(sa.String(64))),
        sa.column("search_text", sa.Text()),
        schema="app",
    )
    after = None
    while True:
        predicate = "" if after is None else "WHERE (product_id,revision)>(:id,:revision)"
        rows = connection.execute(
            sa.text(
                "SELECT product_id,revision,name,aliases,brand,variant FROM app.product_versions "
                + predicate
                + " ORDER BY product_id,revision LIMIT 16"
            ),
            {} if after is None else {"id": after[0], "revision": after[1]},
        ).all()
        if not rows:
            break
        connection.execute(table.insert(), [_metadata(row) for row in rows])
        after = (rows[-1].product_id, rows[-1].revision)


def downgrade():
    # These rows contain only reproducible normalization, never authoritative
    # catalogue/history/receipts. 0013 retains its independent durable E6 guard.
    op.execute("DROP TRIGGER catalog_search_membership ON app.offline_packages")
    op.execute("DROP FUNCTION app.catalog_search_membership_guard()")
    op.execute("DROP TRIGGER product_search_immutable ON app.product_search_metadata")
    op.execute("DROP FUNCTION app.product_search_immutable_guard()")
    op.drop_table("product_search_metadata", schema="app")
