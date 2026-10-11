-- Every call, including countTokens, consumes one request and a conservative 10240-token budget.
CREATE FUNCTION app.e7_provider_day(p_instant timestamptz) RETURNS date
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,pg_temp AS $$
 SELECT (p_instant AT TIME ZONE 'America/Los_Angeles')::date;
$$;
REVOKE ALL ON FUNCTION app.e7_provider_day(timestamptz) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
CREATE FUNCTION app.e7_reserve(p_scope text,p_purpose text,p_kind text,p_job uuid,p_ordinal integer,
 p_attempt uuid,p_worker uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE pool app.ai_pools%ROWTYPE; t timestamptz; d date; n bigint; tokens bigint; slot_no integer; BEGIN
 IF p_purpose NOT IN ('food_photo','energy_adjustment') OR p_kind NOT IN ('count_tokens','generate')
 OR p_attempt IS NULL OR p_worker IS NULL THEN RAISE EXCEPTION 'invalid reservation' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM app.ai_controls c JOIN app.installation_state i ON i.id=c.id
 WHERE c.id=1 AND c.dispatch_open AND c.sync_epoch=i.sync_epoch) THEN RETURN jsonb_build_object('error','ai_restore_pending'); END IF;
 SELECT * INTO pool FROM app.ai_pools WHERE scope=p_scope FOR UPDATE;
 IF NOT FOUND OR NOT pool.enabled THEN RETURN jsonb_build_object('error','ai_unavailable'); END IF;
 t:=clock_timestamp(); d:=app.e7_provider_day(t);
 SELECT count(*),coalesce(sum(reserved_tokens),0) INTO n,tokens FROM app.ai_attempts
 WHERE pool_scope=p_scope AND dispatched_at>t-interval '60 seconds';
 IF n>=pool.rpm OR tokens+10240>pool.tpm THEN RETURN jsonb_build_object('error','ai_rate_limited'); END IF;
 SELECT count(*) INTO n FROM app.ai_attempts WHERE pool_scope=p_scope AND pacific_day=d;
 IF n>=pool.rpd THEN RETURN jsonb_build_object('error','ai_quota_exhausted'); END IF;
 SELECT slot INTO slot_no FROM app.ai_transport_permits WHERE environment=pool.environment
 AND attempt_id IS NULL ORDER BY slot LIMIT 1 FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','ai_outbound_busy'); END IF;
 INSERT INTO app.ai_attempts(id,job_id,pool_scope,purpose,kind,ordinal,dispatched_at,pacific_day,
 reserved_tokens,worker_token_hash) VALUES(p_attempt,p_job,p_scope,p_purpose,p_kind,p_ordinal,t,d,10240,
 encode(sha256(convert_to(p_worker::text,'UTF8')),'hex'));
 UPDATE app.ai_transport_permits SET attempt_id=p_attempt WHERE environment=pool.environment AND slot=slot_no;
 RETURN jsonb_build_object('attempt_id',p_attempt,'slot',slot_no,'dispatched_at',t);
END $$;
REVOKE ALL ON FUNCTION app.e7_reserve(text,text,text,uuid,integer,uuid,uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
-- Only dispatch calls this internal primitive. Migrator can test both future purposes.

CREATE FUNCTION app.e7_io_finished(p_attempt uuid,p_worker uuid,p_status text,p_input integer,
 p_output integer,p_thoughts integer) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE a app.ai_attempts%ROWTYPE; BEGIN
 IF p_status IS NULL OR p_status NOT IN ('ok','unknown','denied','invalid') THEN
   RAISE EXCEPTION 'invalid transport completion' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO a FROM app.ai_attempts WHERE id=p_attempt AND worker_token_hash=
 encode(sha256(convert_to(p_worker::text,'UTF8')),'hex') FOR UPDATE;
 IF NOT FOUND OR a.io_finished_at IS NOT NULL THEN RETURN false; END IF;
 -- Caller asserts physical subprocess termination; no lease or account state can release a permit.
 UPDATE app.ai_attempts SET io_finished_at=clock_timestamp(),status=p_status,
 input_tokens=p_input,output_tokens=p_output,thoughts_tokens=p_thoughts,
 reserved_tokens=CASE WHEN p_status='ok' AND p_input BETWEEN 0 AND 8192 AND p_output>=0
 AND p_thoughts>=0 AND p_output+p_thoughts<=2048 THEN p_input+p_output+p_thoughts ELSE reserved_tokens END
 WHERE id=p_attempt;
 UPDATE app.ai_transport_permits SET attempt_id=NULL WHERE attempt_id=p_attempt;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION app.e7_io_finished(uuid,uuid,text,integer,integer,integer) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_io_finished(uuid,uuid,text,integer,integer,integer) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_restore_gate() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF NEW.sync_epoch IS DISTINCT FROM OLD.sync_epoch THEN
   UPDATE app.ai_controls SET dispatch_open=false,closed_at=clock_timestamp(),reconciled_at=NULL,reconciliation_hash=NULL WHERE id=1;
 END IF; RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.e7_restore_gate() FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
CREATE TRIGGER e7_restore_gate AFTER UPDATE OF sync_epoch ON app.installation_state
 FOR EACH ROW EXECUTE FUNCTION app.e7_restore_gate();

CREATE FUNCTION app.e7_reconcile(p_epoch uuid,p_evidence text,p_previous_io_fenced boolean) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE c app.ai_controls%ROWTYPE; BEGIN
 -- Operator command, executed with stopped traffic and physically fenced former workers.
 IF p_evidence IS NULL OR p_evidence !~ '^[0-9a-f]{64}$' OR p_previous_io_fenced IS DISTINCT FROM true
 OR p_epoch IS DISTINCT FROM (SELECT sync_epoch FROM app.installation_state WHERE id=1) THEN
   RAISE EXCEPTION 'reconciliation requires exact current epoch and fencing evidence' USING ERRCODE='23514'; END IF;
 SELECT * INTO c FROM app.ai_controls WHERE id=1 FOR UPDATE;
 IF c.closed_at IS NULL OR c.closed_at>clock_timestamp()-interval '336 hours' THEN
   RAISE EXCEPTION 'uncertain restored windows remain closed' USING ERRCODE='23514'; END IF;
 -- Conservative v1 resumes only after all possible E7/E9 windows have elapsed; no quota reset.
 UPDATE app.ai_attempts SET status='unknown',io_finished_at=coalesce(io_finished_at,clock_timestamp()),
 fenced_at=clock_timestamp(),fencing_evidence_hash=p_evidence
 WHERE id IN (SELECT attempt_id FROM app.ai_transport_permits WHERE attempt_id IS NOT NULL);
 UPDATE app.ai_transport_permits SET attempt_id=NULL;
 UPDATE app.ai_controls SET sync_epoch=p_epoch,dispatch_open=true,reconciled_at=clock_timestamp(),reconciliation_hash=p_evidence WHERE id=1;
END $$;
REVOKE ALL ON FUNCTION app.e7_reconcile(uuid,text,boolean) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;

CREATE FUNCTION app.e7_fence_permit(p_attempt uuid,p_evidence text,p_previous_io_fenced boolean) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF p_evidence IS NULL OR p_evidence !~ '^[0-9a-f]{64}$' OR p_previous_io_fenced IS DISTINCT FROM true THEN
   RAISE EXCEPTION 'physical IO fencing evidence required' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 UPDATE app.ai_attempts SET status='unknown',io_finished_at=coalesce(io_finished_at,clock_timestamp()),
 fenced_at=clock_timestamp(),fencing_evidence_hash=p_evidence WHERE id=p_attempt;
 UPDATE app.ai_transport_permits SET attempt_id=NULL WHERE attempt_id=p_attempt;
END $$;
REVOKE ALL ON FUNCTION app.e7_fence_permit(uuid,text,boolean) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
