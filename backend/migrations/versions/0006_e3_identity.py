"""Persist installation epoch, online receipts and private profile/goal aggregates."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006_e3_identity"
down_revision = "0005_ration_cursors"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "generation_range", "user_accounts", "generation <= 2147483647", schema="app"
    )
    op.create_table(
        "installation_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sync_epoch", sa.Uuid(), nullable=False),
        sa.CheckConstraint("id = 1", name="singleton"),
        schema="app",
    )
    # Generated once by the migration, never by startup or a runtime API principal.
    op.execute(
        sa.text("INSERT INTO app.installation_state VALUES (1, :epoch)").bindparams(epoch=uuid4())
    )
    op.create_table(
        "user_consents",
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("app.user_accounts.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("ranking", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "automatic_energy_adjustment", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("revision BETWEEN 1 AND 2147483647", name="revision_range"),
        schema="app",
    )
    op.execute("INSERT INTO app.user_consents (owner_id) SELECT id FROM app.user_accounts")
    op.create_table(
        "online_receipts",
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("app.user_accounts.id"), primary_key=True),
        sa.Column("operation", sa.String(20), primary_key=True),
        sa.Column("key", sa.Uuid(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("sync_epoch", sa.Uuid(), nullable=False),
        sa.Column("response", JSONB()),
        sa.Column("accepted_revision", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("operation IN ('bootstrap','consents')", name="receipt_operation"),
        sa.CheckConstraint("generation BETWEEN 1 AND 2147483647", name="generation_range"),
        sa.CheckConstraint("length(request_hash) = 64", name="request_hash_length"),
        sa.CheckConstraint(
            "(operation='bootstrap' AND accepted_revision IS NULL "
            "AND response IS NOT NULL) OR (operation='consents' "
            "AND accepted_revision IS NOT NULL "
            "AND accepted_revision BETWEEN 1 AND 2147483647)",
            name="receipt_result",
        ),
        schema="app",
    )
    op.create_index(
        "ix_online_receipts_retention",
        "online_receipts",
        ["created_at"],
        postgresql_where=sa.text("operation='consents' AND response IS NOT NULL"),
        schema="app",
    )
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("app.user_accounts.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("pseudonym", sa.String(80), nullable=False),
        sa.Column("height_cm", sa.Numeric(12, 6)),
        sa.Column("activity_class", sa.String(16), nullable=False),
        sa.Column("time_zone", sa.String(100), nullable=False),
        sa.UniqueConstraint("owner_id", "id"),
        sa.CheckConstraint("revision BETWEEN 1 AND 2147483647", name="revision_range"),
        sa.CheckConstraint("length(pseudonym) BETWEEN 1 AND 80", name="pseudonym_length"),
        sa.CheckConstraint(
            "height_cm IS NULL OR (height_cm > 0 AND height_cm <= 300 "
            "AND height_cm::text NOT IN ('NaN','Infinity','-Infinity'))",
            name="height_range",
        ),
        sa.CheckConstraint(
            "activity_class IN ('stationary','line','commando')", name="activity_class"
        ),
        sa.CheckConstraint("length(time_zone) BETWEEN 1 AND 100", name="time_zone_length"),
        schema="app",
    )
    op.create_index(
        "uq_user_profiles_live_owner",
        "user_profiles",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        schema="app",
    )
    op.create_table(
        "goal_timelines",
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("app.user_accounts.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("revision BETWEEN 0 AND 2147483647", name="revision_range"),
        schema="app",
    )
    op.create_table(
        "goal_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("app.user_accounts.id"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("timeline_revision", sa.Integer(), nullable=False),
        sa.Column("timeline_base_revision", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_zone", sa.String(100), nullable=False),
        sa.Column("goal_type", sa.String(16), nullable=False),
        sa.Column("energy_kcal", sa.Numeric(12, 6), nullable=False),
        sa.Column("protein_g", sa.Numeric(12, 6)),
        sa.Column("fat_g", sa.Numeric(12, 6)),
        sa.Column("carbs_g", sa.Numeric(12, 6)),
        sa.Column("activity_class", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("correction_of", sa.Uuid()),
        sa.Column("payload", JSONB(), nullable=False),
        sa.UniqueConstraint("owner_id", "id"),
        sa.UniqueConstraint(
            "owner_id", "timeline_revision", name="uq_goal_versions_owner_timeline"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "correction_of"], ["app.goal_versions.owner_id", "app.goal_versions.id"]
        ),
        sa.CheckConstraint("revision = 1", name="immutable_revision"),
        sa.CheckConstraint("timeline_revision BETWEEN 1 AND 2147483647", name="timeline_range"),
        sa.CheckConstraint("timeline_base_revision = timeline_revision - 1", name="timeline_base"),
        sa.CheckConstraint(
            "energy_kcal > 0 AND energy_kcal <= 20000 "
            "AND energy_kcal::text NOT IN ('NaN','Infinity','-Infinity')",
            name="energy_range",
        ),
        *[
            sa.CheckConstraint(
                f"{field} IS NULL OR ({field} >= 0 AND {field} <= 5000 "
                f"AND {field}::text NOT IN ('NaN','Infinity','-Infinity'))",
                name=f"{field}_range",
            )
            for field in ("protein_g", "fat_g", "carbs_g")
        ],
        sa.CheckConstraint(
            "activity_class IN ('stationary','line','commando')", name="activity_class"
        ),
        sa.CheckConstraint("goal_type IN ('reduce','maintain','gain')", name="goal_type"),
        sa.CheckConstraint(
            "(reason='user_decision' AND correction_of IS NULL) OR "
            "(reason='history_correction' AND correction_of IS NOT NULL)",
            name="correction_audit",
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        sa.CheckConstraint(
            "correction_of IS NULL OR correction_of <> id", name="no_self_correction"
        ),
        schema="app",
    )
    op.execute("""
    CREATE FUNCTION app.private_time_zone_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
    DECLARE expected_payload jsonb;
    BEGIN
        IF NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=NEW.time_zone) THEN
            RAISE EXCEPTION 'invalid time zone' USING ERRCODE='23514';
        END IF;
        IF TG_TABLE_NAME='goal_versions' THEN
            expected_payload := jsonb_build_object(
                'effective_from', to_char(NEW.effective_from,'YYYY-MM-DD'),
                'time_zone',NEW.time_zone,'goal_type',NEW.goal_type,
                'energy_kcal',trim_scale(NEW.energy_kcal)::text,
                'protein_g',CASE WHEN NEW.protein_g IS NULL THEN NULL
                                ELSE trim_scale(NEW.protein_g)::text END,
                'fat_g',CASE WHEN NEW.fat_g IS NULL THEN NULL ELSE trim_scale(NEW.fat_g)::text END,
                'carbs_g',CASE WHEN NEW.carbs_g IS NULL THEN NULL
                              ELSE trim_scale(NEW.carbs_g)::text END,
                'activity_class',NEW.activity_class,'timeline_base_revision',NEW.timeline_base_revision,
                'reason',NEW.reason,'correction_of',NEW.correction_of);
            IF NEW.payload - 'decided_at' - 'estimate' IS DISTINCT FROM expected_payload
               OR NEW.payload->>'timeline_base_revision'
                  IS DISTINCT FROM NEW.timeline_base_revision::text
               OR jsonb_typeof(NEW.payload->'decided_at') IS DISTINCT FROM 'string'
               OR NEW.payload->>'decided_at' !~
                  '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?Z$'
               OR (NEW.payload->>'decided_at')::timestamptz IS DISTINCT FROM NEW.decided_at
               OR ((jsonb_typeof(NEW.payload->'estimate') IS DISTINCT FROM 'object')
                   AND (jsonb_typeof(NEW.payload->'estimate') IS DISTINCT FROM 'null')) THEN
                RAISE EXCEPTION 'goal snapshot differs from typed fields' USING ERRCODE='23514';
            END IF;
            IF NEW.reason='user_decision'
               AND NEW.effective_from < (NEW.decided_at AT TIME ZONE NEW.time_zone)::date THEN
                RAISE EXCEPTION 'decision date is in the past' USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """)
    for table in ("user_profiles", "goal_versions"):
        op.execute(
            f"CREATE TRIGGER private_time_zone BEFORE INSERT OR UPDATE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.private_time_zone_guard()"
        )
    op.execute("""
    CREATE FUNCTION app.goal_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'goal versions are immutable' USING ERRCODE='23514';
    END $$
    """)
    op.execute(
        "CREATE TRIGGER goal_immutable BEFORE UPDATE OR DELETE ON app.goal_versions "
        "FOR EACH ROW EXECUTE FUNCTION app.goal_immutable_guard()"
    )
    op.execute("""
    CREATE FUNCTION app.online_receipt_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
        IF NEW.owner_id IS DISTINCT FROM OLD.owner_id
           OR NEW.operation IS DISTINCT FROM OLD.operation
           OR NEW.key IS DISTINCT FROM OLD.key OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
           OR NEW.generation IS DISTINCT FROM OLD.generation
           OR NEW.sync_epoch IS DISTINCT FROM OLD.sync_epoch
           OR NEW.accepted_revision IS DISTINCT FROM OLD.accepted_revision
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.response IS NOT NULL OR OLD.operation <> 'consents'
           OR OLD.created_at > clock_timestamp() - INTERVAL '60 days' THEN
            RAISE EXCEPTION 'receipt evidence is immutable' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER online_receipt_immutable BEFORE UPDATE ON app.online_receipts "
        "FOR EACH ROW EXECUTE FUNCTION app.online_receipt_guard()"
    )
    op.execute("""
    CREATE FUNCTION app.account_anchor_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.issuer IS DISTINCT FROM OLD.issuer
           OR NEW.subject IS DISTINCT FROM OLD.subject
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.generation < OLD.generation
           OR (OLD.state='deleting' AND NEW.state <> 'deleting')
           OR (OLD.state='active' AND NEW.state='deleting'
               AND NEW.generation <= OLD.generation) THEN
            RAISE EXCEPTION 'account identity or state transition is invalid' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER account_anchor BEFORE UPDATE ON app.user_accounts "
        "FOR EACH ROW EXECUTE FUNCTION app.account_anchor_guard()"
    )
    op.execute("""
    CREATE FUNCTION app.goal_axis_insert_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
    DECLARE axis_revision integer; previous_revision integer; target_revision integer;
    BEGIN
        SELECT revision INTO axis_revision FROM app.goal_timelines WHERE owner_id=NEW.owner_id;
        SELECT coalesce(max(timeline_revision),0) INTO previous_revision
          FROM app.goal_versions WHERE owner_id=NEW.owner_id;
        IF axis_revision IS DISTINCT FROM NEW.timeline_revision
           OR previous_revision <> NEW.timeline_base_revision THEN
            RAISE EXCEPTION 'goal requires the next owner timeline revision' USING ERRCODE='23514';
        END IF;
        IF NEW.correction_of IS NOT NULL THEN
            SELECT timeline_revision INTO target_revision FROM app.goal_versions
              WHERE owner_id=NEW.owner_id AND id=NEW.correction_of;
            IF target_revision IS NULL OR target_revision >= NEW.timeline_revision THEN
                RAISE EXCEPTION 'correction requires an earlier owner version'
                    USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """)
    op.execute(
        "CREATE TRIGGER goal_axis_insert BEFORE INSERT ON app.goal_versions "
        "FOR EACH ROW EXECUTE FUNCTION app.goal_axis_insert_guard()"
    )
    op.execute("""
    CREATE FUNCTION app.goal_axis_commit_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
    DECLARE axis_revision integer; version_count bigint; latest_revision integer;
    BEGIN
        SELECT revision INTO axis_revision FROM app.goal_timelines WHERE owner_id=NEW.owner_id;
        SELECT count(*),coalesce(max(timeline_revision),0) INTO version_count,latest_revision
          FROM app.goal_versions WHERE owner_id=NEW.owner_id;
        IF axis_revision IS NULL OR axis_revision <> version_count
           OR axis_revision <> latest_revision THEN
            RAISE EXCEPTION 'goal timeline and immutable versions must commit atomically'
                USING ERRCODE='23514';
        END IF;
        RETURN NULL;
    END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER goal_axis_complete AFTER INSERT OR UPDATE "
        "ON app.goal_timelines DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION app.goal_axis_commit_guard()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER goal_axis_complete AFTER INSERT ON app.goal_versions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION app.goal_axis_commit_guard()"
    )
    op.execute("""
    CREATE FUNCTION app.private_owner_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.owner_id IS DISTINCT FROM OLD.owner_id OR NEW.revision <> OLD.revision + 1 THEN
            RAISE EXCEPTION 'private ownership or revision transition is invalid'
                USING ERRCODE='23514';
        END IF;
        IF TG_TABLE_NAME='user_profiles' THEN
            IF NEW.id IS DISTINCT FROM OLD.id OR OLD.deleted_at IS NOT NULL THEN
                RAISE EXCEPTION 'profile identity and tombstones are immutable'
                    USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """)
    for table in ("user_profiles", "user_consents", "goal_timelines"):
        op.execute(
            f"CREATE TRIGGER private_owner BEFORE UPDATE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.private_owner_guard()"
        )
    op.execute("""
    CREATE FUNCTION app.private_account_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
    DECLARE account_state text; account_generation integer;
    BEGIN
        SELECT state,generation INTO account_state,account_generation
          FROM app.user_accounts WHERE id=NEW.owner_id FOR UPDATE;
        IF NOT FOUND OR account_state <> 'active' THEN
            RAISE EXCEPTION 'private writes require an active account' USING ERRCODE='23514';
        END IF;
        IF TG_TABLE_NAME='online_receipts' THEN
            IF NEW.generation <> account_generation THEN
                RAISE EXCEPTION 'receipt generation is invalid' USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """)
    for table in ("user_profiles", "user_consents", "goal_timelines"):
        op.execute(
            f"CREATE TRIGGER private_account BEFORE INSERT OR UPDATE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.private_account_guard()"
        )
    for table in ("goal_versions", "online_receipts"):
        op.execute(
            f"CREATE TRIGGER private_account BEFORE INSERT ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.private_account_guard()"
        )
    op.execute("REVOKE DELETE ON app.user_accounts FROM calorie_app_api, calorie_app_worker")
    op.execute("""
    CREATE FUNCTION app.prune_consent_responses() RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE n integer;
    BEGIN
        WITH expired AS (
            SELECT owner_id, operation, key FROM app.online_receipts
            WHERE operation='consents' AND response IS NOT NULL
              AND created_at <= clock_timestamp() - INTERVAL '60 days'
            ORDER BY created_at, owner_id, key LIMIT 1000 FOR UPDATE SKIP LOCKED
        ) UPDATE app.online_receipts r SET response=NULL FROM expired e
          WHERE r.owner_id=e.owner_id AND r.operation=e.operation AND r.key=e.key;
        GET DIAGNOSTICS n=ROW_COUNT;
        RETURN n;
    END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.prune_consent_responses() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.prune_consent_responses() TO calorie_app_worker")
    for table in (
        "installation_state",
        "online_receipts",
        "user_profiles",
        "user_consents",
        "goal_timelines",
        "goal_versions",
    ):
        op.execute(f"REVOKE ALL ON app.{table} FROM calorie_app_api, calorie_app_worker")
        op.execute(f"GRANT SELECT ON app.{table} TO calorie_app_api, calorie_app_worker")
    for table in ("user_profiles", "user_consents", "goal_timelines"):
        op.execute(f"GRANT INSERT, UPDATE ON app.{table} TO calorie_app_api, calorie_app_worker")
    for table in ("online_receipts", "goal_versions"):
        op.execute(f"GRANT INSERT ON app.{table} TO calorie_app_api, calorie_app_worker")


def downgrade():
    # Do not silently destroy private records or rotate an already-issued epoch.
    op.execute("""
    DO $$ BEGIN
        IF EXISTS(SELECT 1 FROM app.online_receipts)
           OR EXISTS(SELECT 1 FROM app.user_profiles)
           OR EXISTS(SELECT 1 FROM app.goal_versions) THEN
            RAISE EXCEPTION 'private E3 data prevents destructive downgrade' USING ERRCODE='23514';
        END IF;
    END $$
    """)
    op.execute("DROP FUNCTION app.prune_consent_responses()")
    op.execute("DROP TRIGGER account_anchor ON app.user_accounts")
    op.execute("DROP FUNCTION app.account_anchor_guard()")
    for table in (
        "goal_versions",
        "goal_timelines",
        "user_profiles",
        "online_receipts",
        "user_consents",
        "installation_state",
    ):
        op.drop_table(table, schema="app")
    op.execute("DROP FUNCTION app.online_receipt_guard()")
    op.execute("DROP FUNCTION app.goal_immutable_guard()")
    op.execute("DROP FUNCTION app.private_time_zone_guard()")
    op.execute("DROP FUNCTION app.private_owner_guard()")
    op.execute("DROP FUNCTION app.private_account_guard()")
    op.execute("DROP FUNCTION app.goal_axis_insert_guard()")
    op.execute("DROP FUNCTION app.goal_axis_commit_guard()")
    op.execute("GRANT DELETE ON app.user_accounts TO calorie_app_api, calorie_app_worker")
    op.drop_constraint("ck_user_accounts_generation_range", "user_accounts", schema="app")
