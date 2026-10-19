"""Keep ledger downgrade safety extensible without changing0025 evidence."""

from pathlib import Path

from alembic import op

revision = "0026_ledger_review"
down_revision = "0025_deletion_ledger"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(Path(__file__).with_name("ledger_0026").joinpath("guard.sql").read_text("utf-8"))


def downgrade():
    # The corrected safety barrier must survive26->25->24, like ledger evidence.
    op.get_context().config.print_stdout(
        "Corrected deletion downgrade guard and ledger barriers retained."
    )
