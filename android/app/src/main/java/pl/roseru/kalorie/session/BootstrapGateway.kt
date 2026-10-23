package pl.roseru.kalorie.session

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import org.json.JSONArray
import pl.roseru.kalorie.core.BootstrapProtocol
import pl.roseru.kalorie.core.SessionIdentity
import pl.roseru.kalorie.core.RankingConsentAttempt
import pl.roseru.kalorie.core.RankingQuery
import pl.roseru.kalorie.core.NemesisQuery
import pl.roseru.kalorie.core.NemesisReadProtocol
import pl.roseru.kalorie.core.PhotoHttpRequest
import pl.roseru.kalorie.core.NemesisAttempt
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.requireHttps
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.core.sync.SnapshotQuery
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.core.sync.PushBatch
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.URL
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import javax.net.ssl.HttpsURLConnection

/** Captured credentials stay internal and are never part of UI state or a generated toString. */
internal class ApiSession(val identity: SessionIdentity, val lease: OwnerLease,
    internal val accessToken: String, internal val authState: String, internal val revision: Long) {
    override fun toString() = "ApiSession(redacted)"
}

internal class BootstrapHttpResult(val status: Int, val body: ByteArray, val retryAfter: String? = null, val etag: String? = null) {
    override fun toString() = "BootstrapHttpResult(status=$status)"
}

internal interface BootstrapGateway {
    suspend fun post(session: ApiSession, operationId: String, beforeSend: suspend () -> Unit): BootstrapHttpResult
}

internal interface ProfileGateway {
    suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit): BootstrapHttpResult
}
internal interface PhotoCapabilitiesGateway : ProfileGateway
internal class HttpsPhotoCapabilitiesGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : PhotoCapabilitiesGateway {
    private val url = URL(BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/me/bootstrap") + "/ai/capabilities")
    override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit) =
        HttpsJsonTransport.request(url, "GET", session, null, open, beforeSend, requireNoStore = true, privateErrors = true)
}
internal interface MotivationGateway : ProfileGateway
internal interface RankingGateway {
    suspend fun get(session: ApiSession, query: RankingQuery, beforeSend: suspend () -> Unit): BootstrapHttpResult
}
internal interface NemesisGateway {
    suspend fun get(session: ApiSession, epoch: String, query: NemesisQuery, beforeSend: suspend () -> Unit): BootstrapHttpResult
}
internal interface NemesisWriteGateway {
    suspend fun send(session: ApiSession, request: NemesisAttempt, beforeSend: suspend () -> Unit): BootstrapHttpResult
}
internal interface RankingConsentGateway {
    suspend fun put(session: ApiSession, request: RankingConsentAttempt, beforeSend: suspend () -> Unit): BootstrapHttpResult
}
internal interface SnapshotGateway {
    suspend fun get(session: ApiSession, query: SnapshotQuery, beforeSend: suspend () -> Unit): BootstrapHttpResult
}

internal object BootstrapHttpProtocol {
    const val MAX_BYTES = 65_536
    fun endpoint(base: String): URL {
        val uri = requireHttps(base)
        require(uri.rawPath == "/api/v1" || uri.rawPath == "/api/v1/")
        return URL(base.trimEnd('/') + "/me/bootstrap")
    }
    /** No server text is displayed/logged. Only strictly shaped codes drive decisions. */
    fun errorCode(body: ByteArray): String {
        require(body.size in 1..MAX_BYTES)
        val json = StrictJson.read(body)
        require(json.keys().asSequence().toSet() == setOf("code", "message", "details", "request_id"))
        val code = json.get("code") as String
        require(Regex("[a-z][a-z0-9_]{0,99}").matches(code))
        require((json.get("message") as String).length <= 4096)
        require(BootstrapProtocol.uuid.matches(json.get("request_id") as String))
        val details = json.get("details") as JSONArray
        require(details.length() <= 20)
        for (index in 0 until details.length()) {
            val detail = details.getJSONObject(index)
            require(detail.keys().asSequence().toSet() == setOf("field", "reason"))
            require((detail.get("field") as String).length <= 255 && (detail.get("reason") as String).length <= 4096)
        }
        return code
    }
    fun retrySeconds(value: String?, nowMillis: Long): Long {
        if (value == null || value.length > 128) return 30
        val trimmed = value.trim()
        if (Regex("[0-9]{1,12}").matches(trimmed)) return trimmed.toLong()
        return try {
            val target = ZonedDateTime.parse(trimmed, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli()
            if (target <= nowMillis) 0 else Math.addExact(Math.subtractExact(target, nowMillis), 999) / 1000
        } catch (_: Exception) { 30 }
    }
    fun read(stream: InputStream, maxBytes: Int = MAX_BYTES, beforeRead: () -> Unit = {}): ByteArray {
        require(maxBytes in 1..SnapshotProtocol.MAX_BYTES)
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        while (true) {
            beforeRead()
            val count = stream.read(buffer, 0, minOf(buffer.size, maxBytes + 1 - output.size()))
            if (count == -1) break
            output.write(buffer, 0, count)
            require(output.size() <= maxBytes)
        }
        return output.toByteArray()
    }
}

/** System TLS/hostname verification; no redirects, caches, body or application-level retries. */
internal class HttpsBootstrapGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : BootstrapGateway {
    private val url = BootstrapHttpProtocol.endpoint(base)
    override suspend fun post(session: ApiSession, operationId: String, beforeSend: suspend () -> Unit): BootstrapHttpResult {
        require(BootstrapProtocol.uuid.matches(operationId))
        return HttpsJsonTransport.request(url, "POST", session, operationId, open, beforeSend)
    }
}

internal class HttpsProfileGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : ProfileGateway {
    private val url = URL(BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/bootstrap"))
    override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit) =
        HttpsJsonTransport.request(url, "GET", session, null, open, beforeSend)
}
internal class HttpsMotivationGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : MotivationGateway {
    private val url = URL(BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/bootstrap") + "/motivation")
    override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit) =
        HttpsJsonTransport.request(url, "GET", session, null, open, beforeSend, requireNoStore = true)
}
internal class HttpsSnapshotGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : SnapshotGateway {
    private val endpoint = BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/me/bootstrap") + "/sync/pull"
    override suspend fun get(session: ApiSession, query: SnapshotQuery, beforeSend: suspend () -> Unit) =
        HttpsJsonTransport.request(URL(endpoint + "?" + query.encoded()), "GET", session, null, open, beforeSend, SnapshotProtocol.MAX_BYTES)
}

internal class HttpsRankingConsentGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : RankingConsentGateway {
    private val url = URL(BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/bootstrap") + "/consents")
    override suspend fun put(session: ApiSession, request: RankingConsentAttempt, beforeSend: suspend () -> Unit) =
        HttpsJsonTransport.request(url, "PUT", session, request.key, open, beforeSend, requireNoStore = true, consent = request)
}

internal class HttpsRankingGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : RankingGateway {
    private val endpoint = BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/me/bootstrap") + "/ranking"
    override suspend fun get(session: ApiSession, query: RankingQuery, beforeSend: suspend () -> Unit) =
        HttpsJsonTransport.request(URL(endpoint + "?" + query.encoded()), "GET", session, null, open, beforeSend, requireNoStore = true)
}

internal class HttpsNemesisGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : NemesisGateway {
    private val endpoint = BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/me/bootstrap")
    override suspend fun get(session: ApiSession, epoch: String, query: NemesisQuery, beforeSend: suspend () -> Unit): BootstrapHttpResult =
        HttpsJsonTransport.request(URL(endpoint + query.path()), "GET", session, null, open, beforeSend,
            NemesisReadProtocol.MAX_BYTES, requireNoStore = true, syncEpoch = epoch, privateErrors = true)
}

/** Shared bounded transport; callers cannot supply an arbitrary URL or extra headers. */
internal class HttpsNemesisWriteGateway(base: String,
    private val open: (URL) -> HttpsURLConnection = { it.openConnection() as HttpsURLConnection }) : NemesisWriteGateway {
    private val endpoint = BootstrapHttpProtocol.endpoint(base).toString().removeSuffix("/me/bootstrap")
    override suspend fun send(session: ApiSession, request: NemesisAttempt, beforeSend: suspend () -> Unit) =
        HttpsJsonTransport.request(URL(endpoint + request.command.path()), request.command.method, session, request.key, open, beforeSend,
            NemesisReadProtocol.MAX_BYTES, requireNoStore = true, syncEpoch = request.epoch, privateErrors = true, nemesis = request)
}

internal object HttpsJsonTransport {
    suspend fun request(url: URL, method: String, session: ApiSession, key: String?,
        open: (URL) -> HttpsURLConnection, beforeSend: suspend () -> Unit,
        maxBytes: Int = BootstrapHttpProtocol.MAX_BYTES, requireNoStore: Boolean = false,
        consent: RankingConsentAttempt? = null, syncEpoch: String? = null, privateErrors: Boolean = false,
        nemesis: NemesisAttempt? = null, photo: PhotoHttpRequest? = null, push: PushBatch? = null) = withContext(Dispatchers.IO) {
        syncEpoch?.let(NemesisReadProtocol::uuid)
        require(listOfNotNull(consent, nemesis, photo, push).size <= 1)
        if (nemesis != null) require(key == nemesis.key && syncEpoch == nemesis.epoch && method == nemesis.command.method)
        if (photo != null) require(key == photo.key && syncEpoch == photo.epoch && method == photo.method &&
            url.path == "/api/v1" + photo.path)
        if (push != null) require(method == "POST" && key == null && syncEpoch == null &&
            url.path == "/api/v1/sync/push" && url.query == null)
        val payload = consent?.body() ?: nemesis?.command?.body() ?: photo?.body() ?: push?.body()
        require(session.accessToken.isNotBlank() && session.accessToken.length <= 65_536 &&
            session.accessToken.none { it.isWhitespace() || it.isISOControl() })
        val connection = open(url)
        try {
            connection.requestMethod = method
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.doOutput = payload != null
            connection.connectTimeout = 15_000
            connection.readTimeout = 15_000
            connection.setRequestProperty("Authorization", "Bearer ${session.accessToken}")
            key?.let { connection.setRequestProperty("Idempotency-Key", it) }
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Accept-Encoding", "identity")
            connection.setRequestProperty("Cache-Control", "no-store")
            syncEpoch?.let { connection.setRequestProperty("X-Sync-Epoch", it) }
            if (consent != null) {
                require(method == "PUT" && key == consent.key)
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.setRequestProperty("If-Match", "\"${consent.baseRevision}\"")
                consent.consentEpoch?.let { connection.setRequestProperty("X-Ranking-Consent-Epoch", it) }
            }
            nemesis?.command?.baseRevision?.let { connection.setRequestProperty("If-Match", "\"$it\"") }
            if (payload != null) {
                connection.setRequestProperty("Content-Type", photo?.contentType ?: "application/json; charset=utf-8")
                connection.setFixedLengthStreamingMode(payload.size)
            }
            coroutineContext.ensureActive()
            beforeSend()
            val deadline = System.nanoTime() + 30_000_000_000L
            if (payload != null) connection.outputStream.use { output ->
                var offset = 0
                while (offset < payload.size) {
                    coroutineContext.ensureActive()
                    check(System.nanoTime() < deadline)
                    val count = minOf(4096, payload.size - offset)
                    output.write(payload, offset, count)
                    offset += count
                }
            }
            val status = connection.responseCode
            require(status in 200..599 && status !in 300..399)
            if (MealPushObservation.ENABLED && push != null) MealPushObservation.record(push.sha256, method, url.path, status,
                connection.getHeaderField("Cache-Control"), connection.getHeaderField("X-Request-ID"))
            if (ApiReadObservation.ENABLED && method == "GET" &&
                url.path in setOf("/api/v1/me", "/api/v1/me/motivation")) ApiReadObservation.record(method, url.path, status,
                connection.getHeaderField("Cache-Control"), connection.getHeaderField("X-Request-ID"))
            // A proxy may return HTML for overload. Honour its delay without reading/echoing the body.
            if (status == 429 || status == 503) return@withContext BootstrapHttpResult(status, ByteArray(0), connection.getHeaderField("Retry-After"))
            if ((status == 200 || privateErrors) && requireNoStore) require(connection.getHeaderField("Cache-Control")
                ?.split(',')?.any { it.trim().equals("no-store", ignoreCase = true) } == true)
            val contentType = connection.contentType?.substringBefore(';')?.trim()
            require(contentType.equals("application/json", ignoreCase = true))
            require(connection.getHeaderField("Content-Encoding").let { it == null || it.equals("identity", ignoreCase = true) })
            val bound = if (status in 200..299) maxBytes else BootstrapHttpProtocol.MAX_BYTES
            require(connection.contentLengthLong <= bound)
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val bytes = checkNotNull(stream).use {
                BootstrapHttpProtocol.read(it, bound) {
                    coroutineContext.ensureActive()
                    val remaining = (deadline - System.nanoTime()) / 1_000_000
                    check(remaining > 0)
                    connection.readTimeout = minOf(15_000, remaining.toInt())
                }
            }
            val etag = if (consent != null) connection.getHeaderField("ETag")?.also { require(it.length <= 32) } else null
            if (ApiReadObservation.ENABLED) ApiReadObservation.beforeReturn(method, url.path, status, deadline)
            BootstrapHttpResult(status, bytes, connection.getHeaderField("Retry-After"), etag)
        } finally { connection.disconnect() }
    }
}
