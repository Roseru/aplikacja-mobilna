package pl.roseru.kalorie

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.session.*
import java.io.ByteArrayInputStream
import java.net.URL
import java.security.cert.Certificate
import javax.net.ssl.HttpsURLConnection

class RankingHttpTest {
    private val token = "rk1." + "A".repeat(43)
    private fun session() = ApiSession(SessionIdentity("https://id.example/realm", "A"), OwnerLease("b1111111-1111-4111-8111-111111111111", 1), "fixture-access", "fixture-state", 1)
    private class Connection(val status: Int = 200, val payload: ByteArray = "{}".toByteArray(), val cache: String? = "no-store", val encoding: String? = null) : HttpsURLConnection(URL("https://api.example/api/v1/ranking")) {
        var touched = false; var read = false; var disconnected = false
        override fun getResponseCode(): Int { touched = true; return status }
        override fun getInputStream() = ByteArrayInputStream(payload).also { read = true }
        override fun getErrorStream() = inputStream
        override fun getOutputStream() = error("GET must never write")
        override fun getContentType() = "application/json"
        override fun getContentLengthLong() = -1L
        override fun getHeaderField(name: String?) = when (name) { "Cache-Control" -> cache; "Content-Encoding" -> encoding; "Retry-After" -> "600"; else -> null }
        override fun connect() { touched = true }; override fun disconnect() { disconnected = true }
        override fun usingProxy() = false; override fun getCipherSuite() = "fixture-only"
        override fun getLocalCertificates(): Array<Certificate>? = null
        override fun getServerCertificates(): Array<Certificate> = emptyArray()
    }
    @Test fun typedQueryCannotAddressOwnersOrSendConsentAndFencePrecedesNetwork() = runBlocking<Unit> {
        for (cursor in listOf(null, token)) {
            val connection = Connection()
            HttpsRankingGateway("https://api.example/api/v1/") { url ->
                assertEquals("/api/v1/ranking", url.path); assertEquals(RankingQuery(cursor).encoded(), url.query); connection
            }.get(session(), RankingQuery(cursor)) { assertFalse(connection.touched) }
            assertEquals("GET", connection.requestMethod); assertFalse(connection.doOutput)
            assertEquals("Bearer fixture-access", connection.getRequestProperty("Authorization")); assertEquals("no-store", connection.getRequestProperty("Cache-Control"))
            for (header in listOf("X-Sync-Epoch", "X-Ranking-Consent-Epoch", "If-Match", "Idempotency-Key")) assertNull(connection.getRequestProperty(header))
            assertFalse(connection.useCaches); assertFalse(connection.instanceFollowRedirects); assertTrue(connection.disconnected)
        }
    }
    @Test fun staleFenceAndRedirectDoNotReadAnotherRanking() {
        for ((connection, stopped) in listOf(Connection() to true, Connection(302) to false)) {
            assertThrows(Exception::class.java) { runBlocking { HttpsRankingGateway("https://api.example/api/v1") { connection }.get(session(), RankingQuery()) { if (stopped) error("stale") } } }
            if (stopped) assertFalse(connection.touched)
            assertFalse(connection.read); assertTrue(connection.disconnected)
        }
    }
    @Test fun successMustBeBoundedUncompressedAndNoStore() {
        for (connection in listOf(Connection(cache = null), Connection(cache = "max-age=30"), Connection(encoding = "gzip"), Connection(payload = ByteArray(65_537)))) {
            assertThrows(Exception::class.java) { runBlocking { HttpsRankingGateway("https://api.example/api/v1") { connection }.get(session(), RankingQuery()) {} } }
            assertTrue(connection.disconnected)
        }
    }
    @Test fun overloadDoesNotReadProxyBodyOrRepeatOnItsOwn() = runBlocking<Unit> {
        val connection = Connection(429, "private proxy text".toByteArray(), cache = null)
        val result = HttpsRankingGateway("https://api.example/api/v1") { connection }.get(session(), RankingQuery(token)) {}
        assertEquals(429, result.status); assertEquals("600", result.retryAfter); assertTrue(result.body.isEmpty()); assertFalse(connection.read)
    }
}
