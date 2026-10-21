-- Provision NOLOGIN exporter before migration (init-db/provisioner).
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='calorie_app_deletion_exporter') THEN
  RAISE EXCEPTION 'provision deletion exporter base role before migration';
 END IF;
 IF EXISTS(SELECT FROM pg_roles WHERE rolname='calorie_app_deletion_exporter'
   AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
 OR EXISTS(SELECT FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
   WHERE r.rolname='calorie_app_deletion_exporter')
 OR EXISTS(SELECT FROM pg_roles WHERE rolname IN('calorie_app_api','calorie_app_worker',
   'calorie_app_ai_worker','calorie_app_motivation_worker','calorie_app_nemesis_worker',
   'calorie_app_nemesis_finalizer','calorie_app_deletion_operator')
   AND pg_has_role(oid,'calorie_app_deletion_exporter','MEMBER')) THEN
  RAISE EXCEPTION 'unsafe exporter base role or runtime membership';
 END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS ledger_crypto;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA ledger_crypto;
-- Refuse an extension resolved from an unexpected, potentially writable schema.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
   WHERE e.extname='pgcrypto' AND n.nspname='ledger_crypto') THEN
  RAISE EXCEPTION 'pgcrypto must be installed in ledger_crypto';
 END IF;
END $$;
REVOKE ALL ON SCHEMA ledger_crypto FROM PUBLIC;
CREATE TABLE IF NOT EXISTS app.deletion_ledger_source (
 id integer PRIMARY KEY CHECK(id=1), installation_id uuid NOT NULL UNIQUE,
 stream_id uuid NOT NULL UNIQUE, anchor_id uuid NOT NULL UNIQUE, epoch uuid NOT NULL,
 issuer text, receiver_id uuid, source_key bytea, ack_key bytea,
 enabled boolean NOT NULL DEFAULT false, next_sequence bigint NOT NULL DEFAULT 1 CHECK(next_sequence>0),
 head_hash text NOT NULL DEFAULT repeat('0',64) CHECK(head_hash ~ '^[0-9a-f]{64}$'),
 ack_sequence bigint NOT NULL DEFAULT 0 CHECK(ack_sequence>=0),
 ack_hash text NOT NULL DEFAULT repeat('0',64) CHECK(ack_hash ~ '^[0-9a-f]{64}$'),
 CHECK(ack_sequence<next_sequence), CHECK(NOT enabled OR
   (issuer IS NOT NULL AND receiver_id IS NOT NULL AND octet_length(source_key)=32 AND octet_length(ack_key)=32))
);
INSERT INTO app.deletion_ledger_source(id,installation_id,stream_id,anchor_id,epoch)
 SELECT 1,gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),sync_epoch FROM app.installation_state
 ON CONFLICT(id) DO NOTHING;
CREATE TABLE IF NOT EXISTS app.deletion_ledger_events (
 sequence bigint PRIMARY KEY CHECK(sequence>0), event_id uuid NOT NULL UNIQUE,
 operation_id uuid, stage text NOT NULL, outcome text NOT NULL, attempt uuid,
 content text NOT NULL, content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
 previous_hash text NOT NULL CHECK(previous_hash ~ '^[0-9a-f]{64}$'),
 chain_hash text NOT NULL UNIQUE CHECK(chain_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE IF NOT EXISTS app.deletion_ledger_operations (
 operation_id uuid PRIMARY KEY REFERENCES app.account_deletion_jobs(operation_id),
 begin_sequence bigint NOT NULL REFERENCES app.deletion_ledger_events(sequence),
 provider_sequence bigint REFERENCES app.deletion_ledger_events(sequence),
 provider_token uuid, provider_until timestamptz, provider_result text,
 provider_result_sequence bigint REFERENCES app.deletion_ledger_events(sequence),
 confirm_sequence bigint REFERENCES app.deletion_ledger_events(sequence),
 purge_intent_sequence bigint REFERENCES app.deletion_ledger_events(sequence),
 purge_sequence bigint REFERENCES app.deletion_ledger_events(sequence)
);
CREATE TABLE IF NOT EXISTS app.deletion_ledger_receipts (
 sequence bigint PRIMARY KEY REFERENCES app.deletion_ledger_events(sequence),
 chain_hash text NOT NULL, receiver_id uuid NOT NULL, mac text NOT NULL,
 received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS app._ledger_account_context (
 transaction_id bigint PRIMARY KEY, account_id uuid NOT NULL, operation_id uuid NOT NULL
);
DO $$ DECLARE r record; t text; BEGIN
 FOREACH t IN ARRAY ARRAY['deletion_ledger_source','deletion_ledger_events',
 'deletion_ledger_operations','deletion_ledger_receipts','_ledger_account_context'] LOOP
  EXECUTE format('REVOKE ALL ON app.%I FROM PUBLIC',t);
  FOR r IN SELECT rolname FROM pg_roles WHERE rolname LIKE 'calorie_app_%' AND rolname<>'calorie_app_migrator' LOOP
   EXECUTE format('REVOKE ALL ON app.%I FROM %I',t,r.rolname);
  END LOOP;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION app._ledger_source_ready() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF NOT EXISTS(SELECT FROM app.deletion_ledger_source s JOIN app.installation_state i ON i.id=s.id
   WHERE s.enabled AND s.epoch=i.sync_epoch) THEN
  RAISE EXCEPTION 'deletion ledger unconfigured or restore fenced' USING ERRCODE='23514';
 END IF;
END $$;
CREATE OR REPLACE FUNCTION app._ledger_append(p_operation uuid,p_stage text,p_outcome text,p_attempt uuid DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE s app.deletion_ledger_source%ROWTYPE; j app.account_deletion_jobs%ROWTYPE;
 n bigint; eid uuid:=gen_random_uuid(); body text; digest text; chain text;
BEGIN
 PERFORM app._ledger_source_ready();
 SELECT * INTO s FROM app.deletion_ledger_source WHERE id=1 FOR UPDATE;
 -- A freeze can win while this append waits. Recheck under the acquired lock.
 IF NOT s.enabled OR s.epoch IS DISTINCT FROM (SELECT sync_epoch FROM app.installation_state WHERE id=1) THEN
  RAISE EXCEPTION 'deletion ledger restore fenced after wait' USING ERRCODE='23514';
 END IF;
 IF p_operation IS NOT NULL THEN
  SELECT * INTO STRICT j FROM app.account_deletion_jobs WHERE operation_id=p_operation;

 END IF;
 n:=s.next_sequence;
 body:=jsonb_build_object('version',1,'installation_id',s.installation_id,'stream_id',s.stream_id,
 'anchor_id',s.anchor_id,'sequence',n,'event_id',eid,'operation_id',p_operation,
 'account_id',j.account_id,'issuer',coalesce(j.issuer,s.issuer),'subject',j.subject,
 'expected_generation',j.expected_generation,'deleting_generation',j.deleting_generation,
 'stage',p_stage,'outcome',p_outcome,'attempt',p_attempt)::text;
 digest:=encode(sha256(convert_to(body,'UTF8')),'hex');
 chain:=encode(sha256(decode(s.head_hash,'hex')||decode(digest,'hex')),'hex');
 INSERT INTO app.deletion_ledger_events VALUES(n,eid,p_operation,p_stage,p_outcome,p_attempt,body,digest,s.head_hash,chain);
 UPDATE app.deletion_ledger_source SET next_sequence=n+1,head_hash=chain WHERE id=1;
 RETURN n;
END $$;
CREATE OR REPLACE FUNCTION app._ledger_require_ack(p_sequence bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 PERFORM app._ledger_source_ready();
 IF p_sequence IS NULL OR NOT EXISTS(SELECT FROM app.deletion_ledger_source WHERE id=1 AND ack_sequence>=p_sequence) THEN
  RAISE EXCEPTION 'authenticated durable prefix ACK required' USING ERRCODE='23514';
 END IF;
END $$;
CREATE OR REPLACE FUNCTION app.ledger_configure(p_issuer text,p_receiver uuid,p_source_key bytea,p_ack_key bytea)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE legacy record;
BEGIN
 PERFORM 1 FROM app.deletion_ledger_source WHERE id=1 FOR UPDATE;
 IF EXISTS(SELECT FROM app.deletion_ledger_events) OR p_issuer IS NULL OR length(p_issuer)=0
   OR p_receiver IS NULL OR octet_length(p_source_key) IS DISTINCT FROM 32
   OR octet_length(p_ack_key) IS DISTINCT FROM 32 OR p_source_key=p_ack_key THEN
  RAISE EXCEPTION 'invalid or already configured cutover' USING ERRCODE='23514';
 END IF;
 UPDATE app.deletion_ledger_source SET issuer=p_issuer,receiver_id=p_receiver,
   source_key=p_source_key,ack_key=p_ack_key,enabled=true WHERE id=1;
 PERFORM app._ledger_append(NULL,'anchor','cutover_unknown_history');
 -- Old jobs remain unknown; observing them now does not fabricate past coverage.
 FOR legacy IN SELECT operation_id FROM app.account_deletion_jobs ORDER BY account_id LOOP
  PERFORM app._ledger_append(legacy.operation_id,'legacy','unknown');
 END LOOP;
END $$;

-- Preserve the complete current E9->E8->E7->E6->E4 graph, never copy an old purge.
DO $$ BEGIN
 IF to_regprocedure('app.begin_account_deletion_pre25(uuid,uuid,integer)') IS NULL THEN
  ALTER FUNCTION app.begin_account_deletion(uuid,uuid,integer) RENAME TO begin_account_deletion_pre25;
  ALTER FUNCTION app.confirm_account_deletion(uuid) RENAME TO confirm_account_deletion_pre25;
  ALTER FUNCTION app.purge_deleted_account(uuid) RENAME TO purge_deleted_account_pre25;
 END IF;
END $$;
CREATE OR REPLACE FUNCTION app.ledger_account_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'active' OR NEW.generation<>1 THEN RAISE EXCEPTION 'new account requires initial lifecycle' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF (NEW.id,NEW.issuer,NEW.subject) IS DISTINCT FROM (OLD.id,OLD.issuer,OLD.subject) THEN
  RAISE EXCEPTION 'account identity is immutable' USING ERRCODE='23514';
 END IF;
 IF (NEW.state,NEW.generation) IS DISTINCT FROM (OLD.state,OLD.generation) AND NOT EXISTS(
  SELECT FROM app._ledger_account_context c JOIN app.account_deletion_jobs j ON j.operation_id=c.operation_id
  WHERE c.transaction_id=txid_current() AND c.account_id=OLD.id AND j.account_id=OLD.id
   AND j.issuer=OLD.issuer AND j.subject=OLD.subject AND j.expected_generation=OLD.generation
   AND NEW.state='deleting' AND NEW.generation=j.deleting_generation) THEN
  RAISE EXCEPTION 'account lifecycle requires ledger producer' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
-- Parent creates job before updating the account. Context is installed by a job trigger,
-- and cannot be written by any runtime role. All are in the same transaction.
CREATE OR REPLACE FUNCTION app.ledger_job_context() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF NOT EXISTS(SELECT FROM app._ledger_account_context WHERE transaction_id=txid_current()
   AND account_id=NEW.account_id AND operation_id=NEW.operation_id) THEN
  PERFORM app._ledger_source_ready();
  INSERT INTO app._ledger_account_context VALUES(txid_current(),NEW.account_id,NEW.operation_id);
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS ledger_job_context ON app.account_deletion_jobs;
CREATE TRIGGER ledger_job_context AFTER INSERT ON app.account_deletion_jobs
 FOR EACH ROW EXECUTE FUNCTION app.ledger_job_context();
DROP TRIGGER IF EXISTS ledger_account_guard ON app.user_accounts;
CREATE TRIGGER ledger_account_guard BEFORE INSERT OR UPDATE OF state,generation,id,issuer,subject ON app.user_accounts
 FOR EACH ROW EXECUTE FUNCTION app.ledger_account_guard();
CREATE OR REPLACE FUNCTION app.begin_account_deletion(p_owner uuid,p_operation uuid,p_generation integer)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE n bigint;
BEGIN
 PERFORM app._ledger_source_ready();
 PERFORM app.begin_account_deletion_pre25(p_owner,p_operation,p_generation);
 IF NOT EXISTS(SELECT FROM app.deletion_ledger_operations WHERE operation_id=p_operation) THEN
  -- Existing pre-cutover jobs never silently become covered operations.
  IF NOT EXISTS(SELECT FROM app._ledger_account_context WHERE transaction_id=txid_current()
    AND operation_id=p_operation AND account_id=p_owner) THEN
   RAISE EXCEPTION 'legacy deletion requires explicit reconciliation' USING ERRCODE='23514';
  END IF;
  n:=app._ledger_append(p_operation,'begin','intent');
  INSERT INTO app.deletion_ledger_operations(operation_id,begin_sequence) VALUES(p_operation,n);
 END IF;
 DELETE FROM app._ledger_account_context WHERE transaction_id=txid_current();
 RETURN p_operation;
END $$;
CREATE OR REPLACE FUNCTION app._ledger_lock(p_operation uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.account_deletion_jobs%ROWTYPE;
BEGIN
 SELECT * INTO STRICT j FROM app.account_deletion_jobs WHERE operation_id=p_operation;
 PERFORM 1 FROM app.user_accounts WHERE id=j.account_id FOR UPDATE;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=j.account_id FOR UPDATE;
 PERFORM 1 FROM app.account_deletion_jobs WHERE operation_id=p_operation FOR UPDATE;
 PERFORM 1 FROM app.deletion_ledger_operations WHERE operation_id=p_operation FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'legacy deletion requires reconciliation' USING ERRCODE='23514'; END IF;
END $$;
CREATE OR REPLACE FUNCTION app.ledger_prepare_provider(p_operation uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE o app.deletion_ledger_operations%ROWTYPE; token uuid:=gen_random_uuid(); n bigint;
BEGIN
 PERFORM app._ledger_lock(p_operation);
 SELECT * INTO STRICT o FROM app.deletion_ledger_operations WHERE operation_id=p_operation;
 PERFORM app._ledger_require_ack(o.begin_sequence);
 IF o.provider_result='confirmed' THEN RETURN o.provider_token; END IF;
 IF o.provider_token IS NOT NULL AND o.provider_until>clock_timestamp() THEN RETURN o.provider_token; END IF;
 IF o.provider_token IS NOT NULL AND o.provider_result IS NULL THEN
  PERFORM app._ledger_append(p_operation,'provider','uncertain',o.provider_token);
 END IF;
 n:=app._ledger_append(p_operation,'provider','intent',token);
 UPDATE app.deletion_ledger_operations SET provider_sequence=n,provider_token=token,
 provider_until=clock_timestamp()+interval '90 seconds',provider_result=NULL,provider_result_sequence=NULL
 WHERE operation_id=p_operation;
 RETURN token;
END $$;
CREATE OR REPLACE FUNCTION app.ledger_provider_target(p_operation uuid,p_token uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE o app.deletion_ledger_operations%ROWTYPE; j app.account_deletion_jobs%ROWTYPE;
BEGIN
 PERFORM app._ledger_lock(p_operation);
 SELECT * INTO STRICT o FROM app.deletion_ledger_operations WHERE operation_id=p_operation;
 SELECT * INTO STRICT j FROM app.account_deletion_jobs WHERE operation_id=p_operation;
 IF o.provider_token IS DISTINCT FROM p_token OR o.provider_until<=clock_timestamp()
   OR o.provider_result IS NOT NULL OR j.identity_confirmed_at IS NOT NULL THEN
  RAISE EXCEPTION 'provider attempt stale or closed' USING ERRCODE='23514';
 END IF;
 PERFORM app._ledger_require_ack(o.provider_sequence);
 RETURN jsonb_build_object('issuer',j.issuer,'subject',j.subject);
END $$;
CREATE OR REPLACE FUNCTION app.ledger_provider_result(p_operation uuid,p_token uuid,p_result text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE o app.deletion_ledger_operations%ROWTYPE; n bigint;
BEGIN
 PERFORM app._ledger_lock(p_operation);
 SELECT * INTO STRICT o FROM app.deletion_ledger_operations WHERE operation_id=p_operation;
 IF p_result NOT IN('confirmed','failed','uncertain') OR p_result IS NULL
   OR o.provider_token IS DISTINCT FROM p_token OR o.provider_until<=clock_timestamp() THEN
  RAISE EXCEPTION 'provider result stale or invalid' USING ERRCODE='23514';
 END IF;
 PERFORM app._ledger_require_ack(o.provider_sequence);
 IF o.provider_result IS NOT NULL THEN
  IF o.provider_result=p_result THEN RETURN; END IF;
  RAISE EXCEPTION 'provider result conflict' USING ERRCODE='23514';
 END IF;
 n:=app._ledger_append(p_operation,'provider',p_result,p_token);
 UPDATE app.deletion_ledger_operations SET provider_result=p_result,provider_result_sequence=n,
 provider_until=CASE WHEN p_result='confirmed' THEN provider_until ELSE clock_timestamp() END
 WHERE operation_id=p_operation;
END $$;
CREATE OR REPLACE FUNCTION app.confirm_account_deletion(p_operation uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE o app.deletion_ledger_operations%ROWTYPE; n bigint;
BEGIN
 PERFORM app._ledger_lock(p_operation);
 SELECT * INTO STRICT o FROM app.deletion_ledger_operations WHERE operation_id=p_operation;
 PERFORM app._ledger_require_ack(o.provider_result_sequence);
 IF o.provider_result IS DISTINCT FROM 'confirmed' THEN RAISE EXCEPTION 'provider outcome uncertain' USING ERRCODE='23514'; END IF;
 IF o.confirm_sequence IS NOT NULL THEN RETURN; END IF;
 PERFORM app.confirm_account_deletion_pre25(p_operation);
 n:=app._ledger_append(p_operation,'confirm','confirmed');
 UPDATE app.deletion_ledger_operations SET confirm_sequence=n WHERE operation_id=p_operation;
END $$;
CREATE OR REPLACE FUNCTION app.ledger_prepare_purge(p_operation uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE o app.deletion_ledger_operations%ROWTYPE; n bigint;
BEGIN
 PERFORM app._ledger_lock(p_operation);
 SELECT * INTO STRICT o FROM app.deletion_ledger_operations WHERE operation_id=p_operation;
 PERFORM app._ledger_require_ack(o.confirm_sequence);
 IF o.purge_intent_sequence IS NOT NULL THEN RETURN; END IF;
 n:=app._ledger_append(p_operation,'purge','intent');
 UPDATE app.deletion_ledger_operations SET purge_intent_sequence=n WHERE operation_id=p_operation;
END $$;
CREATE OR REPLACE FUNCTION app.purge_deleted_account(p_operation uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE o app.deletion_ledger_operations%ROWTYPE; n bigint; j app.account_deletion_jobs%ROWTYPE;
BEGIN
 -- Preserve original account->counter->community->AI->job lock order.
 SELECT * INTO STRICT j FROM app.account_deletion_jobs WHERE operation_id=p_operation;
 PERFORM 1 FROM app.user_accounts WHERE id=j.account_id FOR UPDATE;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=j.account_id FOR UPDATE;
 PERFORM 1 FROM app.community_catalog_state WHERE id=1 FOR UPDATE;
 PERFORM 1 FROM app.ai_controls WHERE id=1 FOR UPDATE;
 PERFORM app._ledger_lock(p_operation);
 SELECT * INTO STRICT o FROM app.deletion_ledger_operations WHERE operation_id=p_operation;
 PERFORM app._ledger_require_ack(o.purge_intent_sequence);
 IF o.purge_sequence IS NOT NULL THEN RETURN; END IF;
 PERFORM app.purge_deleted_account_pre25(p_operation);
 n:=app._ledger_append(p_operation,'purge','confirmed');
 UPDATE app.deletion_ledger_operations SET purge_sequence=n WHERE operation_id=p_operation;
END $$;

CREATE OR REPLACE FUNCTION app.ledger_status(p_operation uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE j app.account_deletion_jobs%ROWTYPE; o app.deletion_ledger_operations%ROWTYPE; a bigint;
BEGIN
 PERFORM app._ledger_source_ready();
 SELECT * INTO STRICT j FROM app.account_deletion_jobs WHERE operation_id=p_operation;
 SELECT * INTO o FROM app.deletion_ledger_operations WHERE operation_id=p_operation;
 SELECT ack_sequence INTO a FROM app.deletion_ledger_source WHERE id=1;
 RETURN to_jsonb(j)||jsonb_build_object('ledger_version',1,'legacy_unknown',o.operation_id IS NULL,
 'ledger_complete',coalesce(o.purge_sequence<=a,false),'provider_result',o.provider_result);
END $$;
CREATE OR REPLACE FUNCTION app.ledger_batch(p_start bigint,p_limit integer DEFAULT 64) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE s app.deletion_ledger_source%ROWTYPE; body text;
BEGIN
 PERFORM app._ledger_source_ready();
 IF p_start IS NULL OR p_start<1 OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 128 THEN
  RAISE EXCEPTION 'invalid bounded ledger batch' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT s FROM app.deletion_ledger_source WHERE id=1;
 SELECT jsonb_build_object('version',1,'installation_id',s.installation_id,'stream_id',s.stream_id,
 'anchor_id',s.anchor_id,'receiver_id',s.receiver_id,'events',coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.sequence),'[]'::jsonb))::text
 INTO body FROM (SELECT * FROM app.deletion_ledger_events WHERE sequence>=p_start ORDER BY sequence LIMIT p_limit) e;
 IF octet_length(convert_to(body,'UTF8'))>1048576 THEN
  RAISE EXCEPTION 'ledger batch exceeds byte bound; reduce limit' USING ERRCODE='54000'; END IF;
 RETURN jsonb_build_object('body',body,'mac',encode(ledger_crypto.hmac(
  convert_to('deletion-ledger-source-v1'||chr(10)||body,'UTF8'),s.source_key,'sha256'),'hex'));
END $$;
CREATE OR REPLACE FUNCTION app.ledger_ack(p_installation uuid,p_stream uuid,p_anchor uuid,p_receiver uuid,p_sequence bigint,p_hash text,p_mac text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE s app.deletion_ledger_source%ROWTYPE; frame text; expected text;
BEGIN
 PERFORM app._ledger_source_ready();
 SELECT * INTO STRICT s FROM app.deletion_ledger_source WHERE id=1 FOR UPDATE;
 IF NOT s.enabled OR s.epoch IS DISTINCT FROM (SELECT sync_epoch FROM app.installation_state WHERE id=1) THEN
  RAISE EXCEPTION 'deletion ledger restore fenced after wait' USING ERRCODE='23514'; END IF;
 frame:=concat_ws(chr(10),'deletion-ledger-ack-v1',p_installation,p_stream,p_anchor,p_receiver,p_sequence,p_hash);
 expected:=encode(ledger_crypto.hmac(convert_to(frame,'UTF8'),s.ack_key,'sha256'),'hex');
 IF (s.installation_id,s.stream_id,s.anchor_id,s.receiver_id) IS DISTINCT FROM (p_installation,p_stream,p_anchor,p_receiver)
   OR p_mac IS DISTINCT FROM expected OR p_sequence IS NULL OR p_sequence<s.ack_sequence
   OR NOT EXISTS(SELECT FROM app.deletion_ledger_events WHERE sequence=p_sequence AND chain_hash=p_hash) THEN
  RAISE EXCEPTION 'unauthenticated conflicting or stale ledger ACK' USING ERRCODE='23514';
 END IF;
 INSERT INTO app.deletion_ledger_receipts(sequence,chain_hash,receiver_id,mac)
 VALUES(p_sequence,p_hash,p_receiver,p_mac) ON CONFLICT(sequence) DO NOTHING;
 UPDATE app.deletion_ledger_source SET ack_sequence=p_sequence,ack_hash=p_hash WHERE id=1;
END $$;

-- Revoke direct job reads: old resume() must fail BEFORE its network call.
REVOKE ALL ON app.account_deletion_jobs FROM calorie_app_deletion_operator;
-- Remove every column grant too, including inherited grants verified by provisioner.
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT attname FROM pg_attribute WHERE attrelid='app.account_deletion_jobs'::regclass AND attnum>0 AND NOT attisdropped LOOP
  EXECUTE format('REVOKE SELECT(%I) ON app.account_deletion_jobs FROM calorie_app_deletion_operator',c.attname);
 END LOOP;
END $$;
DO $$ DECLARE item record; r record; BEGIN
 FOR item IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='app' AND (p.proname ~ '^_?ledger_' OR p.proname IN
 ('begin_account_deletion','confirm_account_deletion','purge_deleted_account',
  'begin_account_deletion_pre25','confirm_account_deletion_pre25','purge_deleted_account_pre25')) LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',item.signature);
  FOR r IN SELECT rolname FROM pg_roles WHERE rolname LIKE 'calorie_app_%' AND rolname<>'calorie_app_migrator' LOOP
   EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I',item.signature,r.rolname);
  END LOOP;
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA app TO calorie_app_deletion_operator,calorie_app_deletion_exporter;
GRANT EXECUTE ON FUNCTION app.begin_account_deletion(uuid,uuid,integer),app.confirm_account_deletion(uuid),
 app.purge_deleted_account(uuid),app.ledger_status(uuid),app.ledger_prepare_provider(uuid),
 app.ledger_provider_target(uuid,uuid),app.ledger_provider_result(uuid,uuid,text),app.ledger_prepare_purge(uuid)
 TO calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.ledger_batch(bigint,integer),app.ledger_ack(uuid,uuid,uuid,uuid,bigint,text,text)
 TO calorie_app_deletion_exporter;

CREATE OR REPLACE FUNCTION app.ledger_export_position() RETURNS bigint
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT ack_sequence+1 FROM app.deletion_ledger_source WHERE id=1
$$;
REVOKE ALL ON FUNCTION app.ledger_export_position() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.ledger_export_position() TO calorie_app_deletion_exporter;
CREATE OR REPLACE FUNCTION app.ledger_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 RAISE EXCEPTION 'deletion ledger is append only' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION app.ledger_append_only() FROM PUBLIC;
DROP TRIGGER IF EXISTS ledger_events_immutable ON app.deletion_ledger_events;
CREATE TRIGGER ledger_events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON app.deletion_ledger_events
 FOR EACH STATEMENT EXECUTE FUNCTION app.ledger_append_only();
DROP TRIGGER IF EXISTS ledger_receipts_immutable ON app.deletion_ledger_receipts;
CREATE TRIGGER ledger_receipts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON app.deletion_ledger_receipts
 FOR EACH STATEMENT EXECUTE FUNCTION app.ledger_append_only();
CREATE OR REPLACE FUNCTION app.ledger_downgrade_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF NEW.version_num NOT IN('0025_deletion_ledger','0024_e9_history_graph') THEN
  RAISE EXCEPTION 'cannot downgrade deletion safety below0024' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.ledger_downgrade_guard() FROM PUBLIC;
DROP TRIGGER IF EXISTS ledger_downgrade_guard ON app.alembic_version;
CREATE TRIGGER ledger_downgrade_guard BEFORE UPDATE ON app.alembic_version
 FOR EACH ROW EXECUTE FUNCTION app.ledger_downgrade_guard();
CREATE TABLE IF NOT EXISTS app.deletion_ledger_restore_receipts (
 receipt_hash text PRIMARY KEY CHECK(receipt_hash ~ '^[0-9a-f]{64}$'),
 receipt jsonb NOT NULL, received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $$ DECLARE r record; BEGIN
 REVOKE ALL ON app.deletion_ledger_restore_receipts FROM PUBLIC;
 FOR r IN SELECT rolname FROM pg_roles WHERE rolname LIKE 'calorie_app_%' AND rolname<>'calorie_app_migrator' LOOP
  EXECUTE format('REVOKE ALL ON app.deletion_ledger_restore_receipts FROM %I',r.rolname);
 END LOOP;
END $$;
DROP TRIGGER IF EXISTS ledger_restore_receipts_immutable ON app.deletion_ledger_restore_receipts;
CREATE TRIGGER ledger_restore_receipts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON app.deletion_ledger_restore_receipts
 FOR EACH STATEMENT EXECUTE FUNCTION app.ledger_append_only();
-- Ledger tables do not change the E9 projection algorithm/release0024.
-- Keep its gate/release/active state and every activation precondition; only
-- accept the new actual Alembic head for a fresh/repeated activation.
CREATE OR REPLACE FUNCTION app.e8n_activate(p_epoch uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch FOR SHARE;
 IF NOT FOUND OR NOT app.e8n_runtime_ready()
 OR (SELECT array_agg(version_num) FROM app.alembic_version) IS DISTINCT FROM ARRAY['0025_deletion_ledger']::varchar[]
 OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer' AND NOT rolcanlogin
 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT has_function_privilege('calorie_app_nemesis_finalizer','app.e8n_finalize_batch(integer)','EXECUTE')
 OR EXISTS(SELECT 1 FROM app.nemesis_challenges WHERE sync_epoch<>p_epoch AND status<>'cancelled')
 THEN RAISE EXCEPTION 'Nemesis activation preconditions unavailable' USING ERRCODE='55000'; END IF;
 UPDATE app.nemesis_control SET sync_epoch=p_epoch,enabled=true,schema_revision='0024_e9_history_graph',
 initializer_revision='0021_initializer_v1',projector_revision='0024_projection_v1',finalizer_revision='0021_finalizer_v1' WHERE id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Nemesis control unavailable' USING ERRCODE='55000'; END IF;
END $$;
