"""Independent historical E, typed E7 jobs, owner decisions and opt-in sync."""

from pathlib import Path

from alembic import op

revision = "0022_e9_energy"
down_revision = "0021_e8_nemesis_results"
branch_labels = None
depends_on = None
ROOT = Path(__file__).with_name("e9_0022")


def upgrade():
    for name in (
        "schema",
        "history",
        "rules",
        "decisions",
        "worker",
        "maintenance",
        "projections",
        "acl",
    ):
        op.execute(ROOT.joinpath(name + ".sql").read_text(encoding="utf-8"))
    op.execute("""UPDATE app.nemesis_runtime_contract SET body_sha256=
        (SELECT encode(sha256(convert_to(prosrc,'UTF8')),'hex') FROM pg_proc
        WHERE oid=to_regprocedure('app.e8n_write_projection(uuid,uuid,text,timestamptz)'))
        WHERE signature='e8n_write_projection(uuid,uuid,text,timestamptz)'""")


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM app.energy_analyses)
        OR EXISTS(SELECT 1 FROM app.energy_versions WHERE source<>'legacy')
        OR EXISTS(SELECT 1 FROM app.energy_receipts)
        THEN RAISE EXCEPTION 'cannot downgrade nonempty E9 decisions';END IF;END $$""")
    op.execute(ROOT.joinpath("downgrade.sql").read_text(encoding="utf-8"))
