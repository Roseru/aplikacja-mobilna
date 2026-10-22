package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.core.catalog.StrictJson
import java.util.UUID

class ServerDiaryProtocolTest {
    private fun bytes(path: String) = javaClass.getResourceAsStream(path)!!.use { it.readBytes() }
    private val schema = SyncWireSchema(SyncWireSchema.FILES.associateWith { bytes("/sync/$it") })
    private val snapshots = SnapshotProtocol(schema)
    private val protocol = ServerDiaryProtocol(schema)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private fun entity(type: String) = JSONObject().put("entity_type", type).put("entity_id", UUID.randomUUID().toString())
        .put("revision", 1).put("deleted", false).put("payload", JSONObject(String(bytes("/sync/${type.replace('_','-')}.json"))))
    private fun response(rows: List<JSONObject>, next: String? = null) = JSONObject().put("sync_epoch", epoch)
        .put("mode", "snapshot").put("snapshot_token", "synthetic-snapshot").put("page_token", next ?: JSONObject.NULL)
        .put("checkpoint", if(next==null) "synthetic-checkpoint" else JSONObject.NULL).put("server_time", "2026-10-22T10:00:00Z")
        .put("goal_timeline_revision", 1).put("entities", JSONArray(rows)).put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray())
    private fun page(value: JSONObject, query: SnapshotQuery = snapshots.query(epoch)) = ArchivedDiaryPage(query.canonical, StrictJson.canonical(value))

    @Test fun fullCopyRetainsAllSixTypesAndExactMissingNutritionIndependentlyOfMutableInput() {
        val rows = listOf("profile","goal","meal","weight","diary_day","product_draft").map(::entity)
        val value = response(rows); val read = protocol.read(epoch, listOf(page(value)))
        assertEquals(6, read.entities.size); assertEquals(1, read.timelineRevision)
        val draft = read.entities.single { it.type=="product_draft" }
        assertTrue(JSONObject(draft.payload!!).getJSONObject("nutrition_per_100").isNull("protein_g"))
        value.getJSONArray("entities").getJSONObject(0).getJSONObject("payload").put("pseudonym","Changed")
        assertFalse(read.entities.first().payload!!.contains("Changed"))
        assertEquals("ServerDiarySnapshot(redacted)",read.toString())
    }
    @Test fun entirePaginationChainAndCompleteCheckpointAreRequired() {
        val first=entity("weight"); val second=entity("meal")
        val start=page(response(listOf(first),"next"))
        val end=page(response(listOf(second)),snapshots.query(epoch,100,"synthetic-snapshot","next"))
        assertEquals(2,protocol.read(epoch,listOf(start,end)).entities.size)
        assertThrows(Exception::class.java){protocol.read(epoch,listOf(start))}
        assertThrows(Exception::class.java){protocol.read(epoch,listOf(end))}
        assertThrows(Exception::class.java){protocol.read(epoch,listOf(start,page(response(listOf(second)))))}
    }
    @Test fun duplicateIdentityOrAnInvalidLaterEntityCannotReturnAnEarlierValidPrefix() {
        val row=entity("weight")
        val start=page(response(listOf(row),"next"))
        val end=page(response(listOf(row)),snapshots.query(epoch,100,"synthetic-snapshot","next"))
        assertThrows(Exception::class.java){protocol.read(epoch,listOf(start,end))}
        val profile=entity("profile");profile.getJSONObject("payload").put("height_cm","301")
        assertThrows(Exception::class.java){protocol.read(epoch,listOf(page(response(listOf(row,profile)))))}
    }
    @Test fun goalOrderCorrectionsAndUniqueProfileAndDayHaveCrossRecordConstraints() {
        val goal=entity("goal");val bad=entity("goal")
        assertThrows(Exception::class.java){protocol.read(epoch,listOf(page(response(listOf(goal,bad)))))}
        for(type in listOf("profile","diary_day")) {
            val value=response(listOf(entity(type),entity(type)))
            assertThrows(Exception::class.java){protocol.read(epoch,listOf(page(value)))}
        }
        bad.getJSONObject("payload").put("reason","history_correction").put("correction_of",UUID.randomUUID().toString())
        assertThrows(Exception::class.java){protocol.read(epoch,listOf(page(response(listOf(bad)))))}
    }
    @Test fun privateDraftKeepsMlDensityAndUnknownEnergyWithoutAnOfficialProductIdentity() {
        val draft=entity("product_draft").getJSONObject("payload")
        draft.put("basis_unit","ml").put("density_g_per_ml","1.25").put("density_source","Synthetic label")
        draft.getJSONObject("nutrition_per_100").put("energy_kcal",JSONObject.NULL)
        val text=StrictJson.canonical(draft)
        val amount=PrivateProductWire.portion(text,"125","g").asExact()
        assertFalse(amount.energy.complete);assertEquals(1,amount.energy.missingCount)
        val meal=PrivateProductWire.meal(text,UUID.randomUUID().toString(),"125","g",
            "2026-10-22T08:00:00Z","Europe/Warsaw","lunch",schema).json()
        val item=meal.getJSONArray("items").getJSONObject(0)
        assertTrue(item.isNull("product"));assertEquals("ml",item.getString("basis_unit"))
        assertEquals("1.25",item.getString("density_g_per_ml"))
    }
}
