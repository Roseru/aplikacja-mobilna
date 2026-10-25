package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.energy.*

class IncrementalSyncProtocolTest {
    private fun resource(path:String)=javaClass.getResourceAsStream(path)!!.use {it.readBytes()}
    private val schema get()=SyncWireSchema(SyncWireSchema.FILES.associateWith {resource("/sync/$it")})
    private val energy get()=EnergySchema(resource("/energy/energy.schema.json"))
    private val epoch="11111111-1111-4111-8111-111111111111"
    private val weight="99999999-9999-4999-8999-999999999999"
    private fun row(revision:Int,kg:String)=JSONObject().put("entity_type","weight").put("entity_id",weight).put("revision",revision)
        .put("deleted",false).put("payload",JSONObject().put("weight_kg",kg).put("occurred_at","2026-10-24T09:00:00Z")
            .put("time_zone","UTC").put("local_date","2026-10-24"))
    private fun page(rows:List<JSONObject>,next:String?)=StrictJson.canonical(JSONObject().put("sync_epoch",epoch).put("mode","incremental")
        .put("snapshot_token",JSONObject.NULL).put("page_token",next?:JSONObject.NULL).put("checkpoint",if(next==null)"new-checkpoint"else JSONObject.NULL)
        .put("server_time","2026-10-24T10:00:00Z").put("goal_timeline_revision",0).put("entities",JSONArray(rows))
        .put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray()))
    @Test fun orderedChangesAcrossPagesPreserveUnchangedAxisAndOriginalQueryBytes() {
        val legacy=SnapshotProtocol(schema);val snapshots=SnapshotProtocol(schema,energy)
        val original=legacy.query(epoch).canonical
        assertEquals(original,snapshots.query(epoch,scope=SyncProtocolScope.ENERGY_V1).canonical)
        val old=row(1,"80");val version=EnergyProtocol(energy).version(StrictJson.read(resource("/energy/energy-version.json")))
        val base=ServerDiarySnapshot(epoch,"base-checkpoint","2026-10-24T09:00:00Z","2026-10-24T09:00:00Z",0,
            listOf(ServerDiaryEntity(weight,"weight",1,false,StrictJson.canonical(old.getJSONObject("payload")))),
            energyVersions=listOf(version),protocolScope=SyncProtocolScope.ENERGY_V1)
        val first=snapshots.incrementalQuery(epoch,"base-checkpoint",page=null)
        val second=snapshots.incrementalQuery(epoch,"base-checkpoint",page="continuation")
        val archive=listOf(ArchivedDiaryPage(first.canonical,page(listOf(row(2,"81")),"continuation")),
            ArchivedDiaryPage(second.canonical,page(listOf(row(3,"82")),null)))
        val result=IncrementalDiaryProtocol(schema,energy).read(epoch,archive,base,"base-checkpoint")
        assertEquals(3,result.entities.single().revision)
        assertEquals("82",StrictJson.read(result.entities.single().payload!!.toByteArray()).getString("weight_kg"))
        assertEquals(version,result.energyVersions.single());assertEquals("new-checkpoint",result.checkpoint)
        assertEquals(1,base.entities.single().revision);assertEquals("base-checkpoint",base.checkpoint)
        val reversed=archive.toMutableList().also {it[1]=ArchivedDiaryPage(second.canonical,page(listOf(row(1,"80")),null))}
        assertThrows(SyncWireException::class.java){IncrementalDiaryProtocol(schema,energy).read(epoch,reversed,base,"base-checkpoint")}
        assertThrows(IllegalArgumentException::class.java){legacy.incrementalQuery(epoch,"base-checkpoint")}
        assertThrows(IllegalArgumentException::class.java){snapshots.response(first,page(listOf(row(2,"81")),null).replace("incremental","snapshot").toByteArray())}
    }
}
