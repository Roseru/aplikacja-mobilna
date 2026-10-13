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
 IF EXISTS(SELECT 1 FROM app.energy_versions e WHERE e.owner_id=p_owner
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
 WHERE NOT EXISTS(SELECT 1 FROM app.energy_versions prior WHERE prior.owner_id=p_owner
 AND prior.source='legacy' AND prior.revision<e.revision AND prior.audit->'estimate'=e.audit->'estimate')
 ORDER BY t.root,g.timeline_revision DESC
 ), heads AS(
 SELECT e.* FROM app.energy_versions e WHERE e.owner_id=p_owner
 AND(e.source<>'legacy' OR e.id IN(SELECT id FROM legacy_heads))
 AND NOT EXISTS(SELECT 1 FROM app.energy_versions n WHERE n.owner_id=p_owner AND n.supersedes=e.id AND n.source<>'legacy' AND n.effective_from<=p_day)
 )
 SELECT * INTO resolved FROM heads h WHERE h.effective_from<=p_day ORDER BY h.effective_from DESC,h.revision DESC LIMIT 1;
 RETURN resolved;END $$;

-- The scoped deletion helper is internal; a replacement must not inherit
-- PostgreSQL's default PUBLIC EXECUTE.
REVOKE ALL ON FUNCTION app.e8n_delete_helper(uuid,uuid,boolean) FROM PUBLIC;
DO $$ DECLARE r record;BEGIN
 FOR r IN SELECT rolname FROM pg_roles WHERE rolname IN('calorie_app_api',
 'calorie_app_worker','calorie_app_ai_worker','calorie_app_motivation_worker',
 'calorie_app_nemesis_worker','calorie_app_nemesis_finalizer','calorie_app_deletion_operator') LOOP
 EXECUTE 'REVOKE ALL ON FUNCTION app.e8n_delete_helper(uuid,uuid,boolean) FROM '||quote_ident(r.rolname);
 END LOOP;
END $$;
CREATE OR REPLACE FUNCTION app.e8n_gate() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT app.e8n_runtime_ready() AND EXISTS(SELECT 1 FROM app.nemesis_control c JOIN app.installation_state i
 ON i.id=c.id AND i.sync_epoch=c.sync_epoch JOIN app.nemesis_releases r USING(projector_revision,finalizer_revision)
 WHERE c.id=1 AND c.enabled AND c.schema_revision='0023_e9_qualification' AND c.initializer_revision='0021_initializer_v1'
 AND c.projector_revision='0023_projection_v1' AND c.finalizer_revision='0021_finalizer_v1'
 AND r.schema_revision=c.schema_revision AND r.initializer_revision=c.initializer_revision)
$$;
CREATE OR REPLACE FUNCTION app.e8n_activate(p_epoch uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch FOR SHARE;
 IF NOT FOUND OR NOT app.e8n_runtime_ready()
 OR (SELECT array_agg(version_num) FROM app.alembic_version) IS DISTINCT FROM ARRAY['0023_e9_qualification']::varchar[]
 OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer' AND NOT rolcanlogin
 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT has_function_privilege('calorie_app_nemesis_finalizer','app.e8n_finalize_batch(integer)','EXECUTE')
 OR EXISTS(SELECT 1 FROM app.nemesis_challenges WHERE sync_epoch<>p_epoch AND status<>'cancelled')
 THEN RAISE EXCEPTION 'Nemesis activation preconditions unavailable' USING ERRCODE='55000'; END IF;
 UPDATE app.nemesis_control SET sync_epoch=p_epoch,enabled=true,schema_revision='0023_e9_qualification',
 initializer_revision='0021_initializer_v1',projector_revision='0023_projection_v1',finalizer_revision='0021_finalizer_v1' WHERE id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Nemesis control unavailable' USING ERRCODE='55000'; END IF;
END $$;
INSERT INTO app.nemesis_releases(projector_revision,finalizer_revision,schema_revision,initializer_revision)
 VALUES('0023_projection_v1','0021_finalizer_v1','0023_e9_qualification','0021_initializer_v1');
UPDATE app.nemesis_control SET enabled=false;

CREATE OR REPLACE FUNCTION app.e9_rules(p jsonb,p_auto boolean) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$
DECLARE complete integer;observed integer;n1 integer;n2 integer;m1 numeric;m2 numeric;e numeric;b numeric;
 numerator numeric;denominator numeric:=14;lo numeric;hi numeric;units numeric;proposal text;
 result jsonb;version_count integer;missing integer;
BEGIN
 WITH days AS(SELECT v,ord FROM jsonb_array_elements(p->'days') WITH ORDINALITY AS d(v,ord)),
 medians AS(SELECT ord,(SELECT avg(x) FROM(SELECT x,row_number() OVER(ORDER BY x) r,count(*) OVER() n FROM
 (SELECT v::numeric x FROM jsonb_array_elements_text(days.v->'weights') w(v)) s) ranked WHERE r IN((n+1)/2,(n+2)/2)) m FROM days)
 SELECT count(*) FILTER(WHERE (v->>'complete')::boolean AND (v->>'kcal')::numeric>0),
 count(DISTINCT v->>'energy_version'),count(*) FILTER(WHERE v->>'energy_version' IS NULL)
 INTO complete,version_count,missing FROM days;
 WITH days AS(SELECT v,ord FROM jsonb_array_elements(p->'days') WITH ORDINALITY AS d(v,ord)),
 medians AS(SELECT ord,(SELECT avg(x) FROM(SELECT x,row_number() OVER(ORDER BY x) r,count(*) OVER() n FROM
 (SELECT v::numeric x FROM jsonb_array_elements_text(days.v->'weights') w(v)) s) ranked WHERE r IN((n+1)/2,(n+2)/2)) m FROM days),
 ranked AS(SELECT *,row_number() OVER(PARTITION BY (ord-1)/7 ORDER BY m) r,count(*) OVER(PARTITION BY (ord-1)/7) n FROM medians WHERE m IS NOT NULL)
 SELECT count(*),count(*) FILTER(WHERE ord<=7),count(*) FILTER(WHERE ord>7),
 avg(m) FILTER(WHERE ord<=7 AND r IN((n+1)/2,(n+2)/2)),
 avg(m) FILTER(WHERE ord>7 AND r IN((n+1)/2,(n+2)/2))
 INTO observed,n1,n2,m1,m2 FROM ranked;
 result:=jsonb_build_object('rule_version','energy_adjustment_v1','complete_days',complete,'weight_days',observed,
 'first_median',CASE WHEN m1>0 THEN app.e9_wire(m1) END,'second_median',CASE WHEN m2>0 THEN app.e9_wire(m2) END,'proposed',NULL);
 IF complete<10 OR n1<2 OR n2<2 OR m1 IS NULL OR m2 IS NULL OR m1<=0 OR m2<=0 THEN
 RETURN result||jsonb_build_object('state','insufficient_data');END IF;
 e:=(p->>'current')::numeric;
 IF version_count<>1 OR missing>0 OR e IS NULL OR e<=0 THEN
 RETURN result||jsonb_build_object('state','energy_history_unavailable');END IF;
 IF complete<>14 OR abs(m2-m1)*200>m1 THEN
 RETURN result||jsonb_build_object('state','manual_review_required');END IF;
 lo:=e*0.95;hi:=e*1.05;
 IF p_auto THEN b:=(p->>'baseline')::numeric;
 IF b IS NULL OR b<=0 THEN RETURN result||jsonb_build_object('state','baseline_required');END IF;
 lo:=greatest(lo,b*0.9);hi:=least(hi,b*1.1);
 IF lo>hi THEN RETURN result||jsonb_build_object('state','baseline_range_conflict');END IF;END IF;
 IF ceil(lo*1000000000000)>floor(hi*1000000000000) THEN
 RETURN result||jsonb_build_object('state','baseline_range_conflict');END IF;
 SELECT sum((v->>'kcal')::numeric) INTO numerator FROM jsonb_array_elements(p->'days') v;
 numerator:=greatest(lo*14,least(hi*14,numerator));
 result:=result||jsonb_build_object('lower',lo::text,'upper',hi::text);
 IF abs(numerator-e*14)*100<e*14 THEN RETURN result||jsonb_build_object('state','no_change');END IF;
 proposal:=app.e9_wire(numerator,denominator);
 IF proposal::numeric<lo THEN proposal:=app.e9_wire(ceil(lo*1000000000000),1000000000000);END IF;
 IF proposal::numeric>hi THEN proposal:=app.e9_wire(floor(hi*1000000000000),1000000000000);END IF;
 RETURN result||jsonb_build_object('state','ready','proposed',proposal);
END $$;


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
 context:=app.e9_context(p_owner,today-14,today-1);
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
