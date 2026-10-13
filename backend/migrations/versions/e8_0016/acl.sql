-- Freeze privileged entrypoints. Internal helpers have no runtime EXECUTE grant.
DO $$ DECLARE f record; BEGIN FOR f IN
 SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='app' AND p.proname LIKE 'e8\_%' ESCAPE '\'
 LOOP EXECUTE 'REVOKE ALL ON FUNCTION '||f.signature||
 ' FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_motivation_worker,calorie_app_deletion_operator';
 END LOOP; END $$;
GRANT EXECUTE ON FUNCTION app.e8_refresh(uuid,date[],integer),app.e8_day_facts(uuid,date[]),
 app.e8_affirm_ranking(uuid,uuid,integer),app.e8_revoke_ranking(uuid) TO calorie_app_api;
GRANT EXECUTE ON FUNCTION app.e8_process(uuid,integer),app.e8_candidates(integer),app.e8_status(),
 app.e8_prune_ranking_sessions(integer) TO calorie_app_motivation_worker;
