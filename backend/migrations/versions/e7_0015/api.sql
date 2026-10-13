CREATE FUNCTION app.e7_context(p_owner uuid,p_generation integer,p_epoch uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' AND generation=p_generation FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'e7_account_context' USING ERRCODE='23514'; END IF;
 IF p_epoch IS DISTINCT FROM (SELECT sync_epoch FROM app.installation_state WHERE id=1) THEN
   RAISE EXCEPTION 'e7_epoch_context' USING ERRCODE='23514'; END IF;
END $$;
REVOKE ALL ON FUNCTION app.e7_context(uuid,integer,uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;

CREATE FUNCTION app.e7_admit(p_owner uuid,p_kind text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE d date; t timestamptz; used integer; BEGIN
 IF p_kind IS NULL OR p_kind NOT IN ('receipts','food_photo','energy_adjustment') THEN
   RAISE EXCEPTION 'invalid E7 admission purpose' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'e7_account_context' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 t:=clock_timestamp(); d:=(t AT TIME ZONE 'UTC')::date;
 IF p_kind='energy_adjustment' THEN
   SELECT accepted_at INTO t FROM app.ai_energy_admissions WHERE owner_id=p_owner FOR UPDATE;
   IF FOUND AND t>clock_timestamp()-interval '336 hours' THEN RETURN false; END IF;
   INSERT INTO app.ai_energy_admissions VALUES(p_owner,clock_timestamp())
   ON CONFLICT(owner_id) DO UPDATE SET accepted_at=excluded.accepted_at;
   RETURN true;
 END IF;
 INSERT INTO app.ai_admissions(owner_id,day) VALUES(p_owner,d) ON CONFLICT DO NOTHING;
 SELECT CASE p_kind WHEN 'receipts' THEN receipts ELSE photos END INTO used
 FROM app.ai_admissions WHERE owner_id=p_owner AND day=d FOR UPDATE;
 IF used>=(CASE p_kind WHEN 'receipts' THEN 1000 ELSE 10 END) THEN RETURN false; END IF;
 UPDATE app.ai_admissions SET receipts=receipts+CASE WHEN p_kind='receipts' THEN 1 ELSE 0 END,
 photos=photos+CASE WHEN p_kind='food_photo' THEN 1 ELSE 0 END WHERE owner_id=p_owner AND day=d;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION app.e7_admit(uuid,text) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_admit(uuid,text) TO calorie_app_api;

CREATE FUNCTION app.e7_save_receipt(p_owner uuid,p_generation integer,p_epoch uuid,p_key uuid,
 p_kind text,p_hash text,p_status integer,p_response jsonb,p_minimal jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 PERFORM app.e7_context(p_owner,p_generation,p_epoch);
 INSERT INTO app.ai_receipts(owner_id,operation_id,operation_kind,request_hash,generation,sync_epoch,
 status_code,response_payload,result_minimal) VALUES(p_owner,p_key,p_kind,p_hash,p_generation,p_epoch,
 p_status,p_response,p_minimal);
END $$;
REVOKE ALL ON FUNCTION app.e7_save_receipt(uuid,integer,uuid,uuid,text,text,integer,jsonb,jsonb)
 FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_save_receipt(uuid,integer,uuid,uuid,text,text,integer,jsonb,jsonb) TO calorie_app_api;

CREATE FUNCTION app.e7_accept(p_owner uuid,p_generation integer,p_epoch uuid,p_id uuid,p_job uuid,
 p_original text,p_prepared text,p_key text,p_width integer,p_height integer,p_profile jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE t timestamptz; pool app.ai_pools%ROWTYPE; BEGIN
 PERFORM app.e7_context(p_owner,p_generation,p_epoch);
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM app.ai_controls WHERE id=1 AND sync_epoch=p_epoch AND dispatch_open) THEN
   RETURN jsonb_build_object('error','ai_restore_pending'); END IF;
 SELECT * INTO pool FROM app.ai_pools WHERE scope=p_profile->>'pool_scope' FOR UPDATE;
 IF NOT FOUND OR NOT pool.enabled OR pool.provider IS DISTINCT FROM p_profile->>'provider'
 OR pool.model IS DISTINCT FROM p_profile->>'model' THEN RETURN jsonb_build_object('error','ai_unavailable'); END IF;
 IF EXISTS(SELECT 1 FROM app.ai_jobs WHERE owner_id=p_owner AND state IN ('queued','running')) THEN
   RETURN jsonb_build_object('error','ai_active_job'); END IF;
 IF NOT app.e7_admit(p_owner,'food_photo') THEN RETURN jsonb_build_object('error','ai_user_quota_exhausted'); END IF;
 t:=clock_timestamp();
 INSERT INTO app.ai_analyses(id,owner_id,generation,sync_epoch,profile,original_hash,prepared_hash,width,height,
 storage_key,accepted_at,photo_expires_at,state) VALUES(p_id,p_owner,p_generation,p_epoch,p_profile,p_original,
 p_prepared,p_width,p_height,p_key,t,t+interval '24 hours','queued');
 INSERT INTO app.ai_photo_consents(analysis_id,owner_id,notice_version,provider,scope,accepted_at,original_hash)
 VALUES(p_id,p_owner,'food-photo-notice-v1',pool.provider,'this_photo',t,p_original);
 INSERT INTO app.ai_jobs(id,owner_id,analysis_id,purpose,generation,sync_epoch,pool_scope,state,queue_deadline,next_attempt_at)
 VALUES(p_job,p_owner,p_id,'food_photo',p_generation,p_epoch,pool.scope,'queued',t+interval '5 minutes',t);
 DELETE FROM app.ai_cleanup_intents WHERE storage_key=p_key;
 RETURN jsonb_build_object('analysis_id',p_id,'revision',1,'state','queued','queue_deadline',
 to_char((t+interval '5 minutes') AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'profile',p_profile);
END $$;
REVOKE ALL ON FUNCTION app.e7_accept(uuid,integer,uuid,uuid,uuid,text,text,text,integer,integer,jsonb)
 FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_accept(uuid,integer,uuid,uuid,uuid,text,text,text,integer,integer,jsonb) TO calorie_app_api;

CREATE FUNCTION app.e7_cancel(p_owner uuid,p_generation integer,p_epoch uuid,p_id uuid,p_revision integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE a app.ai_analyses%ROWTYPE; BEGIN
 PERFORM app.e7_context(p_owner,p_generation,p_epoch);
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO a FROM app.ai_analyses WHERE id=p_id AND owner_id=p_owner FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF a.sync_epoch<>p_epoch OR a.generation<>p_generation THEN RETURN jsonb_build_object('error','analysis_context_changed'); END IF;
 IF a.decision_state='confirmed' THEN RETURN jsonb_build_object('error','analysis_already_confirmed'); END IF;
 IF a.decision_state='cancelled' THEN RETURN jsonb_build_object('analysis_id',p_id,'revision',a.revision,'state','failed','decision_state','cancelled','error_code','analysis_cancelled'); END IF;
 IF a.revision<>p_revision THEN RETURN jsonb_build_object('error','proposal_revision_conflict'); END IF;
 IF a.storage_key IS NOT NULL THEN INSERT INTO app.ai_cleanup_intents(storage_key) VALUES(a.storage_key) ON CONFLICT DO NOTHING; END IF;
 UPDATE app.ai_analyses SET state='failed',proposal=NULL,error_code='analysis_cancelled',decision_state='cancelled',revision=revision+1 WHERE id=p_id;
 UPDATE app.ai_photo_consents SET revoked_at=clock_timestamp() WHERE analysis_id=p_id;
 UPDATE app.ai_jobs SET state='failed',phase='completed',fence=gen_random_uuid() WHERE analysis_id=p_id;
 RETURN jsonb_build_object('analysis_id',p_id,'revision',a.revision+1,'state','failed','decision_state','cancelled','error_code','analysis_cancelled');
END $$;
REVOKE ALL ON FUNCTION app.e7_cancel(uuid,integer,uuid,uuid,integer) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_cancel(uuid,integer,uuid,uuid,integer) TO calorie_app_api;

CREATE FUNCTION app.e7_confirm(p_owner uuid,p_generation integer,p_epoch uuid,p_id uuid,p_revision integer,
 p_hash text,p_meal_id uuid,p_response jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE a app.ai_analyses%ROWTYPE; d app.ai_decisions%ROWTYPE; BEGIN
 PERFORM app.e7_context(p_owner,p_generation,p_epoch);
 -- Caller has already locked the catalog and validated exact public choices.
 PERFORM 1 FROM app.community_catalog_state WHERE id=1 FOR SHARE;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO a FROM app.ai_analyses WHERE id=p_id AND owner_id=p_owner FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF a.sync_epoch<>p_epoch OR a.generation<>p_generation THEN RETURN jsonb_build_object('error','analysis_context_changed'); END IF;
 SELECT * INTO d FROM app.ai_decisions WHERE analysis_id=p_id;
 IF FOUND THEN
   IF d.decision_hash=p_hash THEN RETURN d.response; END IF;
   RETURN jsonb_build_object('error','analysis_already_confirmed');
 END IF;
 IF a.state<>'succeeded' OR a.decision_state<>'pending' THEN RETURN jsonb_build_object('error','analysis_not_confirmable'); END IF;
 IF a.revision<>p_revision THEN RETURN jsonb_build_object('error','proposal_revision_conflict'); END IF;
 INSERT INTO app.ai_decisions(analysis_id,owner_id,decision_hash,meal_id,response) VALUES(p_id,p_owner,p_hash,p_meal_id,p_response);
 UPDATE app.ai_analyses SET decision_state='confirmed',revision=revision+1 WHERE id=p_id;
 RETURN p_response;
END $$;
REVOKE ALL ON FUNCTION app.e7_confirm(uuid,integer,uuid,uuid,integer,text,uuid,jsonb)
 FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_confirm(uuid,integer,uuid,uuid,integer,text,uuid,jsonb) TO calorie_app_api;

CREATE FUNCTION app.e7_compensation_intent(p_key text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF p_key IS NULL OR p_key !~ '^[0-9a-f]{32}$' THEN RAISE EXCEPTION 'invalid storage key' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 IF EXISTS(SELECT 1 FROM app.ai_analyses WHERE storage_key=p_key) THEN RETURN false; END IF;
 INSERT INTO app.ai_cleanup_intents(storage_key) VALUES(p_key) ON CONFLICT DO NOTHING;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION app.e7_compensation_intent(text) FROM PUBLIC,calorie_app_api,
 calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_compensation_intent(text) TO calorie_app_api;

CREATE FUNCTION app.e7_compensation_ack(p_key text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 IF EXISTS(SELECT 1 FROM app.ai_analyses WHERE storage_key=p_key) THEN
 RAISE EXCEPTION 'accepted photo requires worker cleanup' USING ERRCODE='23514'; END IF;
 DELETE FROM app.ai_cleanup_intents WHERE storage_key=p_key;
END $$;
REVOKE ALL ON FUNCTION app.e7_compensation_ack(text) FROM PUBLIC,calorie_app_api,
 calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_compensation_ack(text) TO calorie_app_api;
