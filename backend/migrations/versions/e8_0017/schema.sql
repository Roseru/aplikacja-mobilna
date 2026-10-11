CREATE TABLE app.nemesis_control (
 id integer PRIMARY KEY CHECK(id=1), sync_epoch uuid NOT NULL,
 enabled boolean NOT NULL DEFAULT false,
 projector_revision text, finalizer_revision text,
 CHECK(NOT enabled OR (projector_revision IS NOT NULL AND finalizer_revision IS NOT NULL))
);
INSERT INTO app.nemesis_control(id,sync_epoch) SELECT 1,sync_epoch FROM app.installation_state WHERE id=1;
CREATE TABLE app.nemesis_challenges (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 inviter_id uuid REFERENCES app.user_accounts(id), invitee_id uuid REFERENCES app.user_accounts(id),
 inviter_generation integer NOT NULL CHECK(inviter_generation>0),
 invitee_generation integer NOT NULL CHECK(invitee_generation>0), sync_epoch uuid NOT NULL,
 revision bigint NOT NULL DEFAULT 1 CHECK(revision BETWEEN 1 AND 2147483647),
 status text NOT NULL CHECK(status IN ('invited','active','finished','cancelled')),
 terms jsonb NOT NULL, created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 accepted_at timestamptz, start_date date, end_date date,
 start_at timestamptz, end_at timestamptz, deadline_at timestamptz,
 result_status text CHECK(result_status='provisional'), cancel_reason text
 CHECK(cancel_reason IN ('withdrawn','declined','sharing_revoked','expired','deleted','restore')),
 CHECK(inviter_id IS DISTINCT FROM invitee_id),
 CHECK(expires_at=created_at+interval '168 hours'),
 CHECK(jsonb_typeof(terms)='object' AND octet_length(terms::text)<=1024),
 CHECK((accepted_at IS NULL AND start_date IS NULL AND end_date IS NULL AND start_at IS NULL AND end_at IS NULL AND deadline_at IS NULL AND result_status IS NULL)
 OR (accepted_at IS NOT NULL AND start_date IS NOT NULL AND end_date IS NOT NULL AND start_at IS NOT NULL AND end_at IS NOT NULL AND deadline_at=end_at+interval '720 hours' AND result_status='provisional' AND start_at>accepted_at AND end_at>start_at AND end_date-start_date=(terms->>'duration_days')::integer)),
 CHECK((status IN ('active','finished') AND accepted_at IS NOT NULL AND cancel_reason IS NULL)
 OR (status='invited' AND accepted_at IS NULL AND cancel_reason IS NULL)
 OR (status='cancelled' AND cancel_reason IS NOT NULL)),
 CHECK((inviter_id IS NOT NULL AND invitee_id IS NOT NULL) OR (status='cancelled' AND cancel_reason='deleted'))
);
CREATE INDEX ix_nemesis_inviter_history ON app.nemesis_challenges(inviter_id,created_at DESC,id DESC);
CREATE INDEX ix_nemesis_invitee_history ON app.nemesis_challenges(invitee_id,created_at DESC,id DESC);
CREATE INDEX ix_nemesis_due ON app.nemesis_challenges(status,expires_at,end_at,id) WHERE status IN ('invited','active');
CREATE TABLE app.nemesis_slots (
 owner_id uuid PRIMARY KEY REFERENCES app.user_accounts(id),
 challenge_id uuid NOT NULL REFERENCES app.nemesis_challenges(id) ON DELETE CASCADE,
 UNIQUE(challenge_id,owner_id)
);
CREATE TABLE app.nemesis_share_codes (
 owner_id uuid PRIMARY KEY REFERENCES app.user_accounts(id), digest varchar(64) NOT NULL UNIQUE CHECK(digest ~ '^[0-9a-f]{64}$'),
 generation integer NOT NULL CHECK(generation>0), sync_epoch uuid NOT NULL,
 issued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 revoked_at timestamptz, consumed_at timestamptz,
 CHECK(expires_at=issued_at+interval '24 hours'), CHECK(NOT(revoked_at IS NOT NULL AND consumed_at IS NOT NULL))
);
CREATE TABLE app.nemesis_receipts (
 owner_id uuid NOT NULL REFERENCES app.user_accounts(id), operation text NOT NULL CHECK(operation IN ('issue','revoke','create','accept','cancel')),
 key uuid NOT NULL, request_hash varchar(64) NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
 generation integer NOT NULL CHECK(generation>0), sync_epoch uuid NOT NULL,
 entity_id uuid, accepted_revision bigint, http_status integer NOT NULL CHECK(http_status BETWEEN 200 AND 599),
 code text NOT NULL, response jsonb, created_at timestamptz NOT NULL,
 response_expires_at timestamptz NOT NULL, PRIMARY KEY(owner_id,operation,key),
 CHECK(response IS NULL OR (jsonb_typeof(response)='object' AND octet_length(response::text)<=1048576)),
 CHECK(response_expires_at>=created_at), CHECK(accepted_revision IS NULL OR accepted_revision>0)
);
CREATE INDEX ix_nemesis_receipt_cleanup ON app.nemesis_receipts(response_expires_at,owner_id,operation,key) WHERE response IS NOT NULL;
CREATE TABLE app.nemesis_admissions (
 owner_id uuid NOT NULL REFERENCES app.user_accounts(id), kind text NOT NULL CHECK(kind IN ('issue','attempt','invite')),
 key uuid NOT NULL, admitted_at timestamptz NOT NULL, PRIMARY KEY(owner_id,kind,key)
);
CREATE INDEX ix_nemesis_admission_window ON app.nemesis_admissions(owner_id,kind,admitted_at);

CREATE FUNCTION app.e8n_terms_valid(p jsonb) RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF p IS NULL OR jsonb_typeof(p) IS DISTINCT FROM 'object' OR jsonb_typeof(p->'scope') IS DISTINCT FROM 'object' THEN RETURN false; END IF;
 RETURN coalesce(p IS NOT NULL AND jsonb_typeof(p)='object' AND
 (SELECT count(*) FROM jsonb_object_keys(p))=4 AND
 p->>'rule_version'='regularity_v1' AND p->'duration_days' IN ('7'::jsonb,'30'::jsonb,'90'::jsonb) AND
 jsonb_typeof(p->'time_zone')='string' AND length(p->>'time_zone') BETWEEN 1 AND 100 AND
 EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=p->>'time_zone') AND
 jsonb_typeof(p->'scope')='object' AND (SELECT count(*) FROM jsonb_object_keys(p->'scope'))=3 AND
 p->'scope'->'regularity'='true'::jsonb AND jsonb_typeof(p->'scope'->'weight_change')='boolean' AND
 jsonb_typeof(p->'scope'->'mean_deficit')='boolean',false);
END $$;
ALTER TABLE app.nemesis_challenges ADD CHECK(app.e8n_terms_valid(terms));
CREATE FUNCTION app.e8n_challenge_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
 IF NEW.id<>OLD.id OR NEW.terms IS DISTINCT FROM OLD.terms OR
 NEW.created_at<>OLD.created_at OR NEW.expires_at<>OLD.expires_at OR NEW.sync_epoch<>OLD.sync_epoch OR
 NEW.inviter_generation<>OLD.inviter_generation OR NEW.invitee_generation<>OLD.invitee_generation OR
 ((NEW.inviter_id IS DISTINCT FROM OLD.inviter_id OR NEW.invitee_id IS DISTINCT FROM OLD.invitee_id) AND NOT
 (NEW.status='cancelled' AND NEW.cancel_reason='deleted' AND (NEW.inviter_id IS NOT DISTINCT FROM OLD.inviter_id OR (NEW.inviter_id IS NULL AND app.deletion_purge_authorized(OLD.inviter_id))) AND (NEW.invitee_id IS NOT DISTINCT FROM OLD.invitee_id OR (NEW.invitee_id IS NULL AND app.deletion_purge_authorized(OLD.invitee_id))))) OR
 NEW.revision<>OLD.revision+1 OR OLD.status='cancelled' AND NEW.status<>'cancelled' OR
 (OLD.status='cancelled' AND NEW.cancel_reason IS DISTINCT FROM OLD.cancel_reason AND NOT(NEW.cancel_reason='deleted' AND (NEW.inviter_id IS NULL OR NEW.invitee_id IS NULL))) OR
 OLD.status='finished' AND NEW.status NOT IN ('finished','cancelled') OR
 OLD.status='active' AND NEW.status NOT IN ('active','finished','cancelled') OR
 (OLD.accepted_at IS NOT NULL AND ROW(NEW.accepted_at,NEW.start_date,NEW.end_date,NEW.start_at,NEW.end_at,NEW.deadline_at,NEW.result_status) IS DISTINCT FROM ROW(OLD.accepted_at,OLD.start_date,OLD.end_date,OLD.start_at,OLD.end_at,OLD.deadline_at,OLD.result_status))
 THEN RAISE EXCEPTION 'immutable Nemesis binding or revision' USING ERRCODE='23514'; END IF;
 END IF; RETURN NEW;
END $$;
CREATE TRIGGER nemesis_challenge_guard BEFORE UPDATE ON app.nemesis_challenges FOR EACH ROW EXECUTE FUNCTION app.e8n_challenge_guard();
CREATE FUNCTION app.e8n_slot_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM app.nemesis_challenges WHERE id=NEW.challenge_id AND status='active' AND NEW.owner_id IN (inviter_id,invitee_id))
 THEN RAISE EXCEPTION 'slot requires active participant' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER nemesis_slot_guard BEFORE INSERT OR UPDATE ON app.nemesis_slots FOR EACH ROW EXECUTE FUNCTION app.e8n_slot_guard();

CREATE FUNCTION app.e8n_slot_consistency() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE candidate uuid; c app.nemesis_challenges%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='nemesis_challenges' THEN candidate:=coalesce(NEW.id,OLD.id); ELSE candidate:=coalesce(NEW.challenge_id,OLD.challenge_id); END IF;
 SELECT * INTO c FROM app.nemesis_challenges WHERE id=candidate;
 IF c.id IS NOT NULL AND ((c.status='active' AND (SELECT count(*) FROM app.nemesis_slots WHERE challenge_id=c.id AND owner_id IN(c.inviter_id,c.invitee_id))<>2) OR(c.status<>'active' AND EXISTS(SELECT 1 FROM app.nemesis_slots WHERE challenge_id=c.id))) THEN RAISE EXCEPTION 'Nemesis active slots must match both participants' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER nemesis_challenge_slots AFTER INSERT OR UPDATE ON app.nemesis_challenges DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.e8n_slot_consistency();
CREATE CONSTRAINT TRIGGER nemesis_slots_consistency AFTER INSERT OR UPDATE OR DELETE ON app.nemesis_slots DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.e8n_slot_consistency();
