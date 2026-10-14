package pl.roseru.kalorie.session

import android.util.Log
import java.time.Instant

/** No URLs, identity, bodies, credentials, cookies or arbitrary response headers. */
internal object ApiReadObservation {
    const val ENABLED = true
    const val TAG = "O1ApiReadReceipt"
    val lateRead = LateReadGate { event, path ->
        try { Log.i("O1ApiReadGate", "event=$event path=$path utc=${Instant.now()}") } catch (_: RuntimeException) { }
    }
    suspend fun beforeReturn(method: String, path: String, status: Int, deadlineNanos: Long) {
        lateRead.beforeReturn(method, path, status, deadlineNanos)
    }
    fun record(method: String, path: String, status: Int, cacheControl: String?, requestId: String?) {
        ApiReadReceipt.format(method, path, status, cacheControl, requestId, Instant.now())?.let {
            // Optional diagnostics must not fail a real GET when the platform logger is unavailable.
            try { Log.i(TAG, it) } catch (_: RuntimeException) { }
        }
    }
}

internal object ApiReadReceipt {
    private val paths = setOf("/api/v1/me", "/api/v1/me/motivation")
    private val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    fun format(method: String, path: String, status: Int, cacheControl: String?, requestId: String?, time: Instant): String? {
        if (method != "GET" || path !in paths || status !in 200..599 || status in 300..399) return null
        val noStore = cacheControl?.takeIf { it.length <= 1024 }?.split(',')
            ?.any { it.trim().equals("no-store", ignoreCase = true) } == true
        val safeId = when {
            requestId == null -> "missing"
            uuid.matches(requestId) -> requestId
            else -> "invalid"
        }
        return "path=$path utc=$time status=$status no_store=$noStore request_id=$safeId"
    }
}
