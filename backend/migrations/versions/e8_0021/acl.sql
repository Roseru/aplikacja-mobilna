-- Remove inherited/default grants on every new private table and entrypoint.
DO $$ DECLARE t text; a record; f record; runtime record; BEGIN
 FOREACH t IN ARRAY ARRAY['nemesis_projection_seeds','nemesis_day_projections','nemesis_final_results','nemesis_runtime_contract'] LOOP
  EXECUTE 'REVOKE ALL ON app.'||quote_ident(t)||' FROM PUBLIC';
  FOR a IN SELECT DISTINCT acl.grantee FROM pg_class c CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) acl
   WHERE c.oid=to_regclass('app.'||t) AND acl.grantee<>c.relowner AND acl.grantee<>0 LOOP
   EXECUTE 'REVOKE ALL ON app.'||quote_ident(t)||' FROM '||quote_ident(pg_get_userbyid(a.grantee));
  END LOOP;
 END LOOP;
 FOR f IN SELECT p.oid,p.proowner,p.oid::regprocedure signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='app' AND left(p.proname,4)='e8n_' LOOP
  EXECUTE 'REVOKE ALL ON FUNCTION '||f.signature||' FROM PUBLIC';
  FOR a IN SELECT DISTINCT acl.grantee FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) acl
    WHERE p.oid=f.oid AND acl.grantee<>p.proowner AND acl.grantee<>0 LOOP
   EXECUTE 'REVOKE ALL ON FUNCTION '||f.signature||' FROM '||quote_ident(pg_get_userbyid(a.grantee));
  END LOOP;
 END LOOP;
 -- Outgoing memberships allow SET ROLE, including NOINHERIT roles.
 IF EXISTS(SELECT 1 FROM pg_roles r JOIN pg_roles o ON o.rolname='calorie_app_migrator'
  WHERE r.rolname IN('calorie_app_api','calorie_app_worker','calorie_app_ai_worker','calorie_app_motivation_worker','calorie_app_nemesis_worker','calorie_app_deletion_operator','calorie_app_nemesis_finalizer')
  AND (r.rolsuper OR r.rolcreaterole OR r.rolbypassrls OR pg_has_role(r.oid,o.oid,'MEMBER'))) THEN
  RAISE EXCEPTION 'unsafe Nemesis runtime role graph' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer') THEN
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer' AND NOT rolcanlogin AND NOT rolinherit
   AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
   OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='calorie_app_nemesis_finalizer')
   OR EXISTS(SELECT 1 FROM pg_roles r JOIN pg_roles b ON b.rolname='calorie_app_nemesis_finalizer'
     WHERE r.rolname IN('calorie_app_api','calorie_app_worker','calorie_app_ai_worker','calorie_app_motivation_worker','calorie_app_nemesis_worker','calorie_app_deletion_operator')
       AND pg_has_role(r.oid,b.oid,'MEMBER')) THEN
   RAISE EXCEPTION 'minimal independent finalizer role required' USING ERRCODE='23514'; END IF;
  FOR runtime IN WITH RECURSIVE members(oid) AS (
   SELECT oid FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer'
   UNION SELECT m.member FROM pg_auth_members m JOIN members b ON m.roleid=b.oid
  ) SELECT r.* FROM pg_roles r JOIN members b ON b.oid=r.oid LOOP
   IF runtime.rolsuper OR runtime.rolcreatedb OR runtime.rolcreaterole OR runtime.rolreplication OR runtime.rolbypassrls
   OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles p ON p.oid=m.roleid
     WHERE m.member=runtime.oid AND p.rolname<>'calorie_app_nemesis_finalizer')
   OR has_schema_privilege(runtime.oid,'app','CREATE')
   OR EXISTS(SELECT 1 FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
    WHERE n.nspname='app' AND t.relkind IN('r','p') AND t.relname<>'alembic_version'
     AND (has_table_privilege(runtime.oid,t.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_any_column_privilege(runtime.oid,t.oid,'SELECT,INSERT,UPDATE,REFERENCES'))) THEN
    RAISE EXCEPTION 'unsafe finalizer member authority' USING ERRCODE='23514'; END IF;
  END LOOP;
  EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA app FROM calorie_app_nemesis_finalizer';
  EXECUTE 'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM calorie_app_nemesis_finalizer';
  EXECUTE 'GRANT USAGE ON SCHEMA app TO calorie_app_nemesis_finalizer';
  EXECUTE 'GRANT EXECUTE ON FUNCTION app.e8n_finalize(uuid),app.e8n_finalize_batch(integer) TO calorie_app_nemesis_finalizer';
 END IF;
END $$;
GRANT EXECUTE ON FUNCTION app.e8n_execute(text,text,uuid,text,uuid,text,jsonb),app.e8n_read(text,text,uuid,uuid,integer,text),
 app.e8n_statistics(text,text,uuid,uuid),app.e8n_source_lock(uuid,integer,uuid,text,date[],date[],boolean),
 app.e8n_source_refresh(uuid,integer,uuid,jsonb,uuid[]) TO calorie_app_api;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_worker') THEN
 GRANT EXECUTE ON FUNCTION app.e8n_maintain(integer) TO calorie_app_nemesis_worker;
END IF; END $$;
