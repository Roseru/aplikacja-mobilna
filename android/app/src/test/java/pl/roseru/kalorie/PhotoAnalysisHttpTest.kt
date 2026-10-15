package pl.roseru.kalorie

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.session.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.URL
import java.security.cert.Certificate
import javax.net.ssl.HttpsURLConnection

class PhotoAnalysisHttpTest {
    private val id="12345678-1234-5678-9234-123456789abc"
    private val epoch="22345678-1234-5678-9234-123456789abc"
    private fun session(token:String="fixture-access")=ApiSession(SessionIdentity("https://id.example/realm","A"),OwnerLease(id,1),token,"fixture-state",1)
    private fun request()=PhotoHttpRequest.Create.prepare(id,epoch,PhotoCapabilitiesRead("mock","mock-food-v1","food-photo-notice-v1",true,null,5_242_880,10),true,
        byteArrayOf(0xff.toByte(),0xd8.toByte(),0xff.toByte())+ByteArray(10_000),"image/jpeg")
    private class Connection(val status:Int=202,val cache:String?="no-store",val payload:ByteArray="{}".toByteArray(),val type:String="application/json",val encoding:String?=null,val lostAck:Boolean=false):
        HttpsURLConnection(URL("https://api.example/api/v1/ai/food-analyses")) {
        val sent=ByteArrayOutputStream();var touched=false;var read=false;var closed=false;var length=0;var writes=0
        var onWrite:(()->Unit)?=null
        override fun setFixedLengthStreamingMode(value:Int){length=value}
        override fun getOutputStream()=object:java.io.OutputStream(){
            override fun write(value:Int){sent.write(value)}
            override fun write(bytes:ByteArray,offset:Int,count:Int){writes++;sent.write(bytes,offset,count);onWrite?.invoke()}
        }.also {touched=true}
        override fun getResponseCode():Int {touched=true;if(lostAck) throw IOException("fixture lost ACK");return status}
        override fun getInputStream()=ByteArrayInputStream(payload).also {read=true}
        override fun getErrorStream()=inputStream
        override fun getContentType()=type
        override fun getContentLengthLong()=payload.size.toLong()
        override fun getHeaderField(name:String?)=when(name){"Cache-Control"->cache;"Retry-After"->"120";"Content-Encoding"->encoding;else->null}
        override fun connect(){touched=true};override fun disconnect(){closed=true};override fun usingProxy()=false
        override fun getCipherSuite()="fixture-only";override fun getLocalCertificates():Array<Certificate>?=null;override fun getServerCertificates():Array<Certificate> = emptyArray()
    }
    @Test fun uploadUsesOneBoundedMultipartFixedLengthAndCapturedKeyEpochWithNoRedirectOrCache()=runBlocking<Unit> {
        val request=request();val connection=Connection();var calls=0
        val result=HttpsPhotoAnalysisGateway("https://api.example/api/v1/"){url->calls++;assertEquals("/api/v1/ai/food-analyses",url.path);assertNull(url.query);connection}
            .send(session(),request){assertFalse(connection.touched)}
        assertEquals(202,result.status);assertEquals(1,calls);assertEquals("POST",connection.requestMethod)
        assertEquals(id,connection.getRequestProperty("Idempotency-Key"));assertEquals(epoch,connection.getRequestProperty("X-Sync-Epoch"))
        assertEquals("Bearer fixture-access",connection.getRequestProperty("Authorization"));assertEquals(request.contentType,connection.getRequestProperty("Content-Type"))
        assertEquals("identity",connection.getRequestProperty("Accept-Encoding"));assertNull(connection.getRequestProperty("If-Match"))
        assertEquals(request.body().size,connection.length);assertArrayEquals(request.body(),connection.sent.toByteArray())
        assertTrue(connection.writes>1);assertTrue(connection.closed);assertFalse(connection.useCaches);assertFalse(connection.instanceFollowRedirects)
    }
    @Test fun staleOwnerOrCancelledOperationCannotWriteAndAlwaysDisconnects() {
        for(cancel in listOf(false,true)) {
            val connection=Connection()
            assertThrows(Exception::class.java){runBlocking {HttpsPhotoAnalysisGateway("https://api.example/api/v1"){connection}.send(session(),request()) {
                if(cancel) throw CancellationException("fixture cancel") else error("fixture stale owner")
            }}}
            assertFalse(connection.touched);assertEquals(0,connection.sent.size());assertTrue(connection.closed)
        }
    }
    @Test fun cancellationBetweenChunksStopsUploadRatherThanFinishingOrRetrying()=runBlocking<Unit> {
        val job=Job();val connection=Connection();connection.onWrite={job.cancel()}
        try { withContext(job) {HttpsPhotoAnalysisGateway("https://api.example/api/v1"){connection}.send(session(),request()) {}};fail() }
        catch(_:CancellationException){}
        assertEquals(1,connection.writes);assertEquals(4096,connection.sent.size());assertTrue(connection.closed);assertFalse(connection.read)
    }
    @Test fun lostAckDoesNotAutomaticallyRepeatAndExplicitSameRequestKeepsExactBytes()=runBlocking<Unit> {
        val request=request();val first=Connection(lostAck=true);var calls=0
        assertThrows(IOException::class.java){runBlocking {HttpsPhotoAnalysisGateway("https://api.example/api/v1"){calls++;first}.send(session(),request){}}}
        assertEquals(1,calls);assertTrue(first.closed)
        val retry=Connection();HttpsPhotoAnalysisGateway("https://api.example/api/v1"){retry}.send(session(),request){}
        assertArrayEquals(first.sent.toByteArray(),retry.sent.toByteArray())
        assertEquals(first.getRequestProperty("Idempotency-Key"),retry.getRequestProperty("Idempotency-Key"))
    }
    @Test fun readAndCancelHaveFixedOwnPathsAndOnlyCancelCarriesMutationHeaders()=runBlocking<Unit> {
        for(request in listOf(PhotoHttpRequest.Read(id),PhotoHttpRequest.Cancel(id,epoch,id,2))) {
            val connection=Connection(200)
            HttpsPhotoAnalysisGateway("https://api.example/api/v1"){url->assertEquals("/api/v1"+request.path,url.path);connection}.send(session(),request){}
            assertEquals(request.method,connection.requestMethod);assertEquals(request.key,connection.getRequestProperty("Idempotency-Key"))
            assertEquals(request.epoch,connection.getRequestProperty("X-Sync-Epoch"))
            assertArrayEquals(request.body()?:byteArrayOf(),connection.sent.toByteArray())
            assertEquals(request.body()!=null,connection.doOutput);assertTrue(connection.closed)
        }
    }
    @Test fun redirectsPrivateCacheCompressedHtmlAndOversizeResponsesCannotReachDecoder() {
        for(connection in listOf(Connection(307),Connection(cache=null),Connection(409,cache=null),Connection(type="text/html"),Connection(encoding="gzip"),Connection(payload=ByteArray(1_048_577)))) {
            assertThrows(Exception::class.java){runBlocking {HttpsPhotoAnalysisGateway("https://api.example/api/v1"){connection}.send(session(),request()){}}}
            assertFalse(connection.read);assertTrue(connection.closed)
        }
    }
    @Test fun overloadHonoursDelayWithoutReadingProxyHtmlAndUntrustedConfigurationCannotSend()=runBlocking<Unit> {
        val connection=Connection(503,null,type="text/html")
        val result=HttpsPhotoAnalysisGateway("https://api.example/api/v1"){connection}.send(session(),request()){}
        assertEquals("120",result.retryAfter);assertTrue(result.body.isEmpty());assertFalse(connection.read);assertTrue(connection.closed)
        for(base in listOf("http://api.example/api/v1","https://api.example/api/v1?x=1","https://api.example/api/v1/../other"))
            assertThrows(Exception::class.java){HttpsPhotoAnalysisGateway(base)}
        var opened=false
        assertThrows(Exception::class.java){runBlocking {HttpsPhotoAnalysisGateway("https://api.example/api/v1"){opened=true;Connection()}.send(session("bad\r\nInjected: yes"),request()){}}}
        assertFalse(opened)
    }
}
