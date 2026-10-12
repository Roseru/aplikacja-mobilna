-- Visible source rows with an in-progress xmin were written in this transaction
-- (including its savepoint subtransaction). Other transactions' pending versions
-- cannot be visible in PostgreSQL's ordinary MVCC snapshot. Reconstruct xid8
-- around the current top-level transaction to handle the 32-bit xmin wrap without a durable ticket.
CREATE FUNCTION app.e8n_source_in_transaction(p_xmin xid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE anchor numeric:=pg_current_xact_id()::text::numeric;
 raw numeric:=p_xmin::text::numeric; low numeric:=mod(anchor,4294967296); candidate numeric;
BEGIN
 candidate:=floor(anchor/4294967296)*4294967296+raw;
 IF raw-low>2147483648 THEN candidate:=candidate-4294967296;
 ELSIF low-raw>2147483648 THEN candidate:=candidate+4294967296; END IF;
 RETURN coalesce(pg_xact_status(candidate::text::xid8)='in progress',false);
 EXCEPTION WHEN invalid_parameter_value THEN RETURN false;
END $$;

-- One authoritative lockset: old/new dates cannot omit an affected challenge.
CREATE OR REPLACE FUNCTION app.e8n_source_lock(p_owner uuid,p_generation integer,p_epoch uuid,p_kind text,p_old_dates date[],p_new_dates date[],p_goal_axis_changed boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ids uuid[];c app.nemesis_challenges%ROWTYPE;t timestamptz;result jsonb:='[]';
BEGIN
 IF p_kind IS NULL OR p_kind NOT IN('profile','meal','diary_day','goal','weight','UserProfile','Meal','DiaryDay','GoalVersion','Weight') THEN RAISE EXCEPTION 'unknown Nemesis source kind' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' AND generation=p_generation AND NOT app.subject_blocked(issuer,subject) FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch) THEN RAISE EXCEPTION 'stale Nemesis source context' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
 SELECT array_agg(candidate.id ORDER BY candidate.id) INTO ids FROM app.nemesis_challenges candidate WHERE p_owner IN(candidate.inviter_id,candidate.invitee_id)
 AND candidate.sync_epoch=p_epoch AND candidate.status IN('active','finished') AND candidate.result_status='provisional' AND app.e8n_access(candidate);
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 t:=app.e8n_clock();
 FOR c IN SELECT candidate.* FROM app.nemesis_challenges candidate WHERE candidate.id=ANY(ids)
 AND candidate.status IN('active','finished') AND candidate.result_status='provisional' AND app.e8n_access(candidate) ORDER BY candidate.id LOOP
 IF c.status='active' AND c.end_at>t AND p_kind IN('profile','UserProfile') AND NOT EXISTS(SELECT 1 FROM app.user_profiles WHERE owner_id=p_owner AND deleted_at IS NULL AND time_zone=c.terms->>'time_zone') THEN RAISE EXCEPTION 'Nemesis profile axis is active' USING ERRCODE='23514', CONSTRAINT='e8n_profile_axis_active'; END IF;
 IF p_kind IN('meal','Meal','diary_day','DiaryDay') AND (
 EXISTS(SELECT 1 FROM app.diary_days WHERE owner_id=p_owner AND deleted_at IS NULL AND local_date>=c.start_date AND local_date<c.end_date AND time_zone<>c.terms->>'time_zone') OR
 EXISTS(SELECT 1 FROM app.meals WHERE owner_id=p_owner AND deleted_at IS NULL AND local_date>=c.start_date AND local_date<c.end_date AND time_zone<>c.terms->>'time_zone')) THEN RAISE EXCEPTION 'Nemesis diary axis conflict' USING ERRCODE='23514', CONSTRAINT='e8n_diary_axis_conflict'; END IF;
 result:=result||jsonb_build_array(jsonb_build_object('id',c.id,'status',c.status,'start_date',c.start_date,'end_date',c.end_date,'time_zone',c.terms->>'time_zone','deadline_at',c.deadline_at));
 END LOOP; RETURN result;
END $$;

CREATE FUNCTION app.e8n_source_refresh(p_owner uuid,p_generation integer,p_epoch uuid,p_source jsonb,p_ids uuid[]) RETURNS timestamptz
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE plan jsonb; ids uuid[]; kind text; source_id uuid; actual_revision integer; actual_date date;
 actual_timeline integer; source_xmin xid; counter_xmin xid; pos bigint; old_dates date[]; new_dates date[]; q timestamptz; c app.nemesis_challenges%ROWTYPE;
BEGIN
 IF p_source IS NULL OR jsonb_typeof(p_source)<>'object' OR p_source->>'owner_id' IS DISTINCT FROM p_owner::text
 OR (SELECT count(*) FROM jsonb_object_keys(p_source))<>13
 OR NOT(p_source ?& ARRAY['owner_id','source_kind','entity_id','old_dates','new_dates','old_revision','new_revision','source_position_before','source_position','goal_axis_changed','goal_axis_revision_before','goal_axis_revision','goal_probe_changed'])
 OR jsonb_typeof(p_source->'old_dates') IS DISTINCT FROM 'array'
 OR jsonb_typeof(p_source->'new_dates') IS DISTINCT FROM 'array'
 OR jsonb_typeof(p_source->'goal_axis_changed') IS DISTINCT FROM 'boolean'
 OR jsonb_typeof(p_source->'goal_probe_changed') IS DISTINCT FROM 'boolean'
 OR jsonb_typeof(p_source->'new_revision') IS DISTINCT FROM 'number'
 OR jsonb_typeof(p_source->'source_position_before') IS DISTINCT FROM 'number'
 OR jsonb_typeof(p_source->'source_position') IS DISTINCT FROM 'number'
 THEN RAISE EXCEPTION 'invalid Nemesis source plan' USING ERRCODE='23514'; END IF;
 kind:=p_source->>'source_kind';source_id:=(p_source->>'entity_id')::uuid;
 SELECT array_agg(v::date ORDER BY v::date) INTO old_dates FROM jsonb_array_elements_text(p_source->'old_dates') v;
 SELECT array_agg(v::date ORDER BY v::date) INTO new_dates FROM jsonb_array_elements_text(p_source->'new_dates') v;
 -- Direct EXECUTE takes the same account/counter/all challenge order as Python.
 plan:=app.e8n_source_lock(p_owner,p_generation,p_epoch,kind,old_dates,new_dates,(p_source->>'goal_axis_changed')::boolean);
 SELECT coalesce(array_agg((v->>'id')::uuid ORDER BY (v->>'id')::uuid),'{}'::uuid[]) INTO ids FROM jsonb_array_elements(plan) v;
 IF ids IS DISTINCT FROM p_ids THEN RAISE EXCEPTION 'exact Nemesis lock plan required' USING ERRCODE='23514'; END IF;
 IF kind='meal' THEN SELECT revision,local_date,xmin INTO actual_revision,actual_date,source_xmin FROM app.meals WHERE owner_id=p_owner AND id=source_id;
 ELSIF kind='diary_day' THEN SELECT revision,local_date,xmin INTO actual_revision,actual_date,source_xmin FROM app.diary_days WHERE owner_id=p_owner AND id=source_id;
 ELSIF kind='weight' THEN SELECT revision,local_date,xmin INTO actual_revision,actual_date,source_xmin FROM app.weights WHERE owner_id=p_owner AND id=source_id;
 ELSIF kind='goal' THEN SELECT revision,effective_from,timeline_revision,xmin INTO actual_revision,actual_date,actual_timeline,source_xmin FROM app.goal_versions WHERE owner_id=p_owner AND id=source_id;
 ELSIF kind='profile' THEN SELECT revision,xmin INTO actual_revision,source_xmin FROM app.user_profiles WHERE owner_id=p_owner AND id=source_id;
 ELSE RAISE EXCEPTION 'invalid Nemesis source kind' USING ERRCODE='23514'; END IF;
 SELECT position,xmin INTO pos,counter_xmin FROM app.sync_counters WHERE owner_id=p_owner;
 IF actual_revision IS NULL OR NOT app.e8n_source_in_transaction(source_xmin)
 OR NOT app.e8n_source_in_transaction(counter_xmin) OR actual_revision IS DISTINCT FROM (p_source->>'new_revision')::integer
 OR pos IS DISTINCT FROM (p_source->>'source_position')::bigint
 OR (p_source->>'source_position_before')::bigint IS NULL OR (p_source->>'source_position_before')::bigint<0
 OR (p_source->>'source_position_before')::bigint>=pos
 OR pos-(p_source->>'source_position_before')::bigint NOT BETWEEN 1 AND 2
 OR EXISTS(SELECT 1 FROM app.sync_changes WHERE owner_id=p_owner AND position>(p_source->>'source_position_before')::bigint
  AND position<=pos AND NOT app.e8n_source_in_transaction(xmin))
 OR (actual_revision>1 AND (p_source->>'old_revision')::integer IS DISTINCT FROM actual_revision-1)
 OR (actual_revision=1 AND p_source->>'old_revision' IS NOT NULL)
 OR actual_date IS NOT NULL AND NOT coalesce(actual_date=ANY(new_dates),false)
 OR (kind='goal') IS DISTINCT FROM (p_source->>'goal_axis_changed')::boolean
 OR (kind='goal' AND (actual_timeline IS DISTINCT FROM (p_source->>'goal_axis_revision')::integer
 OR actual_timeline-1 IS DISTINCT FROM (p_source->>'goal_axis_revision_before')::integer))
 OR NOT EXISTS(SELECT 1 FROM app.sync_changes WHERE owner_id=p_owner AND position=pos
   AND entity->>'entity_id'=source_id::text AND entity->>'entity_type'=kind AND (entity->>'revision')::integer=actual_revision AND app.e8n_source_in_transaction(xmin))
 THEN RAISE EXCEPTION 'source revision or position mismatch' USING ERRCODE='23514'; END IF;
 -- Missing required projector never ACKs source, even while activation is closed.
 -- A complete sparse refresh prevents raw EXECUTE from narrowing old source dates.
 -- e8_refresh performs bounded date batches and returns exactly one DB q.
 q:=app.e8_refresh(p_owner,NULL);
 IF q IS NULL THEN RAISE EXCEPTION 'Nemesis source qualification unavailable' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT 1 FROM app.nemesis_challenges candidate WHERE candidate.id=ANY(ids) AND candidate.result_status='provisional'
   AND q<=candidate.deadline_at AND (NOT app.e8n_seed_ready(candidate) OR NOT app.e8n_runtime_ready()))
 THEN RAISE EXCEPTION 'Nemesis projector unavailable' USING ERRCODE='55000'; END IF;
 FOR c IN SELECT * FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id LOOP
 IF c.result_status='provisional' AND q<=c.deadline_at THEN
 PERFORM app.e8n_write_projection(c.id,p_owner,CASE WHEN c.inviter_id=p_owner THEN 'inviter' ELSE 'invitee' END,q);
 UPDATE app.nemesis_projection_seeds SET read_revision=read_revision+1 WHERE challenge_id=c.id;
 END IF; END LOOP;
 RETURN q;
END $$;
