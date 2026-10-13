CREATE OR REPLACE FUNCTION app.e8n_maintain(p_batch integer DEFAULT 100) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ids uuid[]; t timestamptz; transitioned integer; cleaned integer; admissions_pruned integer;
BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'invalid Nemesis batch' USING ERRCODE='22023'; END IF;
 SELECT array_agg(id ORDER BY id) INTO ids FROM(
   SELECT id FROM app.nemesis_challenges
   WHERE (status='invited' AND expires_at<=app.e8n_clock())
      OR (status='active' AND end_at<=app.e8n_clock())
   ORDER BY id LIMIT p_batch
 ) q;
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 t:=app.e8n_clock();
 UPDATE app.nemesis_challenges SET status=CASE WHEN status='invited' THEN 'cancelled' ELSE 'finished' END,cancel_reason=CASE WHEN status='invited' THEN 'expired' ELSE NULL END,revision=revision+1
 WHERE id=ANY(ids) AND ((status='invited' AND expires_at<=t) OR(status='active' AND end_at<=t));GET DIAGNOSTICS transitioned=ROW_COUNT;
 DELETE FROM app.nemesis_slots s USING app.nemesis_challenges c WHERE s.challenge_id=c.id AND c.id=ANY(ids) AND c.status<>'active';
 WITH q AS(SELECT owner_id,operation,key FROM app.nemesis_receipts WHERE response IS NOT NULL AND response_expires_at<=t ORDER BY response_expires_at,owner_id,operation,key LIMIT p_batch)
 UPDATE app.nemesis_receipts r SET response=NULL FROM q WHERE (r.owner_id,r.operation,r.key)=(q.owner_id,q.operation,q.key);GET DIAGNOSTICS cleaned=ROW_COUNT;
 DELETE FROM app.nemesis_cursors WHERE token IN(SELECT token FROM app.nemesis_cursors WHERE expires_at<=t ORDER BY expires_at,token LIMIT p_batch);
 -- Expired digest rows contain no replay authority; minimal receipts are never removed.
 DELETE FROM app.nemesis_share_codes WHERE owner_id IN(SELECT owner_id FROM app.nemesis_share_codes WHERE expires_at<=t ORDER BY expires_at,owner_id LIMIT p_batch);
 -- Every admission window is at most 24 hours. Pruning the closed boundary
 -- cannot refund a live quota; minimal receipts still fence the old keys.
 WITH old_admissions AS (
   SELECT owner_id, kind, key
   FROM app.nemesis_admissions
   WHERE admitted_at <= t - interval '24 hours'
   ORDER BY admitted_at, owner_id, kind, key
   LIMIT p_batch
 )
 DELETE FROM app.nemesis_admissions AS admission
 USING old_admissions AS old
 WHERE (admission.owner_id, admission.kind, admission.key) =
       (old.owner_id, old.kind, old.key);
 GET DIAGNOSTICS admissions_pruned = ROW_COUNT;
 RETURN jsonb_build_object('transitioned', transitioned,
                           'responses_pruned', cleaned,
                           'admissions_pruned', admissions_pruned);
END $$;
