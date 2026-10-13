CREATE FUNCTION app.e9_apply(p_owner uuid,p_source uuid,p_value numeric,p_source_kind text,p_audit jsonb,p_replace uuid DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE axis app.energy_axes%ROWTYPE;zone text;t timestamptz;day date;v uuid:=gen_random_uuid();scheduled uuid;ids uuid[];c app.nemesis_challenges%ROWTYPE;q timestamptz;a app.energy_analyses%ROWTYPE;previous uuid;
BEGIN
 SELECT * INTO axis FROM app.energy_axes WHERE owner_id=p_owner FOR UPDATE;
 SELECT time_zone INTO zone FROM app.user_profiles WHERE owner_id=p_owner AND deleted_at IS NULL;
 IF zone IS NULL THEN RETURN jsonb_build_object('error','profile_required');END IF;
 -- Account and sync counter are held by every caller, before all challenge locks.
 SELECT array_agg(id ORDER BY id) INTO ids FROM app.nemesis_challenges WHERE p_owner IN(inviter_id,invitee_id)
 AND status IN('active','finished') AND result_status='provisional';
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 t:=clock_timestamp();day:=(t AT TIME ZONE zone)::date+1;
 IF p_source_kind<>'revert' THEN
 SELECT * INTO a FROM app.energy_analyses WHERE owner_id=p_owner AND id=p_source;
 IF NOT FOUND OR a.state<>'ready' THEN RETURN jsonb_build_object('error','analysis_not_ready');END IF;
 IF t>=a.expires_at THEN RETURN jsonb_build_object('error','proposal_expired');END IF;
 IF app.e9_stale(a) THEN RETURN jsonb_build_object('error','analysis_context_changed');END IF;
 END IF;
 SELECT e.id INTO scheduled FROM app.energy_versions e WHERE e.owner_id=p_owner AND e.effective_from=day
 AND NOT EXISTS(SELECT 1 FROM app.energy_versions n WHERE n.owner_id=p_owner AND n.supersedes=e.id);
 IF scheduled IS NOT NULL AND scheduled IS DISTINCT FROM p_replace THEN
 RETURN jsonb_build_object('error','energy_scheduled_conflict');END IF;
 IF p_replace IS NOT NULL AND p_replace IS DISTINCT FROM scheduled THEN RETURN jsonb_build_object('error','version_conflict');END IF;
 IF p_source_kind<>'revert' AND axis.last_applied_at>t-interval '336 hours' THEN RETURN jsonb_build_object('error','energy_apply_cooldown');END IF;
 previous:=coalesce(p_replace,(app.e9_resolve(p_owner,(t AT TIME ZONE zone)::date)).id);
 UPDATE app.energy_axes SET revision=revision+1,last_applied_at=t WHERE owner_id=p_owner RETURNING * INTO axis;
 INSERT INTO app.energy_versions(id,owner_id,revision,effective_from,maintenance_kcal,method,source,source_id,supersedes,decided_at,audit)
 VALUES(v,p_owner,axis.revision,day,p_value,CASE WHEN p_source_kind='revert' THEN 'energy_revert_v1' ELSE 'energy_adjustment_v1' END,
 p_source_kind,p_source,previous,t,p_audit||jsonb_build_object('previous_id',previous,
 'baseline_id_before',axis.baseline_id,'sync_epoch',(SELECT sync_epoch FROM app.installation_state WHERE id=1),
 'consent_revision',(SELECT revision FROM app.user_consents WHERE owner_id=p_owner)));
 UPDATE app.sync_counters SET position=position+1 WHERE owner_id=p_owner;
 INSERT INTO app.sync_changes(owner_id,position,entity,created_at)
 SELECT p_owner,position,NULL,t FROM app.sync_counters WHERE owner_id=p_owner;
 INSERT INTO app.energy_changes(owner_id,position,version_id)
 SELECT p_owner,position,v FROM app.sync_counters WHERE owner_id=p_owner;
 IF p_source_kind<>'automatic' THEN
 UPDATE app.energy_axes SET baseline_id=v,baseline_epoch=(SELECT sync_epoch FROM app.installation_state WHERE id=1),
 baseline_consent_revision=(SELECT revision FROM app.user_consents WHERE owner_id=p_owner) WHERE owner_id=p_owner;
 END IF;
 -- Dedicated source-authoritative energy hook: the version/counter were inserted
 -- in this transaction; all provisional challenges are already locked. No points
 -- or motivation refresh is needed because their goal axis is unchanged.
 IF NOT app.e8n_source_in_transaction((SELECT xmin FROM app.energy_versions WHERE id=v))
 OR NOT app.e8n_source_in_transaction((SELECT xmin FROM app.sync_counters WHERE owner_id=p_owner))
 THEN RAISE EXCEPTION 'energy source qualification missing' USING ERRCODE='23514';END IF;
 q:=app.e8n_clock();
 FOR c IN SELECT * FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id LOOP
 IF q<=c.deadline_at AND c.result_status='provisional' AND app.e8n_access(c) THEN
 IF NOT app.e8n_seed_ready(c) OR NOT app.e8n_runtime_ready() THEN RAISE EXCEPTION 'energy projector unavailable' USING ERRCODE='55000';END IF;
 PERFORM app.e8n_write_projection(c.id,p_owner,CASE WHEN c.inviter_id=p_owner THEN 'inviter' ELSE 'invitee' END,q);
 UPDATE app.nemesis_projection_seeds SET read_revision=read_revision+1 WHERE challenge_id=c.id;
 END IF;END LOOP;
 RETURN app.e9_entity(v);
END $$;

CREATE FUNCTION app.e9_mutate(p_owner uuid,p_generation integer,p_epoch uuid,p_key uuid,p_kind text,p_body jsonb,p_profile jsonb DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE r app.energy_receipts%ROWTYPE;axis app.energy_axes%ROWTYPE;a app.energy_analyses%ROWTYPE;
 hash text;response jsonb;context jsonb;result jsonb;t timestamptz;today date;zone text;new_id uuid;job_id uuid;
 value numeric;version app.energy_versions%ROWTYPE;auto boolean;
BEGIN
 PERFORM app.e7_context(p_owner,p_generation,p_epoch);
 IF EXISTS(SELECT 1 FROM app.user_accounts WHERE id=p_owner AND app.subject_blocked(issuer,subject)) THEN RETURN jsonb_build_object('error','account_deleting');END IF;
 INSERT INTO app.sync_counters(owner_id) VALUES(p_owner) ON CONFLICT DO NOTHING;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch FOR SHARE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','analysis_context_changed');END IF;
 hash:=app.e9_fingerprint(jsonb_build_object('kind',p_kind,'body',p_body));
 SELECT * INTO r FROM app.energy_receipts WHERE owner_id=p_owner AND key=p_key;
 IF FOUND THEN
 IF r.generation<>p_generation OR r.sync_epoch<>p_epoch THEN RETURN jsonb_build_object('error','analysis_context_changed');END IF;
 IF r.request_hash<>hash THEN RETURN jsonb_build_object('error','idempotency_key_reused');END IF;
 IF r.response IS NULL THEN RETURN jsonb_build_object('error','idempotency_result_expired');END IF;
 RETURN r.response;END IF;
 IF NOT app.e7_admit(p_owner,'receipts') THEN RETURN jsonb_build_object('error','ai_user_quota_exhausted');END IF;
 INSERT INTO app.energy_axes(owner_id) VALUES(p_owner) ON CONFLICT DO NOTHING;
 SELECT * INTO axis FROM app.energy_axes WHERE owner_id=p_owner FOR UPDATE;
 IF axis.revision IS DISTINCT FROM (p_body->>'axis_revision')::integer THEN RETURN jsonb_build_object('error','energy_axis_conflict');END IF;
 SELECT time_zone INTO zone FROM app.user_profiles WHERE owner_id=p_owner AND deleted_at IS NULL;
 IF zone IS NULL THEN RETURN jsonb_build_object('error','profile_required');END IF;
 t:=clock_timestamp();today:=(t AT TIME ZONE zone)::date;
 IF p_kind='create' THEN
 IF NOT app.e9_notice_valid(p_body->'notice',p_body#>>'{notice,provider}','this_energy_analysis')
 THEN RETURN jsonb_build_object('error','energy_notice_required');END IF;
 auto:=false;
 context:=app.e9_context(p_owner,today-14,today-1);result:=app.e9_rules(context,auto);
 IF result->>'state' IN('insufficient_data','energy_history_unavailable','baseline_required','baseline_range_conflict') THEN
 response:=jsonb_build_object('state',result->>'state','result',result,'id',NULL,'revision',NULL);
 ELSE
 IF p_profile IS NOT NULL AND p_body#>>'{notice,provider}' IS DISTINCT FROM p_profile->>'provider'
 THEN RETURN jsonb_build_object('error','energy_notice_provider_mismatch');END IF;
 IF p_profile IS NULL OR NOT EXISTS(SELECT 1 FROM app.ai_controls WHERE id=1 AND dispatch_open AND sync_epoch=p_epoch) THEN RETURN jsonb_build_object('error','ai_unavailable');END IF;
 IF NOT EXISTS(SELECT 1 FROM app.ai_pools WHERE scope=p_profile->>'pool_scope' AND enabled AND provider=p_profile->>'provider' AND model=p_profile->>'model') THEN RETURN jsonb_build_object('error','ai_unavailable');END IF;
 IF EXISTS(SELECT 1 FROM app.ai_jobs WHERE owner_id=p_owner AND state IN('queued','running')) THEN RETURN jsonb_build_object('error','ai_active_job');END IF;
 IF NOT app.e7_admit(p_owner,'energy_adjustment') THEN RETURN jsonb_build_object('error','energy_analysis_cooldown');END IF;
 new_id:=gen_random_uuid();job_id:=gen_random_uuid();
 INSERT INTO app.energy_analyses(id,owner_id,generation,sync_epoch,automatic,accepted_at,date_from,date_to,context,fingerprint,profile,notice,result,state)
 VALUES(new_id,p_owner,p_generation,p_epoch,auto,t,today-14,today-1,context,app.e9_fingerprint(context),p_profile,
 app.e9_notice_snapshot(p_body->'notice',context,t,NULL),result,'queued');
 INSERT INTO app.ai_jobs(id,owner_id,energy_analysis_id,purpose,generation,sync_epoch,pool_scope,state,queue_deadline,next_attempt_at)
 VALUES(job_id,p_owner,new_id,'energy_adjustment',p_generation,p_epoch,p_profile->>'pool_scope','queued',t+interval '5 minutes',t);
 response:=app.e9_analysis_read(p_owner,new_id);
 END IF;
 ELSIF p_kind IN('accept','reject') THEN
 SELECT * INTO a FROM app.energy_analyses WHERE owner_id=p_owner AND id=(p_body->>'id')::uuid FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found');END IF;
 IF a.revision IS DISTINCT FROM (p_body->>'revision')::integer THEN RETURN jsonb_build_object('error','version_conflict');END IF;
 IF a.generation<>p_generation OR a.sync_epoch<>p_epoch THEN RETURN jsonb_build_object('error','analysis_context_changed');END IF;
 IF p_kind='reject' THEN
 IF a.state IN('accepted','rejected') THEN RETURN jsonb_build_object('error','analysis_decided');END IF;
 UPDATE app.energy_analyses SET state='rejected',revision=revision+1,
 notice=notice||jsonb_build_object('revoked_at',app.e8n_utc(t)) WHERE id=a.id;
 UPDATE app.ai_jobs SET state='failed',phase='completed',fence=gen_random_uuid() WHERE energy_analysis_id=a.id AND state IN('queued','running');
 response:=app.e9_analysis_read(p_owner,a.id);
 ELSE
 IF a.state<>'ready' THEN RETURN jsonb_build_object('error','analysis_not_ready');END IF;
 IF p_profile IS NULL OR a.profile IS DISTINCT FROM p_profile THEN RETURN jsonb_build_object('error','analysis_context_changed');END IF;
 IF t>=a.expires_at THEN RETURN jsonb_build_object('error','proposal_expired');END IF;
 IF app.e9_stale(a) THEN RETURN jsonb_build_object('error','analysis_context_changed');END IF;
 response:=app.e9_apply(p_owner,a.id,(a.result->>'proposed')::numeric,'manual',
 jsonb_build_object('analysis_id',a.id,'rules',a.result,'explanation',a.explanation,'decider','owner'));
 IF NOT(response ? 'error') THEN UPDATE app.energy_analyses SET state='accepted',revision=revision+1 WHERE id=a.id;END IF;
 END IF;
 ELSIF p_kind IN('affirm','revert') THEN
 SELECT * INTO version FROM app.energy_versions WHERE owner_id=p_owner AND id=(p_body->>'id')::uuid;
 IF NOT FOUND THEN RETURN jsonb_build_object('error','not_found');END IF;
 IF p_kind='affirm' THEN
 IF p_profile IS NULL OR NOT app.e9_notice_valid(p_body->'notice',p_profile->>'provider','automatic_energy_adjustment')
 THEN RETURN jsonb_build_object('error','energy_notice_required');END IF;
 IF version.id IS DISTINCT FROM(app.e9_resolve(p_owner,today)).id THEN RETURN jsonb_build_object('error','version_conflict');END IF;
 IF NOT EXISTS(SELECT 1 FROM app.user_consents WHERE owner_id=p_owner AND automatic_energy_adjustment AND revision=(p_body->>'consent_revision')::integer) THEN RETURN jsonb_build_object('error','energy_consent_required');END IF;
 UPDATE app.energy_axes SET baseline_id=version.id,baseline_epoch=p_epoch,baseline_consent_revision=(p_body->>'consent_revision')::integer,
 baseline_notice=app.e9_notice_snapshot(p_body->'notice',app.e9_context(p_owner,today-14,today-1),t,version.id)
 WHERE owner_id=p_owner;
 response:=jsonb_build_object('baseline_id',version.id,'axis_revision',axis.revision);
 ELSE
 IF version.effective_from>today THEN RETURN jsonb_build_object('error','energy_revert_future_version');END IF;
 response:=app.e9_apply(p_owner,p_key,version.maintenance_kcal,'revert',
 jsonb_build_object('restored_id',version.id,'decider','owner'),(p_body->>'replace_id')::uuid);
 END IF;
 ELSE RAISE EXCEPTION 'invalid energy operation' USING ERRCODE='22023';END IF;
 IF response ? 'error' THEN RETURN response;END IF;
 INSERT INTO app.energy_receipts(owner_id,key,request_hash,generation,sync_epoch,response,result_minimal)
 VALUES(p_owner,p_key,hash,p_generation,p_epoch,response,
 jsonb_build_object('id',coalesce(response->'entity_id',response->'id'),'revision',response->'revision','kind',p_kind));
 RETURN response;
END $$;

CREATE FUNCTION app.e9_append_legacy_change(p_owner uuid,p_id uuid,p_position bigint) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM app.energy_versions WHERE owner_id=p_owner AND id=p_id AND source='legacy'
 AND app.e8n_source_in_transaction(xmin)) THEN RETURN false;END IF;
 IF NOT EXISTS(SELECT 1 FROM app.sync_counters WHERE owner_id=p_owner AND position=p_position AND app.e8n_source_in_transaction(xmin))
 OR NOT EXISTS(SELECT 1 FROM app.sync_changes WHERE owner_id=p_owner AND position=p_position
 AND entity->>'entity_type'='goal' AND entity->>'entity_id'=p_id::text AND app.e8n_source_in_transaction(xmin))
 THEN RAISE EXCEPTION 'legacy energy requires authoritative goal ChangeLog' USING ERRCODE='23514';END IF;
 UPDATE app.sync_counters SET position=position+1 WHERE owner_id=p_owner;
 INSERT INTO app.sync_changes(owner_id,position,entity,created_at)
 SELECT p_owner,position,NULL,clock_timestamp() FROM app.sync_counters WHERE owner_id=p_owner;
 INSERT INTO app.energy_changes(owner_id,position,version_id)
 SELECT p_owner,position,p_id FROM app.sync_counters WHERE owner_id=p_owner;
 RETURN true;
END $$;
