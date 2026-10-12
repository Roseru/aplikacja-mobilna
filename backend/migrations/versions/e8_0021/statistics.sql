-- Signed percentages are emitted once, after aggregation, with canonical scale.
CREATE FUNCTION app.e8n_percent_text(p numeric) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$
 SELECT CASE WHEN p IS NULL THEN NULL WHEN round(p,12)=0 THEN '0'
 WHEN position('.' IN round(p,12)::text)>0 THEN rtrim(rtrim(round(p,12)::text,'0'),'.')
 ELSE round(p,12)::text END
$$;

-- Private helper: exclusively immutable accepted terms and durable projections.
CREATE FUNCTION app.e8n_aggregate_projection(p_id uuid,p_role text,p_at timestamptz)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE regularity jsonb; weight_metric jsonb; deficit_metric jsonb;
 scope jsonb; observed integer; eligible integer; first_day date; last_day date;
 first_weight numeric; last_weight numeric; deficit numeric;
BEGIN
 SELECT terms->'scope' INTO scope FROM app.nemesis_challenges WHERE id=p_id;
 IF scope IS NULL OR p_role IS NULL OR p_role NOT IN('inviter','invitee') OR p_at IS NULL THEN
  RAISE EXCEPTION 'invalid projection aggregate context' USING ERRCODE='23514';
 END IF;
 SELECT jsonb_build_object('points',coalesce(sum(candidate_points),0),
  'closed_days',count(*),'complete_days',count(*) FILTER(WHERE effective_complete),
  'days_in_goal',count(*) FILTER(WHERE in_goal IS TRUE)) INTO regularity
 FROM app.nemesis_day_projections
 WHERE challenge_id=p_id AND participant_role=p_role AND matures_at<=p_at;
 IF scope->'weight_change'='true'::jsonb THEN
  SELECT count(*),(array_agg(local_date ORDER BY local_date))[1],
   (array_agg(local_date ORDER BY local_date DESC))[1],
   (array_agg(weight_kg ORDER BY local_date))[1],
   (array_agg(weight_kg ORDER BY local_date DESC))[1]
  INTO observed,first_day,last_day,first_weight,last_weight
  FROM app.nemesis_day_projections WHERE challenge_id=p_id AND participant_role=p_role
   AND matures_at<=p_at AND weight_kg IS NOT NULL;
  IF observed<2 THEN weight_metric:=jsonb_build_object('state','insufficient_data','value',NULL,'observed_days',observed);
  ELSE weight_metric:=jsonb_build_object('state','available','value',
   app.e8n_percent_text(100*(last_weight-first_weight)/(first_weight*1.000000000000000000000000000000000000000000000000000000000000)),
   'observed_days',observed,'first_date',first_day,'last_date',last_day); END IF;
 ELSE weight_metric:=jsonb_build_object('state','hidden'); END IF;
 IF scope->'mean_deficit'='true'::jsonb THEN
  SELECT count(*),avg(100*(maintenance_kcal-intake_kcal)/
   (maintenance_kcal*1.000000000000000000000000000000000000000000000000000000000000))
  INTO eligible,deficit FROM app.nemesis_day_projections
  WHERE challenge_id=p_id AND participant_role=p_role AND matures_at<=p_at
   AND effective_complete AND maintenance_kcal>0;
  IF eligible=0 THEN deficit_metric:=jsonb_build_object('state','insufficient_data','value',NULL,'eligible_days',0);
  ELSE deficit_metric:=jsonb_build_object('state','available','value',app.e8n_percent_text(deficit),'eligible_days',eligible); END IF;
 ELSE deficit_metric:=jsonb_build_object('state','hidden'); END IF;
 RETURN jsonb_build_object('regularity',regularity,'weight_change',weight_metric,'mean_deficit',deficit_metric);
END $$;

CREATE OR REPLACE FUNCTION app.e8n_statistics(p_issuer text,p_subject text,p_epoch uuid,p_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE a app.user_accounts%ROWTYPE; c app.nemesis_challenges%ROWTYPE;
 seed app.nemesis_projection_seeds%ROWTYPE; own_role text; other_role text;
 t timestamptz; response jsonb; own jsonb; opponent jsonb; result_state text;
 closed integer; result_revision bigint; own_points bigint; opponent_points bigint;
BEGIN
 a:=app.e8n_context(p_issuer,p_subject,p_epoch);
 IF a.id IS NULL THEN RETURN app.e8n_error(404,'nemesis_not_found'); END IF;
 -- Discover bindings without locking the HTTP caller first. Both accounts
 -- are locked globally before the challenge, matching accept/source/deletion.
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=p_id;
 IF c.id IS NULL OR NOT coalesce(a.id IN(c.inviter_id,c.invitee_id),false) THEN
  RETURN app.e8n_error(404,'nemesis_not_found'); END IF;
 PERFORM 1 FROM app.user_accounts WHERE id IN(c.inviter_id,c.invitee_id) ORDER BY id FOR SHARE;
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=p_id FOR SHARE;
 IF c.id IS NULL OR NOT coalesce(a.id IN(c.inviter_id,c.invitee_id),false)
  OR c.status NOT IN('active','finished') OR c.accepted_at IS NULL
  OR c.sync_epoch IS DISTINCT FROM p_epoch OR NOT app.e8n_access(c)
  OR NOT EXISTS(SELECT 1 FROM app.nemesis_control WHERE id=1 AND sync_epoch=p_epoch)
 THEN RETURN app.e8n_error(404,'nemesis_not_found'); END IF;
 IF NOT app.e8n_gate() THEN RETURN app.e8n_error(503,'nemesis_activation_unavailable'); END IF;
 IF NOT app.e8n_seed_ready(c) THEN RETURN app.e8n_error(503,'nemesis_statistics_unavailable'); END IF;
 SELECT * INTO seed FROM app.nemesis_projection_seeds WHERE challenge_id=c.id;
 own_role:=CASE WHEN a.id=c.inviter_id THEN 'inviter' ELSE 'invitee' END;
 other_role:=CASE WHEN own_role='inviter' THEN 'invitee' ELSE 'inviter' END;
 t:=app.e8n_clock();
 SELECT count(*) INTO closed FROM app.nemesis_day_projections
  WHERE challenge_id=c.id AND participant_role=own_role AND matures_at<=t;
 result_revision:=(seed.read_revision-1)*91+closed+1;
 response:=jsonb_build_object('id',c.id,'revision',result_revision,'rule_version','regularity_v1',
  'as_of',app.e8n_utc(t),'time_zone',c.terms->>'time_zone','start_date',c.start_date,
  'end_date',c.end_date,'deadline',app.e8n_utc(c.deadline_at));
 IF c.result_status='final' THEN
  IF seed.final_at IS NULL OR
   (SELECT count(*) FROM app.nemesis_final_results WHERE challenge_id=c.id
    AND finalized_at=seed.final_at AND read_revision=result_revision)<>2 THEN
   RETURN app.e8n_error(503,'nemesis_statistics_unavailable'); END IF;
  SELECT aggregates INTO own FROM app.nemesis_final_results WHERE challenge_id=c.id AND participant_role=own_role;
  SELECT aggregates INTO opponent FROM app.nemesis_final_results WHERE challenge_id=c.id AND participant_role=other_role;
  result_state:='final'; response:=response||jsonb_build_object('finalized_at',app.e8n_utc(seed.final_at));
 ELSE
  IF seed.final_at IS NOT NULL OR EXISTS(SELECT 1 FROM app.nemesis_final_results WHERE challenge_id=c.id) THEN
   RETURN app.e8n_error(503,'nemesis_statistics_unavailable'); END IF;
  IF closed=0 THEN
   RETURN jsonb_build_object('ok',true,'http_status',200,'code','accepted',
    'response',response||jsonb_build_object('status','pending'),'replayed',false);
  END IF;
  own:=app.e8n_aggregate_projection(c.id,own_role,t);
  opponent:=app.e8n_aggregate_projection(c.id,other_role,t); result_state:='provisional';
 END IF;
 own_points:=(own#>>'{regularity,points}')::bigint;
 opponent_points:=(opponent#>>'{regularity,points}')::bigint;
 response:=response||jsonb_build_object('status',result_state,'self',own,'opponent',opponent,
  'outcome',CASE WHEN own_points>opponent_points THEN 'self_wins'
  WHEN own_points<opponent_points THEN 'opponent_wins' ELSE 'tie' END);
 RETURN jsonb_build_object('ok',true,'http_status',200,'code','accepted','response',response,'replayed',false);
END $$;
