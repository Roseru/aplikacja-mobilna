"""Community immutable versions, narrow writes, durable admission and purge extension."""

from alembic import op

revision = "0013_e6_community"
down_revision = "0012_e5_reads"
branch_labels = None
depends_on = None

TABLES = (
    "community_catalog_state",
    "community_products",
    "community_versions",
    "community_authors",
    "community_publication_bindings",
    "community_votes",
    "community_reports",
    "community_audit",
    "community_receipts",
    "community_quotas",
)
ROLES = "PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_deletion_operator"


# Frozen DDL: later ORM evolution must never change this migration.
SCHEMA_SQL = {
    "community_catalog_state": """
CREATE TABLE app.community_catalog_state (
	id SERIAL NOT NULL,
	revision BIGINT DEFAULT '1' NOT NULL,
	queue_revision BIGINT DEFAULT '1' NOT NULL,
	CONSTRAINT pk_community_catalog_state PRIMARY KEY (id),
	CONSTRAINT ck_community_catalog_state_singleton CHECK (id=1),
	CONSTRAINT ck_community_catalog_state_revision_range CHECK (revision>=1 AND queue_revision>=1)
)
    """,
    "community_products": """
CREATE TABLE app.community_products (
	product_id UUID NOT NULL,
	current_revision INTEGER DEFAULT '1' NOT NULL,
	state_revision INTEGER DEFAULT '1' NOT NULL,
	verification VARCHAR(16) DEFAULT 'unverified' NOT NULL,
	visibility VARCHAR(16) DEFAULT 'visible' NOT NULL,
	canonical_id UUID,
	CONSTRAINT pk_community_products PRIMARY KEY (product_id),
	CONSTRAINT ck_community_products_revision_range CHECK (current_revision>=1 AND
	state_revision>=1),
	CONSTRAINT ck_community_products_verification CHECK (verification IN ('unverified','verified')),
	CONSTRAINT ck_community_products_visibility CHECK (visibility IN ('visible','hidden')),
	CONSTRAINT ck_community_products_not_self_merge CHECK (canonical_id IS NULL OR
	canonical_id<>product_id),
	CONSTRAINT fk_community_products_product_id_products FOREIGN KEY(product_id) REFERENCES
	app.products (id),
	CONSTRAINT fk_community_products_canonical_id_community_products FOREIGN KEY(canonical_id)
	REFERENCES app.community_products (product_id)
);
CREATE INDEX ix_community_products_roots ON app.community_products (product_id) WHERE canonical_id
IS NULL AND visibility='visible'
    """,
    "community_versions": """
CREATE TABLE app.community_versions (
	product_id UUID NOT NULL,
	revision INTEGER NOT NULL,
	source_kind VARCHAR(16) NOT NULL,
	source_description VARCHAR(2000) NOT NULL,
	ingredients JSONB,
	recipe VARCHAR(4000),
	identity JSONB NOT NULL,
	normalized_names TEXT[] NOT NULL,
	normalized_name_hashes VARCHAR(64)[] NOT NULL,
	normalized_identity JSONB NOT NULL,
	identity_key VARCHAR(64) NOT NULL,
	search_text TEXT NOT NULL,
	CONSTRAINT pk_community_versions PRIMARY KEY (product_id, revision),
	CONSTRAINT fk_community_versions_product_id_product_versions FOREIGN KEY(product_id, revision)
	REFERENCES app.product_versions (product_id, revision),
	CONSTRAINT ck_community_versions_source_kind CHECK (source_kind IN
	('label','recipe','estimate','ai')),
	CONSTRAINT ck_community_versions_names_limit CHECK (cardinality(normalized_names) BETWEEN 1 AND
	51),
	CONSTRAINT ck_community_versions_ingredients_limit CHECK (ingredients IS NULL OR
	(jsonb_typeof(ingredients)='array' AND jsonb_array_length(ingredients)<=100)),
	CONSTRAINT ck_community_versions_identity_limit CHECK (octet_length(identity::text)<=1048576 AND
	octet_length(normalized_identity::text)<=1048576),
	CONSTRAINT fk_community_versions_product_id_community_products FOREIGN KEY(product_id)
	REFERENCES app.community_products (product_id)
);
CREATE INDEX ix_community_versions_identity ON app.community_versions (identity_key);
CREATE INDEX ix_community_versions_names ON app.community_versions USING gin
(normalized_name_hashes);
CREATE INDEX ix_community_versions_trgm ON app.community_versions USING gin (search_text
gin_trgm_ops)
    """,
    "community_authors": """
CREATE TABLE app.community_authors (
	product_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	CONSTRAINT pk_community_authors PRIMARY KEY (product_id, owner_id),
	CONSTRAINT fk_community_authors_product_id_community_products FOREIGN KEY(product_id) REFERENCES
	app.community_products (product_id),
	CONSTRAINT fk_community_authors_owner_id_user_accounts FOREIGN KEY(owner_id) REFERENCES
	app.user_accounts (id)
)
    """,
    "community_publication_bindings": """
CREATE TABLE app.community_publication_bindings (
	owner_id UUID NOT NULL,
	draft_id UUID NOT NULL,
	draft_revision INTEGER NOT NULL,
	metadata_hash VARCHAR(64) NOT NULL,
	product_id UUID NOT NULL,
	product_revision INTEGER NOT NULL,
	result_minimal JSONB NOT NULL,
	CONSTRAINT pk_community_publication_bindings PRIMARY KEY (owner_id, draft_id, draft_revision),
	CONSTRAINT fk_community_publication_bindings_product_id_product_versions FOREIGN KEY(product_id,
	product_revision) REFERENCES app.product_versions (product_id, revision),
	CONSTRAINT ck_community_publication_bindings_draft_revision CHECK (draft_revision>=1),
	CONSTRAINT ck_community_publication_bindings_metadata_hash CHECK (metadata_hash ~
	'^[0-9a-f]{64}$'),
	CONSTRAINT fk_community_publication_bindings_owner_id_user_accounts FOREIGN KEY(owner_id)
	REFERENCES app.user_accounts (id)
)
    """,
    "community_votes": """
CREATE TABLE app.community_votes (
	owner_id UUID NOT NULL,
	product_id UUID NOT NULL,
	value INTEGER,
	revision INTEGER NOT NULL,
	active BOOLEAN DEFAULT 'true' NOT NULL,
	CONSTRAINT pk_community_votes PRIMARY KEY (owner_id, product_id),
	CONSTRAINT ck_community_votes_value CHECK (value IS NULL OR value IN (-1,1)),
	CONSTRAINT ck_community_votes_revision CHECK (revision BETWEEN 1 AND 2147483647),
	CONSTRAINT ck_community_votes_active_value CHECK (NOT active OR value IS NOT NULL),
	CONSTRAINT fk_community_votes_owner_id_user_accounts FOREIGN KEY(owner_id) REFERENCES
	app.user_accounts (id),
	CONSTRAINT fk_community_votes_product_id_products FOREIGN KEY(product_id) REFERENCES
	app.products (id)
);
CREATE INDEX ix_community_votes_product_active ON app.community_votes (product_id, active)
    """,
    "community_reports": """
CREATE TABLE app.community_reports (
	id UUID NOT NULL,
	owner_id UUID,
	product_id UUID NOT NULL,
	product_revision INTEGER NOT NULL,
	canonical_id UUID NOT NULL,
	reason VARCHAR(2000) NOT NULL,
	description VARCHAR(2000) NOT NULL,
	status VARCHAR(24) DEFAULT 'open' NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	resolution_reason VARCHAR(2000),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	CONSTRAINT pk_community_reports PRIMARY KEY (id),
	CONSTRAINT fk_community_reports_product_id_product_versions FOREIGN KEY(product_id,
	product_revision) REFERENCES app.product_versions (product_id, revision),
	CONSTRAINT ck_community_reports_status CHECK (status IN
	('open','resolved','dismissed','referred_to_admin')),
	CONSTRAINT ck_community_reports_revision CHECK (revision BETWEEN 1 AND 2147483647),
	CONSTRAINT fk_community_reports_owner_id_user_accounts FOREIGN KEY(owner_id) REFERENCES
	app.user_accounts (id),
	CONSTRAINT fk_community_reports_canonical_id_products FOREIGN KEY(canonical_id) REFERENCES
	app.products (id)
);
CREATE INDEX ix_community_reports_queue ON app.community_reports (status, id)
    """,
    "community_audit": """
CREATE TABLE app.community_audit (
	id UUID NOT NULL,
	actor_id UUID,
	operation_id UUID,
	action VARCHAR(40) NOT NULL,
	reason VARCHAR(2000),
	old_ref JSONB,
	new_ref JSONB,
	old_state INTEGER,
	new_state INTEGER,
	source_id UUID,
	target_id UUID,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	CONSTRAINT pk_community_audit PRIMARY KEY (id),
	CONSTRAINT fk_community_audit_actor_id_user_accounts FOREIGN KEY(actor_id) REFERENCES
	app.user_accounts (id),
	CONSTRAINT fk_community_audit_source_id_products FOREIGN KEY(source_id) REFERENCES app.products
	(id),
	CONSTRAINT fk_community_audit_target_id_products FOREIGN KEY(target_id) REFERENCES app.products
	(id)
);
CREATE INDEX ix_community_audit_operation ON app.community_audit (operation_id)
    """,
    "community_receipts": """
CREATE TABLE app.community_receipts (
	owner_id UUID NOT NULL,
	operation_kind VARCHAR(40) NOT NULL,
	operation_id UUID NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	generation INTEGER NOT NULL,
	sync_epoch UUID NOT NULL,
	status_code INTEGER NOT NULL,
	response_payload JSONB,
	result_minimal JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	CONSTRAINT pk_community_receipts PRIMARY KEY (owner_id, operation_kind, operation_id),
	CONSTRAINT ck_community_receipts_generation CHECK (generation>=1),
	CONSTRAINT ck_community_receipts_request_hash CHECK (request_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_community_receipts_status_code CHECK (status_code BETWEEN 200 AND 499),
	CONSTRAINT ck_community_receipts_bounded_response CHECK
	(octet_length(result_minimal::text)<=8192 AND (response_payload IS NULL OR
	octet_length(response_payload::text)<=1048576)),
	CONSTRAINT fk_community_receipts_owner_id_user_accounts FOREIGN KEY(owner_id) REFERENCES
	app.user_accounts (id)
);
CREATE INDEX ix_community_receipts_retention ON app.community_receipts (owner_id, created_at)
WHERE response_payload IS NOT NULL
    """,
    "community_quotas": """
CREATE TABLE app.community_quotas (
	owner_id UUID NOT NULL,
	day DATE NOT NULL,
	receipts INTEGER DEFAULT '0' NOT NULL,
	products INTEGER DEFAULT '0' NOT NULL,
	reports INTEGER DEFAULT '0' NOT NULL,
	votes INTEGER DEFAULT '0' NOT NULL,
	CONSTRAINT pk_community_quotas PRIMARY KEY (owner_id, day),
	CONSTRAINT ck_community_quotas_limits CHECK (receipts BETWEEN 0 AND 1000 AND products BETWEEN 0
	AND 20 AND reports BETWEEN 0 AND 50 AND votes BETWEEN 0 AND 200),
	CONSTRAINT fk_community_quotas_owner_id_user_accounts FOREIGN KEY(owner_id) REFERENCES
	app.user_accounts (id)
)
    """,
}


def upgrade():
    # Trusted pg_trgm is installed by migration/provisioning, never by API startup.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
    for name in TABLES:
        op.execute(SCHEMA_SQL[name])
        op.execute(f"REVOKE ALL ON app.{name} FROM {ROLES}")
    op.execute("INSERT INTO app.community_catalog_state(id) VALUES(1)")
    for table in TABLES:
        op.execute(f"GRANT SELECT ON app.{table} TO calorie_app_api")
    for table in ("community_authors", "community_publication_bindings", "community_receipts"):
        op.execute(f"GRANT INSERT ON app.{table} TO calorie_app_api")
    for table in ("community_votes", "community_reports"):
        op.execute(f"GRANT INSERT,UPDATE ON app.{table} TO calorie_app_api")
    op.execute(
        "GRANT "
        "UPDATE(current_revision,state_revision,verification,visibility,canonical_id) "
        "ON app.community_products TO calorie_app_api"
    )
    # REVOKE table privilege does not revoke legacy column privileges from E1.
    for table in ("products", "product_sources", "product_versions"):
        op.execute(f"REVOKE ALL ON app.{table} FROM {ROLES}")
        op.execute(f"""DO $$ DECLARE cols text; BEGIN
          SELECT string_agg(quote_ident(attname),',') INTO cols FROM pg_catalog.pg_attribute
          WHERE attrelid='app.{table}'::regclass AND attnum>0 AND NOT attisdropped;
          EXECUTE 'REVOKE INSERT('||cols||'),UPDATE('||cols||'),REFERENCES('||cols||')
          ON app.{table} FROM {ROLES}';
        END $$""")
        op.execute(f"GRANT SELECT ON app.{table} TO calorie_app_api,calorie_app_worker")
    _locks()
    _write_version()
    _audit()
    _admission_retention()
    _guards()
    _purge()


def _locks():
    op.execute("""
    CREATE FUNCTION app.lock_community_catalog(p_shared boolean DEFAULT false)
    RETURNS TABLE(revision bigint,queue_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    BEGIN
      IF p_shared THEN
        RETURN QUERY SELECT s.revision,s.queue_revision FROM app.community_catalog_state s
          WHERE s.id=1 FOR SHARE;
      ELSE
        RETURN QUERY SELECT s.revision,s.queue_revision FROM app.community_catalog_state s
          WHERE s.id=1 FOR UPDATE;
      END IF;
    END $$;
    REVOKE ALL ON FUNCTION app.lock_community_catalog(boolean) FROM
    PUBLIC,calorie_app_worker,calorie_app_deletion_operator;
    GRANT EXECUTE ON FUNCTION app.lock_community_catalog(boolean) TO calorie_app_api;
    CREATE FUNCTION app.bump_community_catalog(p_queue boolean DEFAULT false) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE r bigint;
    BEGIN
      UPDATE app.community_catalog_state SET revision=revision+1,
        queue_revision=queue_revision+CASE WHEN p_queue THEN 1 ELSE 0 END WHERE id=1
        RETURNING revision INTO r;
      RETURN r;
    END $$;
    REVOKE ALL ON FUNCTION app.bump_community_catalog(boolean) FROM
    PUBLIC,calorie_app_worker,calorie_app_deletion_operator;
    GRANT EXECUTE ON FUNCTION app.bump_community_catalog(boolean) TO calorie_app_api;
    """)


def _write_version():
    op.execute("""
    CREATE FUNCTION app.create_community_version(p_product uuid,p_revision integer,p_source uuid,
      p_density_source uuid,p_snapshot jsonb,p_metadata jsonb) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE current_rev integer; names text[]; h text;
    BEGIN
      PERFORM 1 FROM app.community_catalog_state WHERE id=1 FOR UPDATE;
      IF p_product IS NULL OR p_source IS NULL OR p_revision IS NULL OR p_revision<1
         OR jsonb_typeof(p_snapshot) IS DISTINCT FROM 'object'
         OR jsonb_typeof(p_metadata) IS DISTINCT FROM 'object'
         OR octet_length(p_snapshot::text)>1048576 OR octet_length(p_metadata::text)>4194304
         OR p_metadata->>'source_kind' NOT IN ('label','recipe','estimate','ai')
         OR coalesce(length(p_metadata->>'source_description'),0) NOT BETWEEN 1 AND 2000
         OR coalesce(length(p_snapshot->>'name'),0) NOT BETWEEN 1 AND 2000
         OR p_snapshot->>'basis_unit' NOT IN ('g','ml')
         OR coalesce(length(p_snapshot->>'source_locator'),0)>2000
         OR coalesce(length(p_snapshot->>'brand'),0)>2000
         OR coalesce(length(p_snapshot->>'variant'),0)>2000
         OR coalesce(length(p_snapshot->>'preparation'),0)>2000
         OR coalesce(length(p_snapshot->>'density_source_description'),0)>2000
         OR jsonb_typeof(p_metadata->'identity') IS DISTINCT FROM 'object'
         OR jsonb_typeof(p_metadata->'normalized_names') IS DISTINCT FROM 'array'
         OR coalesce(length(p_metadata->>'identity_key'),0)<>64
         OR jsonb_typeof(p_metadata->'normalized_identity') IS DISTINCT FROM 'object'
         OR coalesce(length(p_metadata->>'search_text'),0)>1048576
         OR coalesce(length(p_metadata->>'recipe'),0)>4000
         OR jsonb_typeof(p_snapshot->'aliases') IS DISTINCT FROM 'array'
         OR jsonb_array_length(p_snapshot->'aliases')>50
         OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_snapshot->'aliases') a
                   WHERE jsonb_typeof(a)<>'string' OR length(a#>>'{}')>2000)
         OR (p_snapshot->>'package_amount')::numeric IS NULL
         OR p_snapshot->>'package_unit' NOT IN ('g','ml')
         OR ((p_snapshot->>'density_amount') IS NULL) IS DISTINCT FROM (p_density_source IS NULL)
         OR (p_density_source IS NOT NULL AND
         coalesce(length(p_snapshot->>'density_source_description'),0)=0)
      THEN RAISE EXCEPTION 'invalid community snapshot' USING ERRCODE='23514'; END IF;
      SELECT array_agg(a#>>'{}') INTO names FROM
      jsonb_array_elements(p_metadata->'normalized_names') a;
      IF cardinality(names) NOT BETWEEN 1 AND 51 OR EXISTS(SELECT 1 FROM unnest(names) n
      WHERE length(n) NOT BETWEEN 1 AND 36000)
         OR p_metadata->>'identity_key' IS NULL OR p_metadata->>'search_text' IS NULL THEN
        RAISE EXCEPTION 'invalid community identity' USING ERRCODE='23514';
      END IF;
      SELECT current_revision INTO current_rev FROM app.community_products WHERE
      product_id=p_product FOR UPDATE;
      IF p_revision=1 THEN
        IF FOUND OR EXISTS(SELECT 1 FROM app.products WHERE id=p_product) THEN
          RAISE EXCEPTION 'community cannot adopt existing product' USING ERRCODE='23514';
        END IF;
        INSERT INTO app.products(id) VALUES(p_product);
        INSERT INTO app.community_products(product_id) VALUES(p_product);
      ELSIF current_rev IS NULL OR current_rev+1<>p_revision OR EXISTS(
          SELECT 1 FROM app.community_products WHERE product_id=p_product AND
          canonical_id IS NOT NULL) THEN
        RAISE EXCEPTION 'community revision conflict' USING ERRCODE='23514';
      END IF;
      h := encode(sha256(convert_to(p_snapshot::text||p_metadata::text,'UTF8')),'hex');
      INSERT INTO
      app.product_sources(id,description,status,document_id,basis,missing_data,notes,content_hash)
        VALUES(p_source,p_metadata->>'source_description','unverified',
          'community:'||p_product::text||':'||p_revision::text,
          CASE WHEN p_snapshot->>'basis_unit'='g' THEN 'per_100_g' ELSE 'per_100_ml' END,
          '[]'::jsonb,'[]'::jsonb,h);
      IF p_density_source IS NOT NULL THEN
        INSERT INTO
        app.product_sources(id,description,status,document_id,basis,missing_data,notes,content_hash)
          VALUES(p_density_source,p_snapshot->>'density_source_description','unverified',
            'community-density:'||p_product::text||':'||p_revision::text,'per_100_ml','[]'::jsonb,'[]'::jsonb,h);
      END IF;
      INSERT INTO app.product_versions(product_id,revision,source_id,name,basis_unit,
        energy_kcal,protein_g,fat_g,carbs_g,aliases,brand,variant,package_amount,package_unit,
        density_amount,density_source_id,source_locator,status,preparation,content_hash)
      VALUES(p_product,p_revision,p_source,p_snapshot->>'name',p_snapshot->>'basis_unit',
        (p_snapshot->>'energy_kcal')::numeric,(p_snapshot->>'protein_g')::numeric,
        (p_snapshot->>'fat_g')::numeric,(p_snapshot->>'carbs_g')::numeric,
        p_snapshot->'aliases',p_snapshot->>'brand',p_snapshot->>'variant',
        (p_snapshot->>'package_amount')::numeric,p_snapshot->>'package_unit',
        (p_snapshot->>'density_amount')::numeric,p_density_source,
        coalesce(p_snapshot->>'source_locator',p_metadata->>'source_description'),'unverified',
        p_snapshot->>'preparation',h);
      INSERT INTO app.community_versions(product_id,revision,source_kind,source_description,
        ingredients,recipe,identity,normalized_identity,normalized_names,normalized_name_hashes,identity_key,search_text)
      VALUES(p_product,p_revision,p_metadata->>'source_kind',p_metadata->>'source_description',
        nullif(p_metadata->'ingredients','null'::jsonb),p_metadata->>'recipe',p_metadata->'identity',p_metadata->'normalized_identity',names,
        ARRAY(SELECT encode(sha256(convert_to(n,'UTF8')),'hex') FROM unnest(names) n),
        p_metadata->>'identity_key',p_metadata->>'search_text');
    END $$;
    REVOKE ALL ON FUNCTION app.create_community_version(uuid,integer,uuid,uuid,jsonb,jsonb)
      FROM PUBLIC,calorie_app_worker,calorie_app_deletion_operator;
    GRANT EXECUTE ON FUNCTION app.create_community_version(uuid,integer,uuid,uuid,jsonb,jsonb)
    TO calorie_app_api;
    """)


def _audit():
    op.execute("""
    CREATE FUNCTION app.append_community_audit(p_event jsonb) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE event_id uuid; actor uuid;
    BEGIN
      IF jsonb_typeof(p_event) IS DISTINCT FROM 'object' OR octet_length(p_event::text)>16384
         OR coalesce(length(p_event->>'action'),0) NOT BETWEEN 1 AND 40
         OR coalesce(length(p_event->>'reason'),0)>2000 THEN
        RAISE EXCEPTION 'invalid audit event' USING ERRCODE='23514';
      END IF;
      actor := (p_event->>'actor_id')::uuid;
      IF actor IS NULL OR NOT EXISTS(SELECT 1 FROM app.user_accounts WHERE id=actor AND
      state='active') THEN
        RAISE EXCEPTION 'audit requires active actor' USING ERRCODE='23514';
      END IF;
      event_id := coalesce((p_event->>'id')::uuid,gen_random_uuid());
      INSERT INTO app.community_audit(id,actor_id,operation_id,action,reason,old_ref,new_ref,
        old_state,new_state,source_id,target_id)
      VALUES(event_id,actor,(p_event->>'operation_id')::uuid,p_event->>'action',p_event->>'reason',
        nullif(p_event->'old_ref','null'::jsonb),nullif(p_event->'new_ref','null'::jsonb),
        (p_event->>'old_state')::integer,(p_event->>'new_state')::integer,
        (p_event->>'source_id')::uuid,(p_event->>'target_id')::uuid);
      RETURN event_id;
    END $$;
    REVOKE ALL ON FUNCTION app.append_community_audit(jsonb) FROM
    PUBLIC,calorie_app_worker,calorie_app_deletion_operator;
    GRANT EXECUTE ON FUNCTION app.append_community_audit(jsonb) TO calorie_app_api;
    """)


def _admission_retention():
    op.execute("""
    CREATE FUNCTION app.admit_community_operation(p_owner uuid,p_kind text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE today date; cap integer; used integer;
    BEGIN
      IF p_owner IS NULL OR p_kind IS NULL OR p_kind NOT IN
      ('receipts','products','reports','votes') THEN
        RAISE EXCEPTION 'invalid community admission' USING ERRCODE='22023';
      END IF;
      PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' FOR UPDATE;
      IF NOT FOUND THEN RAISE EXCEPTION 'admission requires active owner' USING
      ERRCODE='23514'; END IF;
      today := (clock_timestamp() AT TIME ZONE 'UTC')::date;
      INSERT INTO app.community_quotas(owner_id,day) VALUES(p_owner,today) ON CONFLICT DO NOTHING;
      SELECT CASE p_kind WHEN 'receipts' THEN receipts WHEN 'products' THEN products
        WHEN 'reports' THEN reports ELSE votes END INTO used FROM app.community_quotas
        WHERE owner_id=p_owner AND day=today FOR UPDATE;
      cap := CASE p_kind WHEN 'receipts' THEN 1000 WHEN 'products' THEN 20 WHEN 'reports'
      THEN 50 ELSE 200 END;
      IF used>=cap THEN RETURN false; END IF;
      UPDATE app.community_quotas SET receipts=receipts+CASE WHEN p_kind='receipts' THEN 1
      ELSE 0 END,
        products=products+CASE WHEN p_kind='products' THEN 1 ELSE 0 END,
        reports=reports+CASE WHEN p_kind='reports' THEN 1 ELSE 0 END,
        votes=votes+CASE WHEN p_kind='votes' THEN 1 ELSE 0 END WHERE owner_id=p_owner AND
        day=today;
      RETURN true;
    END $$;
    REVOKE ALL ON FUNCTION app.admit_community_operation(uuid,text) FROM
    PUBLIC,calorie_app_worker,calorie_app_deletion_operator;
    GRANT EXECUTE ON FUNCTION app.admit_community_operation(uuid,text) TO calorie_app_api;
    CREATE FUNCTION app.prune_community_receipts(p_owner uuid,p_batch integer DEFAULT 1000)
    RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE n integer; q integer; cut timestamptz;
    BEGIN
      IF p_owner IS NULL OR p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'invalid community retention' USING ERRCODE='22023';
      END IF;
      PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' FOR UPDATE;
      IF NOT FOUND THEN RAISE EXCEPTION 'retention requires active owner' USING
      ERRCODE='23514'; END IF;
      PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
      cut := clock_timestamp()-interval '60 days';
      WITH expired AS (SELECT owner_id,operation_kind,operation_id FROM app.community_receipts
        WHERE owner_id=p_owner AND created_at<=cut AND response_payload IS NOT NULL
        ORDER BY created_at,operation_kind,operation_id LIMIT p_batch)
      UPDATE app.community_receipts r SET response_payload=NULL FROM expired e
        WHERE r.owner_id=e.owner_id AND r.operation_kind=e.operation_kind AND
        r.operation_id=e.operation_id;
      GET DIAGNOSTICS n=ROW_COUNT;
      WITH expired AS (SELECT owner_id,day FROM app.community_quotas WHERE owner_id=p_owner
        AND day<(clock_timestamp() AT TIME ZONE 'UTC')::date-60 ORDER BY day LIMIT p_batch)
      DELETE FROM app.community_quotas q USING expired e WHERE q.owner_id=e.owner_id AND
      q.day=e.day;
      GET DIAGNOSTICS q=ROW_COUNT;
      RETURN jsonb_build_object('community_receipts',n,'community_quotas',q);
    END $$;
    REVOKE ALL ON FUNCTION app.prune_community_receipts(uuid,integer) FROM
    PUBLIC,calorie_app_api,calorie_app_deletion_operator;
    GRANT EXECUTE ON FUNCTION app.prune_community_receipts(uuid,integer) TO calorie_app_worker;
    """)


def _guards():
    op.execute("""
    CREATE FUNCTION app.community_state_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE root app.community_products%ROWTYPE;
    BEGIN
      IF NEW.product_id<>OLD.product_id OR NEW.state_revision<>OLD.state_revision+1
         OR NEW.current_revision<OLD.current_revision
         OR NOT EXISTS(SELECT 1 FROM app.community_versions
             WHERE product_id=NEW.product_id AND revision=NEW.current_revision) THEN
        RAISE EXCEPTION 'invalid community state transition' USING ERRCODE='23514';
      END IF;
      IF NEW.verification='verified' AND EXISTS(SELECT 1 FROM app.product_versions
          WHERE product_id=NEW.product_id AND revision=NEW.current_revision
            AND (energy_kcal IS NULL OR protein_g IS NULL OR fat_g IS NULL OR carbs_g IS NULL))
        THEN RAISE EXCEPTION 'verified community requires complete nutrition'
          USING ERRCODE='23514'; END IF;
      IF OLD.canonical_id IS NOT NULL AND NEW.canonical_id IS DISTINCT FROM OLD.canonical_id THEN
        IF NEW.canonical_id IS NULL OR NOT EXISTS(
            SELECT 1 FROM app.community_products prior
            JOIN app.community_products target ON target.product_id=NEW.canonical_id
            WHERE prior.product_id=OLD.canonical_id AND prior.canonical_id=NEW.canonical_id
              AND target.canonical_id IS NULL AND target.visibility='visible') THEN
          RAISE EXCEPTION 'canonical mapping only permits guarded compression'
            USING ERRCODE='23514'; END IF;
      END IF;
      IF NEW.canonical_id IS NOT NULL AND OLD.canonical_id IS NULL THEN
        SELECT * INTO root FROM app.community_products WHERE product_id=NEW.canonical_id;
        IF NOT FOUND OR root.canonical_id IS NOT NULL OR root.visibility<>'visible'
           OR OLD.visibility<>'visible' THEN
          RAISE EXCEPTION 'merge requires different visible community roots'
            USING ERRCODE='23514'; END IF;
        -- Existing sources may be compressed only after this root maps to target.
      END IF;
      RETURN NEW;
    END $$;
    REVOKE ALL ON FUNCTION app.community_state_guard() FROM
      PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_deletion_operator;
    CREATE TRIGGER community_state_guard BEFORE UPDATE ON app.community_products
      FOR EACH ROW EXECUTE FUNCTION app.community_state_guard();
    """)
    op.execute("""
    CREATE FUNCTION app.community_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    BEGIN
      IF TG_TABLE_NAME='community_audit' AND TG_OP='UPDATE'
         AND OLD.actor_id IS NOT NULL AND app.deletion_purge_authorized(OLD.actor_id)
         AND NEW.actor_id IS NULL AND NEW.operation_id IS NULL AND NEW.reason IS NULL
         AND (to_jsonb(NEW)-ARRAY['actor_id','operation_id','reason'])=
             (to_jsonb(OLD)-ARRAY['actor_id','operation_id','reason']) THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'immutable community evidence' USING ERRCODE='23514';
    END $$;
    REVOKE ALL ON FUNCTION app.community_immutable_guard() FROM
    PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_deletion_operator;
    CREATE TRIGGER community_immutable BEFORE UPDATE OR DELETE ON app.community_versions
      FOR EACH ROW EXECUTE FUNCTION app.community_immutable_guard();
    CREATE TRIGGER community_immutable BEFORE UPDATE OR DELETE ON app.community_audit
      FOR EACH ROW EXECUTE FUNCTION app.community_immutable_guard();
    CREATE FUNCTION app.community_binding_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$ BEGIN
      IF TG_OP='DELETE' AND app.deletion_purge_authorized(OLD.owner_id) THEN RETURN OLD; END IF;
      RAISE EXCEPTION 'immutable publication binding' USING ERRCODE='23514';
    END $$;
    REVOKE ALL ON FUNCTION app.community_binding_guard() FROM
    PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_deletion_operator;
    CREATE TRIGGER community_binding_immutable BEFORE UPDATE OR DELETE ON
    app.community_publication_bindings
      FOR EACH ROW EXECUTE FUNCTION app.community_binding_guard();
    """)


def _purge():
    # Preserve the complete old graph purge byte-for-byte; only wrapper is new.
    op.execute("ALTER FUNCTION app.purge_deleted_account(uuid) RENAME TO purge_deleted_account_e5")
    op.execute(f"REVOKE ALL ON FUNCTION app.purge_deleted_account_e5(uuid) FROM {ROLES}")
    op.execute("""
    CREATE FUNCTION app.purge_deleted_account(p_operation uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    DECLARE j app.account_deletion_jobs%ROWTYPE;
    BEGIN
      SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation;
      IF NOT FOUND THEN RAISE EXCEPTION 'unknown deletion job' USING ERRCODE='23514'; END IF;
      PERFORM 1 FROM app.user_accounts WHERE id=j.account_id FOR UPDATE;
      PERFORM 1 FROM app.sync_counters WHERE owner_id=j.account_id FOR UPDATE;
      PERFORM 1 FROM app.community_catalog_state WHERE id=1 FOR UPDATE;
      SELECT * INTO j FROM app.account_deletion_jobs WHERE operation_id=p_operation FOR UPDATE;
      IF j.purged_at IS NOT NULL THEN RETURN; END IF;
      IF j.identity_confirmed_at IS NULL OR NOT EXISTS(
          SELECT 1 FROM app.user_accounts WHERE id=j.account_id AND state='deleting'
            AND generation=j.deleting_generation AND issuer=j.issuer AND subject=j.subject)
        OR NOT EXISTS(SELECT 1 FROM app.deleted_subjects WHERE issuer=j.issuer AND
        subject=j.subject AND operation_id=p_operation) THEN
        RAISE EXCEPTION 'purge requires exact confirmed deleting target' USING ERRCODE='23514';
      END IF;
      INSERT INTO app._deletion_context VALUES(txid_current(),j.account_id,p_operation);
      DELETE FROM app.community_publication_bindings WHERE owner_id=j.account_id;
      DELETE FROM app.community_receipts WHERE owner_id=j.account_id;
      DELETE FROM app.community_quotas WHERE owner_id=j.account_id;
      DELETE FROM app.community_votes WHERE owner_id=j.account_id;
      DELETE FROM app.community_reports WHERE owner_id=j.account_id;
      DELETE FROM app.community_authors WHERE owner_id=j.account_id;
      UPDATE app.community_audit SET actor_id=NULL,operation_id=NULL,reason=NULL WHERE
      actor_id=j.account_id;
      DELETE FROM app._deletion_context WHERE transaction_id=txid_current();
      UPDATE app.community_catalog_state SET
      revision=revision+1,queue_revision=queue_revision+1 WHERE id=1;
      PERFORM app.purge_deleted_account_e5(p_operation);
    END $$;
    REVOKE ALL ON FUNCTION app.purge_deleted_account(uuid) FROM
    PUBLIC,calorie_app_api,calorie_app_worker;
    GRANT EXECUTE ON FUNCTION app.purge_deleted_account(uuid) TO calorie_app_deletion_operator;
    """)


def downgrade():
    # Guard precedes every DDL, including extension-dependent artifacts in E2 tables.
    predicate = " OR ".join(
        f"EXISTS(SELECT 1 FROM app.{name})" for name in TABLES if name != "community_catalog_state"
    )
    op.execute(f"""DO $$ BEGIN IF {predicate}
      OR EXISTS(SELECT 1 FROM app.product_sources WHERE document_id LIKE 'community:%' OR
      document_id LIKE 'community-density:%')
      THEN RAISE EXCEPTION 'cannot downgrade durable E6 community evidence' USING
      ERRCODE='23514'; END IF; END $$""")
    op.execute("DROP TRIGGER community_state_guard ON app.community_products")
    op.execute("DROP FUNCTION app.community_state_guard()")
    op.execute("DROP FUNCTION app.purge_deleted_account(uuid)")
    op.execute("ALTER FUNCTION app.purge_deleted_account_e5(uuid) RENAME TO purge_deleted_account")
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.purge_deleted_account(uuid) TO calorie_app_deletion_operator"
    )
    for name in ("community_publication_bindings", "community_audit", "community_versions"):
        trigger = (
            "community_binding_immutable"
            if name == "community_publication_bindings"
            else "community_immutable"
        )
        op.execute(f"DROP TRIGGER {trigger} ON app.{name}")
    for signature in (
        "community_binding_guard()",
        "community_immutable_guard()",
        "prune_community_receipts(uuid,integer)",
        "admit_community_operation(uuid,text)",
        "append_community_audit(jsonb)",
        "create_community_version(uuid,integer,uuid,uuid,jsonb,jsonb)",
        "bump_community_catalog(boolean)",
        "lock_community_catalog(boolean)",
    ):
        op.execute(f"DROP FUNCTION app.{signature}")
    for name in reversed(TABLES):
        op.drop_table(name, schema="app")
    op.execute("GRANT INSERT,UPDATE,DELETE ON app.products TO calorie_app_api,calorie_app_worker")
    op.execute(
        "GRANT DELETE ON app.product_sources,app.product_versions "
        "TO calorie_app_api,calorie_app_worker"
    )
    # pg_trgm is deliberately retained: installations may share this extension.
    # Restore E5 legacy skeleton column privileges exactly; sealed guards remain.
    for table, cols in (
        ("product_sources", "id,description,status"),
        (
            "product_versions",
            "product_id,revision,source_id,name,basis_unit,energy_kcal,protein_g,fat_g,carbs_g",
        ),
    ):
        op.execute(
            f"GRANT INSERT({cols}),UPDATE({cols}) ON app.{table} TO "
            f"calorie_app_api,calorie_app_worker"
        )
