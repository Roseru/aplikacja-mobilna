package pl.roseru.kalorie.core.sync

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson

enum class ConflictServerState { PRESENT, DELETED, UNAVAILABLE }

/** Evidence from the immutable request/receipt, never a replacement for the latest local edit. */
@ConsistentCopyVisibility
data class SyncConflictEvidence internal constructor(
    val operationId: String,
    val entityId: String,
    val entityType: String,
    val status: String,
    val code: String,
    val detailsRetained: Boolean,
    val serverState: ConflictServerState,
    val serverRevision: Int?,
    val serverPayload: String?,
    val originalAction: String,
    val originalPayload: String?,
    val epoch: String,
    val serverTime: String,
    val requestHash: String,
    internal val operationJson: String,
    internal val resultJson: String
) {
    override fun toString() = "SyncConflictEvidence(redacted)"
}

/** The enclosing batch is captured under the account fence by the persistence layer. */
class ConflictProtocol(private val schema: SyncWireSchema) {
    private val push = PushProtocol(schema)

    fun read(batch: PushBatch, response: ByteArray, operationId: String): SyncConflictEvidence = safe {
        // A valid prefix is insufficient: the complete response must match every request operation.
        val receipt = push.response(batch, 200, response).json()
        val request = batch.json()
        val operations = request.getJSONArray("operations")
        val matches = (0 until operations.length()).filter {
            operations.getJSONObject(it).getString("operation_id") == operationId
        }
        require(matches.size == 1)
        val operation = operations.getJSONObject(matches.single())
        val result = receipt.getJSONArray("results").getJSONObject(matches.single())
        val type = operation.getString("entity_type")
        val id = operation.getString("entity_id")
        require(type in setOf("meal", "weight"))
        val status = result.getString("status")
        require(status in setOf("conflict", "rejected"))
        val code = result.getString("code")
        val current = if (result.isNull("current")) null else result.getJSONObject("current")
        current?.let {
            require(it.getString("entity_id") == id && it.getString("entity_type") == type)
            if (!it.getBoolean("deleted")) validatePayload(type, it.getJSONObject("payload"))
        }
        val state = when {
            current != null -> if (current.getBoolean("deleted")) ConflictServerState.DELETED else ConflictServerState.PRESENT
            status == "conflict" && code in setOf("entity_deleted", "entity_id_reserved") -> ConflictServerState.DELETED
            else -> ConflictServerState.UNAVAILABLE
        }
        val revision = current?.getLong("revision")?.also { require(it in 1L..Int.MAX_VALUE.toLong()) }?.toInt()
        SyncConflictEvidence(operationId, id, type, status, code, result.getBoolean("details_retained"),
            state, revision, current?.takeUnless { it.getBoolean("deleted") }
                ?.getJSONObject("payload")?.let(StrictJson::canonical),
            operation.getString("action"), if (operation.isNull("payload")) null else StrictJson.canonical(operation.getJSONObject("payload")),
            request.getString("sync_epoch"), receipt.getString("server_time"), batch.sha256, StrictJson.canonical(operation), StrictJson.canonical(result))
    }

    private fun validatePayload(type: String, payload: JSONObject) {
        when (type) {
            "meal" -> MealWire.read(StrictJson.canonical(payload), schema)
            "weight" -> WeightWire.read(StrictJson.canonical(payload), schema)
            else -> error("Unsupported conflict payload")
        }
    }

    private inline fun <T> safe(action: () -> T): T = try { action() }
        catch (_: Exception) { throw SyncWireException() }
}
