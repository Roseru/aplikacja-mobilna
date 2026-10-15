package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson

class PhotoAnalysisProtocolTest {
    private val key = "12345678-1234-5678-9234-123456789abc"
    private val epoch = "22345678-1234-5678-9234-123456789abc"
    private val id = "c7777777-7777-4777-8777-777777777777"
    private val jpeg = byteArrayOf(0xff.toByte(),0xd8.toByte(),0xff.toByte(),0x00,0x01,0x7f)
    private fun caps(available: Boolean = true, provider: String = "mock", limit: Int = 5_242_880) =
        PhotoCapabilitiesRead(provider,"mock-food-v1","food-photo-notice-v1",available,if(available)null else "offline",limit,10)
    private fun request(image: ByteArray = jpeg) = PhotoHttpRequest.Create.prepare(key,epoch,caps(),true,image,"image/jpeg")
    private fun ack() = JSONObject(checkNotNull(javaClass.getResource("/photo/create-accepted.json")).readText())
    private fun bad(value: JSONObject) { assertThrows(Exception::class.java) { PhotoAnalysisProtocol.create(value.toString().toByteArray(),request()) } }

    @Test fun multipartContainsExactlyTypedMetadataAndOriginalImageWithoutUserFilename() {
        val request = request(); val boundary = request.contentType!!.substringAfter("boundary=")
        val wire = String(request.body(),Charsets.ISO_8859_1)
        val parts = wire.split("--$boundary")
        assertEquals(4,parts.size);assertEquals("",parts[0]);assertEquals("--\r\n",parts[3])
        assertTrue(parts[1].startsWith("\r\nContent-Disposition: form-data; name=\"metadata\"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"))
        val metadata = StrictJson.read(parts[1].substringAfter("\r\n\r\n").removeSuffix("\r\n").toByteArray())
        assertEquals(setOf("consent"),metadata.keys().asSequence().toSet())
        val consent = metadata.getJSONObject("consent")
        assertEquals(setOf("accepted","notice_version","provider","scope"),consent.keys().asSequence().toSet())
        assertEquals(true,consent.get("accepted"));assertEquals("mock",consent.get("provider"));assertEquals("this_photo",consent.get("scope"))
        assertEquals("food-photo-notice-v1",consent.get("notice_version"))
        assertTrue(parts[2].contains("filename=\"photo.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n"))
        assertArrayEquals(jpeg,parts[2].substringAfter("\r\n\r\n").removeSuffix("\r\n").toByteArray(Charsets.ISO_8859_1))
    }
    @Test fun preparedBytesRemainStableAfterCallerMutationAndReturnedBufferMutation() {
        val image=jpeg.copyOf();val prepared=request(image);val expected=prepared.body()
        image.fill(0);prepared.body().fill(0)
        assertArrayEquals(expected,prepared.body());assertArrayEquals(expected,prepared.body())
        assertEquals("PhotoHttpRequest(redacted)",prepared.toString())
    }
    @Test fun noImplicitConsentUnknownNoticeUnavailableAndInvalidContextCannotPrepareUpload() {
        assertThrows(Exception::class.java) { PhotoHttpRequest.Create.prepare(key,epoch,caps(),false,jpeg,"image/jpeg") }
        assertThrows(Exception::class.java) { PhotoHttpRequest.Create.prepare(key,epoch,caps(false),true,jpeg,"image/jpeg") }
        assertThrows(Exception::class.java) { PhotoHttpRequest.Create.prepare(key,epoch,caps(provider="other"),true,jpeg,"image/jpeg") }
        assertThrows(Exception::class.java) { PhotoHttpRequest.Create.prepare(key,epoch,caps().copy(noticeVersion="v2"),true,jpeg,"image/jpeg") }
        for(value in listOf("",key.uppercase(),"$key\r\nInjected: yes")) {
            assertThrows(Exception::class.java) { PhotoHttpRequest.Create.prepare(value,epoch,caps(),true,jpeg,"image/jpeg") }
            assertThrows(Exception::class.java) { PhotoHttpRequest.Create.prepare(key,value,caps(),true,jpeg,"image/jpeg") }
        }
    }
    @Test fun sizesSignaturesMimeAndBoundaryInjectionAreRejectedBeforeTransport() {
        assertThrows(Exception::class.java) { request(byteArrayOf()) }
        assertThrows(Exception::class.java) { PhotoHttpRequest.Create.prepare(key,epoch,caps(limit=5),true,jpeg,"image/jpeg") }
        val large=ByteArray(5_242_881);jpeg.copyInto(large)
        assertThrows(Exception::class.java) { request(large) }
        for(mime in listOf("image/png","image/webp","image/jpeg\r\nX: injected","text/plain"))
            assertThrows(Exception::class.java) { PhotoHttpRequest.Create.prepare(key,epoch,caps(),true,jpeg,mime) }
        assertThrows(Exception::class.java) { request(jpeg+"\r\n--calorie-photo-$key\r\nInjected: yes".toByteArray()) }
        val max=ByteArray(5_242_880);jpeg.copyInto(max)
        assertTrue(request(max).body().size < 6_291_456)
    }
    @Test fun pngAndWebpUseMatchingTypesWhileBytesAreNeverRecoded() {
        val images=listOf("image/png" to byteArrayOf(0x89.toByte(),0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a),"image/webp" to "RIFF0000WEBP".toByteArray())
        for((mime,image) in images) {
            val request=PhotoHttpRequest.Create.prepare(key,epoch,caps(),true,image,mime)
            val body=String(request.body(),Charsets.ISO_8859_1)
            assertTrue(body.contains("Content-Type: $mime\r\n"));assertTrue(body.contains(String(image,Charsets.ISO_8859_1)))
        }
    }
    @Test fun parsesNormativeCreateReceiptWithoutTreatingReplayQueuedAsCurrentState() {
        val receipt=PhotoAnalysisProtocol.create(ack().toString().toByteArray(),request())
        assertEquals(id,receipt.analysisId);assertEquals(1L,receipt.revision);assertEquals("queued",receipt.state)
        assertEquals("mock",receipt.profile.provider);assertEquals("valid",receipt.profile.mockScenario)
        assertEquals("PhotoCreateReceipt(redacted)",receipt.toString())
        assertEquals("PhotoAnalysisProfile(redacted)",receipt.profile.toString())
    }
    @Test fun createRejectsMalformedRevisionProfileAndTimestampInsteadOfCoercing() {
        for(value in listOf<Any>("1",1.5,0,2_147_483_648L,true)) bad(ack().put("revision",value))
        bad(ack().put("analysis_id",id.uppercase()));bad(ack().put("state","done"));bad(ack().put("owner","A"))
        for(time in listOf("2026-10-11T17:00:00+00:00","2026-02-30T17:00:00Z","2026-10-11T17:00:00.1234567Z","2026-10-11T17:00:60Z")) bad(ack().put("queue_deadline",time))
        val provider=ack();provider.getJSONObject("profile").put("provider","gemini");bad(provider)
        val missing=ack();missing.getJSONObject("profile").remove("mock_scenario");bad(missing)
        val extra=ack();extra.getJSONObject("profile").put("key","unexpected");bad(extra)
    }
    @Test fun duplicateKeysInvalidUtf8AndOversizedCreateAckAreRejected() {
        for(body in listOf((ack().toString().dropLast(1)+",\"revision\":1}").toByteArray(),byteArrayOf(0xc3.toByte(),0x28),ByteArray(65_537)))
            assertThrows(Exception::class.java) { PhotoAnalysisProtocol.create(body,request()) }
    }
    @Test fun cancelCarriesOnlyExpectedRevisionAndValidatesItsOwnAnalysisAck() {
        val cancel=PhotoHttpRequest.Cancel(key,epoch,id,4)
        assertEquals("/ai/food-analyses/$id/cancel",cancel.path)
        assertEquals("{\"expected_revision\":4}",cancel.body().toString(Charsets.UTF_8))
        val ack=JSONObject().put("analysis_id",id).put("revision",5).put("state","failed").put("decision_state","cancelled").put("error_code","analysis_cancelled")
        assertEquals(5L,PhotoAnalysisProtocol.cancelled(ack.toString().toByteArray(),id,4))
        for(change in listOf(ack.toString().replace(id,key),ack.toString().replace("cancelled","confirmed"),ack.put("revision",3).toString()))
            assertThrows(Exception::class.java) { PhotoAnalysisProtocol.cancelled(change.toByteArray(),id,4) }
        assertThrows(Exception::class.java) { PhotoHttpRequest.Cancel(key,epoch,id,0) }
        assertThrows(Exception::class.java) { PhotoHttpRequest.Read("$id/../other") }
    }
}
