-- Verify both roles and every date without ever rebuilding from current source.
CREATE FUNCTION app.e8n_seed_ready(c app.nemesis_challenges) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM app.nemesis_projection_seeds s WHERE s.challenge_id=c.id
  AND s.initializer_revision='0021_initializer_v1' AND s.resolver_revision='iana_boundary_v1' AND s.initialized_at=c.accepted_at)
 AND c.accepted_at IS NOT NULL AND c.terms->>'rule_version'='regularity_v1'
 AND (SELECT count(*) FROM app.nemesis_day_projections WHERE challenge_id=c.id)=2*(c.end_date-c.start_date)
 AND NOT EXISTS(SELECT 1 FROM app.nemesis_day_projections p WHERE p.challenge_id=c.id AND
  (p.local_date<c.start_date OR p.local_date>=c.end_date OR p.rule_version<>'regularity_v1'
   OR p.qualified_at>c.deadline_at OR (p.local_date=c.start_date AND p.starts_at<>c.start_at)
   OR (p.local_date=c.end_date-1 AND p.matures_at<>c.end_at)))
 AND NOT EXISTS(SELECT 1 FROM app.nemesis_day_projections a
  FULL JOIN app.nemesis_day_projections b ON b.challenge_id=a.challenge_id AND b.participant_role='invitee'
    AND a.participant_role='inviter' AND b.local_date=a.local_date AND b.rule_version=a.rule_version
  WHERE coalesce(a.challenge_id,b.challenge_id)=c.id AND
    (a.participant_role='inviter' OR b.participant_role='invitee') AND
    (a.challenge_id IS NULL OR b.challenge_id IS NULL OR a.starts_at<>b.starts_at OR a.matures_at<>b.matures_at))
 AND NOT EXISTS(SELECT 1 FROM app.nemesis_day_projections p JOIN app.nemesis_day_projections n
 ON n.challenge_id=p.challenge_id AND n.participant_role=p.participant_role AND n.local_date=p.local_date+1
 WHERE p.challenge_id=c.id AND p.matures_at<>n.starts_at)
$$;

-- Only the initializer/orchestrator call this writer. q never comes from API.
CREATE FUNCTION app.e8n_write_projection(p_id uuid,p_owner uuid,p_role text,p_q timestamptz) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE c app.nemesis_challenges%ROWTYPE; dates date[]; pos bigint;
BEGIN
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=p_id;
 IF c.id IS NULL OR p_q IS NULL OR p_q>c.deadline_at OR c.result_status<>'provisional'
 OR c.status NOT IN('active','finished') OR p_owner IS DISTINCT FROM (CASE WHEN p_role='inviter' THEN c.inviter_id WHEN p_role='invitee' THEN c.invitee_id END)
 THEN RAISE EXCEPTION 'unqualified Nemesis projection' USING ERRCODE='23514'; END IF;
 SELECT array_agg(local_date ORDER BY local_date) INTO dates FROM app.nemesis_day_projections
 WHERE challenge_id=p_id AND participant_role=p_role;
 SELECT position INTO pos FROM app.sync_counters WHERE owner_id=p_owner;
 WITH facts AS MATERIALIZED(SELECT * FROM app.e8_day_facts(p_owner,dates)), fact_values AS (
 SELECT f.*, CASE WHEN (g.payload #>> '{estimate,maintenance_kcal}')::numeric>0
   THEN (g.payload #>> '{estimate,maintenance_kcal}')::numeric END AS maintenance,
  w.id AS weight_id,w.revision AS weight_revision,w.occurred_at,w.weight_kg
 FROM facts f JOIN app.nemesis_day_projections p ON p.challenge_id=p_id AND p.participant_role=p_role AND p.local_date=f.local_date
 LEFT JOIN app.goal_versions g ON g.owner_id=p_owner AND g.id=f.goal_id AND g.revision=f.goal_revision
 LEFT JOIN LATERAL(SELECT v.* FROM app.weights v WHERE v.owner_id=p_owner AND v.deleted_at IS NULL
  AND v.occurred_at>=p.starts_at AND v.occurred_at<p.matures_at ORDER BY v.occurred_at DESC,v.id DESC LIMIT 1) w ON true
 ) UPDATE app.nemesis_day_projections p SET candidate_points=f.effective_complete::integer+(f.in_goal IS TRUE)::integer,
 effective_complete=f.effective_complete,in_goal=f.in_goal,intake_kcal=CASE WHEN f.energy_complete AND f.energy_sum>0 THEN f.energy_sum END,
 maintenance_kcal=f.maintenance,weight_kg=f.weight_kg,weight_id=f.weight_id,weight_revision=f.weight_revision,weight_occurred_at=f.occurred_at,
 source_revisions=f.source_revisions||jsonb_build_object('representative_weight_id',f.weight_id,'representative_weight_revision',f.weight_revision),
 source_position=coalesce(pos,0),qualified_at=p_q,revision=p.revision+1
 FROM fact_values f WHERE p.challenge_id=p_id AND p.participant_role=p_role AND p.local_date=f.local_date;
END $$;
CREATE FUNCTION app.e8n_initialize(p_id uuid,p_q timestamptz) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE c app.nemesis_challenges%ROWTYPE;
BEGIN
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=p_id;
 IF c.accepted_at IS DISTINCT FROM p_q OR c.status<>'active' OR c.result_status<>'provisional'
 OR EXISTS(SELECT 1 FROM app.nemesis_projection_seeds WHERE challenge_id=p_id)
 THEN RAISE EXCEPTION 'invalid Nemesis initializer' USING ERRCODE='23514'; END IF;
 INSERT INTO app.nemesis_projection_seeds(challenge_id,initializer_revision,resolver_revision,initialized_at)
 VALUES(p_id,'0021_initializer_v1','iana_boundary_v1',p_q);
 INSERT INTO app.nemesis_day_projections(challenge_id,participant_role,local_date,rule_version,starts_at,matures_at,
 candidate_points,effective_complete,source_revisions,source_position,qualified_at)
 SELECT p_id,r.role,d.day,'regularity_v1',app.e8n_boundary(d.day,c.terms->>'time_zone'),
 app.e8n_boundary(d.day+1,c.terms->>'time_zone'),0,false,'{}',0,p_q
 FROM (SELECT generate_series(c.start_date::timestamp,(c.end_date-1)::timestamp,interval '1 day')::date AS day) d
 CROSS JOIN (VALUES('inviter'),('invitee')) r(role);
 PERFORM app.e8n_write_projection(p_id,c.inviter_id,'inviter',p_q);
 PERFORM app.e8n_write_projection(p_id,c.invitee_id,'invitee',p_q);
 IF NOT app.e8n_seed_ready(c) THEN RAISE EXCEPTION 'incomplete Nemesis seed' USING ERRCODE='23514'; END IF;
END $$;
