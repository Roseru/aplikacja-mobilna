CREATE FUNCTION app.e8_candidates(p_batch integer DEFAULT 100) RETURNS SETOF uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN
 RAISE EXCEPTION 'invalid motivation batch' USING ERRCODE='22023'; END IF;
 -- No projection row lock before account. Every selected candidate is rechecked
 -- inside e8_process after account -> counter and DB clock acquisition.
 RETURN QUERY SELECT u.id FROM app.user_accounts u
 LEFT JOIN app.motivation_accounts a ON u.id=a.owner_id
 CROSS JOIN app.installation_state i WHERE i.id=1 AND u.state='active' AND
 (a.owner_id IS NULL OR a.backfill_state='pending' OR a.sync_epoch<>i.sync_epoch OR a.next_matures_at<=app.e8_clock())
 ORDER BY coalesce(a.backfill_state='pending',true) DESC,a.next_matures_at NULLS FIRST,u.id LIMIT p_batch;
END $$;
CREATE FUNCTION app.e8_status() RETURNS jsonb
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT jsonb_build_object('pending_backfill',count(*) FILTER(WHERE a.owner_id IS NULL OR a.backfill_state='pending' OR a.sync_epoch<>i.sync_epoch),
 'pending_materialization',count(*) FILTER(WHERE a.next_matures_at<=app.e8_clock()),
 'oldest_matures_at',min(a.next_matures_at) FILTER(WHERE a.next_matures_at<=app.e8_clock()))
 FROM app.user_accounts u LEFT JOIN app.motivation_accounts a ON u.id=a.owner_id
 CROSS JOIN app.installation_state i WHERE i.id=1 AND u.state='active'
$$;
CREATE FUNCTION app.e8_prune_ranking_sessions(p_batch integer DEFAULT 1000) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE n integer;
BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN
 RAISE EXCEPTION 'invalid ranking cleanup batch' USING ERRCODE='22023'; END IF;
 WITH expired AS(SELECT session_id FROM app.ranking_sessions WHERE expires_at<=app.e8_clock()
 ORDER BY expires_at,session_id LIMIT p_batch)
 DELETE FROM app.ranking_sessions WHERE session_id IN(SELECT session_id FROM expired);
 GET DIAGNOSTICS n=ROW_COUNT; RETURN n;
END $$;

ALTER FUNCTION app.purge_deleted_account(uuid) RENAME TO purge_deleted_account_e7;
REVOKE ALL ON FUNCTION app.purge_deleted_account_e7(uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,
 calorie_app_ai_worker,calorie_app_motivation_worker,calorie_app_deletion_operator;
CREATE FUNCTION app.purge_deleted_account(p_operation uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.account_deletion_jobs%ROWTYPE;
BEGIN
 SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation;
 IF NOT FOUND THEN RAISE EXCEPTION 'unknown deletion job' USING ERRCODE='23514'; END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=j.account_id FOR UPDATE;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=j.account_id FOR UPDATE;
 SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation FOR UPDATE;
 IF j.purged_at IS NOT NULL THEN RETURN; END IF;
 IF j.identity_confirmed_at IS NULL OR NOT EXISTS(SELECT 1 FROM app.user_accounts
 WHERE id=j.account_id AND state='deleting' AND generation=j.deleting_generation AND issuer=j.issuer AND subject=j.subject)
 OR NOT EXISTS(SELECT 1 FROM app.deleted_subjects WHERE issuer=j.issuer AND subject=j.subject AND operation_id=p_operation) THEN
 RAISE EXCEPTION 'purge requires exact confirmed deleting target' USING ERRCODE='23514'; END IF;
 DELETE FROM app.ranking_sessions WHERE requester_id=j.account_id;
 -- Removing a foreign anchor leaves NULL, so its next use returns explicit
 -- restart rather than continuing through a purged private identity.
 UPDATE app.ranking_cursors SET anchor_id=NULL WHERE anchor_id=j.account_id;
 DELETE FROM app.ranking_affirmations WHERE owner_id=j.account_id;
 DELETE FROM app.motivation_badges WHERE owner_id=j.account_id;
 DELETE FROM app.motivation_days WHERE owner_id=j.account_id;
 DELETE FROM app.motivation_accounts WHERE owner_id=j.account_id;
 PERFORM app.purge_deleted_account_e7(p_operation);
END $$;
REVOKE ALL ON FUNCTION app.purge_deleted_account(uuid) FROM PUBLIC,calorie_app_api,calorie_app_worker,
 calorie_app_ai_worker,calorie_app_motivation_worker;
GRANT EXECUTE ON FUNCTION app.purge_deleted_account(uuid) TO calorie_app_deletion_operator;
