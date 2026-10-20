-- Exact known unsafe ancestors of0024 in the linear Alembic graph.
-- Future revisions are ordered by their graph, never by their string names.
-- A trusted migration may extend the schema without relabelling old evidence.
CREATE OR REPLACE FUNCTION app.ledger_downgrade_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
 IF NEW.version_num = ANY(ARRAY[
  '0001_foundation',
  '0002_finite_nutrition',
  '0003_catalog_offline',
  '0004_catalog_timestamp',
  '0005_ration_cursors',
  '0006_e3_identity',
  '0007_e3_diary',
  '0008_diary_delete',
  '0009_e4_sync',
  '0010_e4_retention',
  '0011_e4_deletion',
  '0012_e5_reads',
  '0013_e6_community',
  '0014_catalog_search',
  '0015_e7_ai',
  '0016_e8_motivation',
  '0017_e8_purge_commit',
  '0018_e8_nemesis_lifecycle',
  '0019_e8_nemesis_maintenance',
  '0020_e8_nemesis_integration',
  '0021_e8_nemesis_results',
  '0022_e9_energy',
  '0023_e9_qualification'
 ]::text[]) THEN
  RAISE EXCEPTION 'cannot downgrade deletion safety below0024' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION app.ledger_downgrade_guard() FROM PUBLIC;
-- Projection release/algorithms stay0024; only the actual expected head changes.
CREATE OR REPLACE FUNCTION app.e8n_activate(p_epoch uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 PERFORM 1 FROM app.installation_state WHERE id=1 AND sync_epoch=p_epoch FOR SHARE;
 IF NOT FOUND OR NOT app.e8n_runtime_ready()
 OR (SELECT array_agg(version_num) FROM app.alembic_version) IS DISTINCT FROM ARRAY['0026_ledger_review']::varchar[]
 OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='calorie_app_nemesis_finalizer' AND NOT rolcanlogin
 AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls)
 OR NOT has_function_privilege('calorie_app_nemesis_finalizer','app.e8n_finalize_batch(integer)','EXECUTE')
 OR EXISTS(SELECT 1 FROM app.nemesis_challenges WHERE sync_epoch<>p_epoch AND status<>'cancelled')
 THEN RAISE EXCEPTION 'Nemesis activation preconditions unavailable' USING ERRCODE='55000'; END IF;
 UPDATE app.nemesis_control SET sync_epoch=p_epoch,enabled=true,schema_revision='0024_e9_history_graph',
 initializer_revision='0021_initializer_v1',projector_revision='0024_projection_v1',finalizer_revision='0021_finalizer_v1' WHERE id=1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Nemesis control unavailable' USING ERRCODE='55000'; END IF;
END $$;
