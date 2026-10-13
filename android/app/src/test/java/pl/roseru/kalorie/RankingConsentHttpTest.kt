package pl.roseru.kalorie

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.session.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.net.URL
import java.security.cert.Certificate
import javax.net.ssl.HttpsURLConnection

class RankingConsentHttpTest {
    private val epoch = "e1111111-1111-4111-8111-111111111111"
    private val scope = "b1111111-1111-4111-8111-111111111111"
    private fun request(enabled: Boolean = true) = RankingConsentAttempt("a1111111-1111-4111-8111-111111111111", scope, 1,
        "c1111111-1111-4111-8111-111111111111", 1, epoch, 1, 7, enabled, true, if (enabled) epoch else null)
    private fun session() = ApiSession(SessionIdentity("https://id.example/realm", "A"), OwnerLease(scope, 1), "fixture-access", "fixture-state", 1)
    private class Connection(val status: Int = 200, val payload: ByteArray = "{}".toByteArray(), val cache: String? = "no-store",
        val declared: Long = payload.size.toLong(), val type: String = "application/json", val encoding: String? = null) : HttpsURLConnection(URL("https://api.example/api/v1/me/consents")) {
        val written = ByteArrayOutputStream()
        var touched = false
        var read = false
        var disconnected = false
        override fun getOutputStream() = written.also { touched = true }
        override fun getResponseCode(): Int { touched = true; return status }
        override fun getInputStream() = ByteArrayInputStream(payload).also { read = true }
        override fun getErrorStream() = inputStream
        override fun getContentType() = type
        override fun getContentLengthLong() = declared
        override fun getHeaderField(name: String?) = when (name) { "Cache-Control" -> cache; "Retry-After" -> "60"; "ETag" -> "\"8\""; "Content-Encoding" -> encoding; else -> null }
        override fun connect() { touched = true }
        override fun disconnect() { disconnected = true }
        override fun usingProxy() = false
        override fun getCipherSuite() = "fixture-only"
        override fun getLocalCertificates(): Array<Certificate>? = null
        override fun getServerCertificates(): Array<Certificate> = emptyArray()
    }
    @Test fun exactPutHeadersAndBodyAreFencedBeforeTheFirstNetworkWrite() = runBlocking<Unit> {
        for (enabled in listOf(true, false)) {
            val conn = Connection()
            val req = request(enabled)
            val result = HttpsRankingConsentGateway("https://api.example/api/v1") { url -> assertNull(url.query); assertEquals(conn.url, url); conn }
                .put(session(), req) { assertFalse(conn.touched); assertEquals(0, conn.written.size()) }
            assertEquals("PUT", conn.requestMethod); assertTrue(conn.doOutput)
            assertEquals(req.key, conn.getRequestProperty("Idempotency-Key")); assertEquals("\"7\"", conn.getRequestProperty("If-Match"))
            assertEquals(if (enabled) epoch else null, conn.getRequestProperty("X-Ranking-Consent-Epoch"))
            assertNull(conn.getRequestProperty("X-Sync-Epoch")); assertEquals("Bearer fixture-access", conn.getRequestProperty("Authorization"))
            assertEquals("no-store", conn.getRequestProperty("Cache-Control")); assertFalse(conn.useCaches); assertFalse(conn.instanceFollowRedirects)
            assertArrayEquals(req.body(), conn.written.toByteArray()); assertEquals("\"8\"", result.etag); assertTrue(conn.disconnected)
        }
    }
    @Test fun staleFencePreventsWritingAndRedirectCannotResubmitConsent() {
        val stopped = Connection()
        assertThrows(Exception::class.java) { runBlocking { HttpsRankingConsentGateway("https://api.example/api/v1") { stopped }.put(session(), request()) { error("stale") } } }
        assertFalse(stopped.touched); assertEquals(0, stopped.written.size()); assertTrue(stopped.disconnected)
        val redirect = Connection(status = 307)
        assertThrows(Exception::class.java) { runBlocking { HttpsRankingConsentGateway("https://api.example/api/v1") { redirect }.put(session(), request()) {} } }
        assertFalse(redirect.instanceFollowRedirects); assertFalse(redirect.read); assertTrue(redirect.disconnected)
    }
    @Test fun successRequiresNoStoreBoundedJsonAndNoCompression() {
        for (conn in listOf(Connection(cache = null), Connection(cache = "max-age=60"), Connection(payload = ByteArray(65_537), declared = -1),
            Connection(declared = 65_537), Connection(type = "text/html"), Connection(encoding = "gzip"))) {
            assertThrows(Exception::class.java) { runBlocking { HttpsRankingConsentGateway("https://api.example/api/v1") { conn }.put(session(), request()) {} } }
            assertTrue(conn.disconnected)
        }
    }
    @Test fun proxyOverloadDoesNotReadHtmlOrRetryOnItsOwn() = runBlocking<Unit> {
        val conn = Connection(status = 503, payload = "private proxy text".toByteArray(), type = "text/html", cache = null)
        val result = HttpsRankingConsentGateway("https://api.example/api/v1") { conn }.put(session(), request()) {}
        assertEquals(503, result.status); assertEquals("60", result.retryAfter); assertEquals(0, result.body.size)
        assertFalse(conn.read); assertTrue(conn.disconnected); assertFalse(result.toString().contains("private"))
    }
}
