CREATE FUNCTION app.e8_lock(p_owner uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE epoch uuid;
BEGIN
 PERFORM 1 FROM app.user_accounts WHERE id=p_owner AND state='active' FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 INSERT INTO app.sync_counters(owner_id) VALUES(p_owner) ON CONFLICT DO NOTHING;
 PERFORM 1 FROM app.sync_counters WHERE owner_id=p_owner FOR UPDATE;
 SELECT sync_epoch INTO epoch FROM app.installation_state WHERE id=1;
 INSERT INTO app.motivation_accounts(owner_id,sync_epoch,backfill_state)
 VALUES(p_owner,epoch,'pending') ON CONFLICT DO NOTHING;
 IF EXISTS(SELECT 1 FROM app.motivation_accounts WHERE owner_id=p_owner AND sync_epoch<>epoch) THEN
   DELETE FROM app.ranking_affirmations WHERE owner_id=p_owner;
   UPDATE app.motivation_accounts SET sync_epoch=epoch,backfill_state='pending',backfill_after=NULL,
     total_points=0,active_badges=0,next_matures_at=NULL,progress='{}',revision=revision+1 WHERE owner_id=p_owner;
   UPDATE app.motivation_days SET materialized_points=0,day_confirmed=false,
     weight_confirmed=false,ration_confirmed=false WHERE owner_id=p_owner;
   UPDATE app.motivation_badges SET active=false,revoked_at=app.e8_clock(),witness='[]'
     WHERE owner_id=p_owner AND active;
 END IF;
 RETURN true;
END $$;

CREATE FUNCTION app.e8_write_dates(p_owner uuid,p_dates date[],p_qualified_at timestamptz) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE n integer;
BEGIN
 INSERT INTO app.motivation_days(owner_id,local_date,time_zone,matures_at,source_fingerprint,source_revisions,
 effective_complete,in_goal,candidate_points,materialized_points,weight_matures_at,ration_matures_at,
 weight_confirmed,ration_confirmed,day_confirmed,qualified_at)
 SELECT p_owner,f.local_date,f.zone,f.matures_at,
 md5(f.source_revisions::text||coalesce(f.energy_sum::text,'null')||f.effective_complete::text||coalesce(f.in_goal::text,'null'))||
 md5(coalesce((f.weight_matures_at AT TIME ZONE 'UTC')::text,'null')||coalesce((f.ration_matures_at AT TIME ZONE 'UTC')::text,'null')||coalesce(f.zone,'null')),
 f.source_revisions,f.effective_complete,f.in_goal,
 f.effective_complete::integer+(f.in_goal IS TRUE)::integer,
 CASE WHEN f.matures_at<=p_qualified_at THEN f.effective_complete::integer+(f.in_goal IS TRUE)::integer ELSE 0 END,
 f.weight_matures_at,f.ration_matures_at,
 coalesce(f.weight_matures_at<=p_qualified_at,false),coalesce(f.ration_matures_at<=p_qualified_at,false),
 coalesce(f.matures_at<=p_qualified_at,false),p_qualified_at
 FROM app.e8_day_facts(p_owner,p_dates) f
 ON CONFLICT(owner_id,local_date,rule_version) DO UPDATE SET
 time_zone=excluded.time_zone,matures_at=excluded.matures_at,source_fingerprint=excluded.source_fingerprint,
 source_revisions=excluded.source_revisions,effective_complete=excluded.effective_complete,in_goal=excluded.in_goal,
 candidate_points=excluded.candidate_points,materialized_points=excluded.materialized_points,
 weight_matures_at=excluded.weight_matures_at,ration_matures_at=excluded.ration_matures_at,
 weight_confirmed=excluded.weight_confirmed,ration_confirmed=excluded.ration_confirmed,
 day_confirmed=excluded.day_confirmed,qualified_at=excluded.qualified_at;
 GET DIAGNOSTICS n=ROW_COUNT;
 RETURN n;
END $$;

CREATE FUNCTION app.e8_aggregate(p_owner uuid,p_qualified_at timestamptz) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE kind text; evidence jsonb; amount integer; badge_progress jsonb := '{}';
BEGIN
 FOREACH kind IN ARRAY ARRAY['complete_streak_10','in_goal_streak_10','weight_days_4_14','ration_days_5'] LOOP
   evidence := NULL; amount := 0;
   IF kind IN ('complete_streak_10','in_goal_streak_10') THEN
     WITH numbered AS(
       SELECT local_date,local_date-(row_number() OVER(ORDER BY local_date))::integer AS island
       FROM app.motivation_days WHERE owner_id=p_owner AND day_confirmed AND effective_complete
       AND (kind='complete_streak_10' OR in_goal IS TRUE)
     ), groups AS(SELECT island,min(local_date) first,count(*) n FROM numbered GROUP BY island)
     SELECT coalesce(max(n),0)::integer INTO amount FROM groups;
     IF amount>=10 THEN
       WITH numbered AS(
         SELECT local_date,local_date-(row_number() OVER(ORDER BY local_date))::integer AS island
         FROM app.motivation_days WHERE owner_id=p_owner AND day_confirmed AND effective_complete
         AND (kind='complete_streak_10' OR in_goal IS TRUE)
       ), witness AS(SELECT island,min(local_date) first FROM numbered GROUP BY island HAVING count(*)>=10
       ORDER BY min(local_date) LIMIT 1)
       SELECT jsonb_agg(to_char(n.local_date,'YYYY-MM-DD') ORDER BY n.local_date) INTO evidence
       FROM numbered n JOIN witness w ON n.island=w.island WHERE n.local_date<w.first+10;
     END IF;
     amount := least(amount,10);
   ELSIF kind='weight_days_4_14' THEN
     SELECT coalesce(max(n),0)::integer INTO amount FROM(
       SELECT count(*) n FROM app.motivation_days a JOIN app.motivation_days b ON b.owner_id=a.owner_id
       AND b.weight_confirmed AND b.local_date BETWEEN a.local_date AND a.local_date+13
       WHERE a.owner_id=p_owner AND a.weight_confirmed GROUP BY a.local_date) windows;
     IF amount>=4 THEN
       WITH ordered AS(SELECT local_date,lag(local_date,3) OVER(ORDER BY local_date) first
       FROM app.motivation_days WHERE owner_id=p_owner AND weight_confirmed),
       witness AS(SELECT first,local_date last FROM ordered WHERE local_date-first<=13 ORDER BY local_date LIMIT 1)
       SELECT jsonb_agg(to_char(d.local_date,'YYYY-MM-DD') ORDER BY d.local_date) INTO evidence
       FROM app.motivation_days d JOIN witness w ON d.local_date BETWEEN w.first AND w.last
       WHERE d.owner_id=p_owner AND d.weight_confirmed;
     END IF;
     amount := least(amount,4);
   ELSE
     SELECT count(*)::integer INTO amount FROM(SELECT 1 FROM app.motivation_days
     WHERE owner_id=p_owner AND ration_confirmed ORDER BY local_date LIMIT 5) dates;
     IF amount=5 THEN SELECT jsonb_agg(to_char(local_date,'YYYY-MM-DD') ORDER BY local_date) INTO evidence
       FROM(SELECT local_date FROM app.motivation_days WHERE owner_id=p_owner AND ration_confirmed
       ORDER BY local_date LIMIT 5) dates; END IF;
   END IF;
   -- Preliminary progress includes live candidate sources. Award witnesses above
   -- use only confirmed dates, so this never publishes a premature badge.
   IF kind IN ('complete_streak_10','in_goal_streak_10') THEN
     WITH numbered AS(SELECT local_date,local_date-row_number() OVER(ORDER BY local_date)::integer AS island
       FROM app.motivation_days WHERE owner_id=p_owner AND effective_complete
       AND (kind='complete_streak_10' OR in_goal IS TRUE)),
     groups AS(SELECT count(*) n FROM numbered GROUP BY island)
     SELECT least(coalesce(max(n),0),10)::integer INTO amount FROM groups;
   ELSIF kind='weight_days_4_14' THEN
     SELECT least(coalesce(max(n),0),4)::integer INTO amount FROM(
       SELECT count(*) n FROM app.motivation_days a JOIN app.motivation_days b ON b.owner_id=a.owner_id
       AND (b.source_revisions->>'weight_count')::bigint>0 AND b.local_date BETWEEN a.local_date AND a.local_date+13
       WHERE a.owner_id=p_owner AND (a.source_revisions->>'weight_count')::bigint>0 GROUP BY a.local_date) windows;
   ELSE
     SELECT count(*)::integer INTO amount FROM(SELECT 1 FROM app.motivation_days
       WHERE owner_id=p_owner AND ration_matures_at IS NOT NULL ORDER BY local_date LIMIT 5) dates;
   END IF;
   badge_progress := badge_progress||jsonb_build_object(kind,amount);
   IF evidence IS NOT NULL THEN
     INSERT INTO app.motivation_badges(owner_id,badge_code,active,first_awarded_at,activated_at,witness)
     VALUES(p_owner,kind,true,p_qualified_at,p_qualified_at,evidence)
     ON CONFLICT(owner_id,badge_code,rule_version) DO UPDATE SET active=true,revoked_at=NULL,
       activated_at=CASE WHEN app.motivation_badges.active THEN app.motivation_badges.activated_at ELSE p_qualified_at END,
       witness=excluded.witness;
   ELSE
     UPDATE app.motivation_badges SET active=false,revoked_at=p_qualified_at,witness='[]'
     WHERE owner_id=p_owner AND badge_code=kind AND active;
   END IF;
 END LOOP;
 UPDATE app.motivation_accounts SET
 total_points=(SELECT coalesce(sum(materialized_points),0) FROM app.motivation_days WHERE owner_id=p_owner),
 active_badges=(SELECT count(*) FROM app.motivation_badges WHERE owner_id=p_owner AND active),
 source_position=(SELECT position FROM app.sync_counters WHERE owner_id=p_owner),
 next_matures_at=(SELECT min(moment) FROM app.motivation_days d CROSS JOIN LATERAL(VALUES
 (CASE WHEN NOT d.day_confirmed THEN d.matures_at END),
 (CASE WHEN NOT d.weight_confirmed THEN d.weight_matures_at END),
 (CASE WHEN NOT d.ration_confirmed THEN d.ration_matures_at END)) maturity(moment) WHERE d.owner_id=p_owner),
 progress=badge_progress,revision=revision+1 WHERE owner_id=p_owner;
END $$;

CREATE FUNCTION app.e8_source_dates(p_owner uuid,p_after date,p_batch integer) RETURNS date[]
LANGUAGE sql STABLE SET search_path=pg_catalog,pg_temp AS $$
 -- Each indexed stream contributes at most batch DISTINCT dates. Its first
 -- batch dates necessarily contain all dates needed for the merged first page;
 -- later pages seek strictly beyond the durable checkpoint without truncation.
 WITH dates AS (
 (SELECT DISTINCT ON(local_date) local_date FROM app.diary_days WHERE owner_id=p_owner
   AND local_date>coalesce(p_after,'-infinity'::date) ORDER BY local_date LIMIT p_batch)
 UNION
 (SELECT DISTINCT ON(local_date) local_date FROM app.weights WHERE owner_id=p_owner
   AND local_date>coalesce(p_after,'-infinity'::date) ORDER BY local_date LIMIT p_batch)
 UNION
 (SELECT DISTINCT ON(local_date) local_date FROM app.meals WHERE owner_id=p_owner
   AND local_date>coalesce(p_after,'-infinity'::date) ORDER BY local_date LIMIT p_batch)
 UNION
 (SELECT DISTINCT ON(local_date) local_date FROM app.motivation_days WHERE owner_id=p_owner
   AND local_date>coalesce(p_after,'-infinity'::date) ORDER BY local_date LIMIT p_batch)
 ) SELECT coalesce(array_agg(local_date ORDER BY local_date),ARRAY[]::date[])
 FROM(SELECT local_date FROM dates ORDER BY local_date LIMIT p_batch) bounded
$$;
CREATE FUNCTION app.e8_refresh(p_owner uuid,p_dates date[] DEFAULT NULL,p_batch integer DEFAULT 256)
RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE q timestamptz; dates date[]; after_date date;
BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 OR coalesce(cardinality(p_dates),0)>1000 THEN
 RAISE EXCEPTION 'invalid motivation batch' USING ERRCODE='22023'; END IF;
 IF NOT app.e8_lock(p_owner) THEN RETURN NULL; END IF;
 q := app.e8_clock();
 IF p_dates IS NOT NULL THEN PERFORM app.e8_write_dates(p_owner,p_dates,q);
 ELSE LOOP
   dates := app.e8_source_dates(p_owner,after_date,p_batch);
   EXIT WHEN cardinality(dates)=0;
   PERFORM app.e8_write_dates(p_owner,dates,q);
   after_date := dates[cardinality(dates)];
 END LOOP; END IF;
 PERFORM app.e8_aggregate(p_owner,q);
 RETURN q;
END $$;

CREATE FUNCTION app.e8_process(p_owner uuid,p_batch integer DEFAULT 256) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE q timestamptz; dates date[]; a app.motivation_accounts%ROWTYPE; n integer := 0;
BEGIN
 IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 1000 THEN
 RAISE EXCEPTION 'invalid motivation batch' USING ERRCODE='22023'; END IF;
 IF NOT app.e8_lock(p_owner) THEN RETURN jsonb_build_object('processed',0,'backfill_state','inactive'); END IF;
 q := app.e8_clock(); SELECT * INTO a FROM app.motivation_accounts WHERE owner_id=p_owner;
 IF a.backfill_state='pending' THEN
   dates := app.e8_source_dates(p_owner,a.backfill_after,p_batch);
   n := app.e8_write_dates(p_owner,dates,q);
   IF cardinality(dates)<p_batch THEN
     UPDATE app.motivation_accounts SET backfill_state='ready',backfill_after=NULL WHERE owner_id=p_owner;
   ELSE UPDATE app.motivation_accounts SET backfill_after=dates[cardinality(dates)] WHERE owner_id=p_owner; END IF;
 ELSE
   SELECT coalesce(array_agg(local_date ORDER BY local_date),ARRAY[]::date[]) INTO dates FROM(
     SELECT local_date FROM app.motivation_days WHERE owner_id=p_owner AND (
     (NOT day_confirmed AND matures_at<=q) OR (NOT weight_confirmed AND weight_matures_at<=q)
     OR (NOT ration_confirmed AND ration_matures_at<=q)) ORDER BY local_date LIMIT p_batch) due;
   n := app.e8_write_dates(p_owner,dates,q);
 END IF;
 IF n>0 OR a.backfill_state='pending' THEN PERFORM app.e8_aggregate(p_owner,q); END IF;
 RETURN(SELECT jsonb_build_object('processed',n,'backfill_state',backfill_state,'total_points',total_points)
 FROM app.motivation_accounts WHERE owner_id=p_owner);
END $$;





