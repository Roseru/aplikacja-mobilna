"""Consent-bound photos, fenced jobs, shared quotas and durable physical IO permits."""

from pathlib import Path

from alembic import op

revision = "0015_e7_ai"
down_revision = "0014_catalog_search"
branch_labels = None
depends_on = None

ROOT = Path(__file__).with_name("e7_0015")
TABLES = (
    "ai_controls",
    "ai_pools",
    "ai_analyses",
    "ai_jobs",
    "ai_photo_consents",
    "ai_decisions",
    "ai_receipts",
    "ai_admissions",
    "ai_energy_admissions",
    "ai_attempts",
    "ai_transport_permits",
    "ai_cleanup_intents",
)


def upgrade():
    op.execute("""DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles
      WHERE rolname='calorie_app_ai_worker' AND NOT rolcanlogin AND NOT rolinherit
      AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
      AND NOT rolreplication AND NOT rolbypassrls)
      OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
        WHERE r.rolname='calorie_app_ai_worker')
      THEN RAISE EXCEPTION 'provision minimal AI worker base role before E7 upgrade'
      USING ERRCODE='23514'; END IF; END $$""")
    op.execute("""DO $$ BEGIN IF has_schema_privilege('calorie_app_ai_worker','app','CREATE')
      OR EXISTS(SELECT 1 FROM pg_tables t WHERE schemaname='app' AND
        (has_table_privilege('calorie_app_ai_worker',format('%I.%I',schemaname,tablename),
          'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') OR
         has_any_column_privilege('calorie_app_ai_worker',format('%I.%I',schemaname,tablename),
          'INSERT,UPDATE,REFERENCES') OR
         (tablename NOT IN ('alembic_version','installation_state') AND
          has_any_column_privilege('calorie_app_ai_worker',format('%I.%I',schemaname,tablename),'SELECT'))))
      OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='app' AND p.prosecdef
        AND has_function_privilege('calorie_app_ai_worker',p.oid,'EXECUTE'))
      THEN RAISE EXCEPTION 'AI worker has incompatible preexisting privileges'
      USING ERRCODE='23514'; END IF; END $$""")
    # Frozen versioned SQL resources belong to this migration, not mutable runtime.
    for name in ("schema", "api", "quota", "worker", "maintenance", "matching"):
        op.execute(ROOT.joinpath(name + ".sql").read_text(encoding="utf-8"))


def downgrade():
    predicate = " OR ".join(
        f"EXISTS(SELECT 1 FROM app.{name})"
        for name in TABLES
        if name not in {"ai_controls", "ai_pools", "ai_transport_permits"}
    )
    op.execute(f"""DO $$ BEGIN IF {predicate}
      OR EXISTS(SELECT 1 FROM app.ai_transport_permits WHERE attempt_id IS NOT NULL)
      THEN RAISE EXCEPTION 'cannot downgrade durable E7 evidence' USING ERRCODE='23514';
      END IF; END $$""")
    op.execute("DROP FUNCTION app.purge_deleted_account(uuid)")
    op.execute("ALTER FUNCTION app.purge_deleted_account_e6(uuid) RENAME TO purge_deleted_account")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.purge_deleted_account(uuid) TO calorie_app_deletion_operator"
    )
    # Every function created by this migration has the e7_ prefix.
    op.execute(r"""DO $$ DECLARE f record; BEGIN FOR f IN
      SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n
      ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.proname LIKE 'e7\_%' ESCAPE '\'
      LOOP EXECUTE 'DROP FUNCTION '||f.signature||' CASCADE'; END LOOP; END $$""")
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE app.{name} CASCADE")
