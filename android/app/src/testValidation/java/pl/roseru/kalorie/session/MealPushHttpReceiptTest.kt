package pl.roseru.kalorie.session

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class MealPushHttpReceiptTest {
    private val id="00000000-0000-4000-8000-00000000a003"
    private val batch="00000000-0000-4000-8000-000000000001"
    private val hash="a".repeat(64)
    private val time=Instant.parse("2026-10-19T10:00:00Z")
    private fun receipt(code:Int=200,cache:String?="private, NO-STORE",request:String?=id)=
        MealPushHttpReceipt.read("POST","/api/v1/sync/push",code,cache,request,time)!!

    @Test fun metadataHasOnlyFixedPathTimeStatusAndSanitizedHeaders() {
        assertEquals("path=/api/v1/sync/push utc=$time status=200 no_store=true request_id=$id",receipt().format())
    }
    @Test fun arbitraryPathsMethodsAndStatusesAreRejected() {
        assertNull(MealPushHttpReceipt.read("GET","/api/v1/sync/push",200,null,null,time))
        assertNull(MealPushHttpReceipt.read("POST","/private?secret=value",200,null,null,time))
        for(code in listOf(199,301,399,600))assertNull(MealPushHttpReceipt.read("POST","/api/v1/sync/push",code,null,null,time))
    }
    @Test fun headerInjectionAndMissingIdsNeverEchoRawInput() {
        for(value in listOf("secret-token\nforged=true","x".repeat(4096),id.uppercase())) {
            val result=receipt(request=value)
            assertEquals("invalid",result.requestId);assertFalse(result.format().contains(value))
        }
        assertEquals("missing",receipt(request=null).requestId)
    }
    @Test fun missingMalformedAndOversizedCacheControlAreNotNoStore() {
        for(cache in listOf(null,"public","not-no-store","x".repeat(1025)+",no-store"))assertFalse(receipt(cache=cache).noStore)
    }
    @Test fun errorAndOverloadReceiptsDoNotInventSuccess() {
        for(code in listOf(401,409,429,503))assertEquals(code,receipt(code,cache=null).status)
        assertFalse(receipt(503,cache=null).noStore)
    }
    @Test fun onlyArmedEnvelopeGetsReceiptAndHistoryIsBounded() {
        val gate=MealPushAckGate();assertNull(gate.received(hash,receipt()))
        val ticket=gate.arm(batch,hash)
        assertNull(gate.received("b".repeat(64),receipt()))
        repeat(4){assertEquals(ticket.run,gate.received(hash,receipt()))}
        assertNull(gate.received(hash,receipt()));assertEquals(4,ticket.httpReceipts().size)
        assertTrue(ticket.httpOverflow)
        gate.disarm(ticket)
    }
    @Test fun returnedHistoryCannotBeUsedToOverwriteInternalReceipts() {
        val gate=MealPushAckGate();val ticket=gate.arm(batch,hash)
        gate.received(hash,receipt());val copy=ticket.httpReceipts().toMutableList();copy.clear()
        assertEquals(1,ticket.httpReceipts().size);gate.disarm(ticket)
    }
}
