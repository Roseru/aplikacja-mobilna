-- Trusted activation checks the installed bodies, not a caller revision pair.
CREATE FUNCTION app.e8n_runtime_ready() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT (SELECT count(*) FROM app.nemesis_runtime_contract)=10
 AND NOT EXISTS(SELECT 1 FROM app.nemesis_runtime_contract r LEFT JOIN pg_proc p ON p.oid=to_regprocedure('app.'||r.signature)
 LEFT JOIN pg_roles o ON o.oid=p.proowner WHERE p.oid IS NULL OR o.rolname IS DISTINCT FROM 'calorie_app_migrator' OR o.rolsuper
 OR (NOT p.prosecdef AND r.signature<>'e8n_percent_text(numeric)') OR p.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, pg_temp']::text[]
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex')<>r.body_sha256
 OR EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
 LEFT JOIN pg_roles gr ON gr.oid=a.grantee WHERE a.privilege_type='EXECUTE' AND a.grantee<>p.proowner
 AND (a.is_grantable OR NOT coalesce(gr.rolname=CASE
  WHEN r.signature IN('e8n_statistics(text,text,uuid,uuid)','e8n_source_refresh(uuid,integer,uuid,jsonb,uuid[])') THEN 'calorie_app_api'
  WHEN r.signature IN('e8n_finalize(uuid)','e8n_finalize_batch(integer)') THEN 'calorie_app_nemesis_finalizer'
 END,false))))
 AND NOT EXISTS(SELECT 1 FROM pg_roles r CROSS JOIN pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
 WHERE r.rolname IN('calorie_app_api','calorie_app_worker','calorie_app_ai_worker','calorie_app_motivation_worker','calorie_app_nemesis_worker','calorie_app_deletion_operator','calorie_app_nemesis_finalizer')
 AND n.nspname='app' AND t.relname IN('nemesis_projection_seeds','nemesis_day_projections','nemesis_final_results','nemesis_runtime_contract')
 AND (has_table_privilege(r.oid,t.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
 OR has_any_column_privilege(r.oid,t.oid,'SELECT,INSERT,UPDATE,REFERENCES')))
 AND NOT EXISTS(SELECT 1 FROM pg_roles r JOIN pg_roles b ON b.rolname='calorie_app_nemesis_finalizer'
 WHERE r.rolname IN('calorie_app_api','calorie_app_worker','calorie_app_ai_worker','calorie_app_motivation_worker','calorie_app_nemesis_worker','calorie_app_deletion_operator')
 AND pg_has_role(r.oid,b.oid,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles b ON b.oid=m.member WHERE b.rolname='calorie_app_nemesis_finalizer')
$$;
CREATE OR REPLACE FUNCTION app.e8n_gate() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT app.e8n_runtime_ready() AND EXISTS(SELECT 1 FROM app.nemesis_control c JOIN app.installation_state i
 ON i.id=c.id AND i.sync_epoch=c.sync_epoch JOIN app.nemesis_releases r USING(projector_revision,finalizer_revision)
 WHERE c.id=1 AND c.enabled AND c.schema_revision='0021_e8_nemesis_results' AND c.initializer_revision='0021_initializer_v1'
 AND c.projector_revision='0021_projection_v1' AND c.finalizer_revision='0021_finalizer_v1'
 AND r.schema_revision=c.schema_revision AND r.initializer_revision=c.initializer_revision)
$$;
CREATE FUNCTION app.e8n_activate(p_epoch uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch FOR SHARE;
 IF NOT FOUND OR NOT app.e8n_runtime_ready()
 OR (SELECT array_agg(version_num) FROM app.alembic_version) IS DISTINCT FROM ARRAY['0021_e8_nemesis_results']::varchar[]
 OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer' AND NOT rolcanlogin
 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT has_function_privilege('calorie_app_nemesis_finalizer','app.e8n_finalize_batch(integer)','EXECUTE')
 OR EXISTS(SELECT 1 FROM app.nemesis_challenges WHERE sync_epoch<>p_epoch AND status<>'cancelled')
 THEN RAISE EXCEPTION 'Nemesis activation preconditions unavailable' USING ERRCODE='55000'; END IF;
 UPDATE app.nemesis_control SET sync_epoch=p_epoch,enabled=true,schema_revision='0021_e8_nemesis_results',
 initializer_revision='0021_initializer_v1',projector_revision='0021_projection_v1',finalizer_revision='0021_finalizer_v1' WHERE id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Nemesis control unavailable' USING ERRCODE='55000'; END IF;
END $$;
INSERT INTO app.nemesis_releases(projector_revision,finalizer_revision,schema_revision,initializer_revision)
 VALUES('0021_projection_v1','0021_finalizer_v1','0021_e8_nemesis_results','0021_initializer_v1');
UPDATE app.nemesis_control SET enabled=false;
