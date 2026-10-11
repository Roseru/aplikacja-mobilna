CREATE FUNCTION app.e8n_read(p_issuer text,p_subject text,p_epoch uuid,p_id uuid DEFAULT NULL,p_limit integer DEFAULT 30,p_cursor text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE a app.user_accounts%ROWTYPE;c app.nemesis_challenges%ROWTYPE;cur app.nemesis_cursors%ROWTYPE;
 t timestamptz; items jsonb:='[]'; anchor_time timestamptz;anchor_uuid uuid;next_token uuid;
BEGIN
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN RETURN app.e8n_error(422,'invalid_request'); END IF;
 a:=app.e8n_context(p_issuer,p_subject,p_epoch);IF a.id IS NULL THEN RETURN app.e8n_error(409,'account_context_unavailable'); END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=a.id AND state='active' AND generation=a.generation FOR UPDATE;
 IF NOT FOUND OR app.subject_blocked(p_issuer,p_subject) THEN RETURN app.e8n_error(409,'account_context_unavailable'); END IF;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=a.id FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch) THEN RETURN app.e8n_error(409,'sync_epoch_changed'); END IF;
 IF p_id IS NOT NULL THEN
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=p_id AND a.id IN(inviter_id,invitee_id) FOR UPDATE;
 t:=app.e8n_clock();
 IF c.id IS NULL OR NOT app.e8n_access(c) THEN RETURN app.e8n_error(404,'nemesis_not_found'); END IF;
 RETURN jsonb_build_object('ok',true,'http_status',200,'code','accepted','response',app.e8n_metadata(c,a.id,t),'replayed',false);
 END IF;
 t:=app.e8n_clock();
 IF p_cursor IS NOT NULL THEN
 BEGIN SELECT * INTO cur FROM app.nemesis_cursors WHERE token=p_cursor::uuid; EXCEPTION WHEN invalid_text_representation THEN RETURN app.e8n_error(409,'nemesis_cursor_unavailable'); END;
 IF cur.token IS NULL OR cur.requester_id<>a.id OR cur.generation<>a.generation OR cur.sync_epoch<>p_epoch OR cur.expires_at<=t THEN RETURN app.e8n_error(409,'nemesis_cursor_unavailable'); END IF;
 END IF;
 -- A bounded live page, never a cached partner response or globally capped history.
 FOR c IN SELECT * FROM app.nemesis_challenges n WHERE a.id IN(inviter_id,invitee_id) AND app.e8n_access(n) AND
 (cur.token IS NULL OR (n.created_at,n.id)<(cur.anchor_created_at,cur.anchor_id)) ORDER BY created_at DESC,id DESC LIMIT p_limit+1 LOOP
 IF jsonb_array_length(items)=p_limit THEN
 DELETE FROM app.nemesis_cursors WHERE token IN(SELECT token FROM app.nemesis_cursors WHERE requester_id=a.id ORDER BY expires_at,token LIMIT greatest(0,(SELECT count(*)::integer FROM app.nemesis_cursors WHERE requester_id=a.id)-7));
 INSERT INTO app.nemesis_cursors(requester_id,generation,sync_epoch,anchor_created_at,anchor_id,expires_at) VALUES(a.id,a.generation,p_epoch,anchor_time,anchor_uuid,t+interval '15 minutes') RETURNING token INTO next_token; EXIT;
 END IF;
 items:=items||jsonb_build_array(app.e8n_metadata(c,a.id,t));anchor_time:=c.created_at;anchor_uuid:=c.id;
 END LOOP;
 RETURN jsonb_build_object('ok',true,'http_status',200,'code','accepted','response',jsonb_build_object('items',items,'next_cursor',next_token),'replayed',false);
END $$;
CREATE FUNCTION app.e8n_statistics(p_issuer text,p_subject text,p_epoch uuid,p_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE own jsonb;
BEGIN
 own:=app.e8n_read(p_issuer,p_subject,p_epoch,p_id);
 IF NOT (own->>'ok')::boolean THEN RETURN own; END IF;
 IF NOT app.e8n_gate() THEN RETURN app.e8n_error(503,'nemesis_activation_unavailable'); END IF;
 -- No projector/finalizer or fabricated aggregate is provided by E8.3.
 RETURN app.e8n_error(503,'nemesis_statistics_unavailable');
END $$;
CREATE FUNCTION app.e8n_maintain(p_batch integer DEFAULT 100) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ids uuid[]; t timestamptz; transitioned integer; cleaned integer;
BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'invalid Nemesis batch' USING ERRCODE='22023'; END IF;
 SELECT array_agg(id ORDER BY id) INTO ids FROM(SELECT id FROM app.nemesis_challenges WHERE status IN('invited','active') AND (expires_at<=app.e8n_clock() OR end_at<=app.e8n_clock()) ORDER BY id LIMIT p_batch) q;
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 t:=app.e8n_clock();
 UPDATE app.nemesis_challenges SET status=CASE WHEN status='invited' THEN 'cancelled' ELSE 'finished' END,cancel_reason=CASE WHEN status='invited' THEN 'expired' ELSE NULL END,revision=revision+1
 WHERE id=ANY(ids) AND ((status='invited' AND expires_at<=t) OR(status='active' AND end_at<=t));GET DIAGNOSTICS transitioned=ROW_COUNT;
 DELETE FROM app.nemesis_slots s USING app.nemesis_challenges c WHERE s.challenge_id=c.id AND c.id=ANY(ids) AND c.status<>'active';
 WITH q AS(SELECT owner_id,operation,key FROM app.nemesis_receipts WHERE response IS NOT NULL AND response_expires_at<=t ORDER BY response_expires_at,owner_id,operation,key LIMIT p_batch)
 UPDATE app.nemesis_receipts r SET response=NULL FROM q WHERE (r.owner_id,r.operation,r.key)=(q.owner_id,q.operation,q.key);GET DIAGNOSTICS cleaned=ROW_COUNT;
 DELETE FROM app.nemesis_cursors WHERE token IN(SELECT token FROM app.nemesis_cursors WHERE expires_at<=t ORDER BY expires_at,token LIMIT p_batch);
 -- Expired digest rows contain no replay authority; minimal receipts are never removed.
 DELETE FROM app.nemesis_share_codes WHERE owner_id IN(SELECT owner_id FROM app.nemesis_share_codes WHERE expires_at<=t ORDER BY expires_at,owner_id LIMIT p_batch);
 RETURN jsonb_build_object('transitioned',transitioned,'responses_pruned',cleaned);
END $$;
CREATE FUNCTION app.e8n_restore_cancel(p_batch integer DEFAULT 100) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ids uuid[];n integer;
BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'invalid Nemesis batch' USING ERRCODE='22023'; END IF;
 IF (SELECT sync_epoch FROM app.nemesis_control WHERE id=1)=(SELECT sync_epoch FROM app.installation_state WHERE id=1) THEN RAISE EXCEPTION 'restore requires fenced new epoch' USING ERRCODE='23514'; END IF;
 SELECT array_agg(id ORDER BY id) INTO ids FROM(SELECT id FROM app.nemesis_challenges WHERE status<>'cancelled' ORDER BY id LIMIT p_batch) q;
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 UPDATE app.nemesis_challenges SET status='cancelled',cancel_reason='restore',revision=revision+1 WHERE id=ANY(ids) AND status<>'cancelled';GET DIAGNOSTICS n=ROW_COUNT;
 DELETE FROM app.nemesis_slots WHERE challenge_id=ANY(ids);
 RETURN n;
END $$;
CREATE FUNCTION app.e8n_delete_helper(p_owner uuid,p_operation uuid,p_purge boolean DEFAULT false) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ids uuid[];j app.account_deletion_jobs%ROWTYPE;
BEGIN
 SELECT * INTO j FROM app.account_deletion_jobs WHERE account_id=p_owner AND operation_id=p_operation;
 IF j.account_id IS NULL OR NOT EXISTS(SELECT 1 FROM app.user_accounts WHERE id=p_owner AND state='deleting' AND generation=j.deleting_generation) OR NOT EXISTS(SELECT 1 FROM app.deleted_subjects WHERE operation_id=p_operation AND issuer=j.issuer AND subject=j.subject) THEN RAISE EXCEPTION 'exact deletion context required' USING ERRCODE='23514'; END IF;
 -- Caller wrapper already owns account/counter. Never acquire peer account here.
 SELECT array_agg(id ORDER BY id) INTO ids FROM app.nemesis_challenges WHERE p_owner IN(inviter_id,invitee_id);
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 UPDATE app.nemesis_challenges SET status='cancelled',cancel_reason='deleted',revision=revision+1 WHERE id=ANY(ids) AND status<>'cancelled';
 DELETE FROM app.nemesis_slots WHERE challenge_id=ANY(ids);
 IF p_purge THEN
 IF j.identity_confirmed_at IS NULL OR NOT app.deletion_purge_authorized(p_owner) THEN RAISE EXCEPTION 'confirmed purge context required' USING ERRCODE='23514'; END IF;
 -- Clear all private receipt snapshots of this participant, including peer replies.
 UPDATE app.nemesis_receipts SET response=NULL WHERE entity_id=ANY(ids) AND response IS NOT NULL;
 DELETE FROM app.nemesis_receipts WHERE owner_id=p_owner;DELETE FROM app.nemesis_admissions WHERE owner_id=p_owner;
 DELETE FROM app.nemesis_share_codes WHERE owner_id=p_owner;DELETE FROM app.nemesis_cursors WHERE requester_id=p_owner;
 DELETE FROM app.nemesis_challenges WHERE (inviter_id=p_owner AND invitee_id IS NULL) OR(invitee_id=p_owner AND inviter_id IS NULL);
 UPDATE app.nemesis_challenges SET inviter_id=CASE WHEN inviter_id=p_owner THEN NULL ELSE inviter_id END,invitee_id=CASE WHEN invitee_id=p_owner THEN NULL ELSE invitee_id END,cancel_reason='deleted',revision=revision+1 WHERE id=ANY(ids);
 DELETE FROM app.nemesis_challenges WHERE inviter_id IS NULL AND invitee_id IS NULL;
 END IF;
END $$;
CREATE FUNCTION app.e8n_source_lock(p_owner uuid,p_generation integer,p_epoch uuid,p_kind text,p_old_dates date[],p_new_dates date[],p_goal_axis_changed boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ids uuid[];c app.nemesis_challenges%ROWTYPE;t timestamptz;result jsonb:='[]';
BEGIN
 IF p_kind IS NULL OR p_kind NOT IN('profile','meal','diary_day','goal','weight','UserProfile','Meal','DiaryDay','GoalVersion','Weight') THEN RAISE EXCEPTION 'unknown Nemesis source kind' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' AND generation=p_generation AND NOT app.subject_blocked(issuer,subject) FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch) THEN RAISE EXCEPTION 'stale Nemesis source context' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
 SELECT array_agg(id ORDER BY id) INTO ids FROM app.nemesis_challenges WHERE p_owner IN(inviter_id,invitee_id) AND sync_epoch=p_epoch AND status IN('active','finished') AND
 (p_kind IN('profile','UserProfile','weight','Weight') OR p_goal_axis_changed OR EXISTS(SELECT 1 FROM unnest(coalesce(p_old_dates,'{}')||coalesce(p_new_dates,'{}')) d WHERE d>=start_date AND d<end_date));
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;t:=app.e8n_clock();
 FOR c IN SELECT * FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id LOOP
 IF c.status='active' AND c.end_at>t AND p_kind IN('profile','UserProfile') AND NOT EXISTS(SELECT 1 FROM app.user_profiles WHERE owner_id=p_owner AND deleted_at IS NULL AND time_zone=c.terms->>'time_zone') THEN RAISE EXCEPTION 'Nemesis profile axis is active' USING ERRCODE='23514'; END IF;
 IF p_kind IN('meal','Meal','diary_day','DiaryDay') AND (
 EXISTS(SELECT 1 FROM app.diary_days WHERE owner_id=p_owner AND deleted_at IS NULL AND local_date>=c.start_date AND local_date<c.end_date AND local_date=ANY(coalesce(p_old_dates,'{}')||coalesce(p_new_dates,'{}')) AND time_zone<>c.terms->>'time_zone') OR
 EXISTS(SELECT 1 FROM app.meals WHERE owner_id=p_owner AND deleted_at IS NULL AND local_date>=c.start_date AND local_date<c.end_date AND local_date=ANY(coalesce(p_old_dates,'{}')||coalesce(p_new_dates,'{}')) AND time_zone<>c.terms->>'time_zone')) THEN RAISE EXCEPTION 'Nemesis diary axis conflict' USING ERRCODE='23514'; END IF;
 result:=result||jsonb_build_array(jsonb_build_object('id',c.id,'status',c.status,'start_date',c.start_date,'end_date',c.end_date,'time_zone',c.terms->>'time_zone','deadline_at',c.deadline_at));
 END LOOP;RETURN result;
END $$;
