CREATE OR REPLACE FUNCTION app.e8n_source_lock(p_owner uuid,p_generation integer,p_epoch uuid,p_kind text,p_old_dates date[],p_new_dates date[],p_goal_axis_changed boolean) RETURNS jsonb
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
