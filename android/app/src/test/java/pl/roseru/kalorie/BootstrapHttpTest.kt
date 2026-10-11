package pl.roseru.kalorie

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.SessionIdentity
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.session.*
import java.io.ByteArrayInputStream
import java.net.URL
import java.security.cert.Certificate
import javax.net.ssl.HttpsURLConnection

/** Transport configuration fixtures, not proof of a real TLS handshake or backend deployment. */
class BootstrapHttpTest {
    private val key = "a1111111-1111-4111-8111-111111111111"
    private fun session(token: String = "fixture-access") = ApiSession(SessionIdentity("https://id.example/realm", "A"),
        OwnerLease("fixture-A", 1), token, "fixture-state", 1)
    private class Connection(url: URL, val status: Int = 200, val payload: ByteArray = "{}".toByteArray(),
        val type: String = "application/json", val declaredSize: Long = payload.size.toLong(),
        val encoding: String? = null) : HttpsURLConnection(url) {
        var disconnected = false
        var sent = false
        var readBody = false
        override fun disconnect() { disconnected = true }
        override fun usingProxy() = false
        override fun connect() { sent = true }
        override fun getResponseCode(): Int { sent = true; return status }
        override fun getContentType() = type
        override fun getContentLengthLong() = declaredSize
        override fun getHeaderField(name: String?) = when (name) { "Content-Encoding" -> encoding; "Retry-After" -> "60"; else -> null }
        override fun getInputStream(): ByteArrayInputStream { readBody = true; return ByteArrayInputStream(payload) }
        override fun getErrorStream() = inputStream
        override fun getOutputStream(): Nothing = error("A bootstrap request must not have a body")
        override fun getCipherSuite() = "fixture-only"
        override fun getLocalCertificates(): Array<Certificate>? = null
        override fun getServerCertificates(): Array<Certificate> = emptyArray()
    }
    @Test fun exactHttpsEndpointWithoutCredentialsQueryOrEncodedPath() {
        for (base in listOf("https://api.example/api/v1", "https://api.example:18443/api/v1/"))
            assertEquals(base.trimEnd('/') + "/me/bootstrap", BootstrapHttpProtocol.endpoint(base).toString())
        for (base in listOf("http://api.example/api/v1", "https://u:p@api.example/api/v1", "https://api.example/api/v1?q=1",
            "https://api.example/api/v1#fragment", "https://api.example/api/%76%31", "https://api.example/api/v1/../v1", "https://api.example/"))
            assertThrows(Exception::class.java) { BootstrapHttpProtocol.endpoint(base) }
    }
    @Test fun bodylessPostCapturesBearerAndDurableKeyWithoutRedirectCacheOrIfMatch() = runBlocking<Unit> {
        val connection = Connection(URL("https://api.example/api/v1/me/bootstrap"))
        var fenced = false
        val result = HttpsBootstrapGateway("https://api.example/api/v1") { connection }.post(session(), key) {
            assertFalse(connection.sent); fenced = true
        }
        assertTrue(fenced)
        assertEquals(200, result.status)
        assertEquals("POST", connection.requestMethod)
        assertFalse(connection.doOutput)
        assertFalse(connection.instanceFollowRedirects)
        assertFalse(connection.useCaches)
        assertEquals("Bearer fixture-access", connection.getRequestProperty("Authorization"))
        assertEquals(key, connection.getRequestProperty("Idempotency-Key"))
        assertNull(connection.getRequestProperty("If-Match"))
        assertNull(connection.getRequestProperty("X-Sync-Epoch"))
        assertEquals("no-store", connection.getRequestProperty("Cache-Control"))
        assertEquals("identity", connection.getRequestProperty("Accept-Encoding"))
        assertTrue(connection.disconnected)
        assertFalse(session().toString().contains("fixture-access"))
        assertFalse(result.toString().contains("{}"))
    }
    @Test fun staleLeasePreflightPreventsSendingAndAlwaysDisconnects() = runBlocking<Unit> {
        val connection = Connection(URL("https://api.example/api/v1/me/bootstrap"))
        assertThrows(IllegalStateException::class.java) { runBlocking {
            HttpsBootstrapGateway("https://api.example/api/v1") { connection }.post(session(), key) { error("stale") }
        } }
        assertFalse(connection.sent); assertTrue(connection.disconnected)
    }
    @Test fun rejectsRedirectHtmlCompressionAndOversizedResponseBeforeParsing() {
        for (connection in listOf(Connection(URL("https://api.example"), status = 302),
            Connection(URL("https://api.example"), type = "text/html"), Connection(URL("https://api.example"), encoding = "gzip"),
            Connection(URL("https://api.example"), declaredSize = 65_537),
            Connection(URL("https://api.example"), payload = ByteArray(65_537), declaredSize = -1))) {
            assertThrows(Exception::class.java) { runBlocking {
                HttpsBootstrapGateway("https://api.example/api/v1") { connection }.post(session(), key) {}
            } }
            assertTrue(connection.disconnected)
        }
        val atLimit = ByteArray(65_536)
        assertArrayEquals(atLimit, BootstrapHttpProtocol.read(ByteArrayInputStream(atLimit)))
    }
    @Test fun errorShapeRejectsDuplicateKeysAndNeverUsesFreeTextAsACode() {
        val error = """{"code":"unauthorized","message":"server text","details":[],"request_id":"$key"}"""
        assertEquals("unauthorized", BootstrapHttpProtocol.errorCode(error.toByteArray()))
        for (bad in listOf(error.replace("\"code\":\"unauthorized\"", "\"code\":\"unauthorized\",\"code\":\"sync_epoch_changed\""),
            error.replace("unauthorized", "invalid CODE"), error.replace("\"details\":[]", "\"details\":{},\"extra\":1"),
            error.replace(key, "not-a-uuid"), "{}"))
            assertThrows(Exception::class.java) { BootstrapHttpProtocol.errorCode(bad.toByteArray()) }
    }
    @Test fun retryAfterHonoursSecondsAndHttpDateWithoutShorteningLongDelay() {
        val now = java.time.Instant.parse("2026-10-11T10:00:00Z").toEpochMilli()
        assertEquals(60L, BootstrapHttpProtocol.retrySeconds("60", now))
        assertEquals(86400L, BootstrapHttpProtocol.retrySeconds("86400", now))
        assertEquals(60L, BootstrapHttpProtocol.retrySeconds("Sun, 11 Oct 2026 10:01:00 GMT", now))
        assertEquals(0L, BootstrapHttpProtocol.retrySeconds("Sun, 11 Oct 2026 09:59:59 GMT", now))
        for (invalid in listOf(null, "-1", "garbage", "9".repeat(128))) assertEquals(30L, BootstrapHttpProtocol.retrySeconds(invalid, now))
    }
    @Test fun headerInjectionAndNonUuidKeyAreRejectedBeforeOpeningConnection() {
        var opened = false
        val gateway = HttpsBootstrapGateway("https://api.example/api/v1") { opened = true; Connection(it) }
        for ((token, operation) in listOf("bad\r\nHeader:value" to key, "fixture-access" to "not-uuid"))
            assertThrows(Exception::class.java) { runBlocking { gateway.post(session(token), operation) {} } }
        assertFalse(opened)
    }
    @Test fun overloadedProxyDelayIsRespectedEvenWhenItsBodyIsNotJson() = runBlocking<Unit> {
        for (status in listOf(429, 503)) {
            val connection = Connection(URL("https://api.example"), status, "<html>private proxy error</html>".toByteArray(), "text/html")
            val result = HttpsBootstrapGateway("https://api.example/api/v1") { connection }.post(session(), key) {}
            assertEquals(status, result.status); assertEquals("60", result.retryAfter)
            assertTrue(result.body.isEmpty()); assertFalse(connection.readBody); assertTrue(connection.disconnected)
        }
    }
}
