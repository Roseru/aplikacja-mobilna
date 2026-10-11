CREATE FUNCTION app.e7_terminal(p_analysis uuid,p_code text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 INSERT INTO app.ai_cleanup_intents(storage_key) SELECT storage_key FROM app.ai_analyses
 WHERE id=p_analysis AND storage_key IS NOT NULL ON CONFLICT DO NOTHING;
 UPDATE app.ai_analyses SET state='failed',proposal=NULL,error_code=p_code,revision=revision+1 WHERE id=p_analysis AND state IN ('queued','running');
 UPDATE app.ai_jobs SET state='failed',phase='completed',fence=gen_random_uuid() WHERE analysis_id=p_analysis AND state IN ('queued','running');
END $$;
REVOKE ALL ON FUNCTION app.e7_terminal(uuid,text) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;

CREATE FUNCTION app.e7_claim(p_job uuid,p_fence uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE; a app.user_accounts%ROWTYPE; t timestamptz; BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job;
 IF NOT FOUND OR j.purpose<>'food_photo' THEN RETURN NULL; END IF;
 SELECT * INTO a FROM app.user_accounts WHERE id=j.owner_id FOR UPDATE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 PERFORM 1 FROM app.ai_pools WHERE scope=j.pool_scope FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 IF NOT FOUND OR j.state NOT IN ('queued','running') THEN RETURN NULL; END IF;
 t:=clock_timestamp();
 IF a.state<>'active' OR a.generation<>j.generation OR j.sync_epoch IS DISTINCT FROM
 (SELECT sync_epoch FROM app.installation_state WHERE id=1) THEN
   PERFORM app.e7_terminal(j.analysis_id,'analysis_context_changed'); RETURN NULL; END IF;
 IF j.state='running' AND j.lease_until>t THEN RETURN NULL; END IF;
 IF j.phase='dispatch_started' THEN
   PERFORM app.e7_terminal(j.analysis_id,'provider_result_unknown'); RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM app.ai_controls c WHERE c.id=1 AND c.dispatch_open AND c.sync_epoch=j.sync_epoch) THEN
   PERFORM app.e7_terminal(j.analysis_id,'ai_restore_pending'); RETURN NULL; END IF;
 IF j.next_attempt_at>t THEN RETURN NULL; END IF;
 IF j.started_at IS NULL AND j.queue_deadline<=t THEN
   PERFORM app.e7_terminal(j.analysis_id,'analysis_queue_expired'); RETURN NULL; END IF;
 IF j.processing_deadline IS NOT NULL AND j.processing_deadline<=t THEN
   PERFORM app.e7_terminal(j.analysis_id,'analysis_deadline_exceeded'); RETURN NULL; END IF;
 UPDATE app.ai_jobs SET state='running',phase='claimed',fence=p_fence,lease_until=t+interval '60 seconds',
 started_at=coalesce(started_at,t),processing_deadline=coalesce(processing_deadline,t+interval '120 seconds') WHERE id=p_job;
 UPDATE app.ai_analyses SET state='running',revision=revision+1 WHERE id=j.analysis_id AND state='queued';
 RETURN (SELECT jsonb_build_object('job_id',j.id,'analysis_id',j.analysis_id,'owner_id',j.owner_id,
 'fence',p_fence,'profile',x.profile,'storage_key',x.storage_key,'prepared_hash',x.prepared_hash,
 'photo_expires_at',x.photo_expires_at,'input_tokens',j.input_tokens,'preflight_done',j.preflight_done)
 FROM app.ai_analyses x WHERE x.id=j.analysis_id);
END $$;
REVOKE ALL ON FUNCTION app.e7_claim(uuid,uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_claim(uuid,uuid) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_dispatch(p_job uuid,p_fence uuid,p_kind text,p_attempt uuid,p_worker uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE; a app.ai_analyses%ROWTYPE; r jsonb; t timestamptz; ordinal integer; BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job; IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM app.e7_context(j.owner_id,j.generation,j.sync_epoch);
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 PERFORM 1 FROM app.ai_pools WHERE scope=j.pool_scope FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO a FROM app.ai_analyses WHERE id=j.analysis_id FOR UPDATE;
 t:=clock_timestamp();
 IF j.state<>'running' OR j.phase<>'claimed' OR j.fence IS DISTINCT FROM p_fence OR j.lease_until<=t OR
 a.decision_state<>'pending' OR a.state<>'running' THEN RETURN NULL; END IF;
 IF j.processing_deadline<=t OR a.photo_expires_at<=t THEN
   PERFORM app.e7_terminal(j.analysis_id,'analysis_deadline_exceeded'); RETURN NULL; END IF;
 IF p_kind='count_tokens' THEN
   IF j.preflight_done THEN RETURN NULL; END IF; ordinal:=0;
 ELSIF p_kind='generate' THEN
   IF j.input_tokens IS NULL OR j.generate_attempts>=2 THEN RETURN NULL; END IF;
   ordinal:=j.generate_attempts+1;
 ELSE RAISE EXCEPTION 'invalid dispatch kind' USING ERRCODE='22023'; END IF;
 r:=app.e7_reserve(j.pool_scope,j.purpose,p_kind,p_job,ordinal,p_attempt,p_worker);
 IF r ? 'error' THEN
   IF r->>'error' IN ('ai_rate_limited','ai_outbound_busy') THEN
     UPDATE app.ai_jobs SET state='queued',phase='waiting',next_attempt_at=t+interval '1 second' WHERE id=p_job;
   ELSE PERFORM app.e7_terminal(j.analysis_id,r->>'error'); END IF;
   RETURN r;
 END IF;
 UPDATE app.ai_jobs SET phase='dispatch_started',lease_until=t+interval '60 seconds',
 preflight_done=preflight_done OR p_kind='count_tokens',generate_attempts=generate_attempts+CASE WHEN p_kind='generate' THEN 1 ELSE 0 END WHERE id=p_job;
 RETURN r||jsonb_build_object('timeout_seconds',least(45,extract(epoch FROM j.processing_deadline-t)),
 'profile',a.profile,'storage_key',a.storage_key,'prepared_hash',a.prepared_hash,'photo_expires_at',a.photo_expires_at);
END $$;
REVOKE ALL ON FUNCTION app.e7_dispatch(uuid,uuid,text,uuid,uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_dispatch(uuid,uuid,text,uuid,uuid) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_preflight_finish(p_job uuid,p_fence uuid,p_tokens integer) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE; BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job; IF NOT FOUND THEN RETURN false; END IF;
 PERFORM app.e7_context(j.owner_id,j.generation,j.sync_epoch);
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 IF j.state<>'running' OR j.fence IS DISTINCT FROM p_fence OR j.lease_until<=clock_timestamp()
 OR j.processing_deadline<=clock_timestamp() THEN RETURN false; END IF;
 IF j.phase<>'dispatch_started' OR NOT j.preflight_done OR j.generate_attempts<>0
 OR j.input_tokens IS NOT NULL OR NOT EXISTS(SELECT 1 FROM app.ai_attempts
 WHERE job_id=p_job AND kind='count_tokens' AND status='ok' AND io_finished_at IS NOT NULL)
 THEN RETURN false; END IF;
 IF p_tokens IS NULL OR p_tokens NOT BETWEEN 0 AND 8192 THEN
   PERFORM app.e7_terminal(j.analysis_id,'provider_input_budget_exceeded'); RETURN false; END IF;
 UPDATE app.ai_jobs SET input_tokens=p_tokens,phase='claimed' WHERE id=p_job;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION app.e7_preflight_finish(uuid,uuid,integer) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_preflight_finish(uuid,uuid,integer) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_finish(p_job uuid,p_fence uuid,p_proposal jsonb,p_code text,p_retry_seconds integer DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE; a app.ai_analyses%ROWTYPE; t timestamptz; BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job; IF NOT FOUND THEN RETURN false; END IF;
 PERFORM app.e7_context(j.owner_id,j.generation,j.sync_epoch);
 -- Matching is executed in the same short transaction under the public catalog lock.
 PERFORM 1 FROM app.community_catalog_state WHERE id=1 FOR SHARE;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 SELECT * INTO a FROM app.ai_analyses WHERE id=j.analysis_id FOR UPDATE;
 t:=clock_timestamp();
 IF j.state<>'running' OR j.fence IS DISTINCT FROM p_fence OR j.lease_until<=t OR a.decision_state<>'pending'
 OR a.state<>'running' OR NOT EXISTS(SELECT 1 FROM app.ai_controls WHERE id=1 AND dispatch_open AND sync_epoch=j.sync_epoch) THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM app.ai_attempts WHERE job_id=p_job AND io_finished_at IS NULL) THEN RETURN false; END IF;
 IF p_retry_seconds IS NOT NULL AND p_retry_seconds BETWEEN 1 AND 45 AND p_code IN ('provider_before_send','provider_minute_quota')
 AND j.generate_attempts<2 AND t+make_interval(secs=>p_retry_seconds)<j.processing_deadline THEN
   UPDATE app.ai_jobs SET state='queued',phase='waiting',next_attempt_at=t+make_interval(secs=>p_retry_seconds) WHERE id=p_job;
   RETURN true;
 END IF;
 IF j.processing_deadline<=t THEN PERFORM app.e7_terminal(j.analysis_id,'analysis_deadline_exceeded'); RETURN false; END IF;
 IF p_proposal IS NULL OR p_proposal='null'::jsonb THEN PERFORM app.e7_terminal(j.analysis_id,p_code); RETURN true; END IF;
 IF jsonb_typeof(p_proposal->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(p_proposal->'items') NOT BETWEEN 1 AND 30
 OR octet_length(p_proposal::text)>1048576 THEN RAISE EXCEPTION 'invalid proposal' USING ERRCODE='23514'; END IF;
 UPDATE app.ai_jobs SET state='succeeded',phase='completed' WHERE id=p_job;
 UPDATE app.ai_analyses SET state='succeeded',proposal=p_proposal,error_code=NULL,revision=revision+1 WHERE id=j.analysis_id;
 INSERT INTO app.ai_cleanup_intents(storage_key) SELECT storage_key FROM app.ai_analyses WHERE id=j.analysis_id AND storage_key IS NOT NULL ON CONFLICT DO NOTHING;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION app.e7_finish(uuid,uuid,jsonb,text,integer) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_finish(uuid,uuid,jsonb,text,integer) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_finish_context(p_job uuid,p_fence uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE; BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job; IF NOT FOUND THEN RETURN false; END IF;
 PERFORM app.e7_context(j.owner_id,j.generation,j.sync_epoch);
 PERFORM 1 FROM app.community_catalog_state WHERE id=1 FOR SHARE;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 RETURN j.state='running' AND j.fence=p_fence AND j.lease_until>clock_timestamp()
 AND EXISTS(SELECT 1 FROM app.ai_controls WHERE id=1 AND dispatch_open AND sync_epoch=j.sync_epoch);
END $$;
REVOKE ALL ON FUNCTION app.e7_finish_context(uuid,uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_finish_context(uuid,uuid) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_read_descriptor(p_job uuid,p_fence uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.ai_jobs%ROWTYPE; BEGIN
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job; IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM app.e7_context(j.owner_id,j.generation,j.sync_epoch);
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO j FROM app.ai_jobs WHERE id=p_job FOR UPDATE;
 IF j.state<>'running' OR j.fence IS DISTINCT FROM p_fence OR j.lease_until<=clock_timestamp()
 OR j.processing_deadline<=clock_timestamp() THEN RETURN NULL; END IF;
 RETURN (SELECT jsonb_build_object('storage_key',a.storage_key,'prepared_hash',a.prepared_hash)
 FROM app.ai_analyses a WHERE a.id=j.analysis_id AND a.state='running' AND a.decision_state='pending'
 AND a.photo_expires_at>clock_timestamp() AND a.storage_key IS NOT NULL);
END $$;
REVOKE ALL ON FUNCTION app.e7_read_descriptor(uuid,uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_read_descriptor(uuid,uuid) TO calorie_app_ai_worker;
