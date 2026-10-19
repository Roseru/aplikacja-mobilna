package pl.roseru.kalorie.session

/** Only the selected mutation's documented ACK fields may differ across C0/replay. */
internal object MealReplayFingerprint {
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
