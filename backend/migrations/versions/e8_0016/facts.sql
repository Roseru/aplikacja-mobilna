-- Production clock authority. Tests may replace this owner-only implementation
-- in a disposable database; no runtime caller can supply or override its value.
CREATE FUNCTION app.e8_clock() RETURNS timestamptz
LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ SELECT clock_timestamp() $$;
-- IANA closure: gather the actual offsets around the boundary, roundtrip each
-- possible midnight, and select the earliest real instant after the local date.
-- This covers ambiguous midnight, midnight gaps and skipped calendar dates.
CREATE FUNCTION app.e8_day_end(p_day date,p_zone text) RETURNS timestamptz
LANGUAGE plpgsql STABLE SET search_path=pg_catalog,pg_temp AS $$
DECLARE target timestamp; nominal timestamptz; result timestamptz;
 low timestamptz; high timestamptz; midpoint timestamptz;
BEGIN
 -- Source zones passed here were IANA-validated when accepted. PostgreSQL's
 -- timezone operation validates the name without enumerating every IANA zone.
 IF p_day IS NULL OR p_zone IS NULL
 THEN RAISE EXCEPTION 'invalid day closure' USING ERRCODE='22023'; END IF;
 IF p_day=DATE '9999-12-31' THEN
   PERFORM TIMESTAMP '2000-01-01' AT TIME ZONE p_zone; RETURN NULL; END IF;
 target := (p_day+1)::timestamp;
 nominal := target AT TIME ZONE p_zone;
 WITH offsets AS (
   SELECT DISTINCT (t AT TIME ZONE p_zone)-(t AT TIME ZONE 'UTC') AS delta
   FROM generate_series(nominal-interval '48 hours',nominal+interval '48 hours',interval '1 hour') t
 ), candidates AS (
   SELECT (target-delta) AT TIME ZONE 'UTC' AS instant FROM offsets
 ) SELECT min(instant) FILTER(WHERE instant AT TIME ZONE p_zone >= target),
 max(instant) FILTER(WHERE instant AT TIME ZONE p_zone < target)
 INTO result,low FROM candidates;
 -- A gap may start before midnight and end after it (Toronto1919); neither
 -- offset's hypothetical midnight is then the transition instant itself.
 -- Locate that first real boundary between the last invalid and first valid
 -- candidate, using PostgreSQL's exact microsecond timestamp resolution.
 IF low IS NOT NULL AND result IS NOT NULL AND low<result THEN
   high := result;
   WHILE high-low>interval '1 microsecond' LOOP
     midpoint := low+(high-low)/2;
     IF midpoint AT TIME ZONE p_zone >= target THEN high := midpoint;
     ELSE low := midpoint; END IF;
   END LOOP;
   result := high;
 END IF;
 IF result IS NULL OR (result AT TIME ZONE p_zone)::date<=p_day THEN
   RAISE EXCEPTION 'unresolvable day closure' USING ERRCODE='22023'; END IF;
 RETURN result;
END $$;

-- Accepted timeline revision selects one surviving head for each original
-- decision before effective dates are applied. A moved correction never revives
-- the original, including branches which correct an earlier head.
CREATE FUNCTION app.e8_goal_heads(p_owner uuid)
RETURNS TABLE(id uuid,revision integer,timeline_revision integer,effective_from date,energy_kcal numeric)
LANGUAGE sql STABLE SET search_path=pg_catalog,pg_temp AS $$
 WITH RECURSIVE tree AS (
 SELECT v.id,v.id AS root FROM app.goal_versions v WHERE v.owner_id=p_owner AND v.correction_of IS NULL
 UNION ALL SELECT v.id,t.root FROM app.goal_versions v JOIN tree t ON v.correction_of=t.id WHERE v.owner_id=p_owner
 ), heads AS (
 SELECT DISTINCT ON(t.root) v.id,v.revision,v.timeline_revision,v.effective_from,v.energy_kcal
 FROM tree t JOIN app.goal_versions v ON v.id=t.id AND v.owner_id=p_owner
 ORDER BY t.root,v.timeline_revision DESC
 ) SELECT * FROM heads
$$;

CREATE FUNCTION app.e8_day_facts(p_owner uuid,p_dates date[])
RETURNS TABLE(local_date date,zone text,matures_at timestamptz,energy_sum numeric,energy_complete boolean,
 effective_complete boolean,in_goal boolean,goal_id uuid,goal_revision integer,source_revisions jsonb,
 weight_matures_at timestamptz,ration_matures_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 WITH wanted AS (SELECT DISTINCT unnest(p_dates) AS day),
 heads AS MATERIALIZED(SELECT * FROM app.e8_goal_heads(p_owner)),
 energies AS (
 SELECT m.local_date,count(*) AS item_count,count(i.energy_kcal) AS known_count,
 sum(i.energy_kcal * CASE
 WHEN i.quantity_unit=i.basis_unit THEN i.quantity_amount
 WHEN i.quantity_unit='ml' THEN i.quantity_amount*i.density_g_per_ml
 ELSE round(i.quantity_amount::numeric(80,50)/i.density_g_per_ml,12) END *0.01) AS energy
 FROM app.meals m JOIN wanted w ON w.day=m.local_date
 JOIN app.meal_items i ON i.owner_id=m.owner_id AND i.meal_id=m.id
 WHERE m.owner_id=p_owner AND m.deleted_at IS NULL GROUP BY m.local_date
 ), meals AS (
 SELECT m.local_date,count(*) AS meal_count,sum(m.revision)::bigint AS revisions,
 bit_xor(('x'||encode(sha256(convert_to(m.id::text||':'||m.revision::text,'UTF8')),'hex'))::bit(256))::text AS source_hash,
 CASE WHEN bool_or(m.ration IS NOT NULL AND EXISTS(
 SELECT 1 FROM app.meal_items i WHERE i.owner_id=m.owner_id AND i.meal_id=m.id
 AND i.ration_component_position IS NOT NULL AND i.quantity_amount>0))
 THEN app.e8_day_end(m.local_date,min(m.time_zone)) END AS ration_end
 FROM app.meals m JOIN wanted w ON w.day=m.local_date WHERE m.owner_id=p_owner AND m.deleted_at IS NULL GROUP BY m.local_date
 ), weight_zones AS (
 SELECT v.local_date,v.time_zone,count(*) AS weight_count,sum(v.revision)::bigint AS revisions,
 bit_xor(('x'||encode(sha256(convert_to(v.id::text||':'||v.revision::text,'UTF8')),'hex'))::bit(256)) AS source_hash
 FROM app.weights v JOIN wanted w ON w.day=v.local_date WHERE v.owner_id=p_owner AND v.deleted_at IS NULL
 GROUP BY v.local_date,v.time_zone
 ), weights AS (
 SELECT local_date,sum(weight_count) AS weight_count,sum(revisions) AS revisions,
 bit_xor(source_hash)::text AS source_hash,min(app.e8_day_end(local_date,time_zone)) AS weight_end
 FROM weight_zones GROUP BY local_date
 ), facts AS (
 SELECT w.day,d.time_zone::text AS zone,
 CASE WHEN d.id IS NOT NULL THEN app.e8_day_end(w.day,d.time_zone) END AS matures_at,
 e.energy,coalesce(e.item_count>0 AND e.item_count=e.known_count,false) AS known,
 coalesce(d.declared_complete AND m.meal_count>0 AND e.item_count>0 AND e.item_count=e.known_count AND e.energy>0,false) AS complete,
 g.id AS goal_id,g.revision AS goal_revision,g.energy_kcal AS goal_energy,
 jsonb_build_object('diary_revision',d.revision,'goal_id',g.id,'goal_revision',g.revision,
 'goal_timeline_revision',g.timeline_revision,'meal_count',coalesce(m.meal_count,0),
 'meal_revision_sum',coalesce(m.revisions,0),'meal_source_hash',m.source_hash,'weight_count',coalesce(v.weight_count,0),
 'weight_revision_sum',coalesce(v.revisions,0),'weight_source_hash',v.source_hash) AS revisions,v.weight_end,m.ration_end
 FROM wanted w LEFT JOIN app.diary_days d ON d.owner_id=p_owner AND d.local_date=w.day AND d.deleted_at IS NULL
 LEFT JOIN energies e ON e.local_date=w.day LEFT JOIN meals m ON m.local_date=w.day LEFT JOIN weights v ON v.local_date=w.day
 LEFT JOIN LATERAL(SELECT h.* FROM heads h WHERE h.effective_from<=w.day
 ORDER BY h.effective_from DESC,h.timeline_revision DESC LIMIT 1) g ON true
 ) SELECT day,zone,matures_at,energy,known,complete,
 CASE WHEN complete AND goal_energy>0 THEN energy BETWEEN goal_energy*0.9 AND goal_energy*1.1 ELSE NULL END,
 goal_id,goal_revision,revisions,weight_end,ration_end FROM facts ORDER BY day
$$;
