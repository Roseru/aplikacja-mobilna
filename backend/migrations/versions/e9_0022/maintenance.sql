CREATE FUNCTION app.e9_consent_reset() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 -- Any newly accepted consent revision needs fresh affirmation. Restore never
 -- updates this marker back to a former epoch; false->true cannot revive work.
 IF NEW.revision IS DISTINCT FROM OLD.revision THEN
 UPDATE app.energy_axes SET baseline_id=NULL,baseline_epoch=NULL,baseline_consent_revision=NULL,baseline_notice=NULL WHERE owner_id=NEW.owner_id;
 END IF;RETURN NEW;
END $$;
CREATE TRIGGER energy_consent_reset AFTER UPDATE ON app.user_consents FOR EACH ROW EXECUTE FUNCTION app.e9_consent_reset();
CREATE FUNCTION app.e9_auto_candidates(p_batch integer) RETURNS SETOF uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN IF p_batch NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'invalid auto batch';END IF;
 RETURN QUERY SELECT a.owner_id FROM app.energy_axes a JOIN app.user_accounts u ON u.id=a.owner_id
 JOIN app.user_consents c ON c.owner_id=a.owner_id JOIN app.installation_state i ON i.id=1
 JOIN app.user_profiles p ON p.owner_id=a.owner_id AND p.deleted_at IS NULL
 WHERE u.state='active' AND NOT app.subject_blocked(u.issuer,u.subject) AND c.automatic_energy_adjustment
 AND a.last_auto_checked_date IS DISTINCT FROM (clock_timestamp() AT TIME ZONE p.time_zone)::date
 AND a.baseline_id IS NOT NULL AND a.baseline_epoch=i.sync_epoch
 AND app.e9_notice_valid(a.baseline_notice,a.baseline_notice->>'provider','automatic_energy_adjustment')
 AND (a.baseline_notice->>'account_generation')::integer=u.generation AND a.baseline_consent_revision=c.revision
 AND(a.last_applied_at IS NULL OR a.last_applied_at<=clock_timestamp()-interval '336 hours')
 AND NOT EXISTS(SELECT 1 FROM app.ai_energy_admissions e WHERE e.owner_id=a.owner_id AND e.accepted_at>clock_timestamp()-interval '336 hours')
 AND NOT EXISTS(SELECT 1 FROM app.ai_jobs j WHERE j.owner_id=a.owner_id AND j.state IN('queued','running'))
 ORDER BY a.owner_id LIMIT p_batch;
END $$;

CREATE FUNCTION app.e9_auto_enqueue(p_owner uuid,p_profile jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE context jsonb;result jsonb;u app.user_accounts%ROWTYPE;t timestamptz;today date;new_id uuid:=gen_random_uuid();zone text;
BEGIN
 SELECT * INTO u FROM app.user_accounts WHERE id=p_owner AND state='active' FOR UPDATE;
 IF NOT FOUND OR app.subject_blocked(u.issuer,u.subject) THEN RETURN NULL;END IF;
 INSERT INTO app.sync_counters(owner_id) VALUES(p_owner) ON CONFLICT DO NOTHING;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
 PERFORM 1 FROM app.installation_state WHERE id=1 FOR SHARE;
 IF NOT EXISTS(SELECT 1 FROM app.energy_axes a JOIN app.user_consents c ON c.owner_id=a.owner_id
 WHERE a.owner_id=p_owner AND c.automatic_energy_adjustment AND a.baseline_id IS NOT NULL
 AND app.e9_notice_valid(a.baseline_notice,p_profile->>'provider','automatic_energy_adjustment')
 AND (a.baseline_notice->>'account_generation')::integer=u.generation
 AND a.baseline_epoch=(SELECT sync_epoch FROM app.installation_state WHERE id=1) AND a.baseline_consent_revision=c.revision
 AND(a.last_applied_at IS NULL OR a.last_applied_at<=clock_timestamp()-interval '336 hours')) THEN RETURN NULL;END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 IF NOT EXISTS(SELECT 1 FROM app.ai_controls c JOIN app.installation_state i ON i.id=c.id AND i.sync_epoch=c.sync_epoch WHERE c.dispatch_open) THEN RETURN NULL;END IF;
 IF NOT EXISTS(SELECT 1 FROM app.ai_pools WHERE scope=p_profile->>'pool_scope' AND enabled AND provider=p_profile->>'provider' AND model=p_profile->>'model') THEN RETURN NULL;END IF;
 IF EXISTS(SELECT 1 FROM app.ai_jobs WHERE owner_id=p_owner AND state IN('queued','running')) THEN RETURN NULL;END IF;
 SELECT time_zone INTO zone FROM app.user_profiles WHERE owner_id=p_owner AND deleted_at IS NULL;IF zone IS NULL THEN RETURN NULL;END IF;
 t:=clock_timestamp();today:=(t AT TIME ZONE zone)::date;
 IF EXISTS(SELECT 1 FROM app.energy_axes WHERE owner_id=p_owner AND last_auto_checked_date=today) THEN RETURN NULL;END IF;
 context:=app.e9_context(p_owner,today-14,today-1);result:=app.e9_rules(context,true);
 UPDATE app.energy_axes SET last_auto_checked_date=today,last_auto_state=result->>'state' WHERE owner_id=p_owner;
 context:=app.e9_context(p_owner,today-14,today-1);
 IF result->>'state' IN('insufficient_data','energy_history_unavailable','baseline_required','baseline_range_conflict') THEN RETURN NULL;END IF;
 IF NOT app.e7_admit(p_owner,'energy_adjustment') THEN RETURN NULL;END IF;
 INSERT INTO app.energy_analyses(id,owner_id,generation,sync_epoch,automatic,accepted_at,date_from,date_to,context,fingerprint,profile,notice,result,state)
 VALUES(new_id,p_owner,u.generation,(SELECT sync_epoch FROM app.installation_state WHERE id=1),true,t,today-14,today-1,context,app.e9_fingerprint(context),p_profile,
 app.e9_notice_snapshot((SELECT baseline_notice FROM app.energy_axes WHERE owner_id=p_owner),context,t,
 (SELECT baseline_id FROM app.energy_axes WHERE owner_id=p_owner)),result,'queued');
 INSERT INTO app.ai_jobs(id,owner_id,energy_analysis_id,purpose,generation,sync_epoch,pool_scope,state,queue_deadline,next_attempt_at)
 VALUES(gen_random_uuid(),p_owner,new_id,'energy_adjustment',u.generation,(SELECT sync_epoch FROM app.installation_state WHERE id=1),p_profile->>'pool_scope','queued',t+interval '5 minutes',t);
 RETURN jsonb_build_object('id',new_id,'state','queued');
END $$;

ALTER FUNCTION app.e8n_delete_helper(uuid,uuid,boolean) RENAME TO e8n_delete_helper_pre22;
CREATE FUNCTION app.e8n_delete_helper(p_owner uuid,p_operation uuid,p_purge boolean DEFAULT false) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 PERFORM app.e8n_delete_helper_pre22(p_owner,p_operation,p_purge);
 IF p_purge THEN
 IF NOT app.deletion_purge_authorized(p_owner) THEN RAISE EXCEPTION 'exact scoped purge required';END IF;
 DELETE FROM app.ai_jobs WHERE owner_id=p_owner AND purpose='energy_adjustment';
 DELETE FROM app.energy_analyses WHERE owner_id=p_owner;
 DELETE FROM app.energy_receipts WHERE owner_id=p_owner;
 DELETE FROM app.energy_changes WHERE owner_id=p_owner;
 DELETE FROM app.energy_versions WHERE owner_id=p_owner;
 DELETE FROM app.energy_axes WHERE owner_id=p_owner;
 ELSE
 UPDATE app.energy_axes SET baseline_id=NULL,baseline_epoch=NULL,baseline_consent_revision=NULL,baseline_notice=NULL WHERE owner_id=p_owner;
 UPDATE app.energy_analyses SET state='failed',error_code='account_deleting',revision=revision+1 WHERE owner_id=p_owner AND state IN('queued','running','ready','manual_review_required','no_change');
 UPDATE app.ai_jobs SET state='failed',phase='completed',fence=gen_random_uuid() WHERE owner_id=p_owner AND purpose='energy_adjustment' AND state IN('queued','running');
 END IF;
END $$;

ALTER FUNCTION app.e7_prune_receipts(uuid,integer) RENAME TO e7_prune_receipts_pre22;
CREATE FUNCTION app.e7_prune_receipts(p_owner uuid,p_batch integer DEFAULT 1000) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE n integer;photo integer;BEGIN
 photo:=app.e7_prune_receipts_pre22(p_owner,p_batch);
 IF NOT EXISTS(SELECT 1 FROM app.user_accounts WHERE id=p_owner AND state='active') THEN RETURN photo;END IF;
 WITH cut AS(SELECT key FROM app.energy_receipts WHERE owner_id=p_owner AND response IS NOT NULL
 AND created_at<=clock_timestamp()-interval '1440 hours' ORDER BY created_at,key LIMIT p_batch)
 UPDATE app.energy_receipts SET response=NULL WHERE owner_id=p_owner AND key IN(SELECT key FROM cut);
 GET DIAGNOSTICS n=ROW_COUNT;RETURN n+photo;
END $$;
ALTER FUNCTION app.e7_receipt_cleanup_owners(integer) RENAME TO e7_receipt_cleanup_owners_pre22;
CREATE FUNCTION app.e7_receipt_cleanup_owners(p_batch integer DEFAULT 100) RETURNS SETOF uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN IF p_batch NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'invalid cleanup batch';END IF;
 RETURN QUERY SELECT owner_id FROM(
 SELECT owner_id,created_at FROM app.ai_receipts WHERE response_payload IS NOT NULL
 UNION ALL SELECT owner_id,created_at FROM app.energy_receipts WHERE response IS NOT NULL
 ) r WHERE created_at<=clock_timestamp()-interval '1440 hours'
 GROUP BY owner_id ORDER BY min(created_at),owner_id LIMIT p_batch;
END $$;
