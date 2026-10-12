CREATE TABLE app.motivation_accounts (
 owner_id uuid PRIMARY KEY REFERENCES app.user_accounts(id),
 rule_version text NOT NULL DEFAULT 'regularity_v1' CHECK(rule_version='regularity_v1'),
 total_points bigint NOT NULL DEFAULT 0 CHECK(total_points>=0),
 active_badges integer NOT NULL DEFAULT 0 CHECK(active_badges BETWEEN 0 AND 4),
 revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0),
 source_position bigint NOT NULL DEFAULT 0 CHECK(source_position>=0),
 sync_epoch uuid NOT NULL,
 backfill_state text NOT NULL CHECK(backfill_state IN ('pending','ready')),
 backfill_after date, next_matures_at timestamptz,
 progress jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(progress)='object' AND octet_length(progress::text)<=16384)
);
CREATE INDEX ix_motivation_accounts_due ON app.motivation_accounts(next_matures_at,owner_id)
 WHERE next_matures_at IS NOT NULL;
CREATE INDEX ix_motivation_accounts_backfill ON app.motivation_accounts(owner_id)
 WHERE backfill_state='pending';
INSERT INTO app.motivation_accounts(owner_id,sync_epoch,backfill_state)
 SELECT a.id,i.sync_epoch,'pending' FROM app.user_accounts a CROSS JOIN app.installation_state i WHERE i.id=1;
CREATE TABLE app.motivation_days (
 owner_id uuid NOT NULL REFERENCES app.user_accounts(id), local_date date NOT NULL,
 rule_version text NOT NULL DEFAULT 'regularity_v1' CHECK(rule_version='regularity_v1'),
 time_zone varchar(100), matures_at timestamptz,
 source_fingerprint varchar(64) NOT NULL CHECK(length(source_fingerprint)=64),
 source_revisions jsonb NOT NULL CHECK(jsonb_typeof(source_revisions)='object' AND octet_length(source_revisions::text)<=16384),
 effective_complete boolean NOT NULL, in_goal boolean,
 candidate_points smallint NOT NULL CHECK(candidate_points BETWEEN 0 AND 2),
 materialized_points smallint NOT NULL CHECK(materialized_points BETWEEN 0 AND 2),
 weight_matures_at timestamptz, ration_matures_at timestamptz,
 weight_confirmed boolean NOT NULL DEFAULT false, ration_confirmed boolean NOT NULL DEFAULT false,
 PRIMARY KEY(owner_id,local_date,rule_version),
 CHECK(matures_at IS NULL OR time_zone IS NOT NULL),
 CHECK(NOT effective_complete OR time_zone IS NOT NULL),
 CHECK(candidate_points=(CASE WHEN effective_complete THEN 1 ELSE 0 END + CASE WHEN in_goal IS TRUE THEN 1 ELSE 0 END)),
 CHECK(in_goal IS NOT TRUE OR effective_complete),
 CHECK(materialized_points IN (0,candidate_points)),
 CHECK(NOT weight_confirmed OR weight_matures_at IS NOT NULL),
 CHECK(NOT ration_confirmed OR ration_matures_at IS NOT NULL)
);
CREATE INDEX ix_motivation_days_mature ON app.motivation_days(owner_id,matures_at,local_date);
CREATE TABLE app.motivation_badges (
 owner_id uuid NOT NULL REFERENCES app.user_accounts(id), badge_code text NOT NULL
 CHECK(badge_code IN ('complete_streak_10','in_goal_streak_10','weight_days_4_14','ration_days_5')),
 rule_version text NOT NULL DEFAULT 'regularity_v1' CHECK(rule_version='regularity_v1'),
 active boolean NOT NULL, first_awarded_at timestamptz NOT NULL, activated_at timestamptz NOT NULL,
 revoked_at timestamptz, witness jsonb NOT NULL
 CHECK(jsonb_typeof(witness)='array' AND jsonb_array_length(witness) BETWEEN 0 AND 10 AND octet_length(witness::text)<=1024),
 PRIMARY KEY(owner_id,badge_code,rule_version), CHECK(active=(revoked_at IS NULL))
);
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY[
 'motivation_accounts','motivation_days','motivation_badges'] LOOP
 EXECUTE 'REVOKE ALL ON app.'||quote_ident(t)||' FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_motivation_worker,calorie_app_deletion_operator';
 END LOOP; END $$;
GRANT SELECT ON app.motivation_accounts,app.motivation_days,app.motivation_badges TO calorie_app_api;
GRANT USAGE ON SCHEMA app TO calorie_app_motivation_worker;
GRANT SELECT ON app.installation_state,app.alembic_version TO calorie_app_motivation_worker;
ALTER TABLE app.motivation_days ADD COLUMN day_confirmed boolean NOT NULL DEFAULT false;
ALTER TABLE app.motivation_days ADD COLUMN qualified_at timestamptz NOT NULL;
ALTER TABLE app.motivation_days ADD CHECK(NOT day_confirmed OR matures_at IS NOT NULL);
ALTER TABLE app.motivation_days ADD CHECK(materialized_points=0 OR day_confirmed);
