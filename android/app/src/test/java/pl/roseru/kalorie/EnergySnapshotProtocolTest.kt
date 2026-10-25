package pl.roseru.kalorie

import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.core.sync.SyncWireSchema
import pl.roseru.kalorie.energy.*

/** Pending until the complete opt-in consumer is assembled; no live API claims. */
class EnergySnapshotProtocolTest {
    private fun bytes(name:String)=javaClass.getResourceAsStream(name)!!.use {it.readBytes()}
    private val legacy get()=SnapshotProtocol(SyncWireSchema(SyncWireSchema.FILES.associateWith {bytes("/sync/$it")}))
    private val protocol get()=EnergySnapshotProtocol(legacy,EnergySchema(bytes("/energy/energy.schema.json")))

    @Test fun fullSnapshotRetainsLegacyAndEnergyRecordsAndAcceptsFullLengthOpaqueTokens() {
        val value=StrictJson.read(bytes("/sync/sync-pull-response.json"))
            .put("mode","snapshot").put("snapshot_token","s".repeat(4096)).put("checkpoint","c".repeat(4096))
        val weightId=value.getJSONArray("entities").getJSONObject(0).getString("entity_id")
        val version=StrictJson.read(bytes("/energy/energy-version.json"))
        value.getJSONArray("entities").put(version)
        val query=protocol.query(value.getString("sync_epoch"))
        val read=protocol.response(query,StrictJson.canonical(value).toByteArray(Charsets.UTF_8))
        assertEquals(2,read.entityCount);assertEquals(2,read.totalCount)
        assertEquals(version.getString("entity_id"),read.energyVersions.single().id)
        assertEquals(weightId,read.json().getJSONArray("entities").getJSONObject(0).getString("entity_id"))
        assertEquals("s".repeat(4096),read.json().getString("snapshot_token"))
        assertFalse(read.toString().contains("s".repeat(100)))

        val duplicate=StrictJson.read(read.wire.toByteArray(Charsets.UTF_8))
        duplicate.getJSONArray("entities").getJSONObject(1).put("entity_id",weightId)
        assertThrows(IllegalArgumentException::class.java) {
            protocol.response(query,StrictJson.canonical(duplicate).toByteArray(Charsets.UTF_8))
        }
        val oversized=StrictJson.read(read.wire.toByteArray(Charsets.UTF_8)).put("snapshot_token","s".repeat(4097))
        assertThrows(IllegalArgumentException::class.java) {
            protocol.response(query,StrictJson.canonical(oversized).toByteArray(Charsets.UTF_8))
        }
    }
}
