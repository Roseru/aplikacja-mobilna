"""Enforced deletion ledger, authenticated prefix receipts and operator fencing."""

from pathlib import Path

from alembic import op

revision = "0025_deletion_ledger"
down_revision = "0024_e9_history_graph"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(Path(__file__).with_name("ledger_0025").joinpath("ledger.sql").read_text("utf-8"))


def downgrade():
    # Evidence and fences are irreversible safeguards, not disposable schema.
    op.get_context().config.print_stdout(
        "Deletion ledger and barriers retained; old deletion CLI is incompatible."
    )
