DO $$ BEGIN IF NOT EXISTS(
 SELECT 1 FROM pg_proc p JOIN pg_roles o ON o.oid=p.proowner
 WHERE p.oid=to_regprocedure('app.e8n_source_lock(uuid,integer,uuid,text,date[],date[],boolean)') AND o.rolname='calorie_app_migrator' AND NOT o.rolsuper
 AND p.prosecdef AND p.proconfig=ARRAY['search_path=pg_catalog, pg_temp']::text[]
 AND encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')='b176b9d78798b93bd7931011f6fdfce3d77ad9ac1f960df5312336f92cc3464c') THEN
 RAISE EXCEPTION 'frozen Nemesis parent owner path body required' USING ERRCODE='23514';
 END IF; END $$;
DO $$ BEGIN IF NOT EXISTS(
 SELECT 1 FROM pg_proc p JOIN pg_roles o ON o.oid=p.proowner
 WHERE p.oid=to_regprocedure('app.e8n_execute(text,text,uuid,text,uuid,text,jsonb)') AND o.rolname='calorie_app_migrator' AND NOT o.rolsuper
 AND p.prosecdef AND p.proconfig=ARRAY['search_path=pg_catalog, pg_temp']::text[]
 AND encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')='9799ca84954c61166948ddc096f471256b2ed28b67cdca229a9155a347d44ac4') THEN
 RAISE EXCEPTION 'frozen Nemesis parent owner path body required' USING ERRCODE='23514';
 END IF; END $$;
DO $$ BEGIN IF NOT EXISTS(
 SELECT 1 FROM pg_proc p JOIN pg_roles o ON o.oid=p.proowner
 WHERE p.oid=to_regprocedure('app.e8n_delete_helper(uuid,uuid,boolean)') AND o.rolname='calorie_app_migrator' AND NOT o.rolsuper
 AND p.prosecdef AND p.proconfig=ARRAY['search_path=pg_catalog, pg_temp']::text[]
 AND encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')='b2284665e3b41cf90b6239a8edd1ffdee7fd38c18036fbf9fb460f857d4b4a18') THEN
 RAISE EXCEPTION 'frozen Nemesis parent owner path body required' USING ERRCODE='23514';
 END IF; END $$;
