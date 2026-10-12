-- No direct table access, control mutation or internal helper execution.
DO $$ DECLARE f record;t text; BEGIN
 FOREACH t IN ARRAY ARRAY['nemesis_control','nemesis_releases','nemesis_challenges','nemesis_slots','nemesis_share_codes','nemesis_receipts','nemesis_admissions','nemesis_cursors'] LOOP
 EXECUTE 'REVOKE ALL ON app.'||quote_ident(t)||' FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_motivation_worker,calorie_app_deletion_operator';
 END LOOP;
 FOR f IN SELECT p.oid::regprocedure signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='app' AND left(p.proname,4)='e8n_' LOOP
 EXECUTE 'REVOKE ALL ON FUNCTION '||f.signature||' FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_motivation_worker,calorie_app_deletion_operator';
 END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION app.e8n_execute(text,text,uuid,text,uuid,text,jsonb),app.e8n_read(text,text,uuid,uuid,integer,text),app.e8n_statistics(text,text,uuid,uuid),app.e8n_source_lock(uuid,integer,uuid,text,date[],date[],boolean) TO calorie_app_api;
GRANT EXECUTE ON FUNCTION app.e8n_delete_helper(uuid,uuid,boolean) TO calorie_app_deletion_operator;
-- E8.3-C leaves existing workers untouched. Explicit private fixture/provision
-- may supply a minimal base role; phase I owns production role provisioning.
DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_worker') THEN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_worker' AND NOT rolcanlogin AND NOT rolsuper AND NOT rolinherit AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls) THEN RAISE EXCEPTION 'minimal Nemesis worker role required' USING ERRCODE='23514'; END IF;
 EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA app FROM calorie_app_nemesis_worker';
 EXECUTE 'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM calorie_app_nemesis_worker';
 EXECUTE 'GRANT USAGE ON SCHEMA app TO calorie_app_nemesis_worker';
 EXECUTE 'GRANT EXECUTE ON FUNCTION app.e8n_maintain(integer) TO calorie_app_nemesis_worker';
 END IF;END $$;
