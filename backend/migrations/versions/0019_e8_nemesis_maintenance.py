"""Select due Nemesis lifecycle rows without starving them behind active rows.

The published 0018 remains immutable. Downgrade retains this compatible repair;
restoring the old predicate would resume backlog starvation.
"""

from pathlib import Path

from alembic import op

revision = "0019_e8_nemesis_maintenance"
down_revision = "0018_e8_nemesis_lifecycle"
branch_labels = None
depends_on = None
ROOT = Path(__file__).with_name("e8_0019")
ORIGINAL_BODY_SHA256 = "d34581def320c114e3e1e2325eccc5533f4c82d392268bc41afe81a22667ccc0"
REPAIRED_BODY_SHA256 = "8dcd70d6869792f297df482285b683393cd7a9eb6c273c4c8e2d235ed4a56a61"
VERIFY = """
DO $$ BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_catalog.pg_proc p
   JOIN pg_catalog.pg_roles owner ON owner.oid=p.proowner
   JOIN pg_catalog.pg_language language ON language.oid=p.prolang
   WHERE p.oid=pg_catalog.to_regprocedure('app.e8n_maintain(integer)')
     AND owner.rolname='calorie_app_migrator' AND NOT owner.rolsuper
     AND language.lanname='plpgsql' AND p.prokind='f' AND p.prosecdef
     AND p.prorettype='pg_catalog.jsonb'::pg_catalog.regtype
     AND p.pronargs=1 AND p.proargtypes='23'::pg_catalog.oidvector
     AND p.proconfig=ARRAY['search_path=pg_catalog, pg_temp']::text[]
     AND pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex')
         IN (BODY_DIGESTS)
     AND NOT EXISTS (
       SELECT 1 FROM pg_catalog.aclexplode(
         coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) acl
       LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee
       WHERE acl.privilege_type='EXECUTE' AND acl.grantee<>p.proowner
         AND (grantee.rolname IS DISTINCT FROM 'calorie_app_nemesis_worker'
              OR acl.is_grantable))
 ) THEN
   RAISE EXCEPTION 'Nemesis maintenance requires its frozen owner, body, path and ACL'
     USING ERRCODE='23514';
 END IF;
END $$;
"""


def verify(*digests):
    op.execute(VERIFY.replace("BODY_DIGESTS", ",".join("'" + value + "'" for value in digests)))


def upgrade():
    # CREATE OR REPLACE preserves OID, owner and ACL. The migration-owned body
    # changes only candidate selection; lock order, post-lock clock/recheck,
    # cleanup, minimal receipts and default-closed capability stay unchanged.
    verify(ORIGINAL_BODY_SHA256, REPAIRED_BODY_SHA256)
    op.execute(ROOT.joinpath("maintenance.sql").read_text(encoding="utf-8"))
    verify(REPAIRED_BODY_SHA256)


def downgrade():
    verify(REPAIRED_BODY_SHA256)
    op.get_context().config.print_stdout(
        "WARNING: Nemesis maintenance starvation repair is retained on downgrade; "
        "function owner, path, ACL, data, receipts and capability are unchanged."
    )
