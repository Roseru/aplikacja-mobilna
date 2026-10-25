package pl.roseru.kalorie.energy

import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.core.sync.SnapshotQuery

/** Separate opt-in types prevent a seven-domain page from entering the legacy parser. */
internal class EnergySnapshotQuery internal constructor(internal val legacy:SnapshotQuery) {
    fun encoded():String=legacy.encoded()
    override fun toString()="EnergySnapshotQuery(redacted)"
}

/** The complete seven-domain archive is retained, including original receipts and tokens.
 * Parsing this page does not change the checkpoint or acknowledge any pending operation.
 */
internal class EnergySnapshotPage internal constructor(internal val wire:String,
    val energyVersions:List<EnergyVersion>,val entityCount:Int,val totalCount:Int) {
    internal fun json()=StrictJson.read(wire.toByteArray(Charsets.UTF_8))
    override fun toString()="EnergySnapshotPage(entities=$entityCount)"
}

/** Initial full snapshot for an explicit energy_estimates_v1 scope transition.
 * The caller must persist the selected scope with its request before sending the header.
 * This class never silently reinterprets an existing legacy query, page or checkpoint.
 */
internal class EnergySnapshotProtocol(private val legacy:SnapshotProtocol,private val schema:EnergySchema) {
    private val energy=EnergyProtocol(schema)

    fun query(epoch:String,limit:Int=100,snapshot:String?=null,page:String?=null,
        recoveryOperationIds:List<String> = emptyList()):EnergySnapshotQuery =
        EnergySnapshotQuery(legacy.query(epoch,limit,snapshot,page,recoveryOperationIds))

    fun response(query:EnergySnapshotQuery,bytes:ByteArray):EnergySnapshotPage {
        val value=schema.read(bytes,"EnergyPullResponse",SnapshotProtocol.MAX_BYTES)
        val request=query.legacy.json()
        require(value.getString("mode")=="snapshot" && value.getString("sync_epoch")==request.getString("sync_epoch"))
        if(request.has("snapshot_token"))require(value.getString("snapshot_token")==request.getString("snapshot_token"))
        if(!value.isNull("page_token"))require(value.getString("page_token")!=request.optString("page_token"))

        val entities=value.getJSONArray("entities")
        val total=entities.length()+value.getJSONArray("recovery_mappings").length()+value.getJSONArray("operation_receipts").length()
        require(total<=request.getInt("limit"))
        for((field,keys) in SnapshotProtocol.IDENTITIES) {
            val records=value.getJSONArray(field)
            val identities=(0 until records.length()).map {index->
                val record=records.getJSONObject(index)
                keys.joinToString(":"){record.getString(it)}
            }
            require(identities.distinct().size==identities.size)
        }
        val versions=(0 until entities.length()).mapNotNull {index->
            val entity=entities.getJSONObject(index)
            if(entity.getString("entity_type")=="energy_estimate")energy.version(entity)else null
        }
        return EnergySnapshotPage(StrictJson.canonical(value),versions,entities.length(),total)
    }

    companion object {
        const val CAPABILITY="energy_estimates_v1"
        const val SCOPE="calorie-app:energy_estimates_v1"
        const val LEGACY_SCOPE="calorie-app"
    }
}
