-- Capture the frozen E8/E4 entry points. Their immutable bodies remain delegated.
ALTER FUNCTION app.begin_account_deletion(uuid,uuid,integer)
  RENAME TO begin_account_deletion_e8_19;
ALTER FUNCTION app.purge_deleted_account(uuid)
  RENAME TO purge_deleted_account_e8_19;

CREATE FUNCTION app.begin_account_deletion(p_owner uuid,p_operation uuid,p_generation integer)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE job app.account_deletion_jobs%ROWTYPE;
BEGIN
  PERFORM app.begin_account_deletion_e8_19(p_owner,p_operation,p_generation);
  SELECT * INTO job FROM app.account_deletion_jobs WHERE operation_id=p_operation;
  IF job.account_id IS DISTINCT FROM p_owner
     OR job.expected_generation IS DISTINCT FROM p_generation THEN
    RAISE EXCEPTION 'exact deletion job required' USING ERRCODE='23514';
  END IF;
  IF job.purged_at IS NOT NULL THEN RETURN job.operation_id; END IF;
  IF NOT EXISTS (
    SELECT 1 FROM app.user_accounts WHERE id=job.account_id AND state='deleting'
      AND generation=job.deleting_generation AND issuer=job.issuer AND subject=job.subject
  ) OR NOT EXISTS (
    SELECT 1 FROM app.deleted_subjects WHERE operation_id=p_operation
      AND issuer=job.issuer AND subject=job.subject
  ) THEN
    RAISE EXCEPTION 'exact fenced deleting account required' USING ERRCODE='23514';
  END IF;
  -- The parent already owns account -> counter -> job. Sharing/slots terminate
  -- before this transaction commits, without acquiring any peer account.
  PERFORM app.e8n_delete_helper(job.account_id,p_operation,false);
  RETURN job.operation_id;
END $$;

CREATE FUNCTION app.purge_deleted_account(p_operation uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE job app.account_deletion_jobs%ROWTYPE;
BEGIN
  SELECT * INTO job FROM app.account_deletion_jobs WHERE operation_id=p_operation;
  IF job.operation_id IS NULL THEN
    RAISE EXCEPTION 'exact deletion job required' USING ERRCODE='23514';
  END IF;
  PERFORM 1 FROM app.user_accounts WHERE id=job.account_id FOR UPDATE;
  PERFORM 1 FROM app.sync_counters WHERE owner_id=job.account_id FOR UPDATE;
  -- AI source application already owns these global rows before its source
  -- challenge phase. Taking them now prevents challenge -> global inversions.
  PERFORM 1 FROM app.community_catalog_state WHERE id=1 FOR UPDATE;
  PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
  SELECT * INTO job FROM app.account_deletion_jobs
    WHERE operation_id=p_operation FOR UPDATE;
  IF job.purged_at IS NOT NULL THEN RETURN; END IF;
  IF job.identity_confirmed_at IS NULL OR NOT EXISTS (
    SELECT 1 FROM app.user_accounts WHERE id=job.account_id AND state='deleting'
      AND generation=job.deleting_generation AND issuer=job.issuer AND subject=job.subject
  ) OR NOT EXISTS (
    SELECT 1 FROM app.deleted_subjects WHERE operation_id=p_operation
      AND issuer=job.issuer AND subject=job.subject
  ) THEN
    RAISE EXCEPTION 'exact confirmed fenced deleting account required' USING ERRCODE='23514';
  END IF;
  IF EXISTS (SELECT 1 FROM app._deletion_context WHERE transaction_id=txid_current()) THEN
    RAISE EXCEPTION 'deletion context already in use' USING ERRCODE='23514';
  END IF;
  -- Only this privileged wrapper creates this scoped context. Any statement
  -- failure rolls it back together with the helper's bindings and receipt changes.
  INSERT INTO app._deletion_context VALUES(txid_current(),job.account_id,p_operation);
  PERFORM app.e8n_delete_helper(job.account_id,p_operation,true);
  DELETE FROM app._deletion_context WHERE transaction_id=txid_current()
    AND owner_id=job.account_id AND operation_id=p_operation;
  -- The preserved E8 -> E7 -> E6 -> E4 chain establishes its own contexts.
  PERFORM app.purge_deleted_account_e8_19(p_operation);
END $$;

DO $$ DECLARE runtime record; signature text; BEGIN
  FOREACH signature IN ARRAY ARRAY[
    'app.begin_account_deletion_e8_19(uuid,uuid,integer)',
    'app.purge_deleted_account_e8_19(uuid)',
    'app.begin_account_deletion(uuid,uuid,integer)',
    'app.purge_deleted_account(uuid)'] LOOP
    EXECUTE 'REVOKE ALL ON FUNCTION '||signature||' FROM PUBLIC';
    FOR runtime IN SELECT rolname FROM pg_roles WHERE rolname IN (
      'calorie_app_api','calorie_app_worker','calorie_app_ai_worker',
      'calorie_app_motivation_worker','calorie_app_nemesis_worker',
      'calorie_app_deletion_operator') LOOP
      EXECUTE 'REVOKE ALL ON FUNCTION '||signature||' FROM '||quote_ident(runtime.rolname);
    END LOOP;
  END LOOP;
END $$;
GRANT EXECUTE ON FUNCTION app.begin_account_deletion(uuid,uuid,integer),
  app.purge_deleted_account(uuid) TO calorie_app_deletion_operator;
