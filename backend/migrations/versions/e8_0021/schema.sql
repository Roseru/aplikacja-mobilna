-- Private accepted-zone facts; no account FK can acquire hidden RI locks.
CREATE TABLE app.nemesis_projection_seeds (
 challenge_id uuid PRIMARY KEY REFERENCES app.nemesis_challenges(id) ON DELETE CASCADE,
 initializer_revision text NOT NULL CHECK(initializer_revision='0021_initializer_v1'),
 resolver_revision text NOT NULL CHECK(resolver_revision='iana_boundary_v1'),
 initialized_at timestamptz NOT NULL, read_revision bigint NOT NULL DEFAULT 1 CHECK(read_revision>0),
 final_at timestamptz
);
CREATE TABLE app.nemesis_day_projections (
 challenge_id uuid NOT NULL REFERENCES app.nemesis_challenges(id) ON DELETE CASCADE,
 participant_role text NOT NULL CHECK(participant_role IN('inviter','invitee')),
 local_date date NOT NULL, rule_version text NOT NULL CHECK(rule_version='regularity_v1'),
 starts_at timestamptz NOT NULL, matures_at timestamptz NOT NULL CHECK(matures_at>starts_at),
 candidate_points smallint NOT NULL CHECK(candidate_points BETWEEN 0 AND 2),
 effective_complete boolean NOT NULL, in_goal boolean,
 intake_kcal numeric, maintenance_kcal numeric, weight_kg numeric,
 weight_occurred_at timestamptz, weight_id uuid, weight_revision integer CHECK(weight_revision>0),
 source_revisions jsonb NOT NULL CHECK(jsonb_typeof(source_revisions)='object'), source_position bigint NOT NULL CHECK(source_position>=0),
 qualified_at timestamptz NOT NULL, revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
 PRIMARY KEY(challenge_id,participant_role,local_date,rule_version),
 CHECK(candidate_points=effective_complete::integer+(in_goal IS TRUE)::integer),
 CHECK(in_goal IS NOT TRUE OR effective_complete),
 CHECK(NOT effective_complete OR (intake_kcal IS NOT NULL AND intake_kcal>0)),
 CHECK(intake_kcal IS NULL OR (intake_kcal>=0 AND intake_kcal::text NOT IN('NaN','Infinity','-Infinity'))),
 CHECK(maintenance_kcal IS NULL OR (maintenance_kcal>0 AND maintenance_kcal::text NOT IN('NaN','Infinity','-Infinity'))),
 CHECK(weight_kg IS NULL OR (weight_kg>0 AND weight_kg::text NOT IN('NaN','Infinity','-Infinity'))),
 CHECK((weight_kg IS NULL)=(weight_id IS NULL) AND (weight_id IS NULL)=(weight_occurred_at IS NULL) AND (weight_id IS NULL)=(weight_revision IS NULL)),
 CHECK(weight_occurred_at IS NULL OR weight_occurred_at>=starts_at AND weight_occurred_at<matures_at)
);
CREATE TABLE app.nemesis_final_results (
 challenge_id uuid NOT NULL REFERENCES app.nemesis_challenges(id) ON DELETE CASCADE,
 participant_role text NOT NULL CHECK(participant_role IN('inviter','invitee')),
 aggregates jsonb NOT NULL CHECK(jsonb_typeof(aggregates)='object'),
 read_revision bigint NOT NULL CHECK(read_revision>0), finalized_at timestamptz NOT NULL,
 PRIMARY KEY(challenge_id,participant_role)
);
CREATE INDEX ix_nemesis_finalization_due ON app.nemesis_challenges(deadline_at,id)
 WHERE status IN('active','finished') AND result_status='provisional';
ALTER TABLE app.nemesis_control ADD COLUMN schema_revision text, ADD COLUMN initializer_revision text;
ALTER TABLE app.nemesis_releases ADD COLUMN schema_revision text, ADD COLUMN initializer_revision text;
-- Immutable migration-owned runtime source manifest. Runtime cannot add evidence.
CREATE TABLE app.nemesis_runtime_contract (
 signature text PRIMARY KEY, body_sha256 text NOT NULL CHECK(body_sha256 ~ '^[0-9a-f]{64}$')
);
