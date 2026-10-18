package pl.roseru.kalorie

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.SessionIdentity
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.session.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.URL
import java.security.cert.Certificate
import javax.net.ssl.HttpsURLConnection

/** In-memory transport fixtures, not a real TLS or deployed API receipt. */
class MealPushHttpTest {
    private val schema = SyncWireSchema(SyncWireSchema.FILES.associateWith { file ->
        javaClass.getResourceAsStream("/sync/$file")!!.use { it.readBytes() }
    })
    private val protocol = PushProtocol(schema)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private fun resource(path: String) = javaClass.getResourceAsStream("/photo/$path")!!.use { it.readBytes() }
    private fun batch() = protocol.prepare(epoch, "opaque+/?=&ż😀", listOf(
        resource("materialized-meal-operation.json").toString(Charsets.UTF_8)))
    private fun session(token: String = "fixture-access") = ApiSession(
        SessionIdentity("https://id.example/realm", "fixture-A"), OwnerLease("fixture-A", 1), token, "fixture-state", 1)
    private class Connection(val status: Int = 200, val payload: ByteArray = "{}".toByteArray(),
        val type: String = "application/json", val encoding: String? = null,
        val declaredSize: Long = payload.size.toLong(), val cache: String? = "private, no-store",
        val failWrite: Boolean = false) : HttpsURLConnection(URL("https://api.example")) {
        val written = ByteArrayOutputStream()
        var disconnected = false
        var sent = false
        var bodyRead = false
        var fixedLength = -1
        override fun disconnect() { disconnected = true }
        override fun usingProxy() = false
        override fun connect() { sent = true }
        override fun setFixedLengthStreamingMode(contentLength: Int) { fixedLength = contentLength }
        override fun getOutputStream(): ByteArrayOutputStream {
            sent = true
            if (failWrite) throw IOException("synthetic lost connection")
            return written
        }
        override fun getResponseCode(): Int { sent = true; return status }
        override fun getContentType() = type
        override fun getContentLengthLong() = declaredSize
        override fun getHeaderField(name: String?) = when (name) {
            "Cache-Control" -> cache; "Content-Encoding" -> encoding; "Retry-After" -> "86400"; else -> null
        }
        override fun getInputStream(): ByteArrayInputStream { bodyRead = true; return ByteArrayInputStream(payload) }
        override fun getErrorStream() = inputStream
        override fun getCipherSuite() = "fixture-only"
        override fun getLocalCertificates(): Array<Certificate>? = null
        override fun getServerCertificates(): Array<Certificate> = emptyArray()
    }
    private suspend fun send(connection: Connection, batch: PushBatch = batch(), before: suspend () -> Unit = {}) =
        HttpsMealPushGateway("https://api.example/api/v1/") { connection }.post(session(), batch, before)

    @Test fun sendsExactFrozenUtf8EnvelopeWithoutEnvelopeIdempotencyOrInventedCapabilities() = runBlocking<Unit> {
        val batch = batch(); val expected = batch.body(); val hash = batch.sha256
        var requested: URL? = null
        val c = Connection(payload = resource("materialized-meal-push-response.json"))
        val result = HttpsMealPushGateway("https://api.example:18443/api/v1/") { requested = it; c }
            .post(session(), batch) { assertFalse(c.sent); batch.body().fill(0) }
        assertEquals("https://api.example:18443/api/v1/sync/push", requested.toString())
        assertEquals("POST", c.requestMethod); assertTrue(c.doOutput)
        assertArrayEquals(expected, c.written.toByteArray()); assertEquals(expected.size, c.fixedLength)
        assertEquals(hash, batch.sha256); assertFalse(c.instanceFollowRedirects); assertFalse(c.useCaches)
        assertEquals("Bearer fixture-access", c.getRequestProperty("Authorization"))
        assertEquals("application/json; charset=utf-8", c.getRequestProperty("Content-Type"))
        assertEquals("identity", c.getRequestProperty("Accept-Encoding"))
        assertEquals("no-store", c.getRequestProperty("Cache-Control"))
        for (header in listOf("Idempotency-Key", "If-Match", "X-Sync-Epoch", "X-Sync-Capability"))
            assertNull(c.getRequestProperty(header))
        assertEquals(200, result.status); protocol.response(batch, result.status, result.body)
        assertTrue(c.disconnected); assertFalse(result.toString().contains("results"))
    }
    @Test fun staleOrCancelledPreflightDisclosesNoBodyAndAlwaysDisconnects() {
        for (cancel in listOf(false, true)) {
            val c = Connection()
            assertThrows(Exception::class.java) { runBlocking {
                send(c) { if (cancel) throw CancellationException("fixture") else error("stale account") }
            } }
            assertFalse(c.sent); assertEquals(0, c.written.size()); assertTrue(c.disconnected)
        }
    }
    @Test fun interruptedWriteHasNoHiddenRetryAndNextExplicitSendPreservesAllBytes() = runBlocking<Unit> {
        val original = batch(); val restored = protocol.restore(original.body()); var opened = 0
        val failed = Connection(failWrite = true)
        assertThrows(IOException::class.java) { runBlocking {
            HttpsMealPushGateway("https://api.example/api/v1") { opened++; failed }.post(session(), original) {}
        } }
        assertEquals(1, opened); assertTrue(failed.disconnected)
        val retry = Connection(); send(retry, restored)
        assertArrayEquals(original.body(), retry.written.toByteArray())
    }
    @Test fun responseBoundsApplyToAnnouncedAndUnknownLengthIncludingPrivateErrors() {
        for (c in listOf(Connection(declaredSize = PushProtocol.MAX_RESPONSE_BYTES.toLong() + 1),
            Connection(payload = ByteArray(PushProtocol.MAX_RESPONSE_BYTES + 1), declaredSize = -1),
            Connection(status = 401, payload = ByteArray(65_537), declaredSize = -1))) {
            assertThrows(Exception::class.java) { runBlocking { send(c) } }
            assertTrue(c.disconnected)
        }
    }
    @Test fun fullBoundedResponseIsReturnedButOnlyExact200CanBecomeAck() = runBlocking<Unit> {
        val large = Connection(payload = ByteArray(PushProtocol.MAX_RESPONSE_BYTES), declaredSize = -1)
        assertEquals(PushProtocol.MAX_RESPONSE_BYTES, send(large).body.size)
        val request = batch()
        for (status in listOf(201, 202, 204, 400, 401, 409, 410, 413, 422)) {
            val response = send(Connection(status = status, payload = resource("materialized-meal-push-response.json")), request)
            assertThrows(SyncWireException::class.java) { protocol.response(request, response.status, response.body) }
        }
    }
    @Test fun rejectsRedirectCompressionHtmlAndCacheableSuccessOrErrors() {
        for (c in listOf(Connection(status = 302), Connection(status = 307), Connection(type = "text/html"),
            Connection(encoding = "gzip"), Connection(cache = null), Connection(cache = "private, max-age=60"),
            Connection(status = 401, cache = null), Connection(status = 409, cache = "private"))) {
            assertThrows(Exception::class.java) { runBlocking { send(c) } }; assertTrue(c.disconnected)
        }
    }
    @Test fun overloadedProxyHonoursDelayWithoutReadingOrEchoingHtml() = runBlocking<Unit> {
        for (status in listOf(429, 503)) {
            val c = Connection(status = status, payload = "<html>private</html>".toByteArray(), type = "text/html", cache = null)
            val result = send(c)
            assertEquals(status, result.status); assertEquals("86400", result.retryAfter)
            assertTrue(result.body.isEmpty()); assertFalse(c.bodyRead); assertTrue(c.disconnected)
        }
    }
    @Test fun invalidBaseOrTokenCannotOpenTransport() {
        var opened = false
        for (base in listOf("http://api.example/api/v1", "https://u:p@api.example/api/v1", "https://api.example/api/v1?q=secret",
            "https://api.example/api/%76%31", "https://api.example/api/v1/../v1"))
            assertThrows(Exception::class.java) { HttpsMealPushGateway(base) { opened = true; Connection() } }
        assertThrows(Exception::class.java) { runBlocking {
            HttpsMealPushGateway("https://api.example/api/v1") { opened = true; Connection() }
                .post(session("bad\r\nInjected:value"), batch()) {}
        } }
        assertFalse(opened)
    }
    @Test fun syncErrorParserRequiresNormativeObjectDetailsAndDoesNotExposeText() {
        val error = JSONObject().put("code", "sync_epoch_changed").put("message", "private server text")
            .put("request_id", "a1111111-1111-4111-8111-111111111111").put("details", JSONObject()
                .put("current_sync_epoch", "e1111111-1111-4111-8111-111111111111")
                .put("requested_sync_epoch", epoch).put("recovery_required", "epoch_recovery"))
        assertEquals("sync_epoch_changed", protocol.errorCode(StrictJson.canonical(error).toByteArray()))
        for (bad in listOf(JSONObject(error.toString()).put("details", org.json.JSONArray()),
            JSONObject(error.toString()).put("details", JSONObject()),
            JSONObject(error.toString()).put("code", "unknown_code"), JSONObject(error.toString()).put("extra", true))) {
            val failure = assertThrows(SyncWireException::class.java) { protocol.errorCode(bad.toString().toByteArray()) }
            assertNull(failure.cause); assertFalse(failure.toString().contains("private server text"))
        }
        assertThrows(SyncWireException::class.java) { protocol.errorCode(ByteArray(65_537)) }
    }
}
