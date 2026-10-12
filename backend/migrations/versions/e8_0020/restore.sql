-- Owner-only restore maintenance. Traffic and workers are fenced by the caller;
-- this bounded helper never enables the capability or rewrites its epoch.
CREATE FUNCTION app.e8n_restore_maintain(p_batch integer DEFAULT 100)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE current_epoch uuid; control app.nemesis_control%ROWTYPE; candidates uuid[];
  cancelled integer; responses_pruned integer; codes_pruned integer;
  cursors_pruned integer; pending bigint;
BEGIN
  IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN
    RAISE EXCEPTION 'invalid restore batch' USING ERRCODE='22023';
  END IF;
  SELECT sync_epoch INTO current_epoch FROM app.installation_state WHERE id=1 FOR SHARE;
  SELECT * INTO control FROM app.nemesis_control WHERE id=1 FOR UPDATE;
  IF current_epoch IS NULL OR control.id IS NULL OR control.enabled
     OR control.sync_epoch=current_epoch THEN
    RAISE EXCEPTION 'restore requires disabled capability and fenced new epoch'
      USING ERRCODE='23514';
  END IF;
  SELECT array_agg(id ORDER BY id) INTO candidates FROM (
    SELECT id FROM app.nemesis_challenges WHERE sync_epoch<>current_epoch
      AND status<>'cancelled' ORDER BY id LIMIT p_batch
  ) selected;
  PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(candidates) ORDER BY id FOR UPDATE;
  UPDATE app.nemesis_challenges SET status='cancelled',cancel_reason='restore',revision=revision+1
    WHERE id=ANY(candidates) AND sync_epoch<>current_epoch AND status<>'cancelled';
  GET DIAGNOSTICS cancelled=ROW_COUNT;
  DELETE FROM app.nemesis_slots WHERE challenge_id=ANY(candidates);
  WITH expired AS (
    SELECT owner_id,operation,key FROM app.nemesis_receipts
    WHERE sync_epoch<>current_epoch AND response IS NOT NULL
    ORDER BY owner_id,operation,key LIMIT p_batch
  ) UPDATE app.nemesis_receipts AS receipt SET response=NULL FROM expired
    WHERE (receipt.owner_id,receipt.operation,receipt.key)=
          (expired.owner_id,expired.operation,expired.key);
  GET DIAGNOSTICS responses_pruned=ROW_COUNT;
  DELETE FROM app.nemesis_share_codes WHERE owner_id IN (
    SELECT owner_id FROM app.nemesis_share_codes WHERE sync_epoch<>current_epoch
    ORDER BY owner_id LIMIT p_batch
  );
  GET DIAGNOSTICS codes_pruned=ROW_COUNT;
  DELETE FROM app.nemesis_cursors WHERE token IN (
    SELECT token FROM app.nemesis_cursors WHERE sync_epoch<>current_epoch
    ORDER BY token LIMIT p_batch
  );
  GET DIAGNOSTICS cursors_pruned=ROW_COUNT;
  SELECT (SELECT count(*) FROM app.nemesis_challenges
            WHERE sync_epoch<>current_epoch AND status<>'cancelled')
    +(SELECT count(*) FROM app.nemesis_receipts
            WHERE sync_epoch<>current_epoch AND response IS NOT NULL)
    +(SELECT count(*) FROM app.nemesis_share_codes WHERE sync_epoch<>current_epoch)
    +(SELECT count(*) FROM app.nemesis_cursors WHERE sync_epoch<>current_epoch)
    INTO pending;
  RETURN jsonb_build_object('cancelled',cancelled,'responses_pruned',responses_pruned,
    'codes_pruned',codes_pruned,'cursors_pruned',cursors_pruned,'pending',pending);
END $$;
DO $$ DECLARE runtime record; BEGIN
  REVOKE ALL ON FUNCTION app.e8n_restore_maintain(integer) FROM PUBLIC;
  FOR runtime IN SELECT rolname FROM pg_roles WHERE rolname IN (
    'calorie_app_api','calorie_app_worker','calorie_app_ai_worker',
    'calorie_app_motivation_worker','calorie_app_nemesis_worker',
    'calorie_app_deletion_operator') LOOP
    EXECUTE 'REVOKE ALL ON FUNCTION app.e8n_restore_maintain(integer) FROM '
      ||quote_ident(runtime.rolname);
  END LOOP;
END $$;
