package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*

class WeightWireTest {
    private val schema=SyncWireSchema(SyncWireSchema.FILES.associateWith {javaClass.getResourceAsStream("/sync/$it")!!.use {s->s.readBytes()}})
    private val id="11111111-1111-4111-8111-111111111111"
    private val op="44444444-4444-4444-8444-444444444444"
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun weight()=WeightWire.create(80.125,"2026-10-20T23:30:00.123456789Z","Europe/Warsaw","2026-10-21",schema)
    @Test fun exactWeightKeepsLocalDayAndMicrosecondsAndImmutablePayload() {
        val wire=weight();val value=wire.json()
        assertEquals("80.125",value.getString("weight_kg"));assertEquals("2026-10-20T23:30:00.123456Z",value.getString("occurred_at"))
        assertEquals("2026-10-21",value.getString("local_date"));value.put("weight_kg","99")
        assertEquals("80.125",wire.json().getString("weight_kg"));assertEquals("WeightWire(redacted)",wire.toString())
    }
    @Test fun excessivePrecisionInvalidRangeAndInconsistentLocalDateAreRejected() {
        assertThrows(Exception::class.java){weight().withWeight(80.1234567,schema)}
        assertThrows(Exception::class.java){weight().withWeight(Double.NaN,schema)}
        assertThrows(Exception::class.java){weight().withWeight(19.9,schema)}
        assertThrows(Exception::class.java){WeightWire.read(weight().json().put("local_date","2026-10-20").toString(),schema)}
        assertThrows(Exception::class.java){WeightWire.read(weight().json().put("weight_kg",80).toString(),schema)}
    }
    @Test fun createAndDeleteKeepOperationIdentityAndRequireRealRevisionForDelete() {
        val wire=JSONObject(WeightWire.operation(op,id,epoch,null,weight().canonical,schema))
        assertEquals("weight",wire.getString("entity_type"));assertTrue(wire.isNull("base_revision"))
        assertThrows(Exception::class.java){WeightWire.operation(op,id,epoch,null,null,schema)}
        val delete=JSONObject(WeightWire.operation(op,id,epoch,1,null,schema))
        assertEquals(op,delete.getString("operation_id"));assertEquals("delete",delete.getString("action"));assertTrue(delete.isNull("payload"))
    }
    @Test fun persistedEnvelopeReopensIdenticallyAndMalformedWeightCannotEnterPush() {
        val protocol=PushProtocol(schema)
        val batch=protocol.prepare(epoch,"synthetic-checkpoint",listOf(WeightWire.operation(op,id,epoch,null,weight().canonical,schema)))
        assertArrayEquals(batch.body(),protocol.restore(batch.body()).body());assertEquals(batch.sha256,protocol.restore(batch.body()).sha256)
        val malformed=StrictJson.read(batch.body());malformed.getJSONArray("operations").getJSONObject(0).getJSONObject("payload").put("local_date","2026-10-20")
        assertThrows(Exception::class.java){protocol.restore(StrictJson.canonical(malformed).toByteArray())}
    }
}
