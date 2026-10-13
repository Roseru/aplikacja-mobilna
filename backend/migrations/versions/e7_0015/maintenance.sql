CREATE FUNCTION app.e7_expire_photo(p_id uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE a app.ai_analyses%ROWTYPE; BEGIN
 SELECT * INTO a FROM app.ai_analyses WHERE id=p_id; IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=a.owner_id FOR UPDATE;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO a FROM app.ai_analyses WHERE id=p_id FOR UPDATE;
 IF NOT FOUND OR a.storage_key IS NULL THEN RETURN false; END IF;
 IF a.photo_expires_at<=clock_timestamp() THEN PERFORM app.e7_terminal(p_id,'image_expired'); END IF;
 IF a.state IN ('succeeded','failed') OR a.photo_expires_at<=clock_timestamp() THEN
   INSERT INTO app.ai_cleanup_intents(storage_key) VALUES(a.storage_key) ON CONFLICT DO NOTHING;
   RETURN true;
 END IF; RETURN false;
END $$;
REVOKE ALL ON FUNCTION app.e7_expire_photo(uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_expire_photo(uuid) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_orphan_intent(p_key text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF p_key IS NULL OR p_key !~ '^[0-9a-f]{32}$' THEN RAISE EXCEPTION 'invalid storage key' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 IF EXISTS(SELECT 1 FROM app.ai_analyses WHERE storage_key=p_key) THEN RETURN false; END IF;
 INSERT INTO app.ai_cleanup_intents(storage_key) VALUES(p_key) ON CONFLICT DO NOTHING;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION app.e7_orphan_intent(text) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_orphan_intent(text) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_cleanup_candidate(p_key text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF p_key IS NULL OR p_key !~ '^[0-9a-f]{32}$' THEN RAISE EXCEPTION 'invalid storage key' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 -- Recheck current eligibility under the caller's per-storage session lock.
 -- A compensation intent may have disappeared during concurrent acceptance.
 IF EXISTS(SELECT 1 FROM app.ai_analyses WHERE storage_key=p_key AND state IN ('queued','running')) THEN RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM app.ai_analyses WHERE storage_key=p_key) THEN
   INSERT INTO app.ai_cleanup_intents(storage_key) VALUES(p_key) ON CONFLICT DO NOTHING;
 END IF;
 RETURN EXISTS(SELECT 1 FROM app.ai_cleanup_intents WHERE storage_key=p_key);
END $$;
REVOKE ALL ON FUNCTION app.e7_cleanup_candidate(text) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_cleanup_candidate(text) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_cleanup_ack(p_key text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE owner uuid; BEGIN
 SELECT owner_id INTO owner FROM app.ai_analyses WHERE storage_key=p_key;
 IF FOUND THEN PERFORM 1 FROM app.user_accounts WHERE id=owner FOR UPDATE; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 IF EXISTS(SELECT 1 FROM app.ai_analyses WHERE storage_key=p_key AND state IN ('queued','running')) THEN
   RAISE EXCEPTION 'active photo cannot acknowledge deletion' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM app.ai_cleanup_intents WHERE storage_key=p_key) THEN RETURN; END IF;
 UPDATE app.ai_analyses SET storage_key=NULL WHERE storage_key=p_key;
 DELETE FROM app.ai_cleanup_intents WHERE storage_key=p_key;
END $$;
REVOKE ALL ON FUNCTION app.e7_cleanup_ack(text) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_cleanup_ack(text) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_prune_receipts(p_owner uuid,p_batch integer DEFAULT 1000) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE n integer; BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'invalid batch' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' FOR UPDATE;
 IF NOT FOUND THEN RETURN 0; END IF;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 WITH cut AS (SELECT operation_id FROM app.ai_receipts WHERE owner_id=p_owner
 AND response_payload IS NOT NULL AND created_at<=clock_timestamp()-interval '1440 hours'
 ORDER BY created_at,operation_id LIMIT p_batch)
 UPDATE app.ai_receipts SET response_payload=NULL WHERE owner_id=p_owner AND operation_id IN(SELECT operation_id FROM cut);
 GET DIAGNOSTICS n=ROW_COUNT;
 WITH cut AS (SELECT day FROM app.ai_admissions WHERE owner_id=p_owner
 AND day<(clock_timestamp() AT TIME ZONE 'UTC')::date-60 ORDER BY day LIMIT p_batch)
 DELETE FROM app.ai_admissions WHERE owner_id=p_owner AND day IN(SELECT day FROM cut);
 RETURN n;
END $$;
REVOKE ALL ON FUNCTION app.e7_prune_receipts(uuid,integer) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_prune_receipts(uuid,integer) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_receipt_cleanup_owners(p_batch integer DEFAULT 100) RETURNS SETOF uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'invalid batch' USING ERRCODE='22023'; END IF;
 RETURN QUERY SELECT r.owner_id FROM app.ai_receipts r
 WHERE r.response_payload IS NOT NULL AND r.created_at<=clock_timestamp()-interval '1440 hours'
 GROUP BY r.owner_id ORDER BY min(r.created_at),r.owner_id LIMIT p_batch;
END $$;
REVOKE ALL ON FUNCTION app.e7_receipt_cleanup_owners(integer) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_receipt_cleanup_owners(integer) TO calorie_app_ai_worker;

CREATE FUNCTION app.e7_prune_ledger(p_batch integer DEFAULT 1000) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE n integer; BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'invalid batch' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 WITH cut AS(SELECT a.id FROM app.ai_attempts a WHERE a.dispatched_at<=clock_timestamp()-interval '336 hours'
 AND a.io_finished_at IS NOT NULL AND NOT EXISTS(SELECT 1 FROM app.ai_transport_permits p WHERE p.attempt_id=a.id)
 ORDER BY a.dispatched_at,a.id LIMIT p_batch)
 DELETE FROM app.ai_attempts WHERE id IN(SELECT id FROM cut); GET DIAGNOSTICS n=ROW_COUNT;
 RETURN n;
END $$;
REVOKE ALL ON FUNCTION app.e7_prune_ledger(integer) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_prune_ledger(integer) TO calorie_app_ai_worker;

ALTER FUNCTION app.purge_deleted_account(uuid) RENAME TO purge_deleted_account_e6;
REVOKE ALL ON FUNCTION app.purge_deleted_account_e6(uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
CREATE FUNCTION app.purge_deleted_account(p_operation uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.account_deletion_jobs%ROWTYPE; BEGIN
 SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation;
 IF NOT FOUND THEN RAISE EXCEPTION 'unknown deletion job' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=j.account_id FOR UPDATE;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=j.account_id FOR UPDATE;
 PERFORM 1 FROM app.community_catalog_state WHERE id=1 FOR UPDATE;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation FOR UPDATE;
 IF j.purged_at IS NOT NULL THEN RETURN; END IF;
 IF j.identity_confirmed_at IS NULL OR NOT EXISTS(SELECT 1 FROM app.user_accounts
 WHERE id=j.account_id AND state='deleting' AND generation=j.deleting_generation AND issuer=j.issuer AND subject=j.subject)
 OR NOT EXISTS(SELECT 1 FROM app.deleted_subjects WHERE issuer=j.issuer AND subject=j.subject AND operation_id=p_operation) THEN
   RAISE EXCEPTION 'purge requires exact confirmed deleting target' USING ERRCODE='23514'; END IF;
 INSERT INTO app.ai_cleanup_intents(storage_key) SELECT storage_key FROM app.ai_analyses
 WHERE owner_id=j.account_id AND storage_key IS NOT NULL ON CONFLICT DO NOTHING;
 DELETE FROM app.ai_photo_consents WHERE owner_id=j.account_id;
 DELETE FROM app.ai_decisions WHERE owner_id=j.account_id;
 DELETE FROM app.ai_receipts WHERE owner_id=j.account_id;
 DELETE FROM app.ai_admissions WHERE owner_id=j.account_id;
 DELETE FROM app.ai_energy_admissions WHERE owner_id=j.account_id;
 -- Attempts retain only anonymous counters and random attempt IDs; FK removes the job binding.
 DELETE FROM app.ai_jobs WHERE owner_id=j.account_id;
 DELETE FROM app.ai_analyses WHERE owner_id=j.account_id;
 PERFORM app.purge_deleted_account_e6(p_operation);
END $$;
REVOKE ALL ON FUNCTION app.purge_deleted_account(uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker;
GRANT EXECUTE ON FUNCTION app.purge_deleted_account(uuid) TO calorie_app_deletion_operator;
