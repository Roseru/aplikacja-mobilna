CREATE OR REPLACE FUNCTION app.e8n_delete_helper(p_owner uuid,p_operation uuid,p_purge boolean DEFAULT false) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE ids uuid[];j app.account_deletion_jobs%ROWTYPE;
BEGIN
 SELECT * INTO j FROM app.account_deletion_jobs WHERE account_id=p_owner AND operation_id=p_operation;
 IF j.account_id IS NULL OR NOT EXISTS(SELECT 1 FROM app.user_accounts WHERE id=p_owner AND state='deleting' AND generation=j.deleting_generation) OR NOT EXISTS(SELECT 1 FROM app.deleted_subjects WHERE operation_id=p_operation AND issuer=j.issuer AND subject=j.subject) THEN RAISE EXCEPTION 'exact deletion context required' USING ERRCODE='23514'; END IF;
 -- Caller wrapper already owns account/counter. Never acquire peer account here.
 SELECT array_agg(id ORDER BY id) INTO ids FROM app.nemesis_challenges WHERE p_owner IN(inviter_id,invitee_id);
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 UPDATE app.nemesis_challenges SET status='cancelled',cancel_reason='deleted',revision=revision+1 WHERE id=ANY(ids) AND status<>'cancelled';
 DELETE FROM app.nemesis_slots WHERE challenge_id=ANY(ids);
 IF p_purge THEN
 IF j.identity_confirmed_at IS NULL OR NOT app.deletion_purge_authorized(p_owner) THEN RAISE EXCEPTION 'confirmed purge context required' USING ERRCODE='23514'; END IF;
 DELETE FROM app.nemesis_final_results WHERE challenge_id=ANY(ids);
 DELETE FROM app.nemesis_day_projections WHERE challenge_id=ANY(ids);
 DELETE FROM app.nemesis_projection_seeds WHERE challenge_id=ANY(ids);
 DELETE FROM app.nemesis_cursors WHERE anchor_id=ANY(ids);
 -- Clear all private receipt snapshots of this participant, including peer replies.
 UPDATE app.nemesis_receipts SET response=NULL WHERE entity_id=ANY(ids) AND response IS NOT NULL;
 DELETE FROM app.nemesis_receipts WHERE owner_id=p_owner;DELETE FROM app.nemesis_admissions WHERE owner_id=p_owner;
 DELETE FROM app.nemesis_share_codes WHERE owner_id=p_owner;DELETE FROM app.nemesis_cursors WHERE requester_id=p_owner;
 DELETE FROM app.nemesis_challenges WHERE (inviter_id=p_owner AND invitee_id IS NULL) OR(invitee_id=p_owner AND inviter_id IS NULL);
 UPDATE app.nemesis_challenges SET inviter_id=CASE WHEN inviter_id=p_owner THEN NULL ELSE inviter_id END,invitee_id=CASE WHEN invitee_id=p_owner THEN NULL ELSE invitee_id END,cancel_reason='deleted',revision=revision+1 WHERE id=ANY(ids);
 DELETE FROM app.nemesis_challenges WHERE inviter_id IS NULL AND invitee_id IS NULL;
 END IF;
END $$;
