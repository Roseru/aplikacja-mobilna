"""Preserve estimate artifact identity and qualify internal helper ACL."""

from pathlib import Path

from alembic import op

revision = "0023_e9_qualification"
down_revision = "0022_e9_energy"
branch_labels = None
depends_on = None
ROOT = Path(__file__).parent


def refresh_manifest():
    op.execute("""UPDATE app.nemesis_runtime_contract c SET body_sha256=
        (SELECT encode(sha256(convert_to(p.prosrc,'UTF8')),'hex') FROM pg_proc p
         WHERE p.oid=to_regprocedure('app.'||c.signature))""")


def upgrade():
    op.execute(ROOT.joinpath("e9_0023/qualification.sql").read_text(encoding="utf-8"))
    refresh_manifest()


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM app.energy_versions WHERE source<>'legacy')
        OR EXISTS(SELECT 1 FROM app.energy_analyses)
        OR EXISTS(SELECT 1 FROM app.energy_receipts)
        THEN RAISE EXCEPTION 'cannot downgrade populated E9 qualification';END IF;END $$""")
    history = ROOT.joinpath("e9_0022/history.sql").read_text(encoding="utf-8")
    for start, end in (
        ("CREATE FUNCTION app.e9_legacy_import", "-- Import in each accepted source order."),
        ("CREATE FUNCTION app.e9_resolve", "CREATE FUNCTION app.e9_version_guard"),
    ):
        body = history[history.index(start) : history.index(end)]
        op.execute(body.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    rules = ROOT.joinpath("e9_0022/rules.sql").read_text(encoding="utf-8")
    op.execute(
        rules[: rules.index("CREATE FUNCTION app.e9_stale")].replace(
            "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
        )
    )
    maintenance = ROOT.joinpath("e9_0022/maintenance.sql").read_text(encoding="utf-8")
    body = maintenance[
        maintenance.index("CREATE FUNCTION app.e9_auto_enqueue") : maintenance.index(
            "ALTER FUNCTION app.e8n_delete_helper"
        )
    ]
    op.execute(body.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    projection = ROOT.joinpath("e9_0022/projections.sql").read_text(encoding="utf-8")
    body = projection[
        projection.index("CREATE OR REPLACE FUNCTION app.e8n_gate()") : projection.index(
            "INSERT INTO app.nemesis_releases"
        )
    ]
    op.execute(body)
    op.execute("DELETE FROM app.nemesis_releases WHERE schema_revision='0023_e9_qualification'")
    op.execute("UPDATE app.nemesis_control SET enabled=false")
    refresh_manifest()
