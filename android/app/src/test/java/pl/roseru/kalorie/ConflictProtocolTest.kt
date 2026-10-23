package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.sync.*

class ConflictProtocolTest {
    private fun bytes(path: String) = javaClass.getResourceAsStream(path)!!.use { it.readBytes() }
    private val schema = SyncWireSchema(SyncWireSchema.FILES.associateWith { bytes("/sync/$it") })
    private val push = PushProtocol(schema)
    private val protocol = ConflictProtocol(schema)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private val id = "11111111-1111-4111-8111-111111111111"
    private val op = "44444444-4444-4444-8444-444444444444"
    private val other = "22222222-2222-4222-8222-222222222222"
    private fun weight(kg: Double) = WeightWire.create(kg, "2026-10-20T23:30:00Z", "Europe/Warsaw", "2026-10-21", schema)
    private fun operation(key: String = op, entity: String = id) = WeightWire.operation(key, entity, epoch, 1, weight(80.125).canonical, schema)
    private fun batch(vararg rows: String) = push.prepare(epoch, "synthetic-checkpoint", rows.toList())
    private fun response(): JSONObject {
        val value = JSONObject(String(bytes("/photo/materialized-meal-push-response.json")))
        val result = value.getJSONArray("results").getJSONObject(0)
        result.remove("revision")
        result.put("status", "conflict").put("code", "revision_conflict").put("message", "Operacja wymaga uzgodnienia.")
            .put("details_retained", true).put("current", JSONObject().put("entity_type", "weight").put("entity_id", id)
                .put("revision", 2).put("deleted", false).put("payload", weight(82.375).json()))
        return value
    }
    @Test fun serverVersionIsExactAndIndependentOfTheFrozenLocalProposal() {
        val request = batch(operation()); val response = response()
        val evidence = protocol.read(request, response.toString().toByteArray(), op)
        assertEquals(ConflictServerState.PRESENT, evidence.serverState)
        assertEquals(2, evidence.serverRevision)
        assertEquals("82.375", JSONObject(evidence.serverPayload!!).getString("weight_kg"))
        assertEquals("80.125", JSONObject(evidence.originalPayload!!).getString("weight_kg"))
        response.getJSONArray("results").getJSONObject(0).getJSONObject("current").getJSONObject("payload").put("weight_kg", "90")
        assertEquals("82.375", JSONObject(evidence.serverPayload).getString("weight_kg"))
        assertEquals(request.sha256, evidence.requestHash)
        assertEquals("SyncConflictEvidence(redacted)", evidence.toString())
    }
    @Test fun schemaValidForeignIdentityOrDifferentTypeCannotBecomeAConflictPreview() {
        val request = batch(operation())
        val foreign = response(); foreign.getJSONArray("results").getJSONObject(0).getJSONObject("current").put("entity_id", other)
        push.response(request, 200, foreign.toString().toByteArray())
        assertThrows(Exception::class.java) { protocol.read(request, foreign.toString().toByteArray(), op) }
        val wrongType = response()
        val meal = JSONObject(String(bytes("/photo/materialized-meal-operation.json"))).getJSONObject("payload")
        wrongType.getJSONArray("results").getJSONObject(0).getJSONObject("current").put("entity_type", "meal").put("payload", meal)
        push.response(request, 200, wrongType.toString().toByteArray())
        assertThrows(Exception::class.java) { protocol.read(request, wrongType.toString().toByteArray(), op) }
    }
    @Test fun aMalformedLaterResultCannotExposeAValidEarlierConflict() {
        val secondOp = "66666666-6666-4666-8666-666666666666"
        val request = batch(operation(), operation(secondOp, other))
        val value = response()
        value.getJSONArray("results").put(JSONObject().put("operation_id", secondOp).put("entity_id", id)
            .put("status", "accepted").put("revision", 2).put("recovery_mapping", JSONObject.NULL))
        assertThrows(Exception::class.java) { protocol.read(request, value.toString().toByteArray(), op) }
    }
    @Test fun aPurgedResponseDoesNotInventAServerVersionOrReuseAReservedIdentity() {
        val request = batch(operation()); val value = response()
        val result = value.getJSONArray("results").getJSONObject(0)
        result.put("current", JSONObject.NULL).put("details_retained", false)
        val unavailable = protocol.read(request, value.toString().toByteArray(), op)
        assertEquals(ConflictServerState.UNAVAILABLE, unavailable.serverState)
        assertNull(unavailable.serverRevision); assertNull(unavailable.serverPayload)
        result.put("code", "entity_id_reserved")
        val deleted = protocol.read(request, value.toString().toByteArray(), op)
        assertEquals(ConflictServerState.DELETED, deleted.serverState)
        assertNull(deleted.serverRevision); assertNull(deleted.serverPayload)
    }
    @Test fun aServerMeasurementUsesContractBoundsButMustHaveAConsistentLocalDay() {
        val request = batch(operation()); val value = response()
        val payload = value.getJSONArray("results").getJSONObject(0).getJSONObject("current").getJSONObject("payload")
        payload.put("weight_kg", "1")
        assertEquals("1", JSONObject(protocol.read(request, value.toString().toByteArray(), op).serverPayload!!).getString("weight_kg"))
        payload.put("local_date", "2026-10-20")
        push.response(request, 200, value.toString().toByteArray())
        assertThrows(Exception::class.java) { protocol.read(request, value.toString().toByteArray(), op) }
    }
}
