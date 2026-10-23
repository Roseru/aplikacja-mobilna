package pl.roseru.kalorie.core.sync

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.net.URLEncoder

/** Immutable validated query. Tokens and private data never appear in diagnostic strings. */
class SnapshotQuery internal constructor(internal val canonical: String) {
    internal fun json() = StrictJson.read(canonical.toByteArray(Charsets.UTF_8))
    fun encoded(): String {
        val value = json()
        return value.keys().asSequence().toList().sorted().flatMap { key ->
            if (key == "recovery_operation_ids") {
                val ids = value.getJSONArray(key)
                (0 until ids.length()).map { ids.getString(it) }
                    .map { "$key=${URLEncoder.encode(it, "UTF-8")}" }
            } else listOf("$key=${URLEncoder.encode(value.get(key).toString(), "UTF-8")}")
        }.joinToString("&")
    }
    override fun toString() = "SnapshotQuery(redacted)"
}

/** Raw validated server archive, not a local diary projection or permission to ACK outbox. */
class SnapshotPage internal constructor(internal val canonical: String) {
    internal fun json() = StrictJson.read(canonical.toByteArray(Charsets.UTF_8))
    override fun toString() = "SnapshotPage(redacted)"
}

class SnapshotProtocol(private val schema: SyncWireSchema) {
    internal fun validateFull(epoch:String,pages:List<ArchivedDiaryPage>) { ServerDiaryProtocol(schema).read(epoch,pages) }
    fun query(epoch: String, limit: Int = 100, snapshot: String? = null, page: String? = null,
        recoveryOperationIds: List<String> = emptyList()): SnapshotQuery {
        require(recoveryOperationIds.isEmpty() || (snapshot == null && page == null))
        val json = JSONObject().put("sync_epoch", epoch).put("limit", limit)
        if (recoveryOperationIds.isNotEmpty()) json.put("recovery_operation_ids", org.json.JSONArray(recoveryOperationIds))
        snapshot?.let { json.put("snapshot_token", it) }
        page?.let { json.put("page_token", it) }
        val canonical = StrictJson.canonical(json)
        schema.validate(canonical.toByteArray(Charsets.UTF_8), "PullRequest")
        return SnapshotQuery(canonical)
    }
    fun response(query: SnapshotQuery, bytes: ByteArray): SnapshotPage {
        schema.validate(bytes, "PullResponse", MAX_BYTES)
        val value = StrictJson.read(bytes)
        val request = query.json()
        require(value.getString("mode") == "snapshot" && value.getString("sync_epoch") == request.getString("sync_epoch"))
        if (request.has("snapshot_token")) require(value.getString("snapshot_token") == request.getString("snapshot_token"))
        require(value.getJSONArray("entities").length() + value.getJSONArray("recovery_mappings").length() +
            value.getJSONArray("operation_receipts").length() <= request.getInt("limit"))
        if (!value.isNull("page_token")) require(value.getString("page_token") != request.optString("page_token"))
        // Duplicate identities in a full snapshot are ambiguous even if their payloads match.
        for ((field, keys) in IDENTITIES) {
            val records = value.getJSONArray(field)
            val ids = (0 until records.length()).map { index ->
                val record = records.getJSONObject(index)
                keys.joinToString(":") { record.getString(it) }
            }
            require(ids.toSet().size == ids.size)
        }
        return SnapshotPage(StrictJson.canonical(value))
    }
    fun errorCode(bytes: ByteArray): String {
        schema.validate(bytes, "SyncError", 65_536)
        return StrictJson.read(bytes).getString("code")
    }
    companion object {
        const val MAX_BYTES = 4 * 1_048_576
        internal val IDENTITIES = mapOf("entities" to listOf("entity_id"),
            "recovery_mappings" to listOf("source_epoch", "source_entity_id"),
            "operation_receipts" to listOf("source_epoch", "operation_id"))
    }
}
