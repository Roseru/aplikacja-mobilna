"""Qualified accepted-zone Nemesis projections and durable private results."""

from pathlib import Path

from alembic import op

revision = "0021_e8_nemesis_results"
down_revision = "0020_e8_nemesis_integration"
branch_labels = None
depends_on = None
ROOT = Path(__file__).with_name("e8_0021")
CONTRACT = (
    "e8n_initialize(uuid,timestamptz)",
    "e8n_aggregate_projection(uuid,text,timestamptz)",
    "e8n_percent_text(numeric)",
    "e8n_write_projection(uuid,uuid,text,timestamptz)",
    "e8n_seed_ready(app.nemesis_challenges)",
    "e8n_source_refresh(uuid,integer,uuid,jsonb,uuid[])",
    "e8n_source_in_transaction(xid)",
    "e8n_statistics(text,text,uuid,uuid)",
    "e8n_finalize(uuid)",
    "e8n_finalize_batch(integer)",
)


def upgrade():
    op.execute(ROOT.joinpath("parent_preconditions.sql").read_text(encoding="utf-8"))
    for name in (
        "schema",
        "projections",
        "guards",
        "capability",
        "source",
        "lifecycle",
        "statistics",
        "finalizer",
        "deletion",
        "acl",
    ):
        op.execute(ROOT.joinpath(name + ".sql").read_text(encoding="utf-8-sig"))
    for signature in CONTRACT:
        op.execute(f"""INSERT INTO app.nemesis_runtime_contract(signature,body_sha256)
   SELECT '{signature}',encode(sha256(convert_to(prosrc,'UTF8')),'hex')
   FROM pg_proc WHERE oid=to_regprocedure('app.{signature}')""")
    # New sources remain deploy-closed; no seed of legacy accepted history.
    op.execute("""DO $$ BEGIN IF NOT app.e8n_runtime_ready() THEN
 RAISE EXCEPTION 'Nemesis runtime manifest incomplete' USING ERRCODE='23514';
 END IF; END $$""")


def downgrade():
    # Qualified facts and accepted history are never discarded or reconstructed.
    op.execute("""DO $$ BEGIN IF
 EXISTS(SELECT 1 FROM app.nemesis_projection_seeds)
 OR EXISTS(SELECT 1 FROM app.nemesis_day_projections)
 OR EXISTS(SELECT 1 FROM app.nemesis_final_results)
 OR EXISTS(SELECT 1 FROM app.nemesis_challenges)
 OR EXISTS(SELECT 1 FROM app.nemesis_control WHERE enabled) THEN
 RAISE EXCEPTION 'cannot downgrade nonempty or enabled Nemesis results'
 USING ERRCODE='23514'; END IF; END $$""")
    op.execute(ROOT.joinpath("downgrade_parent.sql").read_text(encoding="utf-8-sig"))
