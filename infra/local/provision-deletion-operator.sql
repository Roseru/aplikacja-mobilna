-- Run with psql -X -w -d calorie_app -f this-file as a database/role administrator.
-- Run before upgrading an existing E3 installation to 0011, then again after
-- upgrade to verify effective function/table privileges. No schema/data changes.
-- Supply DELETION_OPERATOR_LOGIN and DELETION_OPERATOR_PASSWORD externally.
-- Password rotation is intentional on each run; never pass secrets with -v.
\set ON_ERROR_STOP on
\set ECHO none
\set QUIET on
\getenv operator_login DELETION_OPERATOR_LOGIN
\getenv operator_password DELETION_OPERATOR_PASSWORD
\if :{?operator_login}
\else
  \echo DELETION_OPERATOR_LOGIN must be supplied externally
  \quit 3
\endif
\if :{?operator_password}
\else
  \echo DELETION_OPERATOR_PASSWORD must be supplied externally
  \quit 3
\endif
SELECT octet_length(:'operator_login') BETWEEN 1 AND 63
       AND length(:'operator_password') > 0 AS configuration_present \gset
\if :configuration_present
\else
  \echo Operator login/password configuration is empty or invalid
  \quit 3
\endif

BEGIN;
SET LOCAL password_encryption='scram-sha-256';
SELECT pg_advisory_xact_lock(hashtextextended('calorie-app-deletion-provision', 0));
SELECT set_config('calorie.operator_login', :'operator_login', true);
SELECT 'CREATE ROLE calorie_app_deletion_operator NOLOGIN NOSUPERUSER '
       'NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='calorie_app_deletion_operator')
\gexec

DO $$
DECLARE login_name text := current_setting('calorie.operator_login');
BEGIN
  IF login_name IN ('calorie_app_deletion_operator', 'calorie_app_api',
                    'calorie_app_worker', 'calorie_app_migrator', 'keycloak')
     OR login_name ~ '^pg_' THEN
    RAISE EXCEPTION 'An independent operator login is required';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='calorie_app_deletion_operator'
             AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
                  OR rolreplication OR rolbypassrls))
     OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
                WHERE r.rolname='calorie_app_deletion_operator') THEN
    RAISE EXCEPTION 'Existing operator role has unexpected privileges or memberships';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=login_name
             AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
     OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
                 JOIN pg_roles parent ON parent.oid=m.roleid
                WHERE r.rolname=login_name
                  AND (parent.rolname<>'calorie_app_deletion_operator' OR m.admin_option)) THEN
    RAISE EXCEPTION 'Existing operator login has unexpected privileges or memberships';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_database d,
             LATERAL aclexplode(coalesce(d.datacl, acldefault('d',d.datdba))) a
             WHERE d.datname=current_database() AND a.grantee=0
               AND a.privilege_type='CONNECT') THEN
    RAISE EXCEPTION 'Revoke PUBLIC CONNECT on the target database before provisioning';
  END IF;
END $$;

SELECT format('CREATE ROLE %I LOGIN INHERIT NOSUPERUSER NOCREATEDB '
              'NOCREATEROLE NOREPLICATION NOBYPASSRLS', :'operator_login')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:'operator_login')
\gexec
SELECT format('ALTER ROLE %I LOGIN INHERIT PASSWORD %L',
              :'operator_login', :'operator_password')
\gexec
SELECT format('GRANT calorie_app_deletion_operator TO %I '
              'WITH INHERIT TRUE, SET TRUE, ADMIN FALSE', :'operator_login')
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO calorie_app_deletion_operator',
              current_database())
\gexec

DO $$
DECLARE login_name text := current_setting('calorie.operator_login');
        function_name text;
BEGIN
  IF NOT has_database_privilege(login_name,current_database(),'CONNECT')
     OR has_database_privilege(login_name,current_database(),'CREATE,TEMP') THEN
    RAISE EXCEPTION 'Operator effective database privileges are not CONNECT-only';
  END IF;
  IF to_regnamespace('app') IS NOT NULL THEN
    IF has_schema_privilege(login_name,'app','CREATE') THEN
      RAISE EXCEPTION 'Operator must not have schema CREATE';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='app' AND c.relkind IN ('r','p','v','m','f')
                 AND (has_table_privilege(login_name,c.oid,
                       'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
                      OR (c.relname<>'account_deletion_jobs'
                          AND has_table_privilege(login_name,c.oid,'SELECT')))) THEN
      RAISE EXCEPTION 'Operator has unexpected effective table privileges';
    END IF;
    IF to_regprocedure('app.begin_account_deletion(uuid,uuid,integer)') IS NOT NULL THEN
      IF NOT has_table_privilege(login_name,'app.account_deletion_jobs','SELECT')
         OR NOT has_schema_privilege(login_name,'app','USAGE') THEN
        RAISE EXCEPTION 'Operator deletion job read privileges are incomplete';
      END IF;
      FOREACH function_name IN ARRAY ARRAY[
        'app.begin_account_deletion(uuid,uuid,integer)',
        'app.confirm_account_deletion(uuid)', 'app.purge_deleted_account(uuid)'] LOOP
        IF NOT has_function_privilege(login_name,function_name,'EXECUTE')
           OR has_function_privilege('calorie_app_api',function_name,'EXECUTE')
           OR has_function_privilege('calorie_app_worker',function_name,'EXECUTE') THEN
          RAISE EXCEPTION 'Deletion function effective privileges are invalid';
        END IF;
      END LOOP;
    END IF;
  END IF;
  IF pg_has_role('calorie_app_api','calorie_app_deletion_operator','MEMBER')
     OR pg_has_role('calorie_app_worker','calorie_app_deletion_operator','MEMBER') THEN
    RAISE EXCEPTION 'API/worker must not be operator members';
  END IF;
END $$;
COMMIT;
SELECT current_database() AS database_name, :'operator_login' AS operator_login,
       true AS connect_verified,
       to_regprocedure('app.begin_account_deletion(uuid,uuid,integer)') IS NOT NULL
         AS deletion_functions_verified;
