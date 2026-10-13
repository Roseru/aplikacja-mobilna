CREATE OR REPLACE FUNCTION app.e8n_write_projection(p_id uuid,p_owner uuid,p_role text,p_q timestamptz) RETURNS void
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
 SELECT f.*, (app.e9_resolve(p_owner,f.local_date)).maintenance_kcal AS maintenance,
  w.id AS weight_id,w.revision AS weight_revision,w.occurred_at,w.weight_kg
 FROM facts f JOIN app.nemesis_day_projections p ON p.challenge_id=p_id AND p.participant_role=p_role AND p.local_date=f.local_date
 
 LEFT JOIN LATERAL(SELECT v.* FROM app.weights v WHERE v.owner_id=p_owner AND v.deleted_at IS NULL
  AND v.occurred_at>=p.starts_at AND v.occurred_at<p.matures_at ORDER BY v.occurred_at DESC,v.id DESC LIMIT 1) w ON true
 ) UPDATE app.nemesis_day_projections p SET candidate_points=f.effective_complete::integer+(f.in_goal IS TRUE)::integer,
 effective_complete=f.effective_complete,in_goal=f.in_goal,intake_kcal=CASE WHEN f.energy_complete AND f.energy_sum>0 THEN f.energy_sum END,
 maintenance_kcal=f.maintenance,weight_kg=f.weight_kg,weight_id=f.weight_id,weight_revision=f.weight_revision,weight_occurred_at=f.occurred_at,
 source_revisions=f.source_revisions||jsonb_build_object('representative_weight_id',f.weight_id,'representative_weight_revision',f.weight_revision,'energy_version_id',(app.e9_resolve(p_owner,f.local_date)).id,'energy_version_revision',(app.e9_resolve(p_owner,f.local_date)).revision),
 source_position=coalesce(pos,0),qualified_at=p_q,revision=p.revision+1
 FROM fact_values f WHERE p.challenge_id=p_id AND p.participant_role=p_role AND p.local_date=f.local_date;
END $$;

CREATE OR REPLACE FUNCTION app.e8n_gate() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT app.e8n_runtime_ready() AND EXISTS(SELECT 1 FROM app.nemesis_control c JOIN app.installation_state i
 ON i.id=c.id AND i.sync_epoch=c.sync_epoch JOIN app.nemesis_releases r USING(projector_revision,finalizer_revision)
 WHERE c.id=1 AND c.enabled AND c.schema_revision='0022_e9_energy' AND c.initializer_revision='0021_initializer_v1'
 AND c.projector_revision='0022_projection_v1' AND c.finalizer_revision='0021_finalizer_v1'
 AND r.schema_revision=c.schema_revision AND r.initializer_revision=c.initializer_revision)
$$;
CREATE OR REPLACE FUNCTION app.e8n_activate(p_epoch uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch FOR SHARE;
 IF NOT FOUND OR NOT app.e8n_runtime_ready()
 OR (SELECT array_agg(version_num) FROM app.alembic_version) IS DISTINCT FROM ARRAY['0022_e9_energy']::varchar[]
 OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer' AND NOT rolcanlogin
 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT has_function_privilege('calorie_app_nemesis_finalizer','app.e8n_finalize_batch(integer)','EXECUTE')
 OR EXISTS(SELECT 1 FROM app.nemesis_challenges WHERE sync_epoch<>p_epoch AND status<>'cancelled')
 THEN RAISE EXCEPTION 'Nemesis activation preconditions unavailable' USING ERRCODE='55000'; END IF;
 UPDATE app.nemesis_control SET sync_epoch=p_epoch,enabled=true,schema_revision='0022_e9_energy',
 initializer_revision='0021_initializer_v1',projector_revision='0022_projection_v1',finalizer_revision='0021_finalizer_v1' WHERE id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Nemesis control unavailable' USING ERRCODE='55000'; END IF;
END $$;
INSERT INTO app.nemesis_releases(projector_revision,finalizer_revision,schema_revision,initializer_revision)
 VALUES('0022_projection_v1','0021_finalizer_v1','0022_e9_energy','0021_initializer_v1');
UPDATE app.nemesis_control SET enabled=false;
