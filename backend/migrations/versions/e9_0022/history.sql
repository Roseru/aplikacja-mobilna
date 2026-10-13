CREATE FUNCTION app.e9_legacy_valid(e jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$
DECLARE i jsonb;r numeric;pal numeric;w numeric;h numeric;age integer;key text;
BEGIN
 IF e IS NULL OR jsonb_typeof(e) IS DISTINCT FROM 'object' OR e->>'method' IS DISTINCT FROM 'mifflin_pal_v1'
 OR (SELECT count(*) FROM jsonb_object_keys(e))<>6 OR NOT(e ?& ARRAY['method','input','resting_kcal','pal','maintenance_kcal','estimated_at'])
 THEN RETURN false;END IF;
 i:=e->'input';
 IF jsonb_typeof(i) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(i))<>5
 OR NOT(i ?& ARRAY['age_years','height_cm','weight_kg','equation_variant','activity_class']) THEN RETURN false;END IF;
 FOREACH key IN ARRAY ARRAY['resting_kcal','pal','maintenance_kcal','estimated_at'] LOOP
 IF jsonb_typeof(e->key) IS DISTINCT FROM 'string' THEN RETURN false;END IF;END LOOP;
 IF jsonb_typeof(i->'equation_variant') IS DISTINCT FROM 'string'
 OR jsonb_typeof(i->'activity_class') IS DISTINCT FROM 'string'
 OR jsonb_typeof(i->'age_years') IS DISTINCT FROM 'number' OR i->>'age_years' !~ '^[1-9][0-9]{1,2}$'
 OR jsonb_typeof(i->'height_cm') IS DISTINCT FROM 'string' OR jsonb_typeof(i->'weight_kg') IS DISTINCT FROM 'string'
 OR i->>'height_cm' !~ '^(0|[1-9][0-9]{0,5})(\.[0-9]{0,5}[1-9])?$' OR i->>'weight_kg' !~ '^(0|[1-9][0-9]{0,5})(\.[0-9]{0,5}[1-9])?$'
 OR e->>'resting_kcal' !~ '^(0|[1-9][0-9]{0,5})(\.[0-9]{0,11}[1-9])?$'
 OR e->>'maintenance_kcal' !~ '^(0|[1-9][0-9]{0,5})(\.[0-9]{0,11}[1-9])?$' THEN RETURN false;END IF;
 age:=(i->>'age_years')::integer;h:=(i->>'height_cm')::numeric;w:=(i->>'weight_kg')::numeric;
 IF age NOT BETWEEN 18 AND 120 OR h<=0 OR h>300 OR w<=0 OR w>1000
 OR i->>'equation_variant' NOT IN('plus_5','minus_161') THEN RETURN false;END IF;
 pal:=CASE i->>'activity_class' WHEN 'stationary' THEN 1.5 WHEN 'line' THEN 1.8 WHEN 'commando' THEN 2.2 END;
 IF pal IS NULL OR e->>'pal'<>pal::text THEN RETURN false;END IF;
 r:=10*w+6.25*h-5*age+CASE i->>'equation_variant' WHEN 'plus_5' THEN 5 ELSE -161 END;
 IF e->>'estimated_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$' THEN RETURN false;END IF;
 PERFORM (e->>'estimated_at')::timestamptz;
 RETURN r>0 AND (e->>'resting_kcal')::numeric=r AND (e->>'maintenance_kcal')::numeric=r*pal;
 EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;

CREATE FUNCTION app.e9_wire(p_num numeric,p_den numeric DEFAULT 1) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$
DECLARE u numeric;BEGIN
 IF p_den<=0 OR p_num<0 THEN RAISE EXCEPTION 'invalid rational' USING ERRCODE='22023';END IF;
 u:=div(p_num*1000000000000,p_den);
 IF mod(p_num*1000000000000,p_den)*2>=p_den THEN u:=u+1;END IF;
 RETURN app.e8n_percent_text(u/1000000000000.000000000000);
END $$;

CREATE FUNCTION app.e9_legacy_import(p_owner uuid,p_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE g app.goal_versions%ROWTYPE;r integer;parent uuid;
BEGIN
 SELECT * INTO g FROM app.goal_versions WHERE owner_id=p_owner AND id=p_id;
 IF NOT FOUND OR g.payload->'estimate' IS NULL OR g.payload->'estimate'='null'::jsonb THEN RETURN;END IF;
 IF NOT app.e9_legacy_valid(g.payload->'estimate') THEN RETURN;END IF;
 IF EXISTS(SELECT 1 FROM app.energy_versions WHERE id=p_id AND owner_id=p_owner) THEN RETURN;END IF;
 PERFORM 1 FROM app.user_accounts WHERE id=p_owner FOR UPDATE;
 INSERT INTO app.energy_axes(owner_id) VALUES(p_owner) ON CONFLICT DO NOTHING;
 UPDATE app.energy_axes SET revision=revision+1 WHERE owner_id=p_owner RETURNING revision INTO r;
 WITH RECURSIVE ancestors AS(
 SELECT id,correction_of FROM app.goal_versions WHERE owner_id=p_owner AND id=g.correction_of
 UNION ALL SELECT v.id,v.correction_of FROM app.goal_versions v JOIN ancestors a ON v.id=a.correction_of WHERE v.owner_id=p_owner
 ) SELECT e.id INTO parent FROM ancestors a JOIN app.energy_versions e ON e.id=a.id AND e.owner_id=p_owner ORDER BY e.revision DESC LIMIT 1;
 INSERT INTO app.energy_versions(id,owner_id,revision,effective_from,maintenance_kcal,method,source,source_id,supersedes,decided_at,audit)
 VALUES(g.id,p_owner,r,g.effective_from,(g.payload#>>'{estimate,maintenance_kcal}')::numeric,
 'mifflin_pal_v1','legacy',g.id,parent,g.decided_at,
 jsonb_build_object('goal_id',g.id,'goal_timeline_revision',g.timeline_revision,'estimate',g.payload->'estimate'));
END $$;
-- Import in each accepted source order. This adapter is also used by future sync.
DO $$ DECLARE v record; BEGIN FOR v IN SELECT owner_id,id FROM app.goal_versions ORDER BY owner_id,timeline_revision LOOP
 PERFORM app.e9_legacy_import(v.owner_id,v.id);END LOOP;END $$;
CREATE FUNCTION app.e9_goal_import_trigger() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN PERFORM app.e9_legacy_import(NEW.owner_id,NEW.id);RETURN NEW;END $$;
CREATE TRIGGER energy_legacy_import AFTER INSERT ON app.goal_versions FOR EACH ROW EXECUTE FUNCTION app.e9_goal_import_trigger();

CREATE FUNCTION app.e9_resolve(p_owner uuid,p_day date) RETURNS app.energy_versions
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE resolved app.energy_versions%ROWTYPE;BEGIN
 WITH RECURSIVE tree AS(
 SELECT id,id AS root FROM app.goal_versions WHERE owner_id=p_owner AND correction_of IS NULL
 UNION ALL SELECT g.id,t.root FROM app.goal_versions g JOIN tree t ON g.correction_of=t.id WHERE g.owner_id=p_owner
 ), legacy_heads AS(
 SELECT DISTINCT ON(t.root) e.id FROM tree t JOIN app.goal_versions g ON g.id=t.id
 JOIN app.energy_versions e ON e.owner_id=p_owner AND e.id=g.id AND e.source='legacy'
 ORDER BY t.root,g.timeline_revision DESC
 ), heads AS(
 SELECT e.* FROM app.energy_versions e WHERE e.owner_id=p_owner
 AND(e.source<>'legacy' OR e.id IN(SELECT id FROM legacy_heads))
 AND NOT EXISTS(SELECT 1 FROM app.energy_versions n WHERE n.owner_id=p_owner AND n.supersedes=e.id AND n.source<>'legacy' AND n.effective_from<=p_day)
 )
 SELECT * INTO resolved FROM heads h WHERE h.effective_from<=p_day ORDER BY h.effective_from DESC,h.revision DESC LIMIT 1;
 RETURN resolved;END $$;
CREATE FUNCTION app.e9_version_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN IF TG_OP='DELETE' AND app.deletion_purge_authorized(OLD.owner_id) THEN RETURN OLD;END IF;
 RAISE EXCEPTION 'immutable energy version' USING ERRCODE='23514';END $$;
CREATE TRIGGER energy_versions_immutable BEFORE UPDATE OR DELETE ON app.energy_versions FOR EACH ROW EXECUTE FUNCTION app.e9_version_guard();

CREATE FUNCTION app.e9_entity(p_id uuid) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT jsonb_build_object('entity_type','energy_estimate','entity_id',id,'revision',revision,'deleted',false,
 'payload',jsonb_build_object('effective_from',effective_from,'maintenance_kcal',app.e9_wire(maintenance_kcal),
 'method',method,'source',source,'source_id',source_id,'supersedes',supersedes,'decided_at',to_char(decided_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'audit',audit))
 FROM app.energy_versions WHERE id=p_id
$$;

CREATE FUNCTION app.e9_context(p_owner uuid,p_from date,p_to date) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE result jsonb;rows integer;BEGIN
 SELECT count(*) INTO rows FROM(
 SELECT id FROM app.diary_days WHERE owner_id=p_owner AND local_date BETWEEN p_from AND p_to
 UNION ALL SELECT id FROM app.meals WHERE owner_id=p_owner AND local_date BETWEEN p_from AND p_to
 UNION ALL SELECT id FROM app.weights WHERE owner_id=p_owner AND local_date BETWEEN p_from AND p_to
 UNION ALL SELECT i.item_id FROM app.meal_items i JOIN app.meals m ON m.owner_id=i.owner_id AND m.id=i.meal_id
 WHERE m.owner_id=p_owner AND m.local_date BETWEEN p_from AND p_to LIMIT 100001) bounded;
 IF rows>100000 THEN RAISE EXCEPTION 'energy input resources exhausted' USING ERRCODE='54000';END IF;
 WITH days AS(
 SELECT generate_series(p_from::timestamp,p_to::timestamp,interval '1 day')::date AS d
 ), facts AS(SELECT f.* FROM app.e8_day_facts(p_owner,ARRAY(SELECT d FROM days)) f)
 SELECT jsonb_build_object(
 'profile',(SELECT to_jsonb(p) FROM app.user_profiles p WHERE owner_id=p_owner AND deleted_at IS NULL),
 'consent',(SELECT to_jsonb(c) FROM app.user_consents c WHERE owner_id=p_owner),
 'axis',(SELECT to_jsonb(a) FROM app.energy_axes a WHERE owner_id=p_owner),
 'generation',(SELECT generation FROM app.user_accounts WHERE id=p_owner),
 'epoch',(SELECT sync_epoch FROM app.installation_state WHERE id=1),
 'goal_revision',(SELECT revision FROM app.goal_timelines WHERE owner_id=p_owner),
 'days',(SELECT jsonb_agg(jsonb_build_object('date',f.local_date,'complete',f.effective_complete AND f.matures_at<=clock_timestamp(),
 'kcal',f.energy_sum::text,'energy_version',(app.e9_resolve(p_owner,f.local_date)).id,
 'energy',(app.e9_resolve(p_owner,f.local_date)).maintenance_kcal::text,
 'source',f.source_revisions,
 'weights',coalesce((SELECT jsonb_agg(w.weight_kg::text ORDER BY w.id) FROM app.weights w WHERE w.owner_id=p_owner AND w.local_date=f.local_date AND w.deleted_at IS NULL),'[]'::jsonb)) ORDER BY f.local_date) FROM facts f),
 'records',jsonb_build_object(
 'days',(SELECT coalesce(jsonb_agg(to_jsonb(d) ORDER BY d.id),'[]'::jsonb) FROM app.diary_days d WHERE d.owner_id=p_owner AND d.local_date BETWEEN p_from AND p_to),
 'weights',(SELECT coalesce(jsonb_agg(to_jsonb(w) ORDER BY w.id),'[]'::jsonb) FROM app.weights w WHERE w.owner_id=p_owner AND w.local_date BETWEEN p_from AND p_to),
 'meals',(SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.id),'[]'::jsonb) FROM app.meals m WHERE m.owner_id=p_owner AND m.local_date BETWEEN p_from AND p_to),
 'items',(SELECT coalesce(jsonb_agg(to_jsonb(i) ORDER BY i.meal_id,i.item_id),'[]'::jsonb) FROM app.meal_items i JOIN app.meals m ON m.owner_id=i.owner_id AND m.id=i.meal_id WHERE m.owner_id=p_owner AND m.local_date BETWEEN p_from AND p_to)),
 'current_id',(app.e9_resolve(p_owner,p_to+1)).id,
 'current',(app.e9_resolve(p_owner,p_to+1)).maintenance_kcal::text,
 'baseline',(SELECT e.maintenance_kcal::text FROM app.energy_axes a JOIN app.energy_versions e ON e.owner_id=a.owner_id AND e.id=a.baseline_id
 JOIN app.user_consents c ON c.owner_id=a.owner_id WHERE a.owner_id=p_owner AND a.baseline_epoch=(SELECT sync_epoch FROM app.installation_state WHERE id=1) AND a.baseline_consent_revision=c.revision)
 ) INTO result;
 IF octet_length(result::text)>8388608 THEN RAISE EXCEPTION 'energy input resources exhausted' USING ERRCODE='54000';END IF;
 RETURN result;
END $$;
CREATE FUNCTION app.e9_fingerprint(p_context jsonb) RETURNS text LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$
 SELECT encode(sha256(convert_to(p_context::text,'UTF8')),'hex')
$$;

CREATE FUNCTION app.e9_state(p_owner uuid) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE axis app.energy_axes%ROWTYPE;c app.user_consents%ROWTYPE;u app.user_accounts%ROWTYPE;epoch uuid;zone text;baseline uuid;
BEGIN
 SELECT * INTO u FROM app.user_accounts WHERE id=p_owner AND state='active';
 IF NOT FOUND OR app.subject_blocked(u.issuer,u.subject) THEN RETURN NULL;END IF;
 SELECT * INTO axis FROM app.energy_axes WHERE owner_id=p_owner;
 SELECT * INTO c FROM app.user_consents WHERE owner_id=p_owner;
 SELECT sync_epoch INTO epoch FROM app.installation_state WHERE id=1;
 SELECT time_zone INTO zone FROM app.user_profiles WHERE owner_id=p_owner AND deleted_at IS NULL;
 IF axis.baseline_epoch=epoch AND axis.baseline_consent_revision=c.revision THEN baseline:=axis.baseline_id;END IF;
 RETURN jsonb_build_object('sync_epoch',epoch,'account_generation',u.generation,'axis_revision',coalesce(axis.revision,0),
 'current_id',CASE WHEN zone IS NOT NULL THEN (app.e9_resolve(p_owner,(clock_timestamp() AT TIME ZONE zone)::date)).id END,
 'baseline_id',baseline,'automatic_requested',coalesce(c.automatic_energy_adjustment,false),
 'automatic_effective',coalesce(c.automatic_energy_adjustment AND baseline IS NOT NULL
 AND app.e9_notice_valid(axis.baseline_notice,axis.baseline_notice->>'provider','automatic_energy_adjustment')
 AND (axis.baseline_notice->>'account_generation')::integer=u.generation,false),
 'automatic_notice',CASE WHEN baseline IS NOT NULL THEN axis.baseline_notice END,
 'last_applied_at',CASE WHEN axis.last_applied_at IS NOT NULL THEN app.e8n_utc(axis.last_applied_at) END,
 'next_apply_at',CASE WHEN axis.last_applied_at IS NOT NULL THEN app.e8n_utc(axis.last_applied_at+interval '336 hours') END);
END $$;

CREATE FUNCTION app.e9_notice_valid(p_notice jsonb,p_provider text,p_scope text) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$
 SELECT coalesce(jsonb_typeof(p_notice)='object' AND p_notice->'accepted'='true'::jsonb
 AND p_notice->'qualified_for_v1'='true'::jsonb AND p_notice->>'notice_version'='energy-aggregates-notice-v1'
 AND p_notice->>'aggregate_scope'='energy_adjustment_v1_minimal_aggregates'
 AND p_notice->>'provider'=p_provider AND p_notice->>'scope'=p_scope
 AND p_notice->>'revoked_at' IS NULL,false)
$$;
CREATE FUNCTION app.e9_notice_snapshot(p_notice jsonb,p_context jsonb,p_t timestamptz,p_baseline uuid) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$
 SELECT p_notice||jsonb_build_object('snapshot_hash',app.e9_fingerprint(p_context),
 'snapshot_at',app.e8n_utc(p_t),'accepted_at',coalesce(p_notice->>'accepted_at',app.e8n_utc(p_t)),
 'sync_epoch',p_context->'epoch','account_generation',p_context->'generation',
 'profile_revision',p_context#>'{profile,revision}','consent_revision',p_context#>'{consent,revision}',
 'baseline_id',p_baseline)
$$;
