package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import java.time.ZoneId

class NemesisMutationProtocolTest {
    private val id="12345678-1234-5678-9234-123456789abc"
    private val code="A".repeat(43)
    private val terms=NemesisTerms(7,ZoneId.of("Europe/Warsaw"),true,true)
    private fun metadata()=JSONObject(checkNotNull(javaClass.getResource("/nemesis/metadata.json")).readText())
    private fun invited(role:String="invitee"):JSONObject=metadata().put("role",role).put("status","invited").also { json ->
        listOf("accepted_at","start_date","end_date","start_at","end_at","deadline","result_status").forEach { json.put(it,JSONObject.NULL) }
    }
    private fun read(json:JSONObject)=NemesisReadProtocol.detail(json.toString().toByteArray(),id)
    private fun receipt(command:NemesisCommand,json:JSONObject)=command.receipt(json.toString().toByteArray())
    private fun attempt(command:NemesisCommand)=NemesisAttempt("22345678-1234-5678-9234-123456789abc",id,2,id,1,
        "32345678-1234-5678-9234-123456789abc",1,command)
    @Test fun typedCommandsHaveExactPathsBodiesAndSeparateScopes() {
        assertNull(NemesisCommand.issue().body());assertNull(NemesisCommand.revoke().body());assertEquals("DELETE",NemesisCommand.revoke().method)
        assertEquals("/me/nemesis/share-code",NemesisCommand.issue().path())
        val create=NemesisCommand.create(code,NemesisTerms(30,ZoneId.of("Europe/Warsaw"),false,false))
        val body=JSONObject(String(create.body()!!));assertEquals(setOf("destination_code","terms"),body.keys().asSequence().toSet())
        assertEquals(code,body.getString("destination_code"));assertFalse(body.getJSONObject("terms").getJSONObject("scope").getBoolean("weight_change"))
        val accept=NemesisCommand.accept(read(invited()));assertEquals("/nemesis/$id/accept",accept.path());assertEquals(1,accept.baseRevision)
        assertEquals(setOf("terms"),JSONObject(String(accept.body()!!)).keys().asSequence().toSet())
        assertThrows(Exception::class.java) { NemesisCommand.create(code,NemesisTerms(10,ZoneId.of("UTC"),false,false)) }
    }
    @Test fun journalRoundTripPreservesExactBytesKeyContextAndRedactsSecrets() {
        for(command in listOf(NemesisCommand.issue(),NemesisCommand.revoke(),NemesisCommand.create(code,terms),NemesisCommand.accept(read(invited())),NemesisCommand.cancel(read(metadata())))) {
            val value=attempt(command);val restored=NemesisAttempt.restore(JSONObject(value.journal().toString()))
            assertEquals(value.key,restored.key);assertEquals(value.epoch,restored.epoch);assertEquals(value.command.path(),restored.command.path())
            assertEquals(value.command.baseRevision,restored.command.baseRevision);assertArrayEquals(value.command.body(),restored.command.body())
            assertFalse(value.toString().contains(code));assertFalse(command.toString().contains(id))
        }
        assertThrows(Exception::class.java) { NemesisAttempt.restore(attempt(NemesisCommand.issue()).journal().put("leaseGeneration",0)) }
        assertThrows(Exception::class.java) { NemesisAttempt.restore(attempt(NemesisCommand.issue()).journal().put("key","bad")) }
        assertThrows(Exception::class.java) { NemesisCommand.restore(NemesisCommand.issue().journal().put("body","{}")) }
    }
    @Test fun canonicalCodeReceiptHasAtMost24HoursAndNoUnknownAuthority() {
        val value=JSONObject().put("destination_code",code).put("issued_at","2026-10-13T00:00:00Z").put("expires_at","2026-10-14T00:00:00Z")
        assertEquals(code,receipt(NemesisCommand.issue(),value)!!.value)
        assertThrows(Exception::class.java) { receipt(NemesisCommand.issue(),JSONObject(value.toString()).put("expires_at","2026-10-14T00:00:01Z")) }
        assertThrows(Exception::class.java) { receipt(NemesisCommand.issue(),JSONObject(value.toString()).put("active",true)) }
        assertThrows(Exception::class.java) { NemesisCommand.validateCode("A".repeat(42)+"B") }
        assertThrows(Exception::class.java) { NemesisCommand.validateCode(code+"=") }
        assertNull(receipt(NemesisCommand.revoke(),JSONObject().put("revoked",true)))
        assertThrows(Exception::class.java) { receipt(NemesisCommand.revoke(),JSONObject().put("revoked","true")) }
    }
    @Test fun replayedCurrentMetadataCanAlreadyBeCancelledWithoutRegrantingSharing() {
        val cancelled=metadata().put("revision",4).put("status","cancelled").put("cancel_reason","sharing_revoked")
        assertNull(receipt(NemesisCommand.accept(read(invited())),cancelled))
        assertNull(receipt(NemesisCommand.create(code,terms),JSONObject(cancelled.toString()).put("role","inviter")))
        assertNull(receipt(NemesisCommand.cancel(read(metadata())),cancelled))
        assertThrows(Exception::class.java) { receipt(NemesisCommand.accept(read(invited())),metadata().put("revision",1)) }
        assertThrows(Exception::class.java) { receipt(NemesisCommand.accept(read(invited())),invited().put("revision",2)) }
    }
    @Test fun cancelReasonsAndTargetsAreBoundToRoleAndLifecycleRevision() {
        assertEquals("withdrawn",JSONObject(String(NemesisCommand.cancel(read(invited("inviter"))).body()!!)).getString("reason"))
        assertEquals("declined",JSONObject(String(NemesisCommand.cancel(read(invited())).body()!!)).getString("reason"))
        assertEquals("sharing_revoked",JSONObject(String(NemesisCommand.cancel(read(metadata())).body()!!)).getString("reason"))
        val wrong=NemesisCommand.cancel(read(invited("inviter"))).journal().put("body","{\"reason\":\"declined\"}")
        assertThrows(Exception::class.java) { NemesisCommand.restore(wrong) }
        val cancel=NemesisCommand.cancel(read(metadata()))
        assertThrows(Exception::class.java) { receipt(cancel,metadata().put("id","42345678-1234-5678-9234-123456789abc").put("status","cancelled").put("cancel_reason","sharing_revoked").put("revision",2)) }
        assertThrows(Exception::class.java) { NemesisCommand.cancel(read(metadata().put("revision",Int.MAX_VALUE))) }
    }
    @Test fun receiptsMustMatchImmutableTermsAndRemainBoundedStrictJson() {
        val accept=NemesisCommand.accept(read(invited()));val value=metadata().put("revision",2)
        value.getJSONObject("terms").getJSONObject("scope").put("mean_deficit",false)
        assertThrows(Exception::class.java) { receipt(accept,value) }
        assertThrows(Exception::class.java) { accept.receipt(ByteArray(NemesisReadProtocol.MAX_BYTES+1)) }
        assertThrows(Exception::class.java) { accept.receipt(byteArrayOf(0xc3.toByte(),0x28)) }
    }
}
