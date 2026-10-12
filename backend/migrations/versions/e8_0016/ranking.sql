-- Frozen E8 ranking provenance and opaque cursor storage. No business-code imports.
CREATE TABLE app.ranking_affirmations (
    owner_id uuid PRIMARY KEY REFERENCES app.user_accounts(id) ON DELETE CASCADE,
    ranking_consent_epoch uuid NOT NULL,
    source_revision integer NOT NULL CHECK (source_revision BETWEEN 1 AND 2147483647)
);
CREATE TABLE app.ranking_sessions (
    session_id uuid PRIMARY KEY,
    requester_id uuid NOT NULL REFERENCES app.user_accounts(id) ON DELETE CASCADE,
    generation integer NOT NULL CHECK (generation BETWEEN 1 AND 2147483647),
    sync_epoch uuid NOT NULL,
    page_limit integer NOT NULL CHECK (page_limit BETWEEN 1 AND 100),
    purpose text NOT NULL CHECK (purpose='ranking_v1'),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    CHECK (expires_at=created_at+interval '10 minutes')
);
CREATE INDEX ix_ranking_sessions_requester ON app.ranking_sessions(requester_id,expires_at);
CREATE INDEX ix_ranking_sessions_expiry ON app.ranking_sessions(expires_at);
CREATE TABLE app.ranking_cursors (
    token_digest varchar(64) PRIMARY KEY CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    session_id uuid NOT NULL REFERENCES app.ranking_sessions(session_id) ON DELETE CASCADE,
    seek_points bigint NOT NULL CHECK (seek_points >= 0),
    seek_pseudonym text COLLATE "C" NOT NULL CHECK (length(seek_pseudonym) BETWEEN 1 AND 80),
    anchor_id uuid REFERENCES app.user_accounts(id) ON DELETE SET NULL,
    step bigint NOT NULL CHECK (step>=1),
    next_token text CHECK (next_token ~ '^rk1\.[A-Za-z0-9_-]{43}$'),
    UNIQUE (session_id,step)
);
CREATE INDEX ix_ranking_cursors_anchor ON app.ranking_cursors(anchor_id);
REVOKE ALL ON app.ranking_affirmations,app.ranking_sessions,app.ranking_cursors
    FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,
         calorie_app_motivation_worker,calorie_app_deletion_operator;
GRANT SELECT ON app.ranking_affirmations TO calorie_app_api;
GRANT SELECT,INSERT,UPDATE,DELETE ON app.ranking_sessions,app.ranking_cursors TO calorie_app_api;

CREATE FUNCTION app.e8_affirm_ranking(p_owner uuid,p_epoch uuid,p_revision integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE accepted boolean;
BEGIN
    PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'ranking_context_invalid'; END IF;
    SELECT c.ranking AND c.revision=p_revision AND i.sync_epoch=p_epoch INTO accepted
      FROM app.user_consents c CROSS JOIN app.installation_state i
      WHERE c.owner_id=p_owner AND i.id=1;
    IF accepted IS DISTINCT FROM true THEN RAISE EXCEPTION 'ranking_context_invalid'; END IF;
    INSERT INTO app.ranking_affirmations(owner_id,ranking_consent_epoch,source_revision)
      VALUES(p_owner,p_epoch,p_revision)
      ON CONFLICT(owner_id) DO UPDATE SET ranking_consent_epoch=EXCLUDED.ranking_consent_epoch,
        source_revision=EXCLUDED.source_revision;
END $$;
CREATE FUNCTION app.e8_revoke_ranking(p_owner uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
    PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'ranking_context_invalid'; END IF;
    IF EXISTS(SELECT 1 FROM app.user_consents WHERE owner_id=p_owner AND NOT ranking) THEN
      DELETE FROM app.ranking_affirmations WHERE owner_id=p_owner;
    ELSE
      RAISE EXCEPTION 'ranking_context_invalid';
    END IF;
END $$;
REVOKE ALL ON FUNCTION app.e8_affirm_ranking(uuid,uuid,integer),app.e8_revoke_ranking(uuid)
    FROM PUBLIC,calorie_app_worker;
GRANT EXECUTE ON FUNCTION app.e8_affirm_ranking(uuid,uuid,integer),app.e8_revoke_ranking(uuid)
    TO calorie_app_api;
