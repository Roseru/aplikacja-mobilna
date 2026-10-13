DO $$ DECLARE f record;r record;BEGIN
 FOR f IN SELECT oid::regprocedure sig FROM pg_proc WHERE pronamespace='app'::regnamespace
 AND(proname LIKE 'e9_%' OR proname LIKE '%photo22' OR proname LIKE '%pre22'
 OR proname IN('e7_claim','e7_dispatch','e7_preflight_finish','e7_finish','e7_finish_context','e7_prune_receipts','e7_receipt_cleanup_owners')) LOOP
 EXECUTE 'REVOKE ALL ON FUNCTION '||f.sig||' FROM PUBLIC';
 FOR r IN SELECT rolname FROM pg_roles WHERE rolname IN('calorie_app_api','calorie_app_worker',
 'calorie_app_ai_worker','calorie_app_motivation_worker','calorie_app_nemesis_worker','calorie_app_nemesis_finalizer','calorie_app_deletion_operator') LOOP
 EXECUTE 'REVOKE ALL ON FUNCTION '||f.sig||' FROM '||quote_ident(r.rolname);END LOOP;END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION app.e7_claim(uuid,uuid),app.e7_dispatch(uuid,uuid,text,uuid,uuid),
 app.e7_preflight_finish(uuid,uuid,integer),app.e7_finish_context(uuid,uuid),
 app.e7_finish(uuid,uuid,jsonb,text,integer),
 app.e9_auto_candidates(integer),app.e9_auto_enqueue(uuid,jsonb) TO calorie_app_ai_worker;
GRANT EXECUTE ON FUNCTION app.e9_mutate(uuid,integer,uuid,uuid,text,jsonb,jsonb),
 app.e9_analysis_read(uuid,uuid),app.e9_entity(uuid) TO calorie_app_api;

GRANT EXECUTE ON FUNCTION app.e7_prune_receipts(uuid,integer),app.e7_receipt_cleanup_owners(integer) TO calorie_app_ai_worker;

GRANT EXECUTE ON FUNCTION app.e9_append_legacy_change(uuid,uuid,bigint) TO calorie_app_api;

GRANT EXECUTE ON FUNCTION app.e9_state(uuid) TO calorie_app_api;
