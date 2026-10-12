"""Keep deferred diary checks privileged through the deletion COMMIT.

The frozen checker reads two qualified source tables and returns no data.
Its body, owner, search_path, trigger timing and runtime ACL stay unchanged.
Downgrade retains this backwards-compatible security repair, as E4 does.
"""

from alembic import op

revision = "0017_e8_purge_commit"
down_revision = "0016_e8_motivation"
branch_labels = None
depends_on = None

# Exact prosrc from the immutable 0007 checker; no runtime imports or body rewrite.
BODY_SHA256 = "a07b30c41bda409d6aaa734486170d0141939eae729007269d3b46f2da5e473d"

VERIFY = """
DO $$ BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_roles owner ON owner.oid=p.proowner
   JOIN pg_catalog.pg_language language ON language.oid=p.prolang
   WHERE p.oid=pg_catalog.to_regprocedure('app.diary_aggregate_count()')
     AND owner.rolname='calorie_app_migrator' AND NOT owner.rolsuper
     AND language.lanname='plpgsql' AND p.prokind='f'
     AND p.prorettype='pg_catalog.trigger'::pg_catalog.regtype AND p.pronargs=0
     AND (SELECT count(*) FROM pg_catalog.pg_trigger t WHERE t.tgfoid=p.oid) = 2
     AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger t WHERE t.tgfoid=p.oid
       AND (t.tgname<>'diary_aggregate_count' OR t.tgtype<>29 OR NOT t.tgdeferrable
         OR NOT t.tginitdeferred OR t.tgenabled<>'O'
         OR t.tgrelid NOT IN ('app.meals'::pg_catalog.regclass,
                             'app.meal_items'::pg_catalog.regclass)))
     AND p.proconfig=ARRAY['search_path=pg_catalog, pg_temp']::text[]
     AND pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')
         = 'BODY_DIGEST'
     AND NOT EXISTS (
       SELECT 1 FROM pg_catalog.aclexplode(
         coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) acl
       WHERE acl.privilege_type='EXECUTE' AND acl.grantee<>p.proowner)
     AND NOT EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles runtime
       WHERE runtime.rolname IN ('calorie_app_api','calorie_app_worker',
         'calorie_app_ai_worker','calorie_app_motivation_worker',
         'calorie_app_deletion_operator')
       AND pg_catalog.has_function_privilege(runtime.oid,p.oid,'EXECUTE'))
 ) THEN
   RAISE EXCEPTION 'deferred diary checker requires its frozen owner, body, path and ACL'
     USING ERRCODE='23514';
 END IF;
END $$;
""".replace("BODY_DIGEST", BODY_SHA256)


def upgrade():
    op.execute(VERIFY)
    op.execute("ALTER FUNCTION app.diary_aggregate_count() SECURITY DEFINER")


def downgrade():
    op.execute(VERIFY)
    op.execute("""DO $$ BEGIN
      IF NOT (SELECT prosecdef FROM pg_catalog.pg_proc
              WHERE oid=pg_catalog.to_regprocedure('app.diary_aggregate_count()')) THEN
        RAISE EXCEPTION 'cannot remove a tampered deferred diary security repair'
          USING ERRCODE='23514';
      END IF;
    END $$;""")
    op.get_context().config.print_stdout(
        "WARNING: deferred diary SECURITY DEFINER repair is retained on downgrade; "
        "no data, deletion jobs, fences, function body, path or ACL are removed."
    )
