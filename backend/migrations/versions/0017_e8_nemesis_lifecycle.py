"""Private E8.3 lifecycle. No production activation or shared integration."""

from pathlib import Path

from alembic import op

revision = "0017_e8_nemesis_lifecycle"
down_revision = "0016_e8_motivation"
branch_labels = None
depends_on = None
ROOT = Path(__file__).with_name("e8_0017")
TABLES = (
    "nemesis_control",
    "nemesis_releases",
    "nemesis_challenges",
    "nemesis_slots",
    "nemesis_share_codes",
    "nemesis_receipts",
    "nemesis_admissions",
    "nemesis_cursors",
)


def upgrade():
    for name in ("schema", "addressing", "lifecycle", "maintenance", "acl"):
        op.execute(ROOT.joinpath(name + ".sql").read_text(encoding="utf-8"))


def downgrade():
    # Test capability/control are configuration; all history and minimal receipts
    # are protected before the first DDL, even if a later DROP would fail.
    predicate = " OR ".join(f"EXISTS(SELECT 1 FROM app.{name})" for name in TABLES[2:])
    op.execute(
        f"DO $$ BEGIN IF {predicate} THEN "
        "RAISE EXCEPTION 'cannot downgrade nonempty Nemesis history' "
        "USING ERRCODE='23514'; END IF; END $$"
    )
    op.execute(
        "DO $$ DECLARE f record; BEGIN FOR f IN SELECT p.oid::regprocedure "
        "signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='app' AND left(p.proname,4)='e8n_' LOOP EXECUTE 'DROP "
        "FUNCTION '||f.signature||' CASCADE'; END LOOP; END $$ "
    )
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE app.{name} CASCADE")
