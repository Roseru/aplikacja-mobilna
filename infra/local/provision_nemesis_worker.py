"""Provision an owned, minimal nemesis-worker LOGIN using locally encrypted SCRAM.

Admin connection comes from standard PG* environment/service/pgpass. Only
NEMESIS_WORKER_LOGIN/NEMESIS_WORKER_PASSWORD describe the worker. No secrets in argv.
Built-in PostgreSQL logging protections are inherited unchanged from the
existing deletion provisioner and verified before generating a verifier.

Only current app/test database CONNECT is granted. Standard PUBLIC CONNECT
to postgres/templates is unchanged; production global ACLs remain O3's job.
Every other non-template database, including Keycloak, must be inaccessible.
External audit hooks/proxies/privileged observers need deployment controls.
"""

import importlib.util
import os
import sys
from collections.abc import Mapping
from pathlib import Path

import psycopg

_SPEC = importlib.util.spec_from_file_location(
    "nemesis_worker_session_guard",
    Path(__file__).with_name("provision_deletion_operator.py"),
)
_GUARD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_GUARD)
STARTUP_OPTIONS = _GUARD.STARTUP_OPTIONS
verify_session = _GUARD.verify_session
ProvisionError = _GUARD.ProvisionError

BASE_ROLE = "calorie_app_nemesis_worker"
RESERVED = {
    BASE_ROLE,
    "calorie_app_api",
    "calorie_app_worker",
    "calorie_app_ai_worker",
    "calorie_app_motivation_worker",
    "calorie_app_migrator",
    "calorie_app_deletion_operator",
    "keycloak",
    "postgres",
}

PREPARE_SQL = r"""
SELECT pg_catalog.pg_advisory_xact_lock(
 pg_catalog.hashtextextended('calorie-app-nemesis-worker-provision-v1',0));
DO $$
DECLARE login_name text := current_setting('calorie.nemesis_worker_login');
        database_oid oid; marker text; role_oid oid;
BEGIN
 IF current_database()<>'calorie_app' AND current_database() !~ '_test$' THEN
   RAISE EXCEPTION 'invalid target context' USING ERRCODE='23514'; END IF;
 SELECT oid INTO database_oid FROM pg_catalog.pg_database WHERE datname=current_database();
 IF login_name=current_user OR login_name ~ '^pg_' OR login_name IN
   ('calorie_app_api','calorie_app_worker','calorie_app_ai_worker','calorie_app_motivation_worker','calorie_app_nemesis_worker','calorie_app_migrator',
    'calorie_app_deletion_operator','keycloak','postgres') THEN
   RAISE EXCEPTION 'independent nemesis login required' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='calorie_app_nemesis_worker'
    AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb
    AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
   OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles r
      ON r.oid=m.member WHERE r.rolname='calorie_app_nemesis_worker') THEN
   RAISE EXCEPTION 'minimal nemesis base role required' USING ERRCODE='23514'; END IF;
 IF to_regprocedure('app.e8n_maintain(integer)') IS NULL
    OR (SELECT array_agg(version_num ORDER BY version_num) FROM app.alembic_version)
       IS DISTINCT FROM ARRAY['0020_e8_nemesis_integration']::varchar[]
    AND (SELECT array_agg(version_num ORDER BY version_num) FROM app.alembic_version)
       IS DISTINCT FROM ARRAY['0023_e9_qualification']::varchar[] THEN
   RAISE EXCEPTION 'Nemesis target schema required' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM pg_catalog.pg_database d,
   LATERAL pg_catalog.aclexplode(coalesce(d.datacl,pg_catalog.acldefault('d',d.datdba))) a
   WHERE d.oid=database_oid AND a.grantee=0
   AND a.privilege_type IN ('CONNECT','CREATE','TEMPORARY')) THEN
   RAISE EXCEPTION 'private target database ACL required' USING ERRCODE='23514'; END IF;
 marker := 'calorie-app-nemesis-worker-provision-v1:'||database_oid::text;
 SELECT oid INTO role_oid FROM pg_catalog.pg_roles WHERE rolname=login_name;
 IF role_oid IS NOT NULL THEN
   IF pg_catalog.shobj_description(role_oid,'pg_authid') IS DISTINCT FROM marker OR
      EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE oid=role_oid AND
        (NOT rolcanlogin OR NOT rolinherit OR rolsuper OR rolcreatedb OR rolcreaterole
         OR rolreplication OR rolbypassrls)) OR
      (SELECT count(*) FROM pg_catalog.pg_auth_members WHERE member=role_oid)<>1 OR
      EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members WHERE roleid=role_oid) OR
      NOT EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles p
        ON p.oid=m.roleid WHERE m.member=role_oid AND p.rolname='calorie_app_nemesis_worker'
        AND m.inherit_option AND NOT m.admin_option AND NOT m.set_option) THEN
     RAISE EXCEPTION 'existing login is not this minimal owned nemesis login'
       USING ERRCODE='23514'; END IF;
 ELSE
   EXECUTE format('CREATE ROLE %I NOLOGIN INHERIT NOSUPERUSER NOCREATEDB '
     ||'NOCREATEROLE NOREPLICATION NOBYPASSRLS',login_name);
   EXECUTE format('COMMENT ON ROLE %I IS %L',login_name,marker);
   EXECUTE format('GRANT calorie_app_nemesis_worker TO %I '
     ||'WITH INHERIT TRUE, SET FALSE, ADMIN FALSE',login_name);
 END IF;
 EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I',current_database(),login_name);
END $$;
"""

VERIFY_ACL_SQL = r"""
DO $$
DECLARE login_name text := current_setting('calorie.nemesis_worker_login');
        allowed_functions text[] := ARRAY['app.e8n_maintain(integer)'];
        signature text; source_role text;
BEGIN
 IF NOT has_database_privilege(login_name,current_database(),'CONNECT') OR
 has_database_privilege(login_name,current_database(),'CREATE,TEMP') THEN
 RAISE EXCEPTION 'CONNECT-only target access required' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM pg_database d WHERE NOT d.datistemplate
 AND d.datname NOT IN(current_database(),'postgres')
 AND has_database_privilege(login_name,d.oid,'CONNECT')) THEN
 RAISE EXCEPTION 'other private database access forbidden' USING ERRCODE='23514'; END IF;
 FOREACH source_role IN ARRAY ARRAY[login_name,'calorie_app_nemesis_worker'] LOOP
 IF NOT has_schema_privilege(source_role,'app','USAGE') OR EXISTS(
 SELECT 1 FROM pg_namespace n WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
 AND has_schema_privilege(source_role,n.oid,'CREATE')) THEN
 RAISE EXCEPTION 'nemesis schema privileges invalid' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
 AND c.relkind IN('r','p','v','m','f') AND(
 has_table_privilege(source_role,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
 OR has_any_column_privilege(source_role,c.oid,'INSERT,UPDATE,REFERENCES')
 OR (NOT(n.nspname='app' AND c.relname IN('installation_state','alembic_version'))
 AND has_any_column_privilege(source_role,c.oid,'SELECT')))) THEN
 RAISE EXCEPTION 'nemesis raw table privileges forbidden' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE CASE WHEN n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND c.relkind='S'
 THEN has_sequence_privilege(source_role,c.oid,'USAGE,SELECT,UPDATE') ELSE false END) THEN
 RAISE EXCEPTION 'nemesis sequence privileges forbidden' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND p.prosecdef
 AND has_function_privilege(source_role,p.oid,'EXECUTE')
 AND p.oid::regprocedure::text<>ALL(allowed_functions)) THEN
 RAISE EXCEPTION 'nemesis privileged function access too broad' USING ERRCODE='23514'; END IF;
 FOREACH signature IN ARRAY allowed_functions LOOP
 IF to_regprocedure(signature) IS NULL
 OR NOT has_function_privilege(source_role,signature,'EXECUTE') THEN
 RAISE EXCEPTION 'nemesis required function access missing' USING ERRCODE='23514'; END IF;
 END LOOP;
 END LOOP;
 IF EXISTS(SELECT 1 FROM pg_roles r JOIN pg_roles b ON b.rolname='calorie_app_nemesis_worker'
 WHERE r.rolname IN('calorie_app_api','calorie_app_worker','calorie_app_ai_worker',
 'calorie_app_migrator','calorie_app_deletion_operator','calorie_app_motivation_worker','keycloak')
 AND pg_has_role(r.oid,b.oid,'MEMBER')) THEN
 RAISE EXCEPTION 'nemesis role isolation invalid' USING ERRCODE='23514'; END IF;
END $$;
"""

PASSWORD_SQL = """
DO $$ BEGIN
 EXECUTE format('ALTER ROLE %I LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE '
   ||'NOREPLICATION NOBYPASSRLS PASSWORD %L',
   current_setting('calorie.nemesis_worker_login'),current_setting('calorie.nemesis_worker_verifier'));
END $$;
"""


def configuration(environment: Mapping[str, str]) -> tuple[bytes, bytes]:
    login = environment.get("NEMESIS_WORKER_LOGIN", "")
    password = environment.get("NEMESIS_WORKER_PASSWORD", "")
    try:
        login_bytes, password_bytes = login.encode("utf-8"), password.encode("utf-8")
    except UnicodeError:
        raise ProvisionError("invalid_configuration") from None
    if (
        not 1 <= len(login_bytes) <= 63
        or not password_bytes
        or b"\x00" in login_bytes
        or b"\x00" in password_bytes
        or login in RESERVED
        or login.startswith("pg_")
    ):
        raise ProvisionError("invalid_configuration")
    return login_bytes, password_bytes


def provision(login_bytes: bytes, password_bytes: bytes) -> None:
    # Revalidate the callable API as well as CLI configuration.
    try:
        checked = configuration(
            {
                "NEMESIS_WORKER_LOGIN": login_bytes.decode("utf-8"),
                "NEMESIS_WORKER_PASSWORD": password_bytes.decode("utf-8"),
            }
        )
    except UnicodeError:
        raise ProvisionError("invalid_configuration") from None
    if checked != (login_bytes, password_bytes):
        raise ProvisionError("invalid_configuration")
    with psycopg.connect(
        "",
        autocommit=True,
        options=STARTUP_OPTIONS,
        client_encoding="UTF8",
        application_name="calorie-nemesis-worker-provision",
        connect_timeout=10,
    ) as connection:
        verify_session(connection)
        with connection.transaction():
            connection.execute(
                "SELECT set_config('calorie.nemesis_worker_login', %s, true)",
                (login_bytes.decode("utf-8"),),
            )
            connection.execute(PREPARE_SQL)
            connection.execute(VERIFY_ACL_SQL)
            verifier = connection.pgconn.encrypt_password(
                password_bytes, login_bytes, algorithm=b"scram-sha-256"
            )
            if not verifier.startswith(b"SCRAM-SHA-256$"):
                raise ProvisionError("unsupported_password_encryption")
            connection.execute(
                "SELECT set_config('calorie.nemesis_worker_verifier', %s, true)",
                (verifier.decode("ascii"),),
            )
            connection.execute(PASSWORD_SQL)
            connection.execute(VERIFY_ACL_SQL)


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise ProvisionError("invalid_arguments")
        provision(*configuration(os.environ))
    except ProvisionError as error:
        print(str(error), file=sys.stderr)
        return 3 if str(error) in {"invalid_configuration", "invalid_arguments"} else 1
    except Exception:  # noqa: BLE001 - never expose SQL/DSN/verifier diagnostics
        print("provisioning_failed", file=sys.stderr)
        return 1
    print("nemesis worker provisioning and effective ACL verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
