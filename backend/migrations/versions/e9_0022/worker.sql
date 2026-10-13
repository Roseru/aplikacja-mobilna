CREATE FUNCTION app.e9_terminal(p_job uuid,p_code text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 UPDATE app.energy_analyses SET state='failed',revision=revision+1,error_code=p_code WHERE id=(SELECT energy_analysis_id FROM app.ai_jobs WHERE id=p_job) AND state IN('queued','running');
 UPDATE app.ai_jobs SET state='failed',phase='completed',fence=gen_random_uuid() WHERE id=p_job AND purpose='energy_adjustment' AND state IN('queued','running');
END $$;
ALTER FUNCTION app.e7_claim(uuid,uuid) RENAME TO e7_claim_photo22;
ALTER FUNCTION app.e7_dispatch(uuid,uuid,text,uuid,uuid) RENAME TO e7_dispatch_photo22;
ALTER FUNCTION app.e7_finish(uuid,uuid,jsonb,text,integer) RENAME TO e7_finish_photo22;
ALTER FUNCTION app.e7_finish_context(uuid,uuid) RENAME TO e7_finish_context_photo22;
ALTER FUNCTION app.e7_preflight_finish(uuid,uuid,integer) RENAME TO e7_preflight_finish_photo22;

CREATE FUNCTION app.e7_claim(p_job uuid,p_fence uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE;a app.energy_analyses%ROWTYPE;t timestamptz;
BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job;
 IF NOT FOUND THEN RETURN NULL;END IF;
 IF j.purpose='food_photo' THEN RETURN app.e7_claim_photo22(p_job,p_fence);END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=j.owner_id FOR UPDATE;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=j.owner_id FOR UPDATE;
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=j.sync_epoch FOR SHARE;
 IF NOT FOUND THEN PERFORM app.e9_terminal(p_job,'analysis_context_changed');RETURN NULL;END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 PERFORM 1 FROM app.ai_pools WHERE scope=j.pool_scope FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO a FROM app.energy_analyses WHERE id=j.energy_analysis_id FOR UPDATE;
 t:=clock_timestamp();
 IF j.state NOT IN('queued','running') OR j.state='running' AND j.lease_until>t THEN RETURN NULL;END IF;
 IF app.e9_stale(a) THEN PERFORM app.e9_terminal(p_job,'analysis_context_changed');RETURN NULL;END IF;
 IF j.phase='dispatch_started' THEN PERFORM app.e9_terminal(p_job,'provider_result_unknown');RETURN NULL;END IF;
 IF NOT EXISTS(SELECT 1 FROM app.ai_controls WHERE id=1 AND dispatch_open AND sync_epoch=j.sync_epoch) THEN PERFORM app.e9_terminal(p_job,'ai_restore_pending');RETURN NULL;END IF;
 IF j.next_attempt_at>t THEN RETURN NULL;END IF;
 IF j.started_at IS NULL AND j.queue_deadline<=t OR j.processing_deadline<=t THEN PERFORM app.e9_terminal(p_job,'analysis_deadline_exceeded');RETURN NULL;END IF;
 UPDATE app.ai_jobs SET state='running',phase='claimed',fence=p_fence,lease_until=t+interval '60 seconds',
 started_at=coalesce(started_at,t),processing_deadline=coalesce(processing_deadline,t+interval '120 seconds') WHERE id=p_job;
 UPDATE app.energy_analyses SET state='running',revision=revision+1 WHERE id=a.id AND state='queued';
 RETURN jsonb_build_object('purpose','energy_adjustment','job_id',j.id,'analysis_id',a.id,'owner_id',j.owner_id,
 'fence',p_fence,'profile',a.profile,'aggregates',a.result||jsonb_build_object('date_from',a.date_from,'date_to',a.date_to),
 'input_tokens',j.input_tokens,'preflight_done',j.preflight_done);
END $$;

CREATE FUNCTION app.e7_dispatch(p_job uuid,p_fence uuid,p_kind text,p_attempt uuid,p_worker uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE;a app.energy_analyses%ROWTYPE;t timestamptz;r jsonb;ordinal integer;
BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job;IF NOT FOUND THEN RETURN NULL;END IF;
 IF j.purpose='food_photo' THEN RETURN app.e7_dispatch_photo22(p_job,p_fence,p_kind,p_attempt,p_worker);END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=j.owner_id FOR UPDATE;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=j.owner_id FOR UPDATE;
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=j.sync_epoch FOR SHARE;
 IF NOT FOUND THEN PERFORM app.e9_terminal(p_job,'analysis_context_changed');RETURN NULL;END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 PERFORM 1 FROM app.ai_pools WHERE scope=j.pool_scope FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO a FROM app.energy_analyses WHERE id=j.energy_analysis_id FOR UPDATE;t:=clock_timestamp();
 IF j.state<>'running' OR j.phase<>'claimed' OR j.fence IS DISTINCT FROM p_fence OR j.lease_until<=t OR a.state<>'running' THEN RETURN NULL;END IF;
 IF app.e9_stale(a) THEN PERFORM app.e9_terminal(p_job,'analysis_context_changed');RETURN NULL;END IF;
 IF j.processing_deadline<=t THEN PERFORM app.e9_terminal(p_job,'analysis_deadline_exceeded');RETURN NULL;END IF;
 IF p_kind='count_tokens' THEN IF j.preflight_done THEN RETURN NULL;END IF;ordinal:=0;
 ELSIF p_kind='generate' THEN IF j.input_tokens IS NULL OR j.generate_attempts>=2 THEN RETURN NULL;END IF;ordinal:=j.generate_attempts+1;
 ELSE RAISE EXCEPTION 'invalid dispatch';END IF;
 r:=app.e7_reserve(j.pool_scope,j.purpose,p_kind,p_job,ordinal,p_attempt,p_worker);
 IF r ? 'error' THEN
 IF r->>'error' IN('ai_rate_limited','ai_outbound_busy') THEN UPDATE app.ai_jobs SET state='queued',phase='waiting',next_attempt_at=t+interval '1 second' WHERE id=p_job;
 ELSE PERFORM app.e9_terminal(p_job,r->>'error');END IF;RETURN r;END IF;
 UPDATE app.ai_jobs SET phase='dispatch_started',lease_until=t+interval '60 seconds',preflight_done=preflight_done OR p_kind='count_tokens',
 generate_attempts=generate_attempts+CASE WHEN p_kind='generate' THEN 1 ELSE 0 END WHERE id=p_job;
 RETURN r||jsonb_build_object('timeout_seconds',least(45,extract(epoch FROM j.processing_deadline-t)),'purpose','energy_adjustment',
 'aggregates',a.result||jsonb_build_object('date_from',a.date_from,'date_to',a.date_to),'profile',a.profile);
END $$;

CREATE FUNCTION app.e7_preflight_finish(p_job uuid,p_fence uuid,p_tokens integer) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE;a app.energy_analyses%ROWTYPE;BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job;IF NOT FOUND THEN RETURN false;END IF;
 IF j.purpose='food_photo' THEN RETURN app.e7_preflight_finish_photo22(p_job,p_fence,p_tokens);END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=j.owner_id FOR UPDATE;
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=j.sync_epoch FOR SHARE;
 IF NOT FOUND THEN PERFORM app.e9_terminal(p_job,'analysis_context_changed');RETURN false;END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO a FROM app.energy_analyses WHERE id=j.energy_analysis_id;
 IF j.state<>'running' OR j.fence IS DISTINCT FROM p_fence OR j.lease_until<=clock_timestamp() OR j.processing_deadline<=clock_timestamp()
 OR NOT EXISTS(SELECT 1 FROM app.ai_controls WHERE id=1 AND dispatch_open AND sync_epoch=j.sync_epoch) THEN RETURN false;END IF;
 IF app.e9_stale(a) THEN PERFORM app.e9_terminal(p_job,'analysis_context_changed');RETURN false;END IF;
 IF j.phase<>'dispatch_started' OR NOT j.preflight_done OR j.generate_attempts<>0 OR j.input_tokens IS NOT NULL
 OR NOT EXISTS(SELECT 1 FROM app.ai_attempts WHERE job_id=p_job AND kind='count_tokens' AND status='ok' AND io_finished_at IS NOT NULL) THEN RETURN false;END IF;
 IF p_tokens IS NULL OR p_tokens NOT BETWEEN 0 AND 8192 THEN PERFORM app.e9_terminal(p_job,'provider_input_budget_exceeded');RETURN false;END IF;
 UPDATE app.ai_jobs SET input_tokens=p_tokens,phase='claimed' WHERE id=p_job;RETURN true;
END $$;

CREATE FUNCTION app.e7_finish_context(p_job uuid,p_fence uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE;a app.energy_analyses%ROWTYPE;BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job;IF NOT FOUND THEN RETURN false;END IF;
 IF j.purpose='food_photo' THEN RETURN app.e7_finish_context_photo22(p_job,p_fence);END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=j.owner_id FOR UPDATE;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=j.owner_id FOR UPDATE;
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=j.sync_epoch FOR SHARE;
 IF NOT FOUND THEN PERFORM app.e9_terminal(p_job,'analysis_context_changed');RETURN false;END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO a FROM app.energy_analyses WHERE id=j.energy_analysis_id;
 IF app.e9_stale(a) THEN PERFORM app.e9_terminal(p_job,'analysis_context_changed');RETURN false;END IF;
 RETURN j.state='running' AND j.fence=p_fence AND j.lease_until>clock_timestamp() AND a.state='running'
 AND EXISTS(SELECT 1 FROM app.ai_controls WHERE id=1 AND dispatch_open AND sync_epoch=j.sync_epoch);
END $$;

CREATE FUNCTION app.e7_finish(p_job uuid,p_fence uuid,p_proposal jsonb,p_code text,p_retry_seconds integer DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE;a app.energy_analyses%ROWTYPE;t timestamptz;applied jsonb;
BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job;IF NOT FOUND THEN RETURN false;END IF;
 IF j.purpose='food_photo' THEN RETURN app.e7_finish_photo22(p_job,p_fence,p_proposal,p_code,p_retry_seconds);END IF;
 IF NOT app.e7_finish_context(p_job,p_fence) THEN RETURN false;END IF;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job;
 SELECT * INTO a FROM app.energy_analyses WHERE id=j.energy_analysis_id FOR UPDATE;t:=clock_timestamp();
 IF EXISTS(SELECT 1 FROM app.ai_attempts WHERE job_id=p_job AND io_finished_at IS NULL) THEN RETURN false;END IF;
 IF p_retry_seconds BETWEEN 1 AND 45 AND p_code IN('provider_before_send','provider_minute_quota')
 AND j.generate_attempts<2 AND t+make_interval(secs=>p_retry_seconds)<j.processing_deadline THEN
 UPDATE app.ai_jobs SET state='queued',phase='waiting',next_attempt_at=t+make_interval(secs=>p_retry_seconds) WHERE id=p_job;RETURN true;END IF;
 IF j.processing_deadline<=t THEN PERFORM app.e9_terminal(p_job,'analysis_deadline_exceeded');RETURN false;END IF;
 IF p_proposal IS NULL OR p_proposal='null'::jsonb THEN PERFORM app.e9_terminal(p_job,coalesce(p_code,'provider_result_invalid'));RETURN true;END IF;
 -- Provider may only explain. No energy number or profile write is accepted.
 IF jsonb_typeof(p_proposal)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(p_proposal))<>3
 OR NOT(p_proposal ?& ARRAY['explanation','uncertainty','suggested_class'])
 OR jsonb_typeof(p_proposal->'explanation')<>'string' OR length(p_proposal->>'explanation') NOT BETWEEN 1 AND 2000
 OR jsonb_typeof(p_proposal->'uncertainty') IS DISTINCT FROM 'string'
 OR p_proposal->>'uncertainty' NOT IN('low','medium','high')
 OR NOT(p_proposal->'suggested_class'='null'::jsonb OR p_proposal->>'suggested_class' IN('stationary','line','commando')) THEN
 PERFORM app.e9_terminal(p_job,'provider_result_invalid');RETURN true;END IF;
 UPDATE app.ai_jobs SET state='succeeded',phase='completed' WHERE id=p_job;
 UPDATE app.energy_analyses SET state=result->>'state',explanation=p_proposal,revision=revision+1,
 created_at=t,expires_at=t+interval '24 hours' WHERE id=a.id;
 IF a.automatic AND a.result->>'state'='ready' THEN
 applied:=app.e9_apply(a.owner_id,a.id,(a.result->>'proposed')::numeric,'automatic',
 jsonb_build_object('analysis_id',a.id,'rules',a.result,'explanation',p_proposal,'decider','automatic'));
 IF applied ? 'error' THEN UPDATE app.energy_analyses SET state='failed',error_code=applied->>'error',revision=revision+1 WHERE id=a.id;
 ELSE UPDATE app.energy_analyses SET state='accepted',revision=revision+1 WHERE id=a.id;END IF;END IF;
 RETURN true;
END $$;
