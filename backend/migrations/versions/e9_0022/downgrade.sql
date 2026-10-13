DROP FUNCTION app.e7_prune_receipts(uuid,integer);
ALTER FUNCTION app.e7_prune_receipts_pre22(uuid,integer) RENAME TO e7_prune_receipts;
DROP FUNCTION app.e7_receipt_cleanup_owners(integer);
ALTER FUNCTION app.e7_receipt_cleanup_owners_pre22(integer) RENAME TO e7_receipt_cleanup_owners;
GRANT EXECUTE ON FUNCTION app.e7_prune_receipts(uuid,integer),app.e7_receipt_cleanup_owners(integer) TO calorie_app_ai_worker;
DROP TRIGGER energy_legacy_import ON app.goal_versions;
DROP TRIGGER energy_consent_reset ON app.user_consents;
DROP FUNCTION app.e7_claim(uuid,uuid);
ALTER FUNCTION app.e7_claim_photo22(uuid,uuid) RENAME TO e7_claim;
GRANT EXECUTE ON FUNCTION app.e7_claim(uuid,uuid) TO calorie_app_ai_worker;
DROP FUNCTION app.e7_dispatch(uuid,uuid,text,uuid,uuid);
ALTER FUNCTION app.e7_dispatch_photo22(uuid,uuid,text,uuid,uuid) RENAME TO e7_dispatch;
GRANT EXECUTE ON FUNCTION app.e7_dispatch(uuid,uuid,text,uuid,uuid) TO calorie_app_ai_worker;
DROP FUNCTION app.e7_preflight_finish(uuid,uuid,integer);
ALTER FUNCTION app.e7_preflight_finish_photo22(uuid,uuid,integer) RENAME TO e7_preflight_finish;
GRANT EXECUTE ON FUNCTION app.e7_preflight_finish(uuid,uuid,integer) TO calorie_app_ai_worker;
DROP FUNCTION app.e7_finish_context(uuid,uuid);
ALTER FUNCTION app.e7_finish_context_photo22(uuid,uuid) RENAME TO e7_finish_context;
GRANT EXECUTE ON FUNCTION app.e7_finish_context(uuid,uuid) TO calorie_app_ai_worker;
DROP FUNCTION app.e7_finish(uuid,uuid,jsonb,text,integer);
ALTER FUNCTION app.e7_finish_photo22(uuid,uuid,jsonb,text,integer) RENAME TO e7_finish;
GRANT EXECUTE ON FUNCTION app.e7_finish(uuid,uuid,jsonb,text,integer) TO calorie_app_ai_worker;
DROP FUNCTION app.e8n_delete_helper(uuid,uuid,boolean);
ALTER FUNCTION app.e8n_delete_helper_pre22(uuid,uuid,boolean) RENAME TO e8n_delete_helper;
ALTER TABLE app.ai_jobs DROP CONSTRAINT ai_jobs_energy_fk;
ALTER TABLE app.ai_jobs DROP CONSTRAINT ai_jobs_energy_unique;
ALTER TABLE app.ai_jobs DROP CONSTRAINT ai_jobs_typed_payload;
ALTER TABLE app.ai_jobs DROP COLUMN energy_analysis_id;
ALTER TABLE app.ai_jobs ALTER COLUMN analysis_id SET NOT NULL;
DO $$ DECLARE f record;BEGIN FOR f IN SELECT oid::regprocedure sig FROM pg_proc WHERE pronamespace='app'::regnamespace AND proname LIKE 'e9_%' LOOP
 EXECUTE 'DROP FUNCTION '||f.sig||' CASCADE';END LOOP;END $$;
DROP TABLE app.energy_changes,app.energy_receipts,app.energy_analyses,app.energy_axes,app.energy_versions CASCADE;
-- Verify both roles and every date without ever rebuilding from current source.
CREATE OR REPLACE FUNCTION app.e8n_seed_ready(c app.nemesis_challenges) RETURNS boolean
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
CREATE OR REPLACE FUNCTION app.e8n_initialize(p_id uuid,p_q timestamptz) RETURNS void
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

CREATE OR REPLACE FUNCTION app.e8n_gate() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT app.e8n_runtime_ready() AND EXISTS(SELECT 1 FROM app.nemesis_control c JOIN app.installation_state i
 ON i.id=c.id AND i.sync_epoch=c.sync_epoch JOIN app.nemesis_releases r USING(projector_revision,finalizer_revision)
 WHERE c.id=1 AND c.enabled AND c.schema_revision='0021_e8_nemesis_results' AND c.initializer_revision='0021_initializer_v1'
 AND c.projector_revision='0021_projection_v1' AND c.finalizer_revision='0021_finalizer_v1'
 AND r.schema_revision=c.schema_revision AND r.initializer_revision=c.initializer_revision)
$$;
CREATE OR REPLACE FUNCTION app.e8n_activate(p_epoch uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch FOR SHARE;
 IF NOT FOUND OR NOT app.e8n_runtime_ready()
 OR (SELECT array_agg(version_num) FROM app.alembic_version) IS DISTINCT FROM ARRAY['0021_e8_nemesis_results']::varchar[]
 OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer' AND NOT rolcanlogin
 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT has_function_privilege('calorie_app_nemesis_finalizer','app.e8n_finalize_batch(integer)','EXECUTE')
 OR EXISTS(SELECT 1 FROM app.nemesis_challenges WHERE sync_epoch<>p_epoch AND status<>'cancelled')
 THEN RAISE EXCEPTION 'Nemesis activation preconditions unavailable' USING ERRCODE='55000'; END IF;
 UPDATE app.nemesis_control SET sync_epoch=p_epoch,enabled=true,schema_revision='0021_e8_nemesis_results',
 initializer_revision='0021_initializer_v1',projector_revision='0021_projection_v1',finalizer_revision='0021_finalizer_v1' WHERE id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Nemesis control unavailable' USING ERRCODE='55000'; END IF;
END $$;

DELETE FROM app.nemesis_releases WHERE schema_revision='0022_e9_energy';UPDATE app.nemesis_control SET enabled=false;
UPDATE app.nemesis_runtime_contract SET body_sha256=(SELECT encode(sha256(convert_to(prosrc,'UTF8')),'hex') FROM pg_proc WHERE oid=to_regprocedure('app.e8n_write_projection(uuid,uuid,text,timestamptz)')) WHERE signature='e8n_write_projection(uuid,uuid,text,timestamptz)';