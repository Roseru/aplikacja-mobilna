"""Production Nemesis deletion, typed source guards and fenced restore cleanup."""

from pathlib import Path

from alembic import op

revision = "0020_e8_nemesis_integration"
down_revision = "0019_e8_nemesis_maintenance"
branch_labels = None
depends_on = None
ROOT = Path(__file__).with_name("e8_0020")
SOURCE_SIGNATURE = "e8n_source_lock(uuid,integer,uuid,text,date[],date[],boolean)"
SOURCE_OLD = "aa42f6d5b76c3f341a2676760eb6c1d8d9d8ee1ff67a1109a7b6f54226a9476a"
SOURCE_NEW = "b176b9d78798b93bd7931011f6fdfce3d77ad9ac1f960df5312336f92cc3464c"
BEGIN_BODY = "146ea7db2b500e1f00946f222cbe763b56e0f74c63db22d14d63a4c04671569d"
PURGE_BODY = "76218198d60204aa3bb58367a47a8f59dc355944c7d66e64c75fc61ded7ccf51"
HELPER_BODY = "b2284665e3b41cf90b6239a8edd1ffdee7fd38c18036fbf9fb460f857d4b4a18"
FROZEN = (
    (
        "confirm_account_deletion(uuid)",
        "283412bc7f7696ebadb4df156d453b7c8ae277ef5129607d25dc326903c3fd3f",
        "void",
        "plpgsql",
        ("calorie_app_deletion_operator",),
    ),
    (
        "purge_deleted_account_e7(uuid)",
        "36c7e5005d8c7c2a8063cbb314c8c0d4e816eb5453615646726db46a04e1ca9e",
        "void",
        "plpgsql",
        (),
    ),
    (
        "purge_deleted_account_e6(uuid)",
        "a290dbfd136d6091b8653472d2e48f46a149d8e9f1315b2ef2db2dbf42abfc60",
        "void",
        "plpgsql",
        (),
    ),
    (
        "purge_deleted_account_e5(uuid)",
        "b801a79e0f73e09e4347119d31034c34b520c2a34959b74eaf2d546ef2fa6c06",
        "void",
        "plpgsql",
        (),
    ),
    (
        "diary_aggregate_count()",
        "a07b30c41bda409d6aaa734486170d0141939eae729007269d3b46f2da5e473d",
        "trigger",
        "plpgsql",
        (),
    ),
    (
        "deletion_purge_authorized(uuid)",
        "a19ad8885e7afb29e12ebb584a34e09e9a840a2cab50c3bc83d21ab6aaf3d28d",
        "boolean",
        "sql",
        ("calorie_app_api", "calorie_app_worker"),
    ),
)
HISTORY = (
    "nemesis_challenges",
    "nemesis_slots",
    "nemesis_share_codes",
    "nemesis_receipts",
    "nemesis_admissions",
    "nemesis_cursors",
)


def verify(functions):
    """Migration-owned source and effective privileges, before any delegation."""
    for signature, digest, result_type, language, permitted in functions:
        roles = "ARRAY[" + ",".join("'" + role + "'" for role in permitted) + "]::text[]"
        op.execute(f"""
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_roles AS owner ON owner.oid=procedure.proowner
            JOIN pg_catalog.pg_language AS language ON language.oid=procedure.prolang
            WHERE procedure.oid=pg_catalog.to_regprocedure('app.{signature}')
              AND owner.rolname='calorie_app_migrator' AND NOT owner.rolsuper
              AND procedure.prokind='f' AND procedure.prosecdef
              AND language.lanname='{language}'
              AND procedure.prorettype=pg_catalog.to_regtype('{result_type}')
              AND procedure.proconfig=ARRAY['search_path=pg_catalog, pg_temp']::text[]
              AND pg_catalog.encode(pg_catalog.sha256(
                pg_catalog.convert_to(procedure.prosrc,'UTF8')),'hex')='{digest}'
              AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.aclexplode(coalesce(procedure.proacl,
                  pg_catalog.acldefault('f',procedure.proowner))) AS acl
                LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid=acl.grantee
                WHERE acl.privilege_type='EXECUTE' AND acl.grantee<>procedure.proowner
                  AND (NOT coalesce(grantee.rolname=ANY({roles}),false) OR acl.is_grantable)
              ) AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles AS runtime
                WHERE runtime.rolname IN ('calorie_app_api','calorie_app_worker',
                  'calorie_app_ai_worker','calorie_app_motivation_worker',
                  'calorie_app_nemesis_worker','calorie_app_deletion_operator')
                  AND NOT(runtime.rolname=ANY({roles}))
                  AND pg_catalog.has_function_privilege(runtime.oid,procedure.oid,'EXECUTE')
              )
          ) THEN
            RAISE EXCEPTION 'integration requires frozen parent body owner path and ACL'
              USING ERRCODE='23514';
          END IF;
        END $$
        """)


def entrypoints(internal=False):
    suffix = "_e8_19" if internal else ""
    roles = () if internal else ("calorie_app_deletion_operator",)
    return (
        (
            f"begin_account_deletion{suffix}(uuid,uuid,integer)",
            BEGIN_BODY,
            "uuid",
            "plpgsql",
            roles,
        ),
        (f"purge_deleted_account{suffix}(uuid)", PURGE_BODY, "void", "plpgsql", roles),
    )


def upgrade():
    verify(
        FROZEN
        + entrypoints()
        + (
            (SOURCE_SIGNATURE, SOURCE_OLD, "jsonb", "plpgsql", ("calorie_app_api",)),
            (
                "e8n_delete_helper(uuid,uuid,boolean)",
                HELPER_BODY,
                "void",
                "plpgsql",
                ("calorie_app_deletion_operator",),
            ),
        )
    )
    op.execute("""DO $$ BEGIN IF
      to_regprocedure('app.begin_account_deletion_e8_19(uuid,uuid,integer)') IS NOT NULL
      OR to_regprocedure('app.purge_deleted_account_e8_19(uuid)') IS NOT NULL THEN
      RAISE EXCEPTION 'integration parent aliases already exist' USING ERRCODE='23514';
      END IF; END $$""")
    for resource in ("deletion", "restore", "source_guard"):
        op.execute(ROOT.joinpath(resource + ".sql").read_text(encoding="utf-8"))
    # The helper is now internal to the exact, fenced production wrappers.
    op.execute(
        "REVOKE ALL ON FUNCTION app.e8n_delete_helper(uuid,uuid,boolean) "
        "FROM calorie_app_deletion_operator"
    )
    verify(
        FROZEN
        + entrypoints(True)
        + (
            (SOURCE_SIGNATURE, SOURCE_NEW, "jsonb", "plpgsql", ("calorie_app_api",)),
            ("e8n_delete_helper(uuid,uuid,boolean)", HELPER_BODY, "void", "plpgsql", ()),
        )
    )


def downgrade():
    # No irreversible evidence is discarded. Disabled capability is additionally
    # required before removing production source/deletion integration.
    predicate = " OR ".join(f"EXISTS(SELECT 1 FROM app.{table})" for table in HISTORY)
    op.execute(f"""DO $$ BEGIN IF {predicate}
      OR EXISTS(SELECT 1 FROM app.nemesis_control WHERE enabled) THEN
      RAISE EXCEPTION 'cannot downgrade nonempty or enabled Nemesis integration'
        USING ERRCODE='23514'; END IF; END $$""")
    verify(
        FROZEN
        + entrypoints(True)
        + (
            (SOURCE_SIGNATURE, SOURCE_NEW, "jsonb", "plpgsql", ("calorie_app_api",)),
            ("e8n_delete_helper(uuid,uuid,boolean)", HELPER_BODY, "void", "plpgsql", ()),
        )
    )
    op.execute(ROOT.joinpath("downgrade_source_guard.sql").read_text(encoding="utf-8"))
    op.execute("DROP FUNCTION app.e8n_restore_maintain(integer)")
    op.execute("DROP FUNCTION app.begin_account_deletion(uuid,uuid,integer)")
    op.execute("DROP FUNCTION app.purge_deleted_account(uuid)")
    op.execute(
        "ALTER FUNCTION app.begin_account_deletion_e8_19(uuid,uuid,integer) "
        "RENAME TO begin_account_deletion"
    )
    op.execute(
        "ALTER FUNCTION app.purge_deleted_account_e8_19(uuid) RENAME TO purge_deleted_account"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.begin_account_deletion(uuid,uuid,integer), "
        "app.purge_deleted_account(uuid),app.e8n_delete_helper(uuid,uuid,boolean) "
        "TO calorie_app_deletion_operator"
    )
    verify(
        FROZEN
        + entrypoints()
        + (
            (SOURCE_SIGNATURE, SOURCE_OLD, "jsonb", "plpgsql", ("calorie_app_api",)),
            (
                "e8n_delete_helper(uuid,uuid,boolean)",
                HELPER_BODY,
                "void",
                "plpgsql",
                ("calorie_app_deletion_operator",),
            ),
        )
    )
