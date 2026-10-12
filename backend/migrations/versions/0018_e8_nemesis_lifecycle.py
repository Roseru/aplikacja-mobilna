"""Private E8.3 lifecycle. No production activation or shared integration."""

from pathlib import Path

from alembic import op

revision = "0018_e8_nemesis_lifecycle"
down_revision = "0017_e8_purge_commit"
branch_labels = None
depends_on = None
ROOT = Path(__file__).with_name("e8_0018")
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
    # Runtime base roles may use SET ROLE even with NOINHERIT. Audit the complete
    # membership topology before the first DDL rather than relying on REVOKE.
    op.execute("""
    DO $$
    DECLARE base_role oid; member_role record;
    BEGIN
      SELECT oid INTO base_role FROM pg_roles
      WHERE rolname = 'calorie_app_nemesis_worker';
      IF base_role IS NULL THEN RETURN; END IF;
      IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE oid = base_role
          AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND NOT rolbypassrls
      ) OR EXISTS (
        SELECT 1 FROM pg_auth_members WHERE member = base_role
      ) OR EXISTS (
        SELECT 1 FROM pg_roles AS runtime_role
        WHERE runtime_role.rolname IN (
          'calorie_app_api', 'calorie_app_worker', 'calorie_app_migrator',
          'calorie_app_deletion_operator', 'calorie_app_ai_worker',
          'calorie_app_motivation_worker', 'keycloak'
        ) AND pg_has_role(runtime_role.oid, base_role, 'MEMBER')
      ) THEN
        RAISE EXCEPTION 'unsafe Nemesis worker role topology'
          USING ERRCODE = '23514';
      END IF;
      -- Inbound dedicated LOGINs are allowed only through this minimal tree.
      -- An extra outgoing role could supply authority after SET ROLE, even when
      -- its privileges are not inherited by the LOGIN in ordinary sessions.
      FOR member_role IN
        WITH RECURSIVE worker_members(oid) AS (
          SELECT base_role
          UNION
          SELECT membership.member FROM pg_auth_members AS membership
          JOIN worker_members ON membership.roleid = worker_members.oid
        ) SELECT role.* FROM pg_roles AS role
          JOIN worker_members ON role.oid = worker_members.oid
      LOOP
        IF member_role.rolsuper OR member_role.rolcreatedb
          OR member_role.rolcreaterole OR member_role.rolreplication
          OR member_role.rolbypassrls OR EXISTS (
            SELECT 1 FROM pg_auth_members AS membership
            WHERE membership.member = member_role.oid
              AND membership.roleid <> base_role
          ) THEN
          RAISE EXCEPTION 'unsafe Nemesis worker member authority'
            USING ERRCODE = '23514';
        END IF;
        IF has_schema_privilege(member_role.oid, 'app', 'CREATE')
          OR EXISTS (
            SELECT 1 FROM pg_tables AS relation WHERE schemaname = 'app'
              AND (
                has_table_privilege(member_role.oid,
                  format('%I.%I', schemaname, tablename),
                  'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
                OR has_any_column_privilege(member_role.oid,
                  format('%I.%I', schemaname, tablename),
                  'INSERT,UPDATE,REFERENCES')
                OR (tablename NOT IN ('alembic_version', 'installation_state')
                  AND has_any_column_privilege(member_role.oid,
                    format('%I.%I', schemaname, tablename), 'SELECT'))
              )
          ) OR EXISTS (
            SELECT 1 FROM pg_proc AS function
              JOIN pg_namespace AS namespace ON namespace.oid = function.pronamespace
            WHERE namespace.nspname = 'app' AND function.prosecdef
              AND has_function_privilege(member_role.oid, function.oid, 'EXECUTE')
          ) THEN
          RAISE EXCEPTION 'unsafe effective Nemesis worker privileges'
            USING ERRCODE = '23514';
        END IF;
      END LOOP;
    END $$
    """)
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
