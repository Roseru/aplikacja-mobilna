-- No source reads, refresh calls, owner FK or owner sync writes are permitted.
CREATE FUNCTION app.e8n_finalize(p_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE c app.nemesis_challenges%ROWTYPE; seed app.nemesis_projection_seeds%ROWTYPE;
 t timestamptz; result_revision bigint; role text;
BEGIN
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=p_id FOR UPDATE;
 t:=app.e8n_clock();
 IF c.id IS NULL OR c.status NOT IN('active','finished') OR c.accepted_at IS NULL
  OR NOT app.e8n_access(c) OR NOT EXISTS(SELECT 1 FROM app.nemesis_control
   WHERE id=1 AND sync_epoch=c.sync_epoch) THEN
  RETURN jsonb_build_object('status','unavailable'); END IF;
 IF NOT app.e8n_gate() OR NOT app.e8n_seed_ready(c) THEN
  RETURN jsonb_build_object('status','unavailable'); END IF;
 SELECT * INTO seed FROM app.nemesis_projection_seeds WHERE challenge_id=c.id;
 IF c.result_status='final' THEN
  IF seed.final_at IS NULL OR (SELECT count(*) FROM app.nemesis_final_results
   WHERE challenge_id=c.id AND finalized_at=seed.final_at)<>2 THEN
   RETURN jsonb_build_object('status','unavailable'); END IF;
  RETURN jsonb_build_object('status','already_final','finalized_at',app.e8n_utc(seed.final_at)); END IF;
 IF t<=c.deadline_at THEN RETURN jsonb_build_object('status','not_due'); END IF;
 IF seed.final_at IS NOT NULL OR EXISTS(SELECT 1 FROM app.nemesis_final_results WHERE challenge_id=c.id) THEN
  RAISE EXCEPTION 'inconsistent durable Nemesis result' USING ERRCODE='23514'; END IF;
 UPDATE app.nemesis_projection_seeds SET read_revision=read_revision+1,final_at=t
  WHERE challenge_id=c.id RETURNING * INTO seed;
 result_revision:=(seed.read_revision-1)*91+(c.end_date-c.start_date)+1;
 FOREACH role IN ARRAY ARRAY['inviter','invitee'] LOOP
  INSERT INTO app.nemesis_final_results(challenge_id,participant_role,aggregates,read_revision,finalized_at)
  VALUES(c.id,role,app.e8n_aggregate_projection(c.id,role,t),result_revision,t);
 END LOOP;
 UPDATE app.nemesis_challenges SET result_status='final',status='finished',revision=revision+1 WHERE id=c.id;
 DELETE FROM app.nemesis_slots WHERE challenge_id=c.id;
 RETURN jsonb_build_object('status','finalized','finalized_at',app.e8n_utc(t));
END $$;

CREATE FUNCTION app.e8n_finalize_batch(p_batch integer DEFAULT 100) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ids uuid[]; candidate uuid; result jsonb; processed integer:=0; finalized integer:=0;
 backlog bigint; t timestamptz;
BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN
  RAISE EXCEPTION 'invalid Nemesis finalization batch' USING ERRCODE='22023'; END IF;
 t:=app.e8n_clock();
 IF NOT app.e8n_gate() THEN RETURN jsonb_build_object('processed',0,'finalized',0,'backlog',0,'ready',false); END IF;
 -- Filter broken/stale records before LIMIT. Due order provides fair progress;
 -- the complete batch locks globally in UUID order, matching source/deletion.
 SELECT array_agg(id ORDER BY id) INTO ids FROM (
  SELECT c.id FROM app.nemesis_challenges c WHERE c.status IN('active','finished')
   AND c.result_status='provisional' AND c.deadline_at<t AND app.e8n_access(c)
   AND app.e8n_seed_ready(c) AND EXISTS(SELECT 1 FROM app.nemesis_control
    WHERE id=1 AND sync_epoch=c.sync_epoch)
   ORDER BY c.deadline_at,c.id LIMIT p_batch
 ) due;
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 FOREACH candidate IN ARRAY coalesce(ids,'{}'::uuid[]) LOOP
  result:=app.e8n_finalize(candidate); processed:=processed+1;
  IF result->>'status'='finalized' THEN finalized:=finalized+1; END IF;
 END LOOP;
 SELECT count(*) INTO backlog FROM app.nemesis_challenges c
 WHERE c.status IN('active','finished') AND c.result_status='provisional'
  AND c.deadline_at<app.e8n_clock() AND app.e8n_access(c) AND app.e8n_seed_ready(c)
  AND EXISTS(SELECT 1 FROM app.nemesis_control WHERE id=1 AND sync_epoch=c.sync_epoch);
 RETURN jsonb_build_object('processed',processed,'finalized',finalized,'backlog',backlog,'ready',true);
END $$;
