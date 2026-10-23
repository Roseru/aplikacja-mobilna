package pl.roseru.kalorie.core.sync

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.security.MessageDigest

/** Immutable wire envelope. A database must persist it before the first HTTP attempt. */
class PushBatch internal constructor(internal val canonical: String) {
    fun body(): ByteArray = canonical.toByteArray(Charsets.UTF_8)
    val sha256: String get() = MessageDigest.getInstance("SHA-256").digest(body())
        .joinToString("") { "%02x".format(it) }
    internal fun json() = StrictJson.read(body())
    override fun toString() = "PushBatch(redacted)"
}

/** Validated complete HTTP200, not permission to ACK outside a captured Room transaction. */
class PushReceipt internal constructor(internal val canonical: String, internal val requestHash: String) {
    internal fun json() = StrictJson.read(canonical.toByteArray(Charsets.UTF_8))
    override fun toString() = "PushReceipt(redacted)"
}

/** Ordinary E4 push only. Recovery requires explicit source/mapping reconciliation elsewhere. */
class PushProtocol(private val schema: SyncWireSchema) {
    /** Contiguous eligible prefix: never skip a second edit and send its dependants first. */
    fun prepare(epoch: String, checkpoint: String, operations: List<String>): PushBatch = safe {
        val selected = JSONArray()
        val ids = mutableSetOf<String>()
        val entities = mutableSetOf<String>()
        for (text in operations) {
            if (selected.length() == MAX_OPERATIONS) break
            val operation = operation(text)
            require(operation.getString("sync_epoch") == epoch)
            require(ids.add(operation.getString("operation_id")))
            val entity = operation.getString("entity_type") + ":" + operation.getString("entity_id")
            if (!entities.add(entity)) break
            val candidate = JSONArray(selected.toString()).put(operation)
            val wire = envelope(epoch, checkpoint, candidate)
            if (wire.toByteArray(Charsets.UTF_8).size > MAX_REQUEST_BYTES) {
                require(selected.length() > 0)
                break
            }
            selected.put(operation)
        }
        restore(envelope(epoch, checkpoint, selected).toByteArray(Charsets.UTF_8))
    }

    /** Reopen the exact persisted envelope after process death; never infer it from current edits. */
    fun restore(bytes: ByteArray): PushBatch = safe {
        schema.validate(bytes, "PushRequest", MAX_REQUEST_BYTES)
        val value = StrictJson.read(bytes)
        val epoch = value.getString("sync_epoch")
        val operations = value.getJSONArray("operations")
        val ids = mutableSetOf<String>()
        val entities = mutableSetOf<String>()
        for (i in 0 until operations.length()) {
            val row = operation(StrictJson.canonical(operations.getJSONObject(i)))
            require(row.getString("sync_epoch") == epoch)
            require(ids.add(row.getString("operation_id")))
            require(entities.add(row.getString("entity_type") + ":" + row.getString("entity_id")))
        }
        val canonical = StrictJson.canonical(value)
        require(canonical.toByteArray(Charsets.UTF_8).contentEquals(bytes))
        PushBatch(canonical)
    }

    /** No prefix ACK for an error response, truncated body or an invalid later result. */
    fun response(batch: PushBatch, httpStatus: Int, bytes: ByteArray): PushReceipt = safe {
        require(httpStatus == 200)
        schema.validate(bytes, "PushResponse", MAX_RESPONSE_BYTES)
        val value = StrictJson.read(bytes)
        val request = batch.json()
        require(value.getString("sync_epoch") == request.getString("sync_epoch"))
        val operations = request.getJSONArray("operations")
        val results = value.getJSONArray("results")
        require(results.length() == operations.length())
        for (i in 0 until results.length()) {
            val operation = operations.getJSONObject(i)
            val result = results.getJSONObject(i)
            require(result.getString("operation_id") == operation.getString("operation_id"))
            require(result.getString("entity_id") == operation.getString("entity_id"))
            require(result.isNull("recovery_mapping"))
            if (result.getString("status") in SUCCESSES) {
                val previous = if (operation.isNull("base_revision")) 0 else operation.getInt("base_revision")
                require(result.getLong("revision") == previous.toLong() + 1)
            }
        }
        PushReceipt(StrictJson.canonical(value), batch.sha256)
    }

    /** E4 errors use object details; E3/bootstrap errors have a different shape. */
    fun errorCode(bytes: ByteArray): String = safe {
        schema.validate(bytes, "SyncError", 65_536)
        StrictJson.read(bytes).getString("code")
    }

    /** accepted→already_applied may replay the original receipt; a new revision is never a replay. */
    fun sameDecision(batch: PushBatch, first: PushReceipt, next: PushReceipt): Boolean = safe {
        require(first.requestHash == batch.sha256 && next.requestHash == batch.sha256)
        val a = first.json().getJSONArray("results")
        val b = next.json().getJSONArray("results")
        (0 until a.length()).all { i ->
            val x = a.getJSONObject(i)
            val y = b.getJSONObject(i)
            if (x.getString("status") in SUCCESSES && y.getString("status") in SUCCESSES) {
                x.put("status", "accepted"); y.put("status", "accepted")
            }
            StrictJson.canonical(x) == StrictJson.canonical(y)
        }
    }

    private fun operation(text: String): JSONObject {
        val bytes = text.toByteArray(Charsets.UTF_8)
        schema.validate(bytes, "Operation", MAX_REQUEST_BYTES)
        val value = StrictJson.read(bytes)
        require(!value.has("recovery"))
        require(StrictJson.canonical(value.get("payload")).toByteArray(Charsets.UTF_8).size <= MAX_PAYLOAD_BYTES)
        if (value.getString("entity_type") == "meal" && value.getString("action") == "upsert") {
            MealWire.read(StrictJson.canonical(value.getJSONObject("payload")), schema)
        }
        if (value.getString("entity_type") == "weight" && value.getString("action") == "upsert") {
            WeightWire.read(StrictJson.canonical(value.getJSONObject("payload")), schema)
        }
        if (value.getString("entity_type") in PrivateDomainsWire.types && value.getString("action") == "upsert") {
            PrivateDomainsWire.read(value.getString("entity_type"), StrictJson.canonical(value.getJSONObject("payload")), schema)
        }
        return value
    }
    private fun envelope(epoch: String, checkpoint: String, operations: JSONArray) = StrictJson.canonical(
        JSONObject().put("protocol_version", 1).put("sync_epoch", epoch)
            .put("checkpoint", checkpoint).put("operations", operations))
    private inline fun <T> safe(action: () -> T): T = try { action() }
        catch (_: Exception) { throw SyncWireException() }

    companion object {
        const val MAX_OPERATIONS = 100
        const val MAX_REQUEST_BYTES = 1_048_576
        const val MAX_PAYLOAD_BYTES = 262_144
        const val MAX_RESPONSE_BYTES = 4 * 1_048_576
        private val SUCCESSES = setOf("accepted", "already_applied")
    }
}
