-- Exact trusted 0023 contract, derived from the unchanged packaged SQL on
-- a pristine 0023 database. Do not bless parent drift during an upgrade.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM (VALUES
 ('e8n_aggregate_projection(uuid,text,timestamptz)','33e4c80889812fe66b41748730d0db07f80b12c509720d047a1e5523c5f18533'),
 ('e8n_finalize(uuid)','de7c711216e0febf36346fcc33a6a949cad6d71aaa4699f71d0b617b726c2250'),
 ('e8n_finalize_batch(integer)','b4b5a3dade63a1b3e64d34d99f990eee50e9174410822af2abe4358d67f148f2'),
 ('e8n_initialize(uuid,timestamptz)','2dde53045779df25fa8823fa0e10b2646d2d1abd3f870561361337c59869e6cf'),
 ('e8n_percent_text(numeric)','7daf5137056d6e8bb9ec6b2047317d2d5af4e03a2f06e346572de38e621e9112'),
 ('e8n_seed_ready(app.nemesis_challenges)','a869bb55dd7bf22128ee68d7e7820a9e22f2f093ce18239ffc010fb4e641d8ee'),
 ('e8n_source_in_transaction(xid)','206ee00d07052b66795bb54461490ccfe71d555b47cd508b882aca8858994aa7'),
 ('e8n_source_refresh(uuid,integer,uuid,jsonb,uuid[])','d061ff64f72e8cdee115e81649ba3d3cf6cbd4550e369d2a0837b5d32c362721'),
 ('e8n_statistics(text,text,uuid,uuid)','47f589588281cfe5095c798f56ad384a76ca74ddcfbf160fd19a153918588982'),
 ('e8n_write_projection(uuid,uuid,text,timestamptz)','1eba603e84f87dcfc559d874b4a31fb1ecfcd6f063f67668fcd86f4eedd7d8db')
 ) expected(signature,digest) LEFT JOIN pg_proc p ON p.oid=to_regprocedure('app.'||expected.signature)
 LEFT JOIN app.nemesis_runtime_contract c USING(signature)
 WHERE p.oid IS NULL OR c.signature IS NULL OR c.body_sha256 IS DISTINCT FROM expected.digest
 OR encode(sha256(convert_to(p.prosrc,'UTF8')),'hex') IS DISTINCT FROM expected.digest)
 OR (SELECT count(*) FROM app.nemesis_runtime_contract)<>10 THEN
 RAISE EXCEPTION 'parent Nemesis contract drift' USING ERRCODE='55000';END IF;
END $$;
CREATE OR REPLACE FUNCTION app.e9_legacy_import(p_owner uuid,p_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE g app.goal_versions%ROWTYPE;r integer;parent uuid;
BEGIN
 SELECT * INTO g FROM app.goal_versions WHERE owner_id=p_owner AND id=p_id;
 IF NOT FOUND OR g.payload->'estimate' IS NULL OR g.payload->'estimate'='null'::jsonb THEN RETURN;END IF;
 IF NOT app.e9_legacy_valid(g.payload->'estimate') THEN RETURN;END IF;
 IF EXISTS(SELECT 1 FROM app.energy_versions WHERE id=p_id AND owner_id=p_owner) THEN RETURN;END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=p_owner FOR UPDATE;
 -- The estimate JSON (including estimation time and inputs) identifies the
 -- artifact. Reusing it while changing a goal must not overwrite a later E9.
 IF g.correction_of IS NULL AND EXISTS(SELECT 1 FROM app.energy_versions e WHERE e.owner_id=p_owner
 AND e.source='legacy' AND e.audit->'estimate'=g.payload->'estimate') THEN RETURN;END IF;
 INSERT INTO app.energy_axes(owner_id) VALUES(p_owner) ON CONFLICT DO NOTHING;
 UPDATE app.energy_axes SET revision=revision+1 WHERE owner_id=p_owner RETURNING revision INTO r;
 WITH RECURSIVE ancestors AS(
 SELECT id,correction_of FROM app.goal_versions WHERE owner_id=p_owner AND id=g.correction_of
 UNION ALL SELECT v.id,v.correction_of FROM app.goal_versions v JOIN ancestors a ON v.id=a.correction_of WHERE v.owner_id=p_owner
 ) SELECT e.id INTO parent FROM ancestors a JOIN app.energy_versions e ON e.id=a.id AND e.owner_id=p_owner ORDER BY e.revision DESC LIMIT 1;
 INSERT INTO app.energy_versions(id,owner_id,revision,effective_from,maintenance_kcal,method,source,source_id,supersedes,decided_at,audit)
 VALUES(g.id,p_owner,r,g.effective_from,(g.payload#>>'{estimate,maintenance_kcal}')::numeric,
 'mifflin_pal_v1','legacy',g.id,parent,g.decided_at,
 jsonb_build_object('goal_id',g.id,'goal_timeline_revision',g.timeline_revision,'estimate',g.payload->'estimate'));
END $$;
CREATE OR REPLACE FUNCTION app.e9_resolve(p_owner uuid,p_day date) RETURNS app.energy_versions
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE resolved app.energy_versions%ROWTYPE;BEGIN
 WITH RECURSIVE tree AS(
 SELECT id,id AS root FROM app.goal_versions WHERE owner_id=p_owner AND correction_of IS NULL
 UNION ALL SELECT g.id,t.root FROM app.goal_versions g JOIN tree t ON g.correction_of=t.id WHERE g.owner_id=p_owner
 ), legacy_heads AS(
 SELECT DISTINCT ON(t.root) e.id FROM tree t JOIN app.goal_versions g ON g.id=t.id
 JOIN app.energy_versions e ON e.owner_id=p_owner AND e.id=g.id AND e.source='legacy'
 WHERE g.correction_of IS NOT NULL OR NOT EXISTS(SELECT 1 FROM app.energy_versions prior WHERE prior.owner_id=p_owner
 AND prior.source='legacy' AND prior.revision<e.revision AND prior.audit->'estimate'=e.audit->'estimate')
 ORDER BY t.root,g.timeline_revision DESC
 ), heads AS(
 SELECT e.* FROM app.energy_versions e WHERE e.owner_id=p_owner
 AND(e.source<>'legacy' OR e.id IN(SELECT id FROM legacy_heads))
 AND NOT EXISTS(SELECT 1 FROM app.energy_versions n WHERE n.owner_id=p_owner AND n.supersedes=e.id AND n.source<>'legacy' AND n.effective_from<=p_day)
 )
 SELECT * INTO resolved FROM heads h WHERE h.effective_from<=p_day ORDER BY h.effective_from DESC,h.revision DESC LIMIT 1;
 RETURN resolved;END $$;

CREATE OR REPLACE FUNCTION app.e8n_gate() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT app.e8n_runtime_ready() AND EXISTS(SELECT 1 FROM app.nemesis_control c JOIN app.installation_state i
 ON i.id=c.id AND i.sync_epoch=c.sync_epoch JOIN app.nemesis_releases r USING(projector_revision,finalizer_revision)
 WHERE c.id=1 AND c.enabled AND c.schema_revision='0024_e9_history_graph' AND c.initializer_revision='0021_initializer_v1'
 AND c.projector_revision='0024_projection_v1' AND c.finalizer_revision='0021_finalizer_v1'
 AND r.schema_revision=c.schema_revision AND r.initializer_revision=c.initializer_revision)
$$;
CREATE OR REPLACE FUNCTION app.e8n_activate(p_epoch uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch FOR SHARE;
 IF NOT FOUND OR NOT app.e8n_runtime_ready()
 OR (SELECT array_agg(version_num) FROM app.alembic_version) IS DISTINCT FROM ARRAY['0024_e9_history_graph']::varchar[]
 OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer' AND NOT rolcanlogin
 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT has_function_privilege('calorie_app_nemesis_finalizer','app.e8n_finalize_batch(integer)','EXECUTE')
 OR EXISTS(SELECT 1 FROM app.nemesis_challenges WHERE sync_epoch<>p_epoch AND status<>'cancelled')
 THEN RAISE EXCEPTION 'Nemesis activation preconditions unavailable' USING ERRCODE='55000'; END IF;
 UPDATE app.nemesis_control SET sync_epoch=p_epoch,enabled=true,schema_revision='0024_e9_history_graph',
 initializer_revision='0021_initializer_v1',projector_revision='0024_projection_v1',finalizer_revision='0021_finalizer_v1' WHERE id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Nemesis control unavailable' USING ERRCODE='55000'; END IF;
END $$;
INSERT INTO app.nemesis_releases(projector_revision,finalizer_revision,schema_revision,initializer_revision)
 VALUES('0024_projection_v1','0021_finalizer_v1','0024_e9_history_graph','0021_initializer_v1');
UPDATE app.nemesis_control SET enabled=false;

CREATE OR REPLACE FUNCTION app.e9_auto_enqueue(p_owner uuid,p_profile jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE context jsonb;result jsonb;u app.user_accounts%ROWTYPE;t timestamptz;today date;new_id uuid:=gen_random_uuid();zone text;
BEGIN
 SELECT * INTO u FROM app.user_accounts WHERE id=p_owner AND state='active' FOR UPDATE;
 IF NOT FOUND OR app.subject_blocked(u.issuer,u.subject) THEN RETURN NULL;END IF;
 INSERT INTO app.sync_counters(owner_id) VALUES(p_owner) ON CONFLICT DO NOTHING;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
 PERFORM 1 FROM app.installation_state WHERE id=1 FOR SHARE;
 IF NOT EXISTS(SELECT 1 FROM app.energy_axes a JOIN app.user_consents c ON c.owner_id=a.owner_id
 WHERE a.owner_id=p_owner AND c.automatic_energy_adjustment AND a.baseline_id IS NOT NULL
 AND app.e9_notice_valid(a.baseline_notice,p_profile->>'provider','automatic_energy_adjustment')
 AND (a.baseline_notice->>'account_generation')::integer=u.generation
 AND a.baseline_epoch=(SELECT sync_epoch FROM app.installation_state WHERE id=1) AND a.baseline_consent_revision=c.revision
 AND(a.last_applied_at IS NULL OR a.last_applied_at<=clock_timestamp()-interval '336 hours')) THEN RETURN NULL;END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM app.ai_controls c JOIN app.installation_state i ON i.id=c.id AND i.sync_epoch=c.sync_epoch WHERE c.dispatch_open) THEN RETURN NULL;END IF;
 IF NOT EXISTS(SELECT 1 FROM app.ai_pools WHERE scope=p_profile->>'pool_scope' AND enabled AND provider=p_profile->>'provider' AND model=p_profile->>'model') THEN RETURN NULL;END IF;
 IF EXISTS(SELECT 1 FROM app.ai_jobs WHERE owner_id=p_owner AND state IN('queued','running')) THEN RETURN NULL;END IF;
 SELECT time_zone INTO zone FROM app.user_profiles WHERE owner_id=p_owner AND deleted_at IS NULL;IF zone IS NULL THEN RETURN NULL;END IF;
 t:=clock_timestamp();today:=(t AT TIME ZONE zone)::date;
 IF EXISTS(SELECT 1 FROM app.energy_axes WHERE owner_id=p_owner AND last_auto_checked_date=today) THEN RETURN NULL;END IF;
 BEGIN
 context:=app.e9_context(p_owner,today-14,today-1);
 EXCEPTION WHEN SQLSTATE '54000' THEN
 -- Only the documented per-owner source limit is an expected refusal.
 -- Other database failures propagate; no quota or job was admitted.
 UPDATE app.energy_axes SET last_auto_checked_date=today,last_auto_state='resource_exhausted'
 WHERE owner_id=p_owner;
 RETURN NULL;
 END;
 result:=app.e9_rules(context,true);
 UPDATE app.energy_axes SET last_auto_checked_date=today,last_auto_state=result->>'state' WHERE owner_id=p_owner;
 BEGIN
 context:=app.e9_context(p_owner,today-14,today-1);
 EXCEPTION WHEN SQLSTATE '54000' THEN
 UPDATE app.energy_axes SET last_auto_state='resource_exhausted' WHERE owner_id=p_owner;
 RETURN NULL;
 END;
 IF result->>'state' IN('insufficient_data','energy_history_unavailable','baseline_required','baseline_range_conflict') THEN RETURN NULL;END IF;
 IF NOT app.e7_admit(p_owner,'energy_adjustment') THEN RETURN NULL;END IF;
 INSERT INTO app.energy_analyses(id,owner_id,generation,sync_epoch,automatic,accepted_at,date_from,date_to,context,fingerprint,profile,notice,result,state)
 VALUES(new_id,p_owner,u.generation,(SELECT sync_epoch FROM app.installation_state WHERE id=1),true,t,today-14,today-1,context,app.e9_fingerprint(context),p_profile,
 app.e9_notice_snapshot((SELECT baseline_notice FROM app.energy_axes WHERE owner_id=p_owner),context,t,
 (SELECT baseline_id FROM app.energy_axes WHERE owner_id=p_owner)),result,'queued');
 INSERT INTO app.ai_jobs(id,owner_id,energy_analysis_id,purpose,generation,sync_epoch,pool_scope,state,queue_deadline,next_attempt_at)
 VALUES(gen_random_uuid(),p_owner,new_id,'energy_adjustment',u.generation,(SELECT sync_epoch FROM app.installation_state WHERE id=1),p_profile->>'pool_scope','queued',t+interval '5 minutes',t);
 RETURN jsonb_build_object('id',new_id,'state','queued');
END $$;
