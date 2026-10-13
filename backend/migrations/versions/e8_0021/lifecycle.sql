CREATE OR REPLACE FUNCTION app.e8n_execute(p_issuer text,p_subject text,p_epoch uuid,p_operation text,p_key uuid,p_request_hash text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE a app.user_accounts%ROWTYPE; initial_a app.user_accounts%ROWTYPE; peer app.user_accounts%ROWTYPE;
 c app.nemesis_challenges%ROWTYPE; code_row app.nemesis_share_codes%ROWTYPE; receipt app.nemesis_receipts%ROWTYPE;
 peer_id uuid; challenge_id uuid; ids uuid[]; t timestamptz; response jsonb; envelope jsonb;
 failure text; generated_code text; semantic_hash text; http integer:=200; terms jsonb; start_day date; end_day date; day date;
 start_time timestamptz; end_time timestamptz; deadline timestamptz; retained_until timestamptz;
BEGIN
 IF p_operation IS NULL OR p_operation NOT IN ('issue','revoke','create','accept','cancel') OR p_key IS NULL OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$' OR p_payload IS NULL OR jsonb_typeof(p_payload)<>'object' OR octet_length(p_payload::text)>16384
 THEN RETURN app.e8n_error(422,'invalid_request'); END IF;
 IF (p_operation IN ('issue','revoke') AND p_payload<>'{}'::jsonb) OR
 (p_operation='create' AND ((SELECT count(*) FROM jsonb_object_keys(p_payload))<>2 OR NOT(p_payload ?& ARRAY['destination_digest','terms']) OR jsonb_typeof(p_payload->'destination_digest') IS DISTINCT FROM 'string' OR coalesce(p_payload->>'destination_digest','') !~ '^[0-9a-f]{64}$')) OR
 (p_operation='accept' AND ((SELECT count(*) FROM jsonb_object_keys(p_payload))<>3 OR NOT(p_payload ?& ARRAY['challenge_id','revision','terms']) OR jsonb_typeof(p_payload->'challenge_id') IS DISTINCT FROM 'string' OR jsonb_typeof(p_payload->'revision') IS DISTINCT FROM 'number')) OR
 (p_operation='cancel' AND ((SELECT count(*) FROM jsonb_object_keys(p_payload))<>3 OR NOT(p_payload ?& ARRAY['challenge_id','revision','reason']) OR jsonb_typeof(p_payload->'challenge_id') IS DISTINCT FROM 'string' OR jsonb_typeof(p_payload->'revision') IS DISTINCT FROM 'number' OR jsonb_typeof(p_payload->'reason') IS DISTINCT FROM 'string'))
 THEN RETURN app.e8n_error(422,'invalid_request'); END IF;
 semantic_hash:=encode(sha256(convert_to(jsonb_build_object('operation',p_operation,'epoch',p_epoch,'payload',p_payload)::text,'UTF8')),'hex');
 initial_a:=app.e8n_context(p_issuer,p_subject,p_epoch);
 IF initial_a.id IS NULL THEN RETURN app.e8n_error(409,'account_context_unavailable'); END IF;
 IF p_operation IN ('issue','create','accept') AND NOT app.e8n_gate() THEN RETURN app.e8n_error(503,'nemesis_activation_unavailable'); END IF;
 -- Binding discovery takes no locks. Replay may refer to an already consumed or
 -- rotated destination code; its immutable entity determines the pair instead.
 SELECT * INTO receipt FROM app.nemesis_receipts WHERE owner_id=initial_a.id AND operation=p_operation AND key=p_key;
 IF p_operation='create' THEN
 IF receipt.entity_id IS NOT NULL THEN SELECT * INTO c FROM app.nemesis_challenges WHERE id=receipt.entity_id; peer_id:=c.invitee_id;
 ELSE SELECT * INTO code_row FROM app.nemesis_share_codes WHERE digest=p_payload->>'destination_digest'; peer_id:=code_row.owner_id; END IF;
 ELSIF p_operation IN ('accept','cancel') THEN
 BEGIN challenge_id:=(p_payload->>'challenge_id')::uuid; EXCEPTION WHEN invalid_text_representation THEN RETURN app.e8n_error(422,'invalid_request'); END;
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=challenge_id;
 IF c.id IS NULL OR NOT coalesce(initial_a.id IN (c.inviter_id,c.invitee_id),false) THEN RETURN app.e8n_error(404,'nemesis_not_found'); END IF;
 IF p_operation='accept' THEN peer_id:=CASE WHEN c.inviter_id=initial_a.id THEN c.invitee_id ELSE c.inviter_id END; END IF;
 END IF;
 -- All accounts, all counters, then the complete candidate/expired-slot set.
 PERFORM 1 FROM app.user_accounts WHERE id IN(initial_a.id,peer_id) ORDER BY id FOR UPDATE;
 PERFORM 1 FROM app.sync_counters WHERE owner_id IN(initial_a.id,peer_id) ORDER BY owner_id FOR UPDATE;
 SELECT * INTO a FROM app.user_accounts WHERE id=initial_a.id;
 IF a.state<>'active' OR a.generation<>initial_a.generation OR a.issuer<>p_issuer OR a.subject<>p_subject OR app.subject_blocked(p_issuer,p_subject) THEN RETURN app.e8n_error(409,'account_context_unavailable'); END IF;
 IF NOT EXISTS(SELECT 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch) THEN RETURN app.e8n_error(409,'sync_epoch_changed'); END IF;
 IF p_operation IN ('issue','create','accept') AND NOT app.e8n_gate() THEN RETURN app.e8n_error(503,'nemesis_activation_unavailable'); END IF;
 IF p_operation='accept' THEN
 SELECT array_agg(id ORDER BY id) INTO ids FROM app.nemesis_challenges WHERE id=challenge_id OR id IN(SELECT s.challenge_id FROM app.nemesis_slots s WHERE s.owner_id IN(a.id,peer_id));
 PERFORM 1 FROM app.nemesis_challenges WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
 ELSIF c.id IS NOT NULL THEN PERFORM 1 FROM app.nemesis_challenges WHERE id=c.id FOR UPDATE;
 END IF;
 t:=app.e8n_clock();
 SELECT * INTO receipt FROM app.nemesis_receipts WHERE owner_id=a.id AND operation=p_operation AND key=p_key;
 IF receipt.owner_id IS NOT NULL THEN
 IF receipt.request_hash<>semantic_hash OR receipt.generation<>a.generation OR receipt.sync_epoch<>p_epoch THEN RETURN app.e8n_error(409,'idempotency_key_reused'); END IF;
 IF receipt.entity_id IS NOT NULL THEN
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=receipt.entity_id;
 IF c.id IS NULL OR NOT coalesce(a.id IN(c.inviter_id,c.invitee_id),false) OR NOT app.e8n_access(c) THEN RETURN app.e8n_error(404,'nemesis_not_found'); END IF;
 END IF;
 IF receipt.http_status>=400 THEN RETURN jsonb_build_object('ok',false,'http_status',receipt.http_status,'code',receipt.code,'response',NULL,'replayed',true); END IF;
 IF p_operation='issue' AND NOT EXISTS(SELECT 1 FROM app.nemesis_share_codes WHERE owner_id=a.id AND digest=encode(sha256(convert_to(receipt.response->>'destination_code','UTF8')),'hex') AND revoked_at IS NULL AND consumed_at IS NULL AND expires_at>t AND generation=a.generation AND sync_epoch=p_epoch) THEN RETURN app.e8n_error(409,'idempotency_result_expired'); END IF;
 IF receipt.response IS NULL OR receipt.response_expires_at<=t THEN
 RETURN app.e8n_error(409,'idempotency_result_expired');
 ELSE response:=receipt.response;
 -- Effective expiry/end may advance without a persisted revision or worker.
 IF c.id IS NOT NULL THEN
   response := app.e8n_metadata(c, a.id, t);
 END IF;
 END IF;
 RETURN jsonb_build_object('ok',receipt.http_status<400,'http_status',receipt.http_status,'code',receipt.code,'response',response,'replayed',true);
 END IF;
 retained_until:=t+interval '1440 hours';
 IF p_operation='issue' THEN
 generated_code:=rtrim(translate(encode(sha256(convert_to(gen_random_uuid()::text||gen_random_uuid()::text||gen_random_uuid()::text,'UTF8')),'base64'),'+/','-_'),'=');
 IF (SELECT count(*) FROM app.nemesis_admissions WHERE owner_id=a.id AND kind='issue' AND admitted_at>t-interval '24 hours')>=5 THEN failure:='nemesis_rate_limited';http:=429;
 ELSE
 INSERT INTO app.nemesis_admissions VALUES(a.id,'issue',p_key,t);
 INSERT INTO app.nemesis_share_codes(owner_id,digest,generation,sync_epoch,issued_at,expires_at) VALUES(a.id,encode(sha256(convert_to(generated_code,'UTF8')),'hex'),a.generation,p_epoch,t,t+interval '24 hours')
 ON CONFLICT(owner_id) DO UPDATE SET digest=EXCLUDED.digest,generation=EXCLUDED.generation,sync_epoch=EXCLUDED.sync_epoch,issued_at=EXCLUDED.issued_at,expires_at=EXCLUDED.expires_at,revoked_at=NULL,consumed_at=NULL;
 response:=jsonb_build_object('destination_code',generated_code,'issued_at',app.e8n_utc(t),'expires_at',app.e8n_utc(t+interval '24 hours'));retained_until:=t+interval '24 hours';
 END IF;
 ELSIF p_operation='revoke' THEN
 UPDATE app.nemesis_share_codes SET revoked_at=t WHERE owner_id=a.id AND revoked_at IS NULL AND consumed_at IS NULL;
 response:=jsonb_build_object('revoked',true);
 ELSIF p_operation='create' THEN
 terms:=p_payload->'terms';
 IF NOT app.e8n_terms_valid(terms) THEN RETURN app.e8n_error(422,'invalid_terms'); END IF;
 -- Every new key is durable admission, including invalid destinations and 429.
 INSERT INTO app.nemesis_admissions VALUES(a.id,'attempt',p_key,t);
 IF (SELECT count(*) FROM app.nemesis_admissions WHERE owner_id=a.id AND kind='attempt' AND admitted_at>t-interval '15 minutes')>20 THEN failure:='nemesis_rate_limited';http:=429;
 ELSE
 SELECT * INTO code_row FROM app.nemesis_share_codes WHERE digest=p_payload->>'destination_digest';
 SELECT * INTO peer FROM app.user_accounts WHERE id=peer_id;
 IF code_row.owner_id IS NULL OR peer_id=a.id OR code_row.owner_id IS DISTINCT FROM peer_id OR peer.state IS DISTINCT FROM 'active' OR code_row.generation IS DISTINCT FROM peer.generation OR code_row.sync_epoch<>p_epoch OR code_row.expires_at<=t OR code_row.consumed_at IS NOT NULL OR code_row.revoked_at IS NOT NULL OR app.subject_blocked(peer.issuer,peer.subject)
 THEN failure:='destination_unavailable';http:=409;
 ELSIF (SELECT count(*) FROM app.nemesis_admissions WHERE owner_id=a.id AND kind='invite' AND admitted_at>t-interval '24 hours')>=5 OR
 (SELECT count(*) FROM app.nemesis_challenges WHERE inviter_id=a.id AND status='invited' AND expires_at>t)>=3 OR
 (SELECT count(*) FROM app.nemesis_challenges WHERE invitee_id=peer_id AND status='invited' AND expires_at>t)>=5 THEN failure:='nemesis_rate_limited';http:=429;
 ELSE
 INSERT INTO app.nemesis_admissions VALUES(a.id,'invite',p_key,t);
 INSERT INTO app.nemesis_challenges(inviter_id,invitee_id,inviter_generation,invitee_generation,sync_epoch,status,terms,created_at,expires_at)
 VALUES(a.id,peer_id,a.generation,peer.generation,p_epoch,'invited',terms,t,t+interval '168 hours') RETURNING * INTO c;
 UPDATE app.nemesis_share_codes SET consumed_at=t WHERE owner_id=peer_id;
 response:=app.e8n_metadata(c,a.id,t);http:=201;
 END IF; END IF;
 ELSE
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=challenge_id;
 IF NOT app.e8n_access(c) THEN RETURN app.e8n_error(404,'nemesis_not_found'); END IF;
 IF p_payload->>'revision' IS NULL OR p_payload->>'revision' !~ '^[1-9][0-9]{0,9}$' OR (p_payload->>'revision')::bigint<>c.revision THEN failure:='nemesis_revision_changed';http:=409;
 ELSIF c.revision=2147483647 THEN failure:='revision_exhausted';http:=409;
 ELSIF p_operation='cancel' THEN
 IF p_payload->>'reason' NOT IN('withdrawn','declined','sharing_revoked') OR
 (c.status='invited' AND ((a.id=c.inviter_id AND p_payload->>'reason'<>'withdrawn') OR(a.id=c.invitee_id AND p_payload->>'reason'<>'declined'))) OR
 (c.status IN('active','finished') AND p_payload->>'reason'<>'sharing_revoked') THEN failure:='invalid_cancel_reason';http:=409;
 ELSE
 IF c.status<>'cancelled' THEN UPDATE app.nemesis_challenges SET status='cancelled',cancel_reason=p_payload->>'reason',revision=revision+1 WHERE id=c.id RETURNING * INTO c; DELETE FROM app.nemesis_slots slot WHERE slot.challenge_id=c.id; END IF;
 response:=app.e8n_metadata(c,a.id,t);
 END IF;
 ELSE
 terms:=p_payload->'terms';
 IF a.id<>c.invitee_id OR c.status<>'invited' THEN failure:='nemesis_accept_unavailable';http:=409;
 ELSIF NOT isfinite(t)
       OR (t AT TIME ZONE 'UTC')::date
            NOT BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'
       OR (t AT TIME ZONE (c.terms->>'time_zone'))::date
            NOT BETWEEN DATE '0001-01-01' AND DATE '9999-12-31' THEN
   failure := 'period_calendar_date_unavailable';
   http := 409;
 ELSIF c.expires_at<=t THEN UPDATE app.nemesis_challenges SET status='cancelled',cancel_reason='expired',revision=revision+1 WHERE id=c.id RETURNING * INTO c;failure:='nemesis_accept_unavailable';http:=409;
 ELSIF terms IS DISTINCT FROM c.terms OR NOT app.e8n_terms_valid(terms) THEN failure:='nemesis_terms_changed';http:=409;
 ELSE
 UPDATE app.nemesis_challenges SET status='finished',revision=revision+1 WHERE id=ANY(ids) AND status='active' AND end_at<=t;
 DELETE FROM app.nemesis_slots s USING app.nemesis_challenges old WHERE s.challenge_id=old.id AND old.id=ANY(ids) AND old.status<>'active';
 IF EXISTS(SELECT 1 FROM app.nemesis_slots WHERE owner_id IN(a.id,peer_id)) THEN failure:='nemesis_accept_unavailable';http:=409;
 ELSE
 BEGIN
 start_day:=(t AT TIME ZONE (terms->>'time_zone'))::date+1;
 start_time:=app.e8n_boundary(start_day,terms->>'time_zone');start_day:=(start_time AT TIME ZONE(terms->>'time_zone'))::date;
 end_day:=start_day+(terms->>'duration_days')::integer;
 end_time:=app.e8n_boundary(end_day,terms->>'time_zone');deadline:=end_time+interval '720 hours';
 -- Both UTC instants and every accepted-zone civil representation must
 -- fit the supported wire/Python calendar, including the accepted clock.
 IF start_day IS NULL OR end_day IS NULL
    OR NOT isfinite(start_day) OR NOT isfinite(end_day)
    OR start_day NOT BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'
    OR end_day NOT BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'
    OR start_time <= t OR EXISTS (
      SELECT 1
      FROM unnest(ARRAY[t, start_time, end_time, deadline]) AS clocks(instant)
      WHERE instant IS NULL OR NOT isfinite(instant)
         OR (instant AT TIME ZONE 'UTC')::date
              NOT BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'
         OR (instant AT TIME ZONE (terms->>'time_zone'))::date
              NOT BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'
    ) THEN
   failure := 'period_calendar_date_unavailable';
   http := 409;
 END IF;
 FOR day IN SELECT generate_series(start_day::timestamp,(end_day-1)::timestamp,interval '1 day')::date LOOP
 IF (app.e8n_boundary(day,terms->>'time_zone') AT TIME ZONE(terms->>'time_zone'))::date<>day THEN failure:='period_calendar_date_unavailable';http:=409; END IF;
 END LOOP;
 EXCEPTION WHEN datetime_field_overflow OR invalid_parameter_value THEN failure:='period_calendar_date_unavailable';http:=409;
 END;
 IF failure IS NULL AND (
 (SELECT count(*) FROM app.user_profiles WHERE owner_id IN(a.id,peer_id) AND deleted_at IS NULL AND time_zone=terms->>'time_zone')<>2 OR
 EXISTS(SELECT 1 FROM app.diary_days WHERE owner_id IN(a.id,peer_id) AND deleted_at IS NULL AND local_date>=start_day AND local_date<end_day AND time_zone<>terms->>'time_zone') OR
 EXISTS(SELECT 1 FROM app.meals WHERE owner_id IN(a.id,peer_id) AND deleted_at IS NULL AND local_date>=start_day AND local_date<end_day AND time_zone<>terms->>'time_zone')) THEN failure:='nemesis_axis_unavailable';http:=409; END IF;
 IF failure IS NULL THEN
 UPDATE app.nemesis_challenges SET status='active',accepted_at=t,start_date=start_day,end_date=end_day,start_at=start_time,end_at=end_time,deadline_at=deadline,result_status='provisional',revision=revision+1 WHERE id=c.id RETURNING * INTO c;
 PERFORM app.e8n_initialize(c.id,t);
 INSERT INTO app.nemesis_slots(owner_id,challenge_id) SELECT x,c.id FROM unnest(ARRAY[a.id,peer_id]) x ORDER BY x;
 response:=app.e8n_metadata(c,a.id,t);
 END IF; END IF; END IF;
 END IF; END IF;
 IF failure IS NOT NULL THEN response:=NULL; END IF;
 INSERT INTO app.nemesis_receipts(owner_id,operation,key,request_hash,generation,sync_epoch,entity_id,accepted_revision,http_status,code,response,created_at,response_expires_at)
 VALUES(a.id,p_operation,p_key,semantic_hash,a.generation,p_epoch,c.id,c.revision,http,coalesce(failure,'accepted'),response,t,retained_until);
 RETURN jsonb_build_object('ok',failure IS NULL,'http_status',http,'code',coalesce(failure,'accepted'),'response',response,'replayed',false);
END $$;
