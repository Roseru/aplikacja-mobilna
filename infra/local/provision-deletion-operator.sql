-- Executed by provision_deletion_operator.py, never directly by psql.
-- This file contains role/ACL provisioning only, with no password or verifier.
-- The helper supplies the validated login as a transaction-local setting,
-- runs these checks, then sets a locally generated SCRAM verifier and commits
-- everything together. Run before E3 upgrade to 0011 and again afterwards.
SELECT pg_advisory_xact_lock(hashtextextended('calorie-app-deletion-provision', 0));

DO $$
DECLARE login_name text := current_setting('calorie.operator_login');
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='calorie_app_deletion_exporter') THEN
    CREATE ROLE calorie_app_deletion_exporter NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='calorie_app_deletion_operator') THEN
    CREATE ROLE calorie_app_deletion_operator NOLOGIN NOSUPERUSER
      NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
  IF login_name LIKE 'calorie_app_%' OR login_name IN ('calorie_app_deletion_operator', 'calorie_app_api',
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
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=login_name) THEN
    EXECUTE format('CREATE ROLE %I LOGIN INHERIT NOSUPERUSER NOCREATEDB '
                   'NOCREATEROLE NOREPLICATION NOBYPASSRLS', login_name);
  END IF;
  EXECUTE format('GRANT calorie_app_deletion_operator TO %I '
                 'WITH INHERIT TRUE, SET TRUE, ADMIN FALSE', login_name);
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO calorie_app_deletion_operator',
                 current_database());
END $$;

DO $$
DECLARE login_name text := current_setting('calorie.operator_login');
        function_name text; ledger boolean := to_regprocedure('app.ledger_status(uuid)') IS NOT NULL;
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
                      OR has_any_column_privilege(login_name,c.oid,
                           'INSERT,UPDATE,REFERENCES')
                      OR ((ledger OR c.relname<>'account_deletion_jobs')
                          AND (has_table_privilege(login_name,c.oid,'SELECT')
                               OR has_any_column_privilege(login_name,c.oid,'SELECT'))))) THEN
      RAISE EXCEPTION 'Operator has unexpected effective table privileges';
    END IF;
    IF to_regprocedure('app.begin_account_deletion(uuid,uuid,integer)') IS NOT NULL THEN
      IF (NOT ledger AND NOT has_table_privilege(login_name,'app.account_deletion_jobs','SELECT'))
         OR NOT has_schema_privilege(login_name,'app','USAGE') THEN
        RAISE EXCEPTION 'Operator deletion job read privileges are incomplete';
      END IF;
      IF ledger AND (has_table_privilege(login_name,'app.account_deletion_jobs','SELECT')
        OR has_any_column_privilege(login_name,'app.account_deletion_jobs','SELECT')
        OR NOT has_function_privilege(login_name,'app.ledger_status(uuid)','EXECUTE')
        OR has_function_privilege(login_name,'app.ledger_ack(uuid,uuid,uuid,uuid,bigint,text,text)','EXECUTE')
        OR has_function_privilege(login_name,'app.ledger_batch(bigint,integer)','EXECUTE')
        OR pg_has_role(login_name,'calorie_app_deletion_exporter','MEMBER')) THEN
        RAISE EXCEPTION 'Ledger operator fencing or role separation invalid';
      END IF;
      IF ledger AND EXISTS(SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='app' AND (p.proname LIKE '_ledger_%'
          OR p.proname LIKE '%pre25' OR p.proname LIKE 'purge_deleted_account_e%'
          OR p.proname LIKE 'begin_account_deletion_e%' OR p.proname LIKE 'e8n_delete_helper%')
        AND has_function_privilege(login_name,p.oid,'EXECUTE')) THEN
        RAISE EXCEPTION 'Operator can execute an internal deletion parent';
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
