package pl.roseru.kalorie.core.sync

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.net.URLEncoder
import pl.roseru.kalorie.energy.EnergySchema
import pl.roseru.kalorie.energy.EnergySnapshotProtocol
import pl.roseru.kalorie.energy.EnergySnapshotQuery

/** Immutable validated query. Tokens and private data never appear in diagnostic strings. */
class SnapshotQuery internal constructor(internal val canonical: String,
    val protocolScope:SyncProtocolScope=SyncProtocolScope.LEGACY) {
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
class SnapshotPage internal constructor(internal val canonical: String,
    val protocolScope:SyncProtocolScope=SyncProtocolScope.LEGACY) {
    internal fun json() = StrictJson.read(canonical.toByteArray(Charsets.UTF_8))
    override fun toString() = "SnapshotPage(redacted)"
}

class SnapshotProtocol(private val schema: SyncWireSchema,private val energySchema:EnergySchema?=null) {
    val supportsEnergy:Boolean get()=energySchema!=null
    internal fun validateFull(epoch:String,pages:List<ArchivedDiaryPage>,scope:SyncProtocolScope=SyncProtocolScope.LEGACY) {
        ServerDiaryProtocol(schema,energySchema).read(epoch,pages,scope)
    }
    fun query(epoch: String, limit: Int = 100, snapshot: String? = null, page: String? = null,
        recoveryOperationIds: List<String> = emptyList(),scope:SyncProtocolScope=SyncProtocolScope.LEGACY): SnapshotQuery {
        require(scope==SyncProtocolScope.LEGACY || supportsEnergy)
        require(recoveryOperationIds.isEmpty() || (snapshot == null && page == null))
        val json = JSONObject().put("sync_epoch", epoch).put("limit", limit)
        if (recoveryOperationIds.isNotEmpty()) json.put("recovery_operation_ids", org.json.JSONArray(recoveryOperationIds))
        snapshot?.let { json.put("snapshot_token", it) }
        page?.let { json.put("page_token", it) }
        val canonical = StrictJson.canonical(json)
        schema.validate(canonical.toByteArray(Charsets.UTF_8), "PullRequest")
        return SnapshotQuery(canonical,scope)
    }
    fun response(query: SnapshotQuery, bytes: ByteArray): SnapshotPage {
        if(query.json().has("checkpoint"))return IncrementalDiaryProtocol(schema,checkNotNull(energySchema)).response(query,bytes)
        if(query.protocolScope==SyncProtocolScope.ENERGY_V1) {
            val page=EnergySnapshotProtocol(this,checkNotNull(energySchema)).response(EnergySnapshotQuery(query),bytes)
            return SnapshotPage(page.wire,query.protocolScope)
        }
        schema.validate(bytes, "PullResponse", MAX_BYTES)
        val value = StrictJson.read(bytes)
        val request = query.json()
        require(value.getString("mode") == "snapshot" && value.getString("sync_epoch") == request.getString("sync_epoch"))
        if (request.has("snapshot_token")) require(value.getString("snapshot_token") == request.getString("snapshot_token"))
        require(value.getJSONArray("entities").length() + value.getJSONArray("recovery_mappings").length() +
            value.getJSONArray("operation_receipts").length() <= request.getInt("limit"))
        if (!value.isNull("page_token")) require(value.getString("page_token") != request.optString("page_token"))
        // Duplicate identities in a full snapshot are ambiguous even if their payloads match.
        for (field in IDENTITIES.keys) {
            val records = value.getJSONArray(field)
            val ids = (0 until records.length()).map { index ->
                val record = records.getJSONObject(index)
                identity(field, record)
            }
            require(ids.toSet().size == ids.size)
        }
        return SnapshotPage(StrictJson.canonical(value))
    }
    fun incrementalQuery(epoch:String,checkpoint:String,limit:Int=100,page:String?=null,
        scope:SyncProtocolScope=SyncProtocolScope.ENERGY_V1):SnapshotQuery {
        require(supportsEnergy && scope==SyncProtocolScope.ENERGY_V1)
        val value=JSONObject().put("sync_epoch",epoch).put("checkpoint",checkpoint).put("limit",limit)
        page?.let {value.put("page_token",it)}
        val canonical=StrictJson.canonical(value)
        schema.validate(canonical.toByteArray(Charsets.UTF_8),"PullRequest")
        return SnapshotQuery(canonical,scope)
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
        // E is a separate immutable axis and legacy E reuses its source goal UUID.
        // Keep the original six-domain UUID guard; general diary collisions also
        // require a separate recovery contract, not just a different parser key.
        internal fun identity(field:String,record:JSONObject):String = if(field=="entities") {
            (if(record.getString("entity_type")=="energy_estimate")"energy_estimate:" else "diary:")+record.getString("entity_id")
        }else IDENTITIES.getValue(field).joinToString(":"){record.getString(it)}
    }
}
