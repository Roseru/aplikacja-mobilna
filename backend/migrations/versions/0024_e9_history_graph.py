"""Keep explicit historical date corrections distinct from goal-only clones."""

from pathlib import Path

from alembic import op

revision = "0024_e9_history_graph"
down_revision = "0023_e9_qualification"
branch_labels = None
depends_on = None
ROOT = Path(__file__).parent


def upgrade():
    op.execute(ROOT.joinpath("e9_0024/history_graph.sql").read_text(encoding="utf-8"))


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM app.energy_versions WHERE source<>'legacy')
        OR EXISTS(SELECT 1 FROM app.energy_analyses) OR EXISTS(SELECT 1 FROM app.energy_receipts)
        THEN RAISE EXCEPTION 'cannot downgrade populated E9 graph';END IF;END $$""")
    previous = ROOT.joinpath("e9_0023/qualification.sql").read_text(encoding="utf-8")
    op.execute(previous[: previous.index("-- The scoped deletion helper")])
    op.execute(
        previous[
            previous.index("CREATE OR REPLACE FUNCTION app.e8n_gate()") : previous.index(
                "INSERT INTO app.nemesis_releases"
            )
        ]
    )
    op.execute("DELETE FROM app.nemesis_releases WHERE schema_revision='0024_e9_history_graph'")
    op.execute("UPDATE app.nemesis_control SET enabled=false")
