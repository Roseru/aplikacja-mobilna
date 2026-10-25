package pl.roseru.kalorie

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.SessionIdentity
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.core.sync.*
import java.io.ByteArrayInputStream
import java.net.URL
import java.security.cert.Certificate
import javax.net.ssl.HttpsURLConnection

/** Transport configuration fixtures, not proof of a real TLS handshake or backend deployment. */
class BootstrapHttpTest {
    private fun snapshotQuery() = SnapshotProtocol(SyncWireSchema(SyncWireSchema.FILES.associateWith { file ->
        javaClass.getResourceAsStream("/sync/$file")!!.use { it.readBytes() }
    })).query("e1111111-1111-4111-8111-111111111111", snapshot = "snapshot+/?=&", page = "next")
    @Test fun snapshotGetEscapesTokensAndAcceptsBoundedLargerJsonWithoutExtraHeaders() = runBlocking {
        var requested: URL? = null
        val connection = Connection(URL("https://api.example"), payload = ByteArray(65_537) { ' '.code.toByte() }, cacheControl = "no-store")
        val result = HttpsSnapshotGateway("https://api.example/api/v1") { requested = it; connection }.get(session(), snapshotQuery()) {}
        assertEquals("/api/v1/sync/pull", requested!!.path)
        assertTrue(requested!!.query.contains("snapshot_token=snapshot%2B%2F%3F%3D%26"))
        assertEquals("GET", connection.requestMethod); assertNull(connection.getRequestProperty("Idempotency-Key"))
        assertNull(connection.getRequestProperty("X-Sync-Epoch")); assertEquals(65_537, result.body.size)
        assertTrue(connection.disconnected)
    }
    @Test fun snapshotPreflightAndResponseBoundsApplyAlsoToUnknownContentLength() {
        val stopped = Connection(URL("https://api.example"))
        assertThrows(Exception::class.java) { runBlocking { HttpsSnapshotGateway("https://api.example/api/v1") { stopped }.get(session(), snapshotQuery()) { error("stale") } } }
        assertFalse(stopped.sent); assertTrue(stopped.disconnected)
        val oversized = Connection(URL("https://api.example"), payload = ByteArray(SnapshotProtocol.MAX_BYTES + 1), declaredSize = -1, cacheControl = "no-store")
        assertThrows(Exception::class.java) { runBlocking { HttpsSnapshotGateway("https://api.example/api/v1") { oversized }.get(session(), snapshotQuery()) {} } }
        assertTrue(oversized.readBody)
        assertTrue(oversized.disconnected)
    }
    private val key = "a1111111-1111-4111-8111-111111111111"
    private fun session(token: String = "fixture-access") = ApiSession(SessionIdentity("https://id.example/realm", "A"),
        OwnerLease("fixture-A", 1), token, "fixture-state", 1)
    private class Connection(url: URL, val status: Int = 200, val payload: ByteArray = "{}".toByteArray(),
        val type: String = "application/json", val declaredSize: Long = payload.size.toLong(),
        val encoding: String? = null, val cacheControl: String? = null) : HttpsURLConnection(url) {
        var disconnected = false
        var sent = false
        var readBody = false
        override fun disconnect() { disconnected = true }
        override fun usingProxy() = false
        override fun connect() { sent = true }
        override fun getResponseCode(): Int { sent = true; return status }
        override fun getContentType() = type
        override fun getContentLengthLong() = declaredSize
        override fun getHeaderField(name: String?) = when (name) { "Content-Encoding" -> encoding; "Retry-After" -> "60"; "Cache-Control" -> cacheControl; else -> null }
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
    @Test fun profileReadUsesExactBodylessGetWithoutMutationHeaders() = runBlocking<Unit> {
        var requested: URL? = null
        val connection = Connection(URL("https://api.example/api/v1/me"))
        val result = HttpsProfileGateway("https://api.example/api/v1/") { requested = it; connection }.get(session()) {
            assertFalse(connection.sent)
        }
        assertEquals("https://api.example/api/v1/me", requested.toString())
        assertEquals("GET", connection.requestMethod)
        assertEquals("Bearer fixture-access", connection.getRequestProperty("Authorization"))
        assertNull(connection.getRequestProperty("Idempotency-Key"))
        assertNull(connection.getRequestProperty("If-Match"))
        assertNull(connection.getRequestProperty("X-Sync-Epoch"))
        assertFalse(connection.doOutput); assertFalse(connection.instanceFollowRedirects); assertFalse(connection.useCaches)
        assertEquals(200, result.status); assertTrue(connection.disconnected)
    }
    @Test fun profileGetCannotBypassPreflightResponseBoundsOrRedirectGuard() {
        val stopped = Connection(URL("https://api.example"))
        assertThrows(Exception::class.java) { runBlocking { HttpsProfileGateway("https://api.example/api/v1") { stopped }.get(session()) { error("stale") } } }
        assertFalse(stopped.sent); assertTrue(stopped.disconnected)
        for (connection in listOf(Connection(URL("https://api.example"), status = 307),
            Connection(URL("https://api.example"), payload = ByteArray(65_537), declaredSize = -1),
            Connection(URL("https://api.example"), type = "text/html"), Connection(URL("https://api.example"), encoding = "gzip"))) {
            assertThrows(Exception::class.java) { runBlocking { HttpsProfileGateway("https://api.example/api/v1") { connection }.get(session()) {} } }
            assertTrue(connection.disconnected)
        }
    }
    @Test fun motivationReadIsPrivateBodylessGetWithNoStoreAndNoMutationHeaders() = runBlocking<Unit> {
        var requested: URL? = null
        val connection = Connection(URL("https://api.example"), cacheControl = "private, no-store")
        val result = HttpsMotivationGateway("https://api.example/api/v1/") { requested = it; connection }.get(session()) { assertFalse(connection.sent) }
        assertEquals("https://api.example/api/v1/me/motivation", requested.toString())
        assertNull(requested!!.query); assertEquals("GET", connection.requestMethod)
        for (header in listOf("Idempotency-Key", "If-Match", "X-Sync-Epoch", "X-Ranking-Consent-Epoch")) assertNull(connection.getRequestProperty(header))
        assertEquals("Bearer fixture-access", connection.getRequestProperty("Authorization"))
        assertFalse(connection.doOutput); assertFalse(connection.instanceFollowRedirects); assertFalse(connection.useCaches)
        assertEquals("no-store", connection.getRequestProperty("Cache-Control"))
        assertEquals(200, result.status); assertTrue(connection.disconnected)
    }
    @Test fun motivationRejectsCacheableSuccessStaleLeaseAndUnboundedResponseButHonoursProxyBackoff() {
        for (connection in listOf(Connection(URL("https://api.example")), Connection(URL("https://api.example"), cacheControl = "max-age=60"),
            Connection(URL("https://api.example"), payload = ByteArray(65_537), declaredSize = -1, cacheControl = "no-store"),
            Connection(URL("https://api.example"), status = 302, cacheControl = "no-store"))) {
            assertThrows(Exception::class.java) { runBlocking { HttpsMotivationGateway("https://api.example/api/v1") { connection }.get(session()) {} } }
            assertTrue(connection.disconnected)
        }
        val stale = Connection(URL("https://api.example"), cacheControl = "no-store")
        assertThrows(Exception::class.java) { runBlocking { HttpsMotivationGateway("https://api.example/api/v1") { stale }.get(session()) { error("stale") } } }
        assertFalse(stale.sent); assertTrue(stale.disconnected)
        for (status in listOf(429, 503)) {
            val proxy = Connection(URL("https://api.example"), status, "private html".toByteArray(), "text/html")
            val response = runBlocking { HttpsMotivationGateway("https://api.example/api/v1") { proxy }.get(session()) {} }
            assertEquals(status, response.status); assertEquals("60", response.retryAfter); assertFalse(proxy.readBody)
        }
    }
}
