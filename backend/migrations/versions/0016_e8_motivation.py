"""Durable, source-derived E8 motivation with a separately privileged worker."""

from pathlib import Path

from alembic import op

revision = "0016_e8_motivation"
down_revision = "0015_e7_ai"
branch_labels = None
depends_on = None
ROOT = Path(__file__).with_name("e8_0016")
TABLES = (
    "motivation_accounts",
    "motivation_days",
    "motivation_badges",
    "ranking_affirmations",
    "ranking_sessions",
    "ranking_cursors",
)


def upgrade():
    op.execute("""DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles
      WHERE rolname='calorie_app_motivation_worker' AND NOT rolcanlogin AND NOT rolinherit
      AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
      AND NOT rolreplication AND NOT rolbypassrls)
      OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
        WHERE r.rolname='calorie_app_motivation_worker')
      OR EXISTS(SELECT 1 FROM pg_roles r JOIN pg_roles b
        ON b.rolname='calorie_app_motivation_worker'
        WHERE r.rolname IN('calorie_app_api','calorie_app_worker','calorie_app_ai_worker',
          'calorie_app_migrator','calorie_app_deletion_operator','keycloak')
        AND pg_has_role(r.oid,b.oid,'MEMBER'))
      THEN RAISE EXCEPTION 'provision minimal motivation worker base role before E8'
      USING ERRCODE='23514'; END IF; END $$""")
    op.execute("""DO $$ BEGIN IF
      has_schema_privilege('calorie_app_motivation_worker','app','CREATE')
      OR EXISTS(SELECT 1 FROM pg_tables t WHERE schemaname='app' AND
        (has_table_privilege('calorie_app_motivation_worker',format('%I.%I',schemaname,tablename),
          'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') OR
         has_any_column_privilege('calorie_app_motivation_worker',format('%I.%I',schemaname,tablename),
          'INSERT,UPDATE,REFERENCES') OR
         (tablename NOT IN ('alembic_version','installation_state') AND
          has_any_column_privilege('calorie_app_motivation_worker',format('%I.%I',schemaname,tablename),'SELECT'))))
      OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='app' AND p.prosecdef
        AND has_function_privilege('calorie_app_motivation_worker',p.oid,'EXECUTE'))
      THEN RAISE EXCEPTION 'motivation worker has incompatible effective privileges'
      USING ERRCODE='23514'; END IF; END $$""")
    # Immutable migration-owned resources; no imports of changing runtime rules.
    for name in ("schema", "facts", "projection", "ranking", "maintenance", "acl"):
        op.execute(ROOT.joinpath(name + ".sql").read_text(encoding="utf-8"))


def downgrade():
    predicate = " OR ".join(f"EXISTS(SELECT 1 FROM app.{name})" for name in TABLES)
    op.execute(f"""DO $$ BEGIN IF {predicate} THEN
      RAISE EXCEPTION 'cannot downgrade nonempty E8 derivatives or consent evidence'
      USING ERRCODE='23514'; END IF; END $$""")
    op.execute("DROP FUNCTION app.purge_deleted_account(uuid)")
    op.execute("ALTER FUNCTION app.purge_deleted_account_e7(uuid) RENAME TO purge_deleted_account")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.purge_deleted_account(uuid) TO calorie_app_deletion_operator"
    )
    op.execute(r"""DO $$ DECLARE f record; BEGIN FOR f IN
      SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n
      ON n.oid=p.pronamespace WHERE n.nspname='app' AND p.proname LIKE 'e8\_%' ESCAPE '\'
      LOOP EXECUTE 'DROP FUNCTION '||f.signature||' CASCADE'; END LOOP; END $$""")
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE app.{name} CASCADE")
