CREATE TABLE app.ai_controls (
  id integer PRIMARY KEY CHECK(id=1), sync_epoch uuid NOT NULL,
  dispatch_open boolean NOT NULL DEFAULT true, closed_at timestamptz, reconciled_at timestamptz,
  reconciliation_hash text CHECK(reconciliation_hash IS NULL OR reconciliation_hash ~ '^[0-9a-f]{64}$')
);
INSERT INTO app.ai_controls(id,sync_epoch) SELECT 1,sync_epoch FROM app.installation_state WHERE id=1;
CREATE TABLE app.ai_pools (
  scope text PRIMARY KEY CHECK(length(scope) BETWEEN 1 AND 250),
  provider text NOT NULL CHECK(provider IN ('mock','gemini')),
  project text NOT NULL CHECK(length(project) BETWEEN 1 AND 100),
  model text NOT NULL CHECK(length(model) BETWEEN 1 AND 100),
  environment text NOT NULL CHECK(length(environment) BETWEEN 1 AND 100),
  rpm integer NOT NULL CHECK(rpm BETWEEN 1 AND 100000),
  tpm bigint NOT NULL CHECK(tpm BETWEEN 10240 AND 1000000000),
  rpd integer NOT NULL CHECK(rpd BETWEEN 1 AND 1000000),
  confirmed_at timestamptz NOT NULL, free_only boolean NOT NULL CHECK(free_only),
  enabled boolean NOT NULL DEFAULT true,
  UNIQUE(provider,project,model,environment)
);
INSERT INTO app.ai_pools VALUES('mock:local:mock-food-v1:local','mock','local','mock-food-v1','local',
  100,1000000,10000,clock_timestamp(),true,true);
CREATE TABLE app.ai_analyses (
  id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES app.user_accounts(id),
  generation integer NOT NULL CHECK(generation>=1), sync_epoch uuid NOT NULL,
  profile jsonb NOT NULL CHECK(jsonb_typeof(profile)='object' AND octet_length(profile::text)<=16384),
  original_hash text NOT NULL CHECK(original_hash ~ '^[0-9a-f]{64}$'),
  prepared_hash text NOT NULL CHECK(prepared_hash ~ '^[0-9a-f]{64}$'),
  width integer NOT NULL CHECK(width BETWEEN 1 AND 1600), height integer NOT NULL CHECK(height BETWEEN 1 AND 1600),
  storage_key text UNIQUE CHECK(storage_key IS NULL OR storage_key ~ '^[0-9a-f]{32}$'),
  accepted_at timestamptz NOT NULL, photo_expires_at timestamptz NOT NULL,
  state text NOT NULL CHECK(state IN ('queued','running','succeeded','failed')),
  revision integer NOT NULL DEFAULT 1 CHECK(revision BETWEEN 1 AND 2147483647),
  proposal jsonb CHECK(proposal IS NULL OR (jsonb_typeof(proposal)='object' AND octet_length(proposal::text)<=1048576)),
  error_code text CHECK(error_code IS NULL OR error_code ~ '^[a-z_]{1,64}$'),
  decision_state text NOT NULL DEFAULT 'pending' CHECK(decision_state IN ('pending','confirmed','cancelled')),
  UNIQUE(owner_id,id), CHECK(photo_expires_at=accepted_at+interval '24 hours'),
  CHECK((state='succeeded')=(proposal IS NOT NULL)), CHECK(state NOT IN ('queued','running') OR storage_key IS NOT NULL)
);
CREATE INDEX ix_ai_analyses_ttl ON app.ai_analyses(photo_expires_at,id) WHERE storage_key IS NOT NULL;
CREATE TABLE app.ai_jobs (
  id uuid PRIMARY KEY, owner_id uuid NOT NULL, analysis_id uuid NOT NULL UNIQUE,
  purpose text NOT NULL CHECK(purpose IN ('food_photo','energy_adjustment')),
  generation integer NOT NULL CHECK(generation>=1), sync_epoch uuid NOT NULL,
  pool_scope text NOT NULL REFERENCES app.ai_pools(scope),
  state text NOT NULL CHECK(state IN ('queued','running','succeeded','failed')),
  phase text NOT NULL DEFAULT 'waiting' CHECK(phase IN ('waiting','claimed','dispatch_started','completed')),
  queue_deadline timestamptz NOT NULL, next_attempt_at timestamptz NOT NULL,
  started_at timestamptz, processing_deadline timestamptz, lease_until timestamptz, fence uuid,
  generate_attempts integer NOT NULL DEFAULT 0 CHECK(generate_attempts BETWEEN 0 AND 2),
  preflight_done boolean NOT NULL DEFAULT false,
  input_tokens integer CHECK(input_tokens BETWEEN 0 AND 8192),
  FOREIGN KEY(owner_id,analysis_id) REFERENCES app.ai_analyses(owner_id,id),
  CHECK((started_at IS NULL)=(processing_deadline IS NULL)),
  CHECK(processing_deadline IS NULL OR processing_deadline=started_at+interval '120 seconds'),
  CHECK(state<>'running' OR (fence IS NOT NULL AND lease_until IS NOT NULL))
);
CREATE UNIQUE INDEX uq_ai_one_active_account ON app.ai_jobs(owner_id) WHERE state IN ('queued','running');
CREATE INDEX ix_ai_jobs_ready ON app.ai_jobs(next_attempt_at,id) WHERE state='queued';
CREATE TABLE app.ai_photo_consents (
  analysis_id uuid PRIMARY KEY, owner_id uuid NOT NULL, notice_version text NOT NULL CHECK(notice_version='food-photo-notice-v1'),
  provider text NOT NULL CHECK(provider IN ('mock','gemini')), scope text NOT NULL CHECK(scope='this_photo'),
  accepted_at timestamptz NOT NULL, original_hash text NOT NULL CHECK(original_hash ~ '^[0-9a-f]{64}$'),
  revoked_at timestamptz, FOREIGN KEY(owner_id,analysis_id) REFERENCES app.ai_analyses(owner_id,id)
);
CREATE TABLE app.ai_decisions (
  analysis_id uuid PRIMARY KEY, owner_id uuid NOT NULL,
  decision_hash text NOT NULL CHECK(decision_hash ~ '^[0-9a-f]{64}$'), meal_id uuid NOT NULL,
  response jsonb NOT NULL CHECK(jsonb_typeof(response)='object' AND octet_length(response::text)<=1048576),
  confirmed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY(owner_id,analysis_id) REFERENCES app.ai_analyses(owner_id,id)
);
CREATE TABLE app.ai_receipts (
  owner_id uuid NOT NULL REFERENCES app.user_accounts(id), operation_id uuid NOT NULL,
  operation_kind text NOT NULL CHECK(operation_kind IN ('create','confirm','cancel')),
  request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  generation integer NOT NULL CHECK(generation>=1), sync_epoch uuid NOT NULL,
  status_code integer NOT NULL CHECK(status_code IN (200,202,403,404,409,410,422,429,503)),
  response_payload jsonb CHECK(response_payload IS NULL OR octet_length(response_payload::text)<=1048576),
  result_minimal jsonb NOT NULL CHECK(octet_length(result_minimal::text)<=16384),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(owner_id,operation_id)
);
CREATE INDEX ix_ai_receipts_retention ON app.ai_receipts(owner_id,created_at,operation_id) WHERE response_payload IS NOT NULL;
CREATE TABLE app.ai_admissions (
  owner_id uuid NOT NULL REFERENCES app.user_accounts(id), day date NOT NULL,
  receipts integer NOT NULL DEFAULT 0 CHECK(receipts BETWEEN 0 AND 1000),
  photos integer NOT NULL DEFAULT 0 CHECK(photos BETWEEN 0 AND 10), PRIMARY KEY(owner_id,day)
);
CREATE TABLE app.ai_energy_admissions (
  owner_id uuid PRIMARY KEY REFERENCES app.user_accounts(id), accepted_at timestamptz NOT NULL
);
CREATE TABLE app.ai_attempts (
  id uuid PRIMARY KEY, job_id uuid REFERENCES app.ai_jobs(id) ON DELETE SET NULL,
  pool_scope text NOT NULL REFERENCES app.ai_pools(scope), purpose text NOT NULL CHECK(purpose IN ('food_photo','energy_adjustment')),
  kind text NOT NULL CHECK(kind IN ('count_tokens','generate')), ordinal integer NOT NULL CHECK(ordinal BETWEEN 0 AND 2),
  dispatched_at timestamptz NOT NULL, pacific_day date NOT NULL,
  reserved_tokens integer NOT NULL CHECK(reserved_tokens BETWEEN 0 AND 10240),
  input_tokens integer CHECK(input_tokens BETWEEN 0 AND 8192),
  output_tokens integer CHECK(output_tokens BETWEEN 0 AND 2048),
  thoughts_tokens integer CHECK(thoughts_tokens BETWEEN 0 AND 2048),
  status text NOT NULL DEFAULT 'dispatch_started' CHECK(status IN ('dispatch_started','ok','unknown','denied','invalid')),
  io_finished_at timestamptz, worker_token_hash text NOT NULL CHECK(worker_token_hash ~ '^[0-9a-f]{64}$'),
  fenced_at timestamptz, fencing_evidence_hash text CHECK(fencing_evidence_hash IS NULL OR fencing_evidence_hash ~ '^[0-9a-f]{64}$'),
  CHECK(output_tokens IS NULL OR thoughts_tokens IS NULL OR output_tokens+thoughts_tokens<=2048)
);
CREATE INDEX ix_ai_attempts_window ON app.ai_attempts(pool_scope,dispatched_at);
CREATE INDEX ix_ai_attempts_day ON app.ai_attempts(pool_scope,pacific_day);
CREATE TABLE app.ai_transport_permits (
  environment text NOT NULL, slot integer NOT NULL CHECK(slot IN (1,2)),
  attempt_id uuid UNIQUE REFERENCES app.ai_attempts(id), PRIMARY KEY(environment,slot)
);
INSERT INTO app.ai_transport_permits(environment,slot) VALUES('local',1),('local',2);
CREATE TABLE app.ai_cleanup_intents (
  storage_key text PRIMARY KEY CHECK(storage_key ~ '^[0-9a-f]{32}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY[
 'ai_controls','ai_pools','ai_analyses','ai_jobs','ai_photo_consents','ai_decisions','ai_receipts',
 'ai_admissions','ai_energy_admissions','ai_attempts','ai_transport_permits','ai_cleanup_intents'] LOOP
 EXECUTE 'REVOKE ALL ON app.'||quote_ident(t)||' FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator';
 END LOOP; END $$;
GRANT SELECT ON app.ai_controls,app.ai_pools,app.ai_analyses,app.ai_jobs,app.ai_receipts,app.ai_decisions TO calorie_app_api;
GRANT SELECT ON app.ai_controls,app.ai_pools,app.ai_analyses,app.ai_attempts,app.ai_transport_permits,app.ai_cleanup_intents TO calorie_app_ai_worker;
-- Claim fences are private capabilities returned only to their successful claimant.
GRANT SELECT(id,purpose,state,next_attempt_at,lease_until) ON app.ai_jobs TO calorie_app_ai_worker;
GRANT USAGE ON SCHEMA app TO calorie_app_ai_worker; GRANT SELECT ON app.installation_state,app.alembic_version TO calorie_app_ai_worker;
