package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.energy.*

/** A legacy E deliberately reuses its source goal UUID; neither domain is a duplicate. */
class GoalEnergyIdentityProtocolTest {
    private fun bytes(path:String)=javaClass.getResourceAsStream(path)!!.use {it.readBytes()}
    private val schema get()=SyncWireSchema(SyncWireSchema.FILES.associateWith {bytes("/sync/$it")})
    private val energy get()=EnergySchema(bytes("/energy/energy.schema.json"))
    private val protocol get()=SnapshotProtocol(schema,energy)
    private val epoch="11111111-1111-4111-8111-111111111111"
    private val shared="22222222-2222-4222-8222-222222222222"
    private fun version()=StrictJson.read(bytes("/energy/energy-version.json")).put("revision",1).also {
        it.getJSONObject("payload").getJSONObject("audit").put("goal_timeline_revision",1)
    }
    private fun goal()=JSONObject().put("entity_type","goal").put("entity_id",shared).put("revision",1).put("deleted",false)
        .put("payload",StrictJson.read(bytes("/sync/goal.json")).put("estimate",version().getJSONObject("payload").getJSONObject("audit").getJSONObject("estimate")))
    private fun response(rows:List<JSONObject>,mode:String="incremental",next:String?=null)=StrictJson.canonical(JSONObject()
        .put("sync_epoch",epoch).put("mode",mode).put("snapshot_token",if(mode=="snapshot")"synthetic-snapshot" else JSONObject.NULL)
        .put("page_token",next?:JSONObject.NULL).put("checkpoint",if(next==null)"synthetic-new-checkpoint" else JSONObject.NULL)
        .put("server_time","2026-10-24T10:00:00Z").put("goal_timeline_revision",1).put("entities",JSONArray(rows))
        .put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray()))
    private fun delta(rows:List<JSONObject>):ServerDiarySnapshot {
        val base=ServerDiarySnapshot(epoch,"synthetic-base-checkpoint","2026-10-24T09:00:00Z","2026-10-24T09:00:00Z",0,
            emptyList(),protocolScope=SyncProtocolScope.ENERGY_V1)
        val query=protocol.incrementalQuery(epoch,base.checkpoint)
        return IncrementalDiaryProtocol(schema,energy).read(epoch,listOf(ArchivedDiaryPage(query.canonical,response(rows))),base,base.checkpoint)
    }
    private fun full(first:List<JSONObject>,second:List<JSONObject>?=null):ServerDiarySnapshot {
        val query=protocol.query(epoch,scope=SyncProtocolScope.ENERGY_V1)
        val pages=mutableListOf(ArchivedDiaryPage(query.canonical,response(first,"snapshot",second?.let {"synthetic-next"})))
        if(second!=null)pages+=ArchivedDiaryPage(protocol.query(epoch,snapshot="synthetic-snapshot",page="synthetic-next",scope=SyncProtocolScope.ENERGY_V1).canonical,response(second,"snapshot"))
        return ServerDiaryProtocol(schema,energy).read(epoch,pages,SyncProtocolScope.ENERGY_V1)
    }
    private fun assertPair(value:ServerDiarySnapshot) {
        assertEquals(shared,value.entities.single().id);assertEquals("goal",value.entities.single().type)
        assertEquals(shared,value.energyVersions.single().id);assertEquals("legacy",value.energyVersions.single().source)
        assertEquals("synthetic-new-checkpoint",value.checkpoint)
    }
    @Test fun incrementalKeepsGoalAndInitialEnergyInBothOrders() {
        assertPair(delta(listOf(goal(),version())))
        assertPair(delta(listOf(version(),goal())))
    }
    @Test fun fullKeepsGoalAndInitialEnergyInBothOrdersAndAcrossPages() {
        assertPair(full(listOf(goal(),version())))
        assertPair(full(listOf(version(),goal())))
        assertPair(full(listOf(goal()),listOf(version())))
        assertPair(full(listOf(version()),listOf(goal())))
    }
    @Test fun fullStillRejectsSameDomainDuplicateInOneOrSeveralPages() {
        for(row in listOf(goal(),version())) {
            assertThrows(SyncWireException::class.java){full(listOf(row,row))}
            assertThrows(SyncWireException::class.java){full(listOf(row),listOf(row))}
        }
    }
    private fun weight(revision:Int=1)=JSONObject().put("entity_type","weight").put("entity_id",shared).put("revision",revision).put("deleted",false)
        .put("payload",JSONObject().put("weight_kg","80").put("occurred_at","2026-10-24T09:00:00Z").put("time_zone","UTC").put("local_date","2026-10-24"))
    @Test fun ordinaryDiaryDomainsRetainTheirPreviousGlobalUuidGuard() {
        val weight=weight()
        assertThrows(SyncWireException::class.java){delta(listOf(goal(),weight))}
        assertThrows(SyncWireException::class.java){delta(listOf(weight,goal()))}
        assertThrows(SyncWireException::class.java){full(listOf(goal(),weight))}
        assertThrows(SyncWireException::class.java){full(listOf(goal()),listOf(weight))}
    }
    @Test fun sameDomainRevisionRegressionAndChangedImmutableEnergyRemainRejected() {
        assertThrows(SyncWireException::class.java){delta(listOf(weight(2),weight(1)))}
        val changed=version().also {it.getJSONObject("payload").put("maintenance_kcal","3205")}
        assertThrows(SyncWireException::class.java){delta(listOf(version(),changed))}
        val conflictingRevision=version().put("entity_id","33333333-3333-4333-8333-333333333333")
        assertThrows(SyncWireException::class.java){delta(listOf(version(),conflictingRevision))}
    }
}
