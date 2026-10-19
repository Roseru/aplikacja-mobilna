SELECT pg_advisory_xact_lock(hashtextextended('calorie-deletion-exporter-provision',0));
DO $$ DECLARE login text:=current_setting('calorie.operator_login'); f text; BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='calorie_app_deletion_exporter') THEN
  CREATE ROLE calorie_app_deletion_exporter NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
 END IF;
 IF login LIKE 'calorie_app_%' OR login LIKE 'pg_%' OR login='keycloak' THEN
  RAISE EXCEPTION 'independent exporter login required'; END IF;
 IF EXISTS(SELECT FROM pg_roles WHERE rolname IN(login,'calorie_app_deletion_exporter')
  AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls
    OR (rolname='calorie_app_deletion_exporter' AND rolcanlogin)))
 OR EXISTS(SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member JOIN pg_roles p ON p.oid=m.roleid
 WHERE r.rolname IN(login,'calorie_app_deletion_exporter') AND
 (r.rolname='calorie_app_deletion_exporter' OR p.rolname<>'calorie_app_deletion_exporter' OR m.admin_option)) THEN
  RAISE EXCEPTION 'exporter topology unsafe'; END IF;
 IF EXISTS(SELECT FROM pg_database d,LATERAL aclexplode(coalesce(d.datacl,acldefault('d',d.datdba))) a
 WHERE d.datname=current_database() AND a.grantee=0 AND a.privilege_type='CONNECT') THEN
  RAISE EXCEPTION 'revoke PUBLIC CONNECT first'; END IF;
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=login) THEN
  EXECUTE format('CREATE ROLE %I LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',login);
 END IF;
 EXECUTE format('GRANT calorie_app_deletion_exporter TO %I WITH INHERIT TRUE,SET TRUE,ADMIN FALSE',login);
 EXECUTE format('GRANT CONNECT ON DATABASE %I TO calorie_app_deletion_exporter',current_database());
 IF NOT has_database_privilege(login,current_database(),'CONNECT') OR has_database_privilege(login,current_database(),'CREATE,TEMP') THEN
  RAISE EXCEPTION 'exporter database ACL unsafe'; END IF;
 IF has_schema_privilege(login,'app','CREATE') THEN RAISE EXCEPTION 'exporter schema ACL unsafe'; END IF;
 IF EXISTS(SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='app' AND c.relkind IN('r','p','v','m','f') AND (
  has_table_privilege(login,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
  OR has_any_column_privilege(login,c.oid,'SELECT,INSERT,UPDATE,REFERENCES'))) THEN
  RAISE EXCEPTION 'exporter table ACL unsafe'; END IF;
 FOR f IN SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='app' AND p.prorettype NOT IN('trigger'::regtype,'event_trigger'::regtype)
 AND has_function_privilege(login,p.oid,'EXECUTE') LOOP
  IF f NOT IN('app.ledger_batch(bigint,integer)','app.ledger_export_position()',
   'app.ledger_ack(uuid,uuid,uuid,uuid,bigint,text,text)') THEN
   RAISE EXCEPTION 'exporter function ACL unsafe'; END IF;
 END LOOP;
 FOREACH f IN ARRAY ARRAY['app.ledger_batch(bigint,integer)','app.ledger_export_position()',
  'app.ledger_ack(uuid,uuid,uuid,uuid,bigint,text,text)'] LOOP
  IF NOT has_function_privilege(login,f,'EXECUTE') THEN RAISE EXCEPTION 'exporter function ACL incomplete'; END IF;
 END LOOP;
END $$;
