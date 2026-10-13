package pl.roseru.kalorie

import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.session.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.net.URL
import java.security.cert.Certificate
import java.time.ZoneId
import javax.net.ssl.HttpsURLConnection

class NemesisMutationHttpTest {
    private val id="12345678-1234-5678-9234-123456789abc"
    private val epoch="22345678-1234-5678-9234-123456789abc"
    private fun session()=ApiSession(SessionIdentity("https://id.example/realm","A"),OwnerLease(id,1),"fixture-access","fixture-state",1)
    private fun attempt(command:NemesisCommand)=NemesisAttempt(id,id,1,id,1,epoch,1,command)
    private fun challenge():NemesisChallenge {
        val value=JSONObject(checkNotNull(javaClass.getResource("/nemesis/metadata.json")).readText()).put("status","invited")
        listOf("accepted_at","start_date","end_date","start_at","end_at","deadline","result_status").forEach { value.put(it,JSONObject.NULL) }
        return NemesisReadProtocol.detail(value.toString().toByteArray(),id)
    }
    private class Connection(val status:Int=200,val cache:String?="no-store"):HttpsURLConnection(URL("https://api.example/api/v1/nemesis")) {
        val sent=ByteArrayOutputStream();var openedOutput=false;var touched=false;var read=false;var closed=false
        override fun getOutputStream()=sent.also {openedOutput=true;touched=true}
        override fun getResponseCode():Int {touched=true;return status}
        override fun getInputStream()=ByteArrayInputStream("{}".toByteArray()).also {read=true}
        override fun getErrorStream()=inputStream
        override fun getContentType()="application/json"
        override fun getContentLengthLong()=-1L
        override fun getHeaderField(name:String?)=when(name) {"Cache-Control"->cache;"Retry-After"->"120";else->null}
        override fun connect() {touched=true};override fun disconnect() {closed=true};override fun usingProxy()=false
        override fun getCipherSuite()="fixture-only";override fun getLocalCertificates():Array<Certificate>?=null;override fun getServerCertificates():Array<Certificate> = emptyArray()
    }
    @Test fun issueAndRevokeSendNoBodyAndTypedKeyEpochWithoutConsentHeaders()=runBlocking<Unit> {
        for(command in listOf(NemesisCommand.issue(),NemesisCommand.revoke())) {
            val request=attempt(command);val connection=Connection()
            HttpsNemesisWriteGateway("https://api.example/api/v1") { url->assertEquals("/api/v1/me/nemesis/share-code",url.path);assertNull(url.query);connection }
                .send(session(),request) {assertFalse(connection.touched)}
            assertEquals(command.method,connection.requestMethod);assertFalse(connection.doOutput);assertFalse(connection.openedOutput)
            assertEquals(id,connection.getRequestProperty("Idempotency-Key"));assertEquals(epoch,connection.getRequestProperty("X-Sync-Epoch"))
            assertNull(connection.getRequestProperty("If-Match"));assertNull(connection.getRequestProperty("Content-Type"));assertNull(connection.getRequestProperty("X-Ranking-Consent-Epoch"))
            assertTrue(connection.closed)
        }
    }
    @Test fun createAcceptCancelUseExactBodiesAndOnlyLifecycleIfMatch()=runBlocking<Unit> {
        for(command in listOf(NemesisCommand.create("A".repeat(43),NemesisTerms(7,ZoneId.of("Europe/Warsaw"),false,false)),NemesisCommand.accept(challenge()),NemesisCommand.cancel(challenge()))) {
            val request=attempt(command);val connection=Connection(command.successStatus)
            HttpsNemesisWriteGateway("https://api.example/api/v1/") { url->assertEquals("https://api.example/api/v1"+command.path(),url.toString());assertFalse(url.toString().contains("A".repeat(43)));connection }
                .send(session(),request) {assertFalse(connection.touched)}
            assertArrayEquals(command.body(),connection.sent.toByteArray());assertEquals(command.baseRevision?.let {"\"$it\""},connection.getRequestProperty("If-Match"))
            assertEquals(epoch,connection.getRequestProperty("X-Sync-Epoch"));assertFalse(connection.useCaches);assertFalse(connection.instanceFollowRedirects)
        }
    }
    @Test fun staleAuthorityCannotWriteABodyAndRedirectCannotReplay() {
        for((connection,stop) in listOf(Connection() to true,Connection(307) to false)) {
            assertThrows(Exception::class.java) {runBlocking {HttpsNemesisWriteGateway("https://api.example/api/v1") {connection}.send(session(),attempt(NemesisCommand.create("A".repeat(43),NemesisTerms(7,ZoneId.of("UTC"),false,false)))) {if(stop) error("stale")} }}
            if(stop) {assertFalse(connection.touched);assertFalse(connection.openedOutput)}
            assertFalse(connection.read);assertTrue(connection.closed)
        }
    }
    @Test fun success201AndErrorsNeedNoStoreWhileProxyDelayNeverReadsItsBody()=runBlocking<Unit> {
        for(status in listOf(200,201,409)) {
            val connection=Connection(status,cache=null)
            assertThrows(Exception::class.java) {runBlocking {HttpsNemesisWriteGateway("https://api.example/api/v1") {connection}.send(session(),attempt(NemesisCommand.issue())) {} }}
            assertFalse(connection.read)
        }
        val connection=Connection(503,cache=null);val result=HttpsNemesisWriteGateway("https://api.example/api/v1") {connection}.send(session(),attempt(NemesisCommand.issue())) {}
        assertEquals("120",result.retryAfter);assertTrue(result.body.isEmpty());assertFalse(connection.read)
    }
}
