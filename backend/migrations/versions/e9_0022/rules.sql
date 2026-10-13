CREATE FUNCTION app.e9_rules(p jsonb,p_auto boolean) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,pg_temp AS $$
DECLARE complete integer;observed integer;n1 integer;n2 integer;m1 numeric;m2 numeric;e numeric;b numeric;
 numerator numeric;denominator numeric:=14;lo numeric;hi numeric;units numeric;proposal text;
 result jsonb;version_count integer;missing integer;
BEGIN
 WITH days AS(SELECT v,ord FROM jsonb_array_elements(p->'days') WITH ORDINALITY AS d(v,ord)),
 medians AS(SELECT ord,(SELECT avg(x) FROM(SELECT x,row_number() OVER(ORDER BY x) r,count(*) OVER() n FROM
 (SELECT v::numeric x FROM jsonb_array_elements_text(days.v->'weights') w(v)) s) ranked WHERE r IN((n+1)/2,(n+2)/2)) m FROM days)
 SELECT count(*) FILTER(WHERE (v->>'complete')::boolean AND (v->>'kcal')::numeric>0),
 count(DISTINCT v->>'energy_version'),count(*) FILTER(WHERE v->>'energy_version' IS NULL)
 INTO complete,version_count,missing FROM days;
 WITH days AS(SELECT v,ord FROM jsonb_array_elements(p->'days') WITH ORDINALITY AS d(v,ord)),
 medians AS(SELECT ord,(SELECT avg(x) FROM(SELECT x,row_number() OVER(ORDER BY x) r,count(*) OVER() n FROM
 (SELECT v::numeric x FROM jsonb_array_elements_text(days.v->'weights') w(v)) s) ranked WHERE r IN((n+1)/2,(n+2)/2)) m FROM days),
 ranked AS(SELECT *,row_number() OVER(PARTITION BY (ord-1)/7 ORDER BY m) r,count(*) OVER(PARTITION BY (ord-1)/7) n FROM medians WHERE m IS NOT NULL)
 SELECT count(*),count(*) FILTER(WHERE ord<=7),count(*) FILTER(WHERE ord>7),
 avg(m) FILTER(WHERE ord<=7 AND r IN((n+1)/2,(n+2)/2)),
 avg(m) FILTER(WHERE ord>7 AND r IN((n+1)/2,(n+2)/2))
 INTO observed,n1,n2,m1,m2 FROM ranked;
 result:=jsonb_build_object('rule_version','energy_adjustment_v1','complete_days',complete,'weight_days',observed,
 'first_median',CASE WHEN m1>0 THEN app.e9_wire(m1) END,'second_median',CASE WHEN m2>0 THEN app.e9_wire(m2) END,'proposed',NULL);
 IF complete<10 OR n1<2 OR n2<2 OR m1 IS NULL OR m2 IS NULL OR m1<=0 OR m2<=0 THEN
 RETURN result||jsonb_build_object('state','insufficient_data');END IF;
 e:=(p->>'current')::numeric;
 IF version_count<>1 OR missing>0 OR e IS NULL OR e<=0 THEN
 RETURN result||jsonb_build_object('state','energy_history_unavailable');END IF;
 IF complete<>14 OR abs(m2-m1)*200>m1 THEN
 RETURN result||jsonb_build_object('state','manual_review_required');END IF;
 lo:=e*0.95;hi:=e*1.05;
 IF p_auto THEN b:=(p->>'baseline')::numeric;
 IF b IS NULL OR b<=0 THEN RETURN result||jsonb_build_object('state','baseline_required');END IF;
 lo:=greatest(lo,b*0.9);hi:=least(hi,b*1.1);
 IF lo>hi THEN RETURN result||jsonb_build_object('state','baseline_range_conflict');END IF;END IF;
 SELECT sum((v->>'kcal')::numeric) INTO numerator FROM jsonb_array_elements(p->'days') v;
 numerator:=greatest(lo*14,least(hi*14,numerator));
 result:=result||jsonb_build_object('lower',lo::text,'upper',hi::text);
 IF abs(numerator-e*14)*100<e*14 THEN RETURN result||jsonb_build_object('state','no_change');END IF;
 proposal:=app.e9_wire(numerator,denominator);
 IF proposal::numeric<lo THEN proposal:=app.e9_wire(ceil(lo*1000000000000),1000000000000);END IF;
 IF proposal::numeric>hi THEN proposal:=app.e9_wire(floor(hi*1000000000000),1000000000000);END IF;
 RETURN result||jsonb_build_object('state','ready','proposed',proposal);
END $$;

CREATE FUNCTION app.e9_stale(a app.energy_analyses) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT a.fingerprint IS DISTINCT FROM app.e9_fingerprint(app.e9_context(a.owner_id,a.date_from,a.date_to))
 OR NOT EXISTS(SELECT 1 FROM app.user_profiles p WHERE p.owner_id=a.owner_id AND p.deleted_at IS NULL
 AND (clock_timestamp() AT TIME ZONE p.time_zone)::date=a.date_to+1)
 OR NOT app.e9_notice_valid(a.notice,a.profile->>'provider',CASE WHEN a.automatic THEN 'automatic_energy_adjustment' ELSE 'this_energy_analysis' END)
 OR a.notice->>'snapshot_hash' IS DISTINCT FROM a.fingerprint
 OR a.notice->>'sync_epoch' IS DISTINCT FROM a.sync_epoch::text
 OR (a.notice->>'account_generation')::integer IS DISTINCT FROM a.generation
 OR a.sync_epoch IS DISTINCT FROM(SELECT sync_epoch FROM app.installation_state WHERE id=1)
 OR NOT EXISTS(SELECT 1 FROM app.user_accounts u WHERE u.id=a.owner_id AND u.state='active' AND u.generation=a.generation AND NOT app.subject_blocked(u.issuer,u.subject))
$$;

CREATE FUNCTION app.e9_analysis_read(p_owner uuid,p_id uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
 SELECT jsonb_build_object('id',id,'revision',revision,
 'state',CASE WHEN state IN('ready','manual_review_required','no_change') AND clock_timestamp()>=expires_at THEN 'expired'
 WHEN state IN('ready','manual_review_required','no_change') AND app.e9_stale(a) THEN 'stale' ELSE state END,
 'automatic',automatic,'notice',notice,
 'source_context',jsonb_build_object('snapshot_hash',fingerprint,'sync_epoch',sync_epoch,'account_generation',generation,
 'profile_revision',(context#>>'{profile,revision}')::integer,'goal_timeline_revision',coalesce((context->>'goal_revision')::integer,0),
 'energy_axis_revision',(context#>>'{axis,revision}')::integer,'current_energy_id',context->>'current_id',
 'consent_revision',(context#>>'{consent,revision}')::integer),
 'accepted_at',app.e8n_utc(accepted_at),'created_at',CASE WHEN created_at IS NOT NULL THEN app.e8n_utc(created_at) END,
 'expires_at',CASE WHEN expires_at IS NOT NULL THEN app.e8n_utc(expires_at) END,
 'date_from',date_from,'date_to',date_to,'result',result,'explanation',explanation,'error_code',error_code)
 FROM app.energy_analyses a WHERE owner_id=p_owner AND id=p_id
$$;
