package pl.roseru.kalorie.core.sync

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson

/** Explicit epoch recovery only. Ownership, consent, source evidence and target state belong to the store. */
class RecoveryProtocol(private val schema: SyncWireSchema) {
    fun operation(opId: String, type: String, id: String, epoch: String, revision: Int?,
        payload: String, recoverySource: String): String = safe { operation(StrictJson.canonical(JSONObject()
        .put("operation_id", opId).put("entity_type", type).put("entity_id", id).put("sync_epoch", epoch)
        .put("action", "upsert").put("base_revision", revision ?: JSONObject.NULL)
        .put("payload", StrictJson.read(payload.toByteArray(Charsets.UTF_8)))
        .put("recovery", StrictJson.read(recoverySource.toByteArray(Charsets.UTF_8))))) }

    /** Returns a detached validated canonical operation; never rewrites an existing operation's epoch. */
    fun operation(text: String): String = safe {
        val bytes = text.toByteArray(Charsets.UTF_8)
        schema.validate(bytes, "Operation", PushProtocol.MAX_REQUEST_BYTES)
        val value = StrictJson.read(bytes)
        require(value.getString("action") == "upsert" && value.has("recovery"))
        val source = value.getJSONObject("recovery")
        require(source.getString("source_epoch") != value.getString("sync_epoch"))
        if (!source.isNull("source_operation_id")) {
            require(source.getString("source_operation_id") != value.getString("operation_id"))
        }
        when (source.getString("decision")) {
            "recreate_missing" -> require(value.isNull("base_revision") &&
                source.getString("source_entity_id") != value.getString("entity_id"))
            "resolve_existing" -> require(!value.isNull("base_revision"))
            else -> throw SyncWireException()
        }
        payload(value.getString("entity_type"), value.getJSONObject("payload"))
        StrictJson.canonical(value)
    }

    /** Same bounded contiguous-prefix policy as ordinary push, with unique recovery sources. */
    fun prepare(epoch: String, checkpoint: String, operations: List<String>): PushBatch = safe {
        val selected = JSONArray()
        val ids = mutableSetOf<String>()
        val entities = mutableSetOf<String>()
        val sources = mutableSetOf<String>()
        for (text in operations) {
            if (selected.length() == PushProtocol.MAX_OPERATIONS) break
            val row = StrictJson.read(operation(text).toByteArray(Charsets.UTF_8))
            require(row.getString("sync_epoch") == epoch)
            require(ids.add(row.getString("operation_id")))
            if (!entities.add(row.getString("entity_type") + ":" + row.getString("entity_id")) ||
                !sources.add(sourceIdentity(row))) break
            val candidate = JSONArray(selected.toString()).put(row)
            if (envelope(epoch, checkpoint, candidate).toByteArray(Charsets.UTF_8).size > PushProtocol.MAX_REQUEST_BYTES) {
                require(selected.length() > 0)
                break
            }
            selected.put(row)
        }
        restore(envelope(epoch, checkpoint, selected).toByteArray(Charsets.UTF_8))
    }

    /** Exact persisted bytes only; no automatic regrouping or checkpoint replacement. */
    fun restore(bytes: ByteArray): PushBatch = safe {
        schema.validate(bytes, "PushRequest", PushProtocol.MAX_REQUEST_BYTES)
        val value = StrictJson.read(bytes)
        val epoch = value.getString("sync_epoch")
        val rows = value.getJSONArray("operations")
        val ids = mutableSetOf<String>()
        val entities = mutableSetOf<String>()
        val sources = mutableSetOf<String>()
        for (i in 0 until rows.length()) {
            val row = StrictJson.read(operation(StrictJson.canonical(rows.getJSONObject(i))).toByteArray(Charsets.UTF_8))
            require(row.getString("sync_epoch") == epoch && ids.add(row.getString("operation_id")))
            require(entities.add(row.getString("entity_type") + ":" + row.getString("entity_id")))
            require(sources.add(sourceIdentity(row)))
        }
        val canonical = StrictJson.canonical(value)
        require(canonical.toByteArray(Charsets.UTF_8).contentEquals(bytes))
        PushBatch(canonical)
    }

    /** Validate every result before returning a receipt. A receipt is not permission to mutate Room. */
    fun response(batch: PushBatch, httpStatus: Int, bytes: ByteArray): PushReceipt = safe {
        require(httpStatus == 200)
        // A PushBatch constructed by the ordinary protocol is not a recovery request.
        restore(batch.body())
        schema.validate(bytes, "PushResponse", PushProtocol.MAX_RESPONSE_BYTES)
        val value = StrictJson.read(bytes)
        val request = batch.json()
        require(value.getString("sync_epoch") == request.getString("sync_epoch"))
        val rows = request.getJSONArray("operations")
        val results = value.getJSONArray("results")
        require(results.length() == rows.length())
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            val result = results.getJSONObject(i)
            require(result.getString("operation_id") == row.getString("operation_id") &&
                result.getString("entity_id") == row.getString("entity_id"))
            val source = row.getJSONObject("recovery")
            val mapping = if (result.isNull("recovery_mapping")) null else result.getJSONObject("recovery_mapping")
            if (mapping != null) {
                require(mapping.getString("source_epoch") == source.getString("source_epoch") &&
                    mapping.getString("source_entity_id") == source.getString("source_entity_id"))
            }
            val status = result.getString("status")
            if (status == "accepted" || status == "already_applied") {
                require(mapping != null)
                if (status == "accepted") {
                    val base = if (row.isNull("base_revision")) 0L else row.getLong("base_revision")
                    require(result.getLong("revision") == base + 1 &&
                        mapping.getString("target_entity_id") == row.getString("entity_id") &&
                        mapping.getLong("target_revision") == result.getLong("revision"))
                } else {
                    // Compact receipts retain the original result revision but expose the current mapping revision.
                    require(mapping.getLong("target_revision") >= result.getLong("revision"))
                }
            } else if (!result.isNull("current")) {
                val current = result.getJSONObject("current")
                require(current.getString("entity_type") == row.getString("entity_type"))
                if (mapping != null) {
                    require(current.getString("entity_id") == mapping.getString("target_entity_id") &&
                        current.getLong("revision") == mapping.getLong("target_revision"))
                } else if (row.getString("entity_type") !in setOf("profile", "diary_day")) {
                    require(current.getString("entity_id") == row.getString("entity_id"))
                }
                if (!current.getBoolean("deleted")) payload(current.getString("entity_type"), current.getJSONObject("payload"))
            }
        }
        PushReceipt(StrictJson.canonical(value), batch.sha256)
    }

    private fun payload(type: String, value: JSONObject) {
        val text = StrictJson.canonical(value)
        require(text.toByteArray(Charsets.UTF_8).size <= PushProtocol.MAX_PAYLOAD_BYTES)
        when (type) {
            "meal" -> MealWire.read(text, schema)
            "weight" -> WeightWire.read(text, schema)
            else -> PrivateDomainsWire.read(type, text, schema)
        }
    }
    private fun sourceIdentity(row: JSONObject): String = row.getJSONObject("recovery").let {
        it.getString("source_epoch") + ":" + it.getString("source_entity_id")
    }
    private fun envelope(epoch: String, checkpoint: String, rows: JSONArray) = StrictJson.canonical(JSONObject()
        .put("protocol_version", 1).put("sync_epoch", epoch).put("checkpoint", checkpoint).put("operations", rows))
    private inline fun <T> safe(action: () -> T): T = try { action() }
        catch (_: Exception) { throw SyncWireException() }
}