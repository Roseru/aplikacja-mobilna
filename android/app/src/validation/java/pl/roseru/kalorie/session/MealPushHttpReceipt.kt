package pl.roseru.kalorie.session

import java.time.Instant

/** Only allowlisted HTTP metadata; never holds an envelope or account identifier. */
internal data class MealPushHttpReceipt(val status: Int, val noStore: Boolean,
    val requestId: String, val utc: String) {
    fun format() = "path=/api/v1/sync/push utc=$utc status=$status no_store=$noStore request_id=$requestId"

    companion object {
        private val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        fun read(method: String, path: String, status: Int, cacheControl: String?,
            requestId: String?, time: Instant): MealPushHttpReceipt? {
            if (method != "POST" || path != "/api/v1/sync/push" || status !in 200..599 || status in 300..399) return null
            val noStore = cacheControl?.takeIf { it.length <= 1024 }?.split(',')
                ?.any { it.trim().equals("no-store", ignoreCase = true) } == true
            val safeId = when { requestId == null -> "missing"; uuid.matches(requestId) -> requestId; else -> "invalid" }
            return MealPushHttpReceipt(status, noStore, safeId, time.toString())
        }
    }
}
