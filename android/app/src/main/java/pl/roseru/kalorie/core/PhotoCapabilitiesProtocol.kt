package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson

data class PhotoCapabilitiesRead(val provider: String, val model: String, val noticeVersion: String,
    val available: Boolean, val unavailableReason: String?, val imageBytes: Int, val dailyPhotos: Int)

sealed interface PhotoCapabilitiesState {
    data object NotRequested : PhotoCapabilitiesState
    data object Loading : PhotoCapabilitiesState
    data class Ready(val read: PhotoCapabilitiesRead) : PhotoCapabilitiesState
    data class Failed(val message: String) : PhotoCapabilitiesState
}

/** Public server configuration only; reading it never grants consent or uploads a photo. */
object PhotoCapabilitiesProtocol {
    fun parse(bytes: ByteArray): PhotoCapabilitiesRead {
        require(bytes.size in 1..65_536)
        val json = StrictJson.read(bytes)
        val limits = mapOf("image_bytes" to 5_242_880, "body_bytes" to 6_291_456,
            "ingredients" to 30, "daily_photos" to 10, "queue_seconds" to 300,
            "attempt_seconds" to 45, "total_seconds" to 120, "max_generate_attempts" to 2,
            "max_outbound_calls" to 2, "active_jobs_per_account" to 1)
        exact(json, setOf("provider", "profile", "notice_version", "available", "unavailable_reason",
            "manual_entry_available") + limits.keys)
        val provider = text(json, "provider").also { require(it in setOf("mock", "gemini")) }
        val profile = json.getJSONObject("profile")
        exact(profile, setOf("provider", "model", "prompt_version", "schema_version",
            "preparation_version", "rest_profile_version", "mock_scenario"))
        require(text(profile, "provider") == provider)
        val model = text(profile, "model")
        for (field in listOf("prompt_version", "schema_version", "preparation_version", "rest_profile_version")) text(profile, field)
        val scenario = nullableText(profile, "mock_scenario")
        require(provider != "gemini" || scenario == null)
        val notice = text(json, "notice_version").also { require(it == "food-photo-notice-v1") }
        val available = json.get("available") as Boolean
        val reason = nullableText(json, "unavailable_reason")
        require(if (available) reason == null else reason != null)
        require((json.get("manual_entry_available") as Boolean) == true)
        for ((field, maximum) in limits) {
            val value = json.get(field)
            require(value is Int || value is Long)
            require((value as Number).toLong() in 1L..maximum.toLong())
        }
        return PhotoCapabilitiesRead(provider, model, notice, available, reason,
            (json.get("image_bytes") as Number).toInt(), (json.get("daily_photos") as Number).toInt())
    }
    private fun exact(json: JSONObject, fields: Set<String>) { require(json.keys().asSequence().toSet() == fields) }
    private fun text(json: JSONObject, field: String) = (json.get(field) as String).also {
        require(it.length in 1..100 && it.none { char -> char.isISOControl() })
    }
    private fun nullableText(json: JSONObject, field: String): String? =
        if (json.get(field) === JSONObject.NULL) null else text(json, field)
}
