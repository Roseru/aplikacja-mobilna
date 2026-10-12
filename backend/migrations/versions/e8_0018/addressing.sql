CREATE TABLE app.nemesis_releases(projector_revision text NOT NULL,finalizer_revision text NOT NULL,PRIMARY KEY(projector_revision,finalizer_revision));
CREATE TABLE app.nemesis_cursors(
 token uuid PRIMARY KEY DEFAULT gen_random_uuid(), requester_id uuid NOT NULL REFERENCES app.user_accounts(id), generation integer NOT NULL,
 sync_epoch uuid NOT NULL, purpose text NOT NULL DEFAULT 'own_metadata' CHECK(purpose='own_metadata'),
 anchor_created_at timestamptz NOT NULL, anchor_id uuid NOT NULL, expires_at timestamptz NOT NULL
);
CREATE INDEX ix_nemesis_cursor_cleanup ON app.nemesis_cursors(expires_at,token);
CREATE FUNCTION app.e8n_clock() RETURNS timestamptz LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ SELECT clock_timestamp() $$;
CREATE FUNCTION app.e8n_gate() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM app.nemesis_control c JOIN app.installation_state i ON i.id=c.id AND i.sync_epoch=c.sync_epoch JOIN app.nemesis_releases r USING(projector_revision,finalizer_revision) WHERE c.id=1 AND c.enabled)
$$;
CREATE FUNCTION app.e8n_error(p_status integer,p_code text) RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$
 SELECT jsonb_build_object('ok',false,'http_status',p_status,'code',p_code,'response',NULL,'replayed',false)
$$;
CREATE FUNCTION app.e8n_context(p_issuer text,p_subject text,p_epoch uuid) RETURNS app.user_accounts
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE a app.user_accounts%ROWTYPE;
BEGIN
 SELECT * INTO a FROM app.user_accounts WHERE issuer=p_issuer AND subject=p_subject;
 IF a.id IS NULL OR a.state<>'active' OR app.subject_blocked(p_issuer,p_subject) THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch) THEN RETURN NULL; END IF;
 RETURN a;
END $$;
CREATE FUNCTION app.e8n_access(c app.nemesis_challenges) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog,pg_temp AS $$
 SELECT c.sync_epoch=(SELECT sync_epoch FROM app.installation_state WHERE id=1) AND
 ((c.cancel_reason='deleted' AND (c.inviter_id IS NULL OR c.invitee_id IS NULL)) OR
 EXISTS(SELECT 1 FROM app.user_accounts WHERE id=c.inviter_id AND state='active' AND generation=c.inviter_generation AND NOT app.subject_blocked(issuer,subject)) AND
 EXISTS(SELECT 1 FROM app.user_accounts WHERE id=c.invitee_id AND state='active' AND generation=c.invitee_generation AND NOT app.subject_blocked(issuer,subject)))
$$;
CREATE FUNCTION app.e8n_utc(p timestamptz) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$ SELECT to_char(p AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') $$;
CREATE FUNCTION app.e8n_metadata(c app.nemesis_challenges,p_owner uuid,p_clock timestamptz) RETURNS jsonb
LANGUAGE sql STABLE SET search_path=pg_catalog,pg_temp AS $$
 SELECT jsonb_build_object('id',c.id,'revision',c.revision,'role',CASE WHEN c.inviter_id=p_owner THEN 'inviter' ELSE 'invitee' END,
 'status',CASE WHEN c.status='invited' AND c.expires_at<=p_clock THEN 'cancelled' WHEN c.status='active' AND c.end_at<=p_clock THEN 'finished' ELSE c.status END,
 'terms',c.terms,'invited_at',app.e8n_utc(c.created_at),'expires_at',app.e8n_utc(c.expires_at),'accepted_at',app.e8n_utc(c.accepted_at),
 'start_date',c.start_date,'end_date',c.end_date,'start_at',app.e8n_utc(c.start_at),'end_at',app.e8n_utc(c.end_at),'deadline',app.e8n_utc(c.deadline_at),
 'result_status',c.result_status,'cancel_reason',CASE WHEN c.status='invited' AND c.expires_at<=p_clock THEN 'expired' ELSE c.cancel_reason END,
 'partner_pseudonym',CASE WHEN c.status<>'cancelled' THEN (SELECT pseudonym FROM app.user_profiles WHERE owner_id=CASE WHEN c.inviter_id=p_owner THEN c.invitee_id ELSE c.inviter_id END AND deleted_at IS NULL) ELSE NULL END)
$$;
CREATE FUNCTION app.e8n_boundary(p_date date,p_zone text) RETURNS timestamptz
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,pg_temp AS $$
DECLARE target timestamp:=p_date::timestamp; nominal timestamptz:=target AT TIME ZONE p_zone;
 result timestamptz; low timestamptz; high timestamptz; middle timestamptz;
BEGIN
 WITH offsets AS(SELECT DISTINCT (t AT TIME ZONE p_zone)-(t AT TIME ZONE 'UTC') delta FROM generate_series(nominal-interval '48 hours',nominal+interval '48 hours',interval '1 hour') t),
 candidates AS(SELECT (target-delta) AT TIME ZONE 'UTC' instant FROM offsets)
 SELECT min(instant) FILTER(WHERE instant AT TIME ZONE p_zone>=target),max(instant) FILTER(WHERE instant AT TIME ZONE p_zone<target) INTO result,low FROM candidates;
 IF low IS NOT NULL AND result IS NOT NULL AND low<result THEN high:=result;
 WHILE high-low>interval '1 microsecond' LOOP middle:=low+(high-low)/2; IF middle AT TIME ZONE p_zone>=target THEN high:=middle; ELSE low:=middle; END IF; END LOOP; result:=high; END IF;
 RETURN result;
END $$;

ALTER TABLE app.nemesis_challenges ADD CHECK(accepted_at IS NULL OR
 (start_at=app.e8n_boundary((accepted_at AT TIME ZONE (terms->>'time_zone'))::date+1,terms->>'time_zone') AND
 start_date=(start_at AT TIME ZONE (terms->>'time_zone'))::date AND
 end_at=app.e8n_boundary(end_date,terms->>'time_zone')));
