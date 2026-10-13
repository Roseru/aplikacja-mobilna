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

class NemesisHttpTest {
    private val id = "12345678-1234-5678-9234-123456789abc"
    private val epoch = "22345678-1234-5678-9234-123456789abc"
    private fun session() = ApiSession(SessionIdentity("https://id.example/realm", "A"), OwnerLease(id, 1), "fixture-access", "fixture-state", 1)
    private class Connection(val status: Int = 200, val body: ByteArray = "{}".toByteArray(), val cache: String? = "no-store", val encoding: String? = null) : HttpsURLConnection(URL("https://api.example/api/v1/me/nemesis")) {
        var touched = false; var read = false; var disconnected = false
        override fun getResponseCode(): Int { touched = true; return status }
        override fun getInputStream() = ByteArrayInputStream(body).also { read = true }
        override fun getErrorStream() = inputStream
        override fun getOutputStream() = error("GET must not write")
        override fun getContentType() = "application/json"
        override fun getContentLengthLong() = -1L
        override fun getHeaderField(name: String?) = when (name) { "Cache-Control" -> cache; "Content-Encoding" -> encoding; "Retry-After" -> "120"; else -> null }
        override fun connect() { touched = true }; override fun disconnect() { disconnected = true }
        override fun usingProxy() = false; override fun getCipherSuite() = "fixture-only"
        override fun getLocalCertificates(): Array<Certificate>? = null
        override fun getServerCertificates(): Array<Certificate> = emptyArray()
    }
    @Test fun pathsAndEpochAreTypedAndNeverIncludeParticipantIdentityOrMutationAuthority() = runBlocking<Unit> {
        for (query in listOf(NemesisQuery.Listing(), NemesisQuery.Listing(id), NemesisQuery.Detail(id), NemesisQuery.Statistics(id))) {
            val connection = Connection()
            HttpsNemesisGateway("https://api.example/api/v1/") { url -> assertEquals("https://api.example/api/v1" + query.path(), url.toString()); connection }
                .get(session(), epoch, query) { assertFalse(connection.touched) }
            assertEquals("GET", connection.requestMethod); assertFalse(connection.doOutput); assertEquals(epoch, connection.getRequestProperty("X-Sync-Epoch"))
            assertEquals("Bearer fixture-access", connection.getRequestProperty("Authorization")); assertEquals("no-store", connection.getRequestProperty("Cache-Control"))
            for (header in listOf("If-Match", "Idempotency-Key", "X-Ranking-Consent-Epoch")) assertNull(connection.getRequestProperty(header))
            assertFalse(connection.useCaches); assertFalse(connection.instanceFollowRedirects); assertTrue(connection.disconnected)
        }
        assertThrows(Exception::class.java) { runBlocking { HttpsNemesisGateway("https://api.example/api/v1") { error("Invalid epoch must not open a connection") }.get(session(), "bad", NemesisQuery.Listing()) {} } }
    }
    @Test fun staleFenceRedirectCompressedAndCacheableSuccessOrPrivateErrorAreRejected() {
        for ((connection, stop) in listOf(Connection() to true, Connection(302) to false, Connection(cache = null) to false,
            Connection(404, cache = "max-age=30") to false, Connection(encoding = "gzip") to false)) {
            assertThrows(Exception::class.java) { runBlocking { HttpsNemesisGateway("https://api.example/api/v1") { connection }.get(session(), epoch, NemesisQuery.Detail(id)) { if (stop) error("stale") } } }
            assertFalse(connection.read); assertTrue(connection.disconnected)
        }
    }
    @Test fun responseBoundsAreOneMiBAndErrorBoundsRemainSmall() {
        for (connection in listOf(Connection(body = ByteArray(NemesisReadProtocol.MAX_BYTES + 1)), Connection(404, body = ByteArray(65_537)))) {
            assertThrows(Exception::class.java) { runBlocking { HttpsNemesisGateway("https://api.example/api/v1") { connection }.get(session(), epoch, NemesisQuery.Statistics(id)) {} } }
            assertTrue(connection.disconnected)
        }
    }
    @Test fun overloadHonoursDelayWithoutReadingProxyTextOrRepeating() = runBlocking<Unit> {
        val connection = Connection(503, "private proxy text".toByteArray(), cache = null)
        val result = HttpsNemesisGateway("https://api.example/api/v1") { connection }.get(session(), epoch, NemesisQuery.Listing()) {}
        assertEquals(503, result.status); assertEquals("120", result.retryAfter); assertTrue(result.body.isEmpty()); assertFalse(connection.read)
    }
}
