CREATE FUNCTION app.e7_match_candidates(p_names text[],p_hashes text[],p_key text,p_identity jsonb,
 p_basis text,p_energy numeric,p_density numeric) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE result jsonb; BEGIN
 IF cardinality(p_names) NOT BETWEEN 1 AND 51 OR cardinality(p_names)<>cardinality(p_hashes)
 OR EXISTS(SELECT 1 FROM unnest(p_names) n WHERE length(n) NOT BETWEEN 1 AND 2000)
 OR p_basis NOT IN ('g','ml') THEN RAISE EXCEPTION 'invalid matching selector' USING ERRCODE='22023'; END IF;
 PERFORM 1 FROM app.community_catalog_state WHERE id=1 FOR SHARE;
 WITH community AS NOT MATERIALIZED (
 SELECT v.*,m.identity,m.normalized_identity,m.identity_key,m.normalized_names,m.normalized_name_hashes,m.search_text
 FROM app.product_versions v JOIN app.community_products c ON c.product_id=v.product_id AND c.current_revision=v.revision
 JOIN app.community_versions m ON m.product_id=v.product_id AND m.revision=v.revision
 WHERE c.visibility='visible' AND (c.canonical_id IS NULL OR c.canonical_id=c.product_id)),
 high AS (
 SELECT c.*,true AS high_selector,'community' AS provenance FROM community c
 WHERE c.identity_key=p_key AND c.normalized_identity=p_identity
 AND c.normalized_name_hashes && p_hashes::varchar[] AND c.normalized_names && p_names
 AND p_energy IS NOT NULL AND c.energy_kcal IS NOT NULL
 AND (p_density IS NULL OR c.density_amount IS NULL OR c.density_amount=p_density)
 AND (c.basis_unit=p_basis OR coalesce(p_density,c.density_amount) IS NOT NULL)
 AND abs(CASE WHEN c.basis_unit<>p_basis AND p_basis='g' THEN p_energy*coalesce(p_density,c.density_amount) ELSE p_energy END
 -CASE WHEN c.basis_unit<>p_basis AND p_basis='ml' THEN c.energy_kcal*coalesce(p_density,c.density_amount) ELSE c.energy_kcal END)*10
 <=greatest(CASE WHEN c.basis_unit<>p_basis AND p_basis='g' THEN p_energy*coalesce(p_density,c.density_amount) ELSE p_energy END,
 CASE WHEN c.basis_unit<>p_basis AND p_basis='ml' THEN c.energy_kcal*coalesce(p_density,c.density_amount) ELSE c.energy_kcal END)
 ORDER BY c.product_id LIMIT 2),
 manual AS (
 SELECT c.*,false AS high_selector,'community' AS provenance FROM community c WHERE
 (c.normalized_name_hashes && p_hashes::varchar[] AND c.normalized_names && p_names)
 OR EXISTS(SELECT 1 FROM unnest(p_names) n WHERE c.search_text ILIKE '%'||replace(replace(replace(n,'\','\\'),'%','\%'),'_','\_')||'%' ESCAPE '\'
 OR c.search_text OPERATOR(public.%) n)
 ORDER BY c.product_id LIMIT 21),
 official AS (
 SELECT v.*,false AS high_selector,'official' AS provenance
 FROM app.product_versions v JOIN app.product_search_metadata m ON m.product_id=v.product_id AND m.revision=v.revision
 JOIN app.offline_package_products i ON i.product_id=v.product_id AND i.product_revision=v.revision
 JOIN app.offline_packages p ON p.package_id=i.package_id AND p.release=i.release
 JOIN app.offline_channels c ON c.package_id=p.package_id AND c.active_release=p.release
 WHERE c.kind='official' AND c.package_id='c12631e2-1a02-547c-a7f9-ebf87bb42e55'::uuid AND p.state='published'
 AND ((m.normalized_name_hashes && p_hashes::varchar[] AND m.normalized_names && p_names)
 OR EXISTS(SELECT 1 FROM unnest(p_names) n WHERE m.search_text ILIKE '%'||replace(replace(replace(n,'\','\\'),'%','\%'),'_','\_')||'%' ESCAPE '\'
 OR m.search_text OPERATOR(public.%) n)) ORDER BY v.product_id,v.revision DESC LIMIT 21),
 rows AS (
 SELECT product_id,revision,name,aliases,brand,variant,basis_unit,energy_kcal,density_amount,identity,high_selector,provenance FROM high
 UNION ALL SELECT product_id,revision,name,aliases,brand,variant,basis_unit,energy_kcal,density_amount,identity,high_selector,provenance FROM manual
 UNION ALL SELECT product_id,revision,name,aliases,brand,variant,basis_unit,energy_kcal,density_amount,NULL::jsonb,high_selector,provenance FROM official)
 SELECT coalesce(jsonb_agg(jsonb_build_object('product',jsonb_build_object('product_id',product_id,'revision',revision),
 'name',name,'aliases',aliases,'brand',brand,'variant',variant,'basis_unit',basis_unit,
 'energy_kcal',energy_kcal::text,'density_amount',density_amount::text,'identity',identity,
 'high_selector',high_selector,'provenance',provenance) ORDER BY provenance,product_id,high_selector DESC,revision DESC),'[]'::jsonb)
 INTO result FROM rows;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION app.e7_match_candidates(text[],text[],text,jsonb,text,numeric,numeric)
 FROM PUBLIC,calorie_app_api,calorie_app_worker,calorie_app_ai_worker,calorie_app_deletion_operator;
GRANT EXECUTE ON FUNCTION app.e7_match_candidates(text[],text[],text,jsonb,text,numeric,numeric) TO calorie_app_ai_worker;
