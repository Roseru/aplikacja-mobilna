package pl.roseru.kalorie.session

/** Only the selected mutation's documented ACK fields may differ across C0/replay. */
internal object MealReplayFingerprint {
    /** Business rows are explicit per supported schema; an unknown migration must be reviewed. */
    fun tables(room:Int, runtimeIsolated:Boolean = false):List<String> {
        require(room in 17..26 && (room <= 20 || runtimeIsolated)) {
            "Unsupported replay schema or missing runtime isolation"
        }
        return buildList {
            addAll(listOf("products","meals","meal_items","goals","outbox","rations","ration_components",
                "profiles","weights","diary_days","catalog_generations","catalog_records","catalog_members",
                "catalog_active","meal_photo_drafts","photo_analysis_requests","photo_materializations",
                "photo_confirmation_history","sync_push_batches","canonical_weights","sync_conflict_decisions"))
            if(room>=18)addAll(listOf("canonical_domains","canonical_goal_timelines"))
            if(room>=19)addAll(listOf("import_plans","guest_assignments","import_sources","import_identities",
                "import_item_identities","import_decisions","reconciliation_batches","reconciliation_evidence","reconciliation_pulls"))
            if(room>=20)add("import_origins")
            if(room>=21)addAll(listOf("snapshot_archive_receipts","sync_work_state"))
            if(room>=22)add("reconciliation_completions")
            if(room>=23)addAll(listOf("community_cache","community_attempts","community_backoff"))
            if(room>=25)addAll(listOf("energy_cache","energy_attempts","energy_backoff"))
            if(room>=26)addAll(listOf("sync_protocol_states","canonical_energy_versions"))
        }
    }
    fun normalize(table: String, rowId: String?, column: String, value: String?,
        mealId: String, operationId: String, batchId: String): String? = when {
        table == "meals" && rowId == mealId && column == "serverRevision" -> "0"
        table == "outbox" && rowId == operationId && column == "status" -> "pending"
        table == "sync_push_batches" && rowId == batchId && column == "attempted" -> "0"
        table == "sync_push_batches" && rowId == batchId && column == "responseJson" -> null
        table == "sync_push_batches" && rowId == batchId && column == "state" -> "pending"
        else -> value
    }
}
