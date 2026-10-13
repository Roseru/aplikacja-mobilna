-- Accepted instants are validated once, then protected from later resolver changes.
DO $$ DECLARE constraint_row record; BEGIN
 FOR constraint_row IN SELECT conname,pg_get_constraintdef(oid) definition FROM pg_constraint
 WHERE conrelid='app.nemesis_challenges'::regclass AND contype='c' LOOP
  IF constraint_row.definition LIKE '%e8n_boundary%' OR constraint_row.definition LIKE '%e8n_terms_valid%'
   OR constraint_row.definition LIKE '%result_status%' AND constraint_row.definition LIKE '%provisional%' THEN
   EXECUTE format('ALTER TABLE app.nemesis_challenges DROP CONSTRAINT %I',constraint_row.conname);
  END IF;
 END LOOP;
END $$;
ALTER TABLE app.nemesis_challenges ADD CONSTRAINT nemesis_result_status_v21 CHECK(result_status IN('provisional','final'));
ALTER TABLE app.nemesis_challenges ADD CONSTRAINT nemesis_accepted_fields_v21 CHECK(
 (accepted_at IS NULL AND start_date IS NULL AND end_date IS NULL AND start_at IS NULL AND end_at IS NULL AND deadline_at IS NULL AND result_status IS NULL)
 OR (accepted_at IS NOT NULL AND start_date IS NOT NULL AND end_date IS NOT NULL AND start_at IS NOT NULL AND end_at IS NOT NULL
 AND deadline_at=end_at+interval '720 hours' AND result_status IN('provisional','final') AND start_at>accepted_at AND end_at>start_at
 AND end_date-start_date=(terms->>'duration_days')::integer));
CREATE OR REPLACE FUNCTION app.e8n_challenge_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 -- New invitation and first accept validate the current resolver once. Later
 -- status transitions preserve already accepted terms even if tzdata changes.
 IF (TG_OP='INSERT' OR OLD.accepted_at IS NULL AND NEW.accepted_at IS NOT NULL)
 AND NOT app.e8n_terms_valid(NEW.terms) THEN
 RAISE EXCEPTION 'invalid new Nemesis terms' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
 IF NEW.id<>OLD.id OR NEW.terms IS DISTINCT FROM OLD.terms OR
 NEW.created_at<>OLD.created_at OR NEW.expires_at<>OLD.expires_at OR NEW.sync_epoch<>OLD.sync_epoch OR
 NEW.inviter_generation<>OLD.inviter_generation OR NEW.invitee_generation<>OLD.invitee_generation OR
 ((NEW.inviter_id IS DISTINCT FROM OLD.inviter_id OR NEW.invitee_id IS DISTINCT FROM OLD.invitee_id) AND NOT
 (NEW.status='cancelled' AND NEW.cancel_reason='deleted' AND (NEW.inviter_id IS NOT DISTINCT FROM OLD.inviter_id OR (NEW.inviter_id IS NULL AND app.deletion_purge_authorized(OLD.inviter_id))) AND (NEW.invitee_id IS NOT DISTINCT FROM OLD.invitee_id OR (NEW.invitee_id IS NULL AND app.deletion_purge_authorized(OLD.invitee_id))))) OR
 NEW.revision<>OLD.revision+1 OR OLD.status='cancelled' AND NEW.status<>'cancelled' OR
 (OLD.status='cancelled' AND NEW.cancel_reason IS DISTINCT FROM OLD.cancel_reason AND NOT(NEW.cancel_reason='deleted' AND (NEW.inviter_id IS NULL OR NEW.invitee_id IS NULL))) OR
 OLD.status='finished' AND NEW.status NOT IN ('finished','cancelled') OR
 OLD.status='active' AND NEW.status NOT IN ('active','finished','cancelled') OR
 (OLD.accepted_at IS NOT NULL AND ROW(NEW.accepted_at,NEW.start_date,NEW.end_date,NEW.start_at,NEW.end_at,NEW.deadline_at)
 IS DISTINCT FROM ROW(OLD.accepted_at,OLD.start_date,OLD.end_date,OLD.start_at,OLD.end_at,OLD.deadline_at))
 OR OLD.result_status='final' AND NEW.result_status IS DISTINCT FROM 'final'
 OR OLD.result_status='provisional' AND NEW.result_status IS DISTINCT FROM 'provisional' AND NOT
 (NEW.result_status='final' AND NEW.status='finished' AND app.e8n_seed_ready(NEW)
 AND EXISTS(SELECT 1 FROM app.nemesis_projection_seeds WHERE challenge_id=NEW.id AND final_at>NEW.deadline_at)
 AND (SELECT count(*) FROM app.nemesis_final_results r JOIN app.nemesis_projection_seeds s ON s.challenge_id=r.challenge_id
 WHERE r.challenge_id=NEW.id AND r.read_revision=(s.read_revision-1)*91+(NEW.end_date-NEW.start_date)+1 AND r.finalized_at=s.final_at)=2)
 THEN RAISE EXCEPTION 'immutable Nemesis binding or revision' USING ERRCODE='23514'; END IF;
 END IF;
 IF NEW.accepted_at IS NOT NULL AND (TG_OP='INSERT' OR OLD.accepted_at IS NULL) AND
 (NEW.result_status IS DISTINCT FROM 'provisional'
 OR NEW.start_at IS DISTINCT FROM app.e8n_boundary((NEW.accepted_at AT TIME ZONE(NEW.terms->>'time_zone'))::date+1,NEW.terms->>'time_zone')
 OR NEW.start_date IS DISTINCT FROM (NEW.start_at AT TIME ZONE(NEW.terms->>'time_zone'))::date
 OR NEW.end_at IS DISTINCT FROM app.e8n_boundary(NEW.end_date,NEW.terms->>'time_zone'))
 THEN RAISE EXCEPTION 'accepted Nemesis resolver mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
-- Existing trigger UPDATE protects immutable terms; INSERT also validates accepted imports.
CREATE TRIGGER nemesis_accepted_insert BEFORE INSERT ON app.nemesis_challenges
 FOR EACH ROW EXECUTE FUNCTION app.e8n_challenge_guard();
