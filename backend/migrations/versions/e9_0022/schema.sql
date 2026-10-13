CREATE TABLE app.energy_axes(
 owner_id uuid PRIMARY KEY REFERENCES app.user_accounts(id),
 revision integer NOT NULL DEFAULT 0 CHECK(revision BETWEEN 0 AND 2147483647),
 baseline_id uuid, baseline_epoch uuid, baseline_consent_revision integer,baseline_notice jsonb,
 last_applied_at timestamptz,last_auto_checked_date date,last_auto_state text
);
CREATE TABLE app.energy_versions(
 id uuid PRIMARY KEY,owner_id uuid NOT NULL REFERENCES app.user_accounts(id),
 revision integer NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
 effective_from date NOT NULL,maintenance_kcal numeric NOT NULL CHECK(maintenance_kcal>0 AND maintenance_kcal::text NOT IN('NaN','Infinity','-Infinity')),
 method text NOT NULL CHECK(method IN('mifflin_pal_v1','energy_adjustment_v1','energy_revert_v1')),
 source text NOT NULL CHECK(source IN('legacy','manual','automatic','revert')),
 source_id uuid NOT NULL, supersedes uuid,decided_at timestamptz NOT NULL,
 audit jsonb NOT NULL CHECK(jsonb_typeof(audit)='object'),
 UNIQUE(owner_id,id),UNIQUE(owner_id,revision),UNIQUE(owner_id,source,source_id),
 FOREIGN KEY(owner_id,supersedes) REFERENCES app.energy_versions(owner_id,id)
);
CREATE INDEX ix_energy_versions_date ON app.energy_versions(owner_id,effective_from,revision);
-- Typed payload is attached to the common ChangeLog position. A NULL internal
-- marker remains safe for published legacy binaries as well as legacy clients.
CREATE TABLE app.energy_changes(
 owner_id uuid NOT NULL,position bigint NOT NULL,version_id uuid NOT NULL,
 PRIMARY KEY(owner_id,position),
 FOREIGN KEY(owner_id,position) REFERENCES app.sync_changes(owner_id,position) ON DELETE CASCADE,
 FOREIGN KEY(owner_id,version_id) REFERENCES app.energy_versions(owner_id,id)
);

CREATE TABLE app.energy_analyses(
 id uuid PRIMARY KEY,owner_id uuid NOT NULL REFERENCES app.user_accounts(id),
 generation integer NOT NULL,sync_epoch uuid NOT NULL,revision integer NOT NULL DEFAULT 1,
 automatic boolean NOT NULL,accepted_at timestamptz NOT NULL,
 date_from date NOT NULL,date_to date NOT NULL,context jsonb NOT NULL,
 fingerprint text NOT NULL,profile jsonb NOT NULL,notice jsonb NOT NULL,result jsonb NOT NULL,
 state text NOT NULL CHECK(state IN('insufficient_data','energy_history_unavailable','baseline_required','baseline_range_conflict','queued','running','ready','manual_review_required','no_change','failed','accepted','rejected')),
 created_at timestamptz,expires_at timestamptz,explanation jsonb,error_code text,
 UNIQUE(owner_id,id),CHECK(date_to=date_from+13),
 CHECK((created_at IS NULL AND expires_at IS NULL) OR expires_at=created_at+interval '24 hours')
);
CREATE INDEX ix_energy_analyses_owner ON app.energy_analyses(owner_id,accepted_at,id);
CREATE TABLE app.energy_receipts(
 owner_id uuid NOT NULL REFERENCES app.user_accounts(id),key uuid NOT NULL,
 request_hash text NOT NULL,generation integer NOT NULL,sync_epoch uuid NOT NULL,
 response jsonb,result_minimal jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(owner_id,key)
);
ALTER TABLE app.ai_jobs ALTER COLUMN analysis_id DROP NOT NULL;
ALTER TABLE app.ai_jobs ADD COLUMN energy_analysis_id uuid;
ALTER TABLE app.ai_jobs ADD CONSTRAINT ai_jobs_energy_fk FOREIGN KEY(owner_id,energy_analysis_id) REFERENCES app.energy_analyses(owner_id,id);
ALTER TABLE app.ai_jobs ADD CONSTRAINT ai_jobs_energy_unique UNIQUE(energy_analysis_id);
ALTER TABLE app.ai_jobs ADD CONSTRAINT ai_jobs_typed_payload CHECK(
 (purpose='food_photo' AND analysis_id IS NOT NULL AND energy_analysis_id IS NULL)
 OR(purpose='energy_adjustment' AND analysis_id IS NULL AND energy_analysis_id IS NOT NULL));
-- Older photo dispatch functions cannot treat an energy job as a photo.
-- New wrappers delegate unchanged food operations to their published implementation.
DO $$ DECLARE t text;BEGIN FOREACH t IN ARRAY ARRAY['energy_axes','energy_versions','energy_analyses','energy_receipts','energy_changes'] LOOP
 EXECUTE 'REVOKE ALL ON app.'||quote_ident(t)||' FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator';
 END LOOP;END $$;
GRANT SELECT ON app.energy_axes,app.energy_versions,app.energy_analyses,app.energy_receipts,app.energy_changes TO calorie_app_api;
