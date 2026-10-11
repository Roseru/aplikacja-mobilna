"""Private E3 diary aggregates, immutable day zones and exact historical snapshots."""

from alembic import op

revision = "0007_e3_diary"
down_revision = "0006_e3_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE app.diary_days (
    id UUID NOT NULL,
    owner_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    local_date DATE NOT NULL,
    time_zone VARCHAR(100) NOT NULL,
    declared_complete BOOLEAN NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_diary_days PRIMARY KEY (id),
    CONSTRAINT uq_diary_days_owner_id UNIQUE (owner_id, id),
    CONSTRAINT uq_diary_days_owner_date UNIQUE (owner_id, local_date),
    CONSTRAINT uq_diary_days_owner_zone UNIQUE (owner_id, local_date, time_zone),
    CONSTRAINT ck_diary_days_revision_range CHECK (revision BETWEEN 1 AND 2147483647),
    CONSTRAINT ck_diary_days_time_zone_length CHECK (length(time_zone) BETWEEN 1 AND 100),
    CONSTRAINT fk_diary_days_owner_id_user_accounts FOREIGN KEY(owner_id) REFERENCES
app.user_accounts (id)
)""")
    op.execute("""CREATE TABLE app.meals (
    id UUID NOT NULL,
    owner_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    local_date DATE NOT NULL,
    time_zone VARCHAR(100) NOT NULL,
    meal_type VARCHAR(20),
    goal_id UUID,
    ration JSONB,
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_meals PRIMARY KEY (id),
    CONSTRAINT uq_meals_owner_id UNIQUE (owner_id, id),
    CONSTRAINT fk_meals_owner_id_goal_versions FOREIGN KEY(owner_id, goal_id) REFERENCES
app.goal_versions (owner_id, id),
    CONSTRAINT fk_meals_owner_id_diary_days FOREIGN KEY(owner_id, local_date, time_zone)
REFERENCES app.diary_days (owner_id, local_date, time_zone),
    CONSTRAINT ck_meals_revision_range CHECK (revision BETWEEN 1 AND 2147483647),
    CONSTRAINT ck_meals_title_length CHECK (length(title) BETWEEN 1 AND 200),
    CONSTRAINT ck_meals_meal_type CHECK (meal_type IS NULL OR meal_type IN
('breakfast','lunch','dinner','snack')),
    CONSTRAINT ck_meals_local_date_matches CHECK ((occurred_at AT TIME ZONE time_zone)::date =
local_date),
    CONSTRAINT fk_meals_owner_id_user_accounts FOREIGN KEY(owner_id) REFERENCES
app.user_accounts (id)
)""")
    op.execute("CREATE INDEX ix_meals_owner_date ON app.meals (owner_id, local_date)")
    op.execute("""CREATE TABLE app.meal_items (
    owner_id UUID NOT NULL,
    meal_id UUID NOT NULL,
    item_id UUID NOT NULL,
    position INTEGER NOT NULL,
    name VARCHAR(200) NOT NULL,
    product_id UUID,
    product_revision INTEGER,
    quantity_amount NUMERIC(12, 6) NOT NULL,
    quantity_unit VARCHAR(2) NOT NULL,
    basis_unit VARCHAR(2) NOT NULL,
    energy_kcal NUMERIC(12, 6),
    protein_g NUMERIC(12, 6),
    fat_g NUMERIC(12, 6),
    carbs_g NUMERIC(12, 6),
    density_g_per_ml NUMERIC(12, 6),
    density_source VARCHAR(500),
    nutrition_origin VARCHAR(20) NOT NULL,
    formula_version VARCHAR(20) NOT NULL,
    ration_component_position INTEGER,
    CONSTRAINT pk_meal_items PRIMARY KEY (owner_id, meal_id, item_id),
    CONSTRAINT fk_meal_items_owner_id_meals FOREIGN KEY(owner_id, meal_id) REFERENCES app.meals
(owner_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_meal_items_product_id_product_versions FOREIGN KEY(product_id,
product_revision) REFERENCES app.product_versions (product_id, revision),
    CONSTRAINT uq_meal_items_owner_id UNIQUE (owner_id, meal_id, position),
    CONSTRAINT ck_meal_items_position_range CHECK (position BETWEEN 1 AND 100),
    CONSTRAINT ck_meal_items_name_length CHECK (length(name) BETWEEN 1 AND 200),
    CONSTRAINT ck_meal_items_exact_product_ref CHECK ((product_id IS NULL) = (product_revision
IS NULL)),
    CONSTRAINT ck_meal_items_product_revision CHECK (product_revision IS NULL OR
product_revision BETWEEN 1 AND 2147483647),
    CONSTRAINT ck_meal_items_quantity_range CHECK (quantity_amount IS NULL OR
(quantity_amount::text NOT IN ('NaN','Infinity','-Infinity') AND quantity_amount > 0 AND
quantity_amount <= 10000)),
    CONSTRAINT ck_meal_items_units CHECK (quantity_unit IN ('g','ml') AND basis_unit IN
('g','ml')),
    CONSTRAINT ck_meal_items_density_source CHECK ((density_g_per_ml IS NULL) = (density_source
IS NULL)),
    CONSTRAINT ck_meal_items_density_range CHECK (density_g_per_ml IS NULL OR
(density_g_per_ml::text NOT IN ('NaN','Infinity','-Infinity') AND density_g_per_ml > 0 AND
density_g_per_ml <= 999999.999999)),
    CONSTRAINT ck_meal_items_conversion_density CHECK (quantity_unit = basis_unit OR
density_g_per_ml IS NOT NULL),
    CONSTRAINT ck_meal_items_density_source_length CHECK (density_source IS NULL OR
length(density_source) BETWEEN 1 AND 500),
    CONSTRAINT ck_meal_items_nutrition_origin CHECK (nutrition_origin IN
('catalog_snapshot','manual','ai_estimate')),
    CONSTRAINT ck_meal_items_formula_version CHECK (formula_version = 'nutrition_v1'),
    CONSTRAINT ck_meal_items_ration_position CHECK (ration_component_position IS NULL OR
ration_component_position BETWEEN 1 AND 100000),
    CONSTRAINT ck_meal_items_energy_kcal_range CHECK (energy_kcal IS NULL OR (energy_kcal::text
NOT IN ('NaN','Infinity','-Infinity') AND energy_kcal >= 0 AND energy_kcal <= 999999.999999)),
    CONSTRAINT ck_meal_items_protein_g_range CHECK (protein_g IS NULL OR (protein_g::text NOT IN
('NaN','Infinity','-Infinity') AND protein_g >= 0 AND protein_g <= 999999.999999)),
    CONSTRAINT ck_meal_items_fat_g_range CHECK (fat_g IS NULL OR (fat_g::text NOT IN
('NaN','Infinity','-Infinity') AND fat_g >= 0 AND fat_g <= 999999.999999)),
    CONSTRAINT ck_meal_items_carbs_g_range CHECK (carbs_g IS NULL OR (carbs_g::text NOT IN
('NaN','Infinity','-Infinity') AND carbs_g >= 0 AND carbs_g <= 999999.999999))
)""")
    op.execute("""CREATE TABLE app.weights (
    id UUID NOT NULL,
    owner_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    weight_kg NUMERIC(12, 6) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    local_date DATE NOT NULL,
    time_zone VARCHAR(100) NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_weights PRIMARY KEY (id),
    CONSTRAINT uq_weights_owner_id UNIQUE (owner_id, id),
    CONSTRAINT ck_weights_revision_range CHECK (revision BETWEEN 1 AND 2147483647),
    CONSTRAINT ck_weights_weight_range CHECK (weight_kg IS NULL OR (weight_kg::text NOT IN
('NaN','Infinity','-Infinity') AND weight_kg > 0 AND weight_kg <= 1000)),
    CONSTRAINT ck_weights_time_zone_length CHECK (length(time_zone) BETWEEN 1 AND 100),
    CONSTRAINT ck_weights_local_date_matches CHECK ((occurred_at AT TIME ZONE time_zone)::date =
local_date),
    CONSTRAINT fk_weights_owner_id_user_accounts FOREIGN KEY(owner_id) REFERENCES
app.user_accounts (id)
)""")
    op.execute("CREATE INDEX ix_weights_owner_date ON app.weights (owner_id, local_date)")
    op.execute("""CREATE TABLE app.product_drafts (
    id UUID NOT NULL,
    owner_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    payload JSONB NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_product_drafts PRIMARY KEY (id),
    CONSTRAINT uq_product_drafts_owner_id UNIQUE (owner_id, id),
    CONSTRAINT ck_product_drafts_revision_range CHECK (revision BETWEEN 1 AND 2147483647),
    CONSTRAINT ck_product_drafts_payload_object CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT fk_product_drafts_owner_id_user_accounts FOREIGN KEY(owner_id) REFERENCES
app.user_accounts (id)
)""")
    op.execute("""
    CREATE FUNCTION app.private_diary_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
    BEGIN
        IF TG_OP = 'UPDATE' THEN
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id THEN
                RAISE EXCEPTION 'private owner is immutable' USING ERRCODE='23514';
            END IF;
            IF TG_TABLE_NAME = 'meal_items' THEN
                IF NEW.meal_id IS DISTINCT FROM OLD.meal_id OR NEW.item_id IS DISTINCT FROM
OLD.item_id THEN
                    RAISE EXCEPTION 'item identity is immutable' USING ERRCODE='23514';
                END IF;
            ELSE
                IF NEW.id IS DISTINCT FROM OLD.id OR
                   (OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL) THEN
                    RAISE EXCEPTION 'entity identity or tombstone is immutable' USING
ERRCODE='23514';
                END IF;
            END IF;
        END IF;
        IF TG_TABLE_NAME IN ('diary_days', 'meals', 'weights') THEN
            IF NOT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name=NEW.time_zone) THEN
                RAISE EXCEPTION 'unknown diary zone' USING ERRCODE='23514';
            END IF;
        END IF;
        IF TG_TABLE_NAME = 'diary_days' THEN
            IF TG_OP = 'UPDATE' AND (NEW.local_date IS DISTINCT FROM OLD.local_date OR
                                    NEW.time_zone IS DISTINCT FROM OLD.time_zone) THEN
                RAISE EXCEPTION 'diary day date and zone are immutable' USING ERRCODE='23514';
            END IF;
            IF NEW.deleted_at IS NOT NULL AND EXISTS (
                SELECT 1 FROM app.meals WHERE owner_id=NEW.owner_id
                    AND local_date=NEW.local_date AND deleted_at IS NULL
            ) THEN
                RAISE EXCEPTION 'live meal requires live diary day' USING ERRCODE='23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'meals' THEN
            IF NEW.deleted_at IS NULL AND NOT EXISTS (
                SELECT 1 FROM app.diary_days WHERE owner_id=NEW.owner_id
                    AND local_date=NEW.local_date AND deleted_at IS NULL
            ) THEN
                RAISE EXCEPTION 'live meal requires live diary day' USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NEW;
    END $$
    """)
    op.execute("""
    ALTER TABLE app.meals ADD CONSTRAINT ck_meals_ration_snapshot CHECK (
        ration IS NULL OR COALESCE((
            jsonb_typeof(ration) = 'object' AND
            ration ?& ARRAY['ration_id','revision','name'] AND
            jsonb_typeof(ration->'ration_id') = 'string' AND
            ration->>'ration_id' ~ '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' AND
            jsonb_typeof(ration->'revision') = 'number' AND
            ration->>'revision' ~ '^[1-9][0-9]{0,9}$' AND
            (ration->>'revision')::numeric BETWEEN 1 AND 2147483647 AND
            jsonb_typeof(ration->'name') = 'string' AND
            length(ration->>'name') BETWEEN 1 AND 200
        ), false)
    )
    """)
    # Item changes lock the aggregate even when issued through raw SQL. The
    # deferred cardinality check sees the final aggregate, including replacements.
    op.execute("""
    CREATE FUNCTION app.diary_item_lock() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
    BEGIN
        IF TG_OP='DELETE' THEN
            PERFORM 1 FROM app.meals WHERE owner_id=OLD.owner_id AND id=OLD.meal_id FOR UPDATE;
            RETURN OLD;
        END IF;
        PERFORM 1 FROM app.meals WHERE owner_id=NEW.owner_id AND id=NEW.meal_id FOR UPDATE;
        RETURN NEW;
    END $$
    """)
    op.execute("""
    CREATE FUNCTION app.diary_aggregate_count() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
    DECLARE meal uuid; owner uuid; size integer;
    BEGIN
        IF TG_TABLE_NAME='meals' THEN
            meal := NEW.id; owner := NEW.owner_id;
        ELSIF TG_OP='DELETE' THEN
            meal := OLD.meal_id; owner := OLD.owner_id;
        ELSE
            meal := NEW.meal_id; owner := NEW.owner_id;
        END IF;
        IF EXISTS (SELECT 1 FROM app.meals WHERE id=meal AND owner_id=owner AND deleted_at IS
NULL) THEN
            SELECT count(*) INTO size FROM app.meal_items WHERE owner_id=owner AND meal_id=meal;
            IF size NOT BETWEEN 1 AND 100 THEN
                RAISE EXCEPTION 'live meal must contain 1..100 items' USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NULL;
    END $$
    """)
    op.execute("""
    CREATE FUNCTION app.private_draft_valid(p jsonb) RETURNS boolean
    LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $$
    DECLARE k text; v jsonb; q jsonb; density jsonb; source jsonb;
    BEGIN
        IF jsonb_typeof(p) <> 'object' OR NOT p ?& ARRAY[
            'name','brand','variant','basis_unit','nutrition_per_100','package_quantity',
            'density_g_per_ml','density_source','source_description'
        ] OR (SELECT count(*) FROM jsonb_object_keys(p)) <> 9 THEN RETURN false; END IF;
        IF jsonb_typeof(p->'name') <> 'string' OR length(p->>'name') NOT BETWEEN 1 AND 200 OR
           jsonb_typeof(p->'source_description') <> 'string' OR
           length(p->>'source_description') NOT BETWEEN 1 AND 2000 OR
           jsonb_typeof(p->'basis_unit') <> 'string' OR
           p->>'basis_unit' NOT IN ('g','ml') THEN RETURN false; END IF;
        FOREACH k IN ARRAY ARRAY['brand','variant'] LOOP
            v := p->k;
            IF v <> 'null'::jsonb AND (jsonb_typeof(v) <> 'string' OR
                length(p->>k) NOT BETWEEN 1 AND 200) THEN RETURN false; END IF;
        END LOOP;
        v := p->'nutrition_per_100';
        IF jsonb_typeof(v) <> 'object' OR NOT v ?& ARRAY[
            'energy_kcal','protein_g','fat_g','carbs_g'
        ] OR (SELECT count(*) FROM jsonb_object_keys(v)) <> 4 THEN RETURN false; END IF;
        FOREACH k IN ARRAY ARRAY['energy_kcal','protein_g','fat_g','carbs_g'] LOOP
            IF v->k <> 'null'::jsonb AND (jsonb_typeof(v->k) <> 'string' OR
                v->>k !~ '^(0|[1-9][0-9]{0,5})([.][0-9]{0,5}[1-9])?$') THEN RETURN false; END
IF;
        END LOOP;
        density := p->'density_g_per_ml'; source := p->'density_source';
        IF (density = 'null'::jsonb) <> (source = 'null'::jsonb) THEN RETURN false; END IF;
        IF density <> 'null'::jsonb THEN
            IF jsonb_typeof(density) <> 'string' OR
               p->>'density_g_per_ml' !~ '^(0|[1-9][0-9]{0,5})([.][0-9]{0,5}[1-9])?$' OR
               (p->>'density_g_per_ml')::numeric <= 0 OR jsonb_typeof(source) <> 'string' OR
               length(p->>'density_source') NOT BETWEEN 1 AND 500 THEN RETURN false; END IF;
        END IF;
        q := p->'package_quantity';
        IF q <> 'null'::jsonb THEN
            IF jsonb_typeof(q) <> 'object' OR NOT q ?& ARRAY['amount','unit'] OR
               (SELECT count(*) FROM jsonb_object_keys(q)) <> 2 OR
               jsonb_typeof(q->'amount') <> 'string' OR
               q->>'amount' !~ '^(0|[1-9][0-9]{0,5})([.][0-9]{0,5}[1-9])?$' OR
               (q->>'amount')::numeric <= 0 OR
               jsonb_typeof(q->'unit') <> 'string' OR q->>'unit' NOT IN ('g','ml') OR
               (q->>'unit' <> p->>'basis_unit' AND density = 'null'::jsonb)
            THEN RETURN false; END IF;
        END IF;
        RETURN true;
    EXCEPTION WHEN others THEN RETURN false;
    END $$
    """)
    op.execute(
        "ALTER TABLE app.product_drafts ADD CONSTRAINT ck_product_drafts_strict_payload "
        "CHECK (app.private_draft_valid(payload))"
    )
    for table in ("diary_days", "meals", "meal_items", "weights", "product_drafts"):
        op.execute(
            f"CREATE TRIGGER private_account BEFORE INSERT OR UPDATE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.private_account_guard()"
        )
        op.execute(
            f"CREATE TRIGGER private_guard BEFORE INSERT OR UPDATE ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.private_diary_guard()"
        )
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC, calorie_app_api, calorie_app_worker")
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON app.{table} "
            "TO calorie_app_api, calorie_app_worker"
        )
    op.execute(
        "CREATE TRIGGER diary_item_lock BEFORE INSERT OR UPDATE OR DELETE ON app.meal_items "
        "FOR EACH ROW EXECUTE FUNCTION app.diary_item_lock()"
    )
    for table in ("meals", "meal_items"):
        op.execute(
            "CREATE CONSTRAINT TRIGGER diary_aggregate_count AFTER INSERT OR UPDATE OR DELETE "
            f"ON app.{table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION app.diary_aggregate_count()"
        )
    for function in (
        "private_diary_guard()",
        "diary_item_lock()",
        "diary_aggregate_count()",
        "private_draft_valid(jsonb)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION app.{function} FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.private_draft_valid(jsonb) "
        "TO calorie_app_api, calorie_app_worker"
    )


def downgrade():
    op.execute("""
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM app.diary_days) OR EXISTS (SELECT 1 FROM app.meals) OR
           EXISTS (SELECT 1 FROM app.weights) OR EXISTS (SELECT 1 FROM app.product_drafts) THEN
            RAISE EXCEPTION 'cannot remove private diary history' USING ERRCODE='23514';
        END IF;
    END $$
    """)
    for table in ("meal_items", "meals", "weights", "product_drafts", "diary_days"):
        op.drop_table(table, schema="app")
    for function in (
        "private_diary_guard()",
        "diary_item_lock()",
        "diary_aggregate_count()",
        "private_draft_valid(jsonb)",
    ):
        op.execute(f"DROP FUNCTION app.{function}")
