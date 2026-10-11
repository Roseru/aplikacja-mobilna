"""Narrow operator deletion jobs, persistent subject fence and authorized graph purge."""

from alembic import op

revision = "0011_e4_deletion"
down_revision = "0010_e4_retention"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE IF NOT EXISTS app.account_deletion_jobs (
        operation_id uuid PRIMARY KEY, account_id uuid NOT NULL UNIQUE,
        issuer varchar(2048) NOT NULL, subject varchar(255) NOT NULL,
        expected_generation integer NOT NULL CHECK(expected_generation BETWEEN 1 AND 2147483646),
        deleting_generation integer NOT NULL CHECK(deleting_generation=expected_generation+1),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        identity_confirmed_at timestamptz, block_until timestamptz, purged_at timestamptz,
        CHECK((identity_confirmed_at IS NULL AND block_until IS NULL AND purged_at IS NULL)
           OR (identity_confirmed_at IS NOT NULL
               AND block_until >= identity_confirmed_at + interval '420 seconds')),
        UNIQUE(issuer,subject)
    );
    CREATE TABLE IF NOT EXISTS app.deleted_subjects (
        issuer varchar(2048) NOT NULL, subject varchar(255) NOT NULL,
        operation_id uuid NOT NULL REFERENCES app.account_deletion_jobs(operation_id),
        PRIMARY KEY(issuer,subject)
    );
    CREATE TABLE IF NOT EXISTS app._deletion_context (
        transaction_id bigint PRIMARY KEY, owner_id uuid NOT NULL,
        operation_id uuid NOT NULL REFERENCES app.account_deletion_jobs(operation_id)
    );
    REVOKE ALL ON app.account_deletion_jobs,app.deleted_subjects,app._deletion_context
      FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_deletion_operator;
    GRANT USAGE ON SCHEMA app TO calorie_app_deletion_operator;
    GRANT SELECT ON app.account_deletion_jobs TO calorie_app_deletion_operator;
    GRANT SELECT ON app.deleted_subjects TO calorie_app_api,calorie_app_worker;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION app.subject_blocked(p_issuer text,p_subject text) RETURNS boolean
    LANGUAGE sql SECURITY DEFINER STABLE SET search_path=pg_catalog,pg_temp AS $$
      SELECT EXISTS(SELECT 1 FROM app.deleted_subjects WHERE issuer=p_issuer AND subject=p_subject)
    $$;
    REVOKE ALL ON FUNCTION app.subject_blocked(text,text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.subject_blocked(text,text)
      TO calorie_app_api,calorie_app_worker;
    CREATE OR REPLACE FUNCTION app.deleted_subject_insert_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
      IF app.subject_blocked(NEW.issuer,NEW.subject) THEN
        RAISE EXCEPTION 'subject is permanently blocked' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION app.deleted_subject_insert_guard() FROM PUBLIC;
    DROP TRIGGER IF EXISTS deleted_subject_account ON app.user_accounts;
    CREATE TRIGGER deleted_subject_account BEFORE INSERT ON app.user_accounts
      FOR EACH ROW EXECUTE FUNCTION app.deleted_subject_insert_guard();
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION app.begin_account_deletion(
      p_owner uuid,p_operation uuid,p_generation integer)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE a app.user_accounts%ROWTYPE; j app.account_deletion_jobs%ROWTYPE;
    BEGIN
      -- Account → account counter → job. Retry after purge uses retained job.
      SELECT * INTO a FROM app.user_accounts WHERE id=p_owner FOR UPDATE;
      IF FOUND THEN
        PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
      END IF;
      SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation FOR UPDATE;
      IF FOUND THEN
        IF j.account_id<>p_owner OR j.expected_generation<>p_generation THEN
          RAISE EXCEPTION 'deletion operation reused' USING ERRCODE='23514';
        END IF;
        RETURN j.operation_id;
      END IF;
      IF a.id IS NULL OR a.state<>'active' OR a.generation<>p_generation
         OR p_generation NOT BETWEEN 1 AND 2147483646 THEN
        RAISE EXCEPTION 'deletion account context invalid' USING ERRCODE='23514';
      END IF;
      INSERT INTO app.account_deletion_jobs
        (operation_id,account_id,issuer,subject,expected_generation,deleting_generation)
        VALUES(p_operation,p_owner,a.issuer,a.subject,p_generation,p_generation+1);
      INSERT INTO app.deleted_subjects VALUES(a.issuer,a.subject,p_operation);
      UPDATE app.user_accounts SET state='deleting',generation=generation+1 WHERE id=p_owner;
      RETURN p_operation;
    END $$;
    REVOKE ALL ON FUNCTION app.begin_account_deletion(uuid,uuid,integer) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.begin_account_deletion(uuid,uuid,integer)
      TO calorie_app_deletion_operator;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION app.confirm_account_deletion(p_operation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE j app.account_deletion_jobs%ROWTYPE; cut timestamptz;
    BEGIN
      SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation;
      IF NOT FOUND THEN RAISE EXCEPTION 'unknown deletion job' USING ERRCODE='23514'; END IF;
      PERFORM 1 FROM app.user_accounts WHERE id=j.account_id FOR UPDATE;
      PERFORM 1 FROM app.sync_counters WHERE owner_id=j.account_id FOR UPDATE;
      SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation FOR UPDATE;
      IF j.identity_confirmed_at IS NULL THEN
        IF NOT EXISTS(SELECT 1 FROM app.user_accounts WHERE id=j.account_id
                      AND state='deleting' AND generation=j.deleting_generation) THEN
          RAISE EXCEPTION 'deletion account context invalid' USING ERRCODE='23514';
        END IF;
        cut := clock_timestamp();
        UPDATE app.account_deletion_jobs SET identity_confirmed_at=cut,
          block_until=cut+interval '420 seconds' WHERE operation_id=p_operation;
      END IF;
    END $$;
    REVOKE ALL ON FUNCTION app.confirm_account_deletion(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.confirm_account_deletion(uuid) TO calorie_app_deletion_operator;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION app.deletion_purge_authorized(p_owner uuid) RETURNS boolean
    LANGUAGE sql SECURITY DEFINER STABLE SET search_path=pg_catalog,pg_temp AS $$
      SELECT EXISTS(
        SELECT 1 FROM app._deletion_context c
        JOIN app.account_deletion_jobs j ON j.operation_id=c.operation_id
        JOIN app.user_accounts a ON a.id=c.owner_id
        WHERE c.transaction_id=txid_current() AND c.owner_id=p_owner
          AND j.account_id=p_owner AND j.identity_confirmed_at IS NOT NULL
          AND j.purged_at IS NULL AND a.state='deleting'
          AND a.generation=j.deleting_generation)
    $$;
    REVOKE ALL ON FUNCTION app.deletion_purge_authorized(uuid) FROM PUBLIC;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION app.goal_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
      IF TG_OP='DELETE' AND app.deletion_purge_authorized(OLD.owner_id) THEN RETURN OLD; END IF;
      RAISE EXCEPTION 'goal versions are immutable' USING ERRCODE='23514';
    END $$;
    CREATE OR REPLACE FUNCTION app.diary_item_delete_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
    DECLARE account_state text; parent_deleted_at timestamptz;
    BEGIN
      IF app.deletion_purge_authorized(OLD.owner_id) THEN RETURN OLD; END IF;
      SELECT state INTO account_state FROM app.user_accounts WHERE id=OLD.owner_id FOR UPDATE;
      IF NOT FOUND OR account_state<>'active' THEN
        RAISE EXCEPTION 'item delete requires an active account' USING ERRCODE='23514';
      END IF;
      SELECT deleted_at INTO parent_deleted_at FROM app.meals
        WHERE owner_id=OLD.owner_id AND id=OLD.meal_id FOR UPDATE;
      IF NOT FOUND OR parent_deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'item delete requires a live meal snapshot' USING ERRCODE='23514';
      END IF;
      RETURN OLD;
    END $$;
    -- Trigger execution needs the boolean helper, but cannot create its context.
    GRANT EXECUTE ON FUNCTION app.deletion_purge_authorized(uuid)
      TO calorie_app_api,calorie_app_worker;
    """)
    op.execute("""
    CREATE OR REPLACE FUNCTION app.purge_deleted_account(p_operation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE j app.account_deletion_jobs%ROWTYPE;
    BEGIN
      SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation;
      IF NOT FOUND THEN RAISE EXCEPTION 'unknown deletion job' USING ERRCODE='23514'; END IF;
      PERFORM 1 FROM app.user_accounts WHERE id=j.account_id FOR UPDATE;
      PERFORM 1 FROM app.sync_counters WHERE owner_id=j.account_id FOR UPDATE;
      SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation FOR UPDATE;
      IF j.purged_at IS NOT NULL THEN RETURN; END IF;
      IF j.identity_confirmed_at IS NULL OR NOT EXISTS(
          SELECT 1 FROM app.user_accounts WHERE id=j.account_id AND state='deleting'
            AND generation=j.deleting_generation AND issuer=j.issuer AND subject=j.subject)
        OR NOT EXISTS(SELECT 1 FROM app.deleted_subjects WHERE issuer=j.issuer
                      AND subject=j.subject AND operation_id=p_operation) THEN
        RAISE EXCEPTION 'purge requires exact confirmed deleting target' USING ERRCODE='23514';
      END IF;
      INSERT INTO app._deletion_context VALUES(txid_current(),j.account_id,p_operation);
      DELETE FROM app.sync_session_items WHERE owner_id=j.account_id;
      DELETE FROM app.sync_sessions WHERE owner_id=j.account_id;
      DELETE FROM app.sync_recovery_mappings WHERE owner_id=j.account_id;
      DELETE FROM app.sync_changes WHERE owner_id=j.account_id;
      DELETE FROM app.sync_receipts WHERE owner_id=j.account_id;
      DELETE FROM app.sync_reservations WHERE owner_id=j.account_id;
      DELETE FROM app.online_receipts WHERE owner_id=j.account_id;
      DELETE FROM app.meal_items WHERE owner_id=j.account_id;
      DELETE FROM app.meals WHERE owner_id=j.account_id;
      DELETE FROM app.weights WHERE owner_id=j.account_id;
      DELETE FROM app.product_drafts WHERE owner_id=j.account_id;
      DELETE FROM app.diary_days WHERE owner_id=j.account_id;
      -- Self-referencing goal corrections are checked at statement completion.
      DELETE FROM app.goal_versions WHERE owner_id=j.account_id;
      DELETE FROM app.goal_timelines WHERE owner_id=j.account_id;
      DELETE FROM app.user_profiles WHERE owner_id=j.account_id;
      DELETE FROM app.user_consents WHERE owner_id=j.account_id;
      DELETE FROM app.sync_counters WHERE owner_id=j.account_id;
      DELETE FROM app.user_accounts WHERE id=j.account_id;
      UPDATE app.account_deletion_jobs SET purged_at=clock_timestamp()
        WHERE operation_id=p_operation;
      DELETE FROM app._deletion_context WHERE transaction_id=txid_current();
    END $$;
    REVOKE ALL ON FUNCTION app.purge_deleted_account(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.purge_deleted_account(uuid) TO calorie_app_deletion_operator;
    """)


def downgrade():
    # Data and the permanent subject fence remain usable by the previous image.
    # Removing these would silently re-enable bootstrap with surviving JWTs.
    op.get_context().config.print_stdout(
        "WARNING: E4 deletion jobs, subject fences, narrow purge and ACL are retained on downgrade."
    )
