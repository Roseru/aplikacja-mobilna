package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.io.ByteArrayOutputStream
import java.time.Instant
import java.time.LocalDateTime

/** Prepared wire operations only. The owner-scoped durable queue must save these before sending. */
internal sealed class PhotoHttpRequest(val key: String?, val epoch: String?, val path: String,
    val method: String, val contentType: String?) {
    abstract fun body(): ByteArray?
    final override fun toString() = "PhotoHttpRequest(redacted)"

    class Create private constructor(key: String, epoch: String, val provider: String,
        val noticeVersion: String, val imageSha256: String, private val wire: ByteArray, contentType: String) :
        PhotoHttpRequest(key, epoch, "/ai/food-analyses", "POST", contentType) {
        override fun body() = wire.copyOf()
        companion object {
            /** Image must already be prepared by the local photo store; no re-encoding on retry. */
            fun prepare(key: String, epoch: String, capabilities: PhotoCapabilitiesRead,
                accepted: Boolean, image: ByteArray, mime: String): Create {
                uuid(key); uuid(epoch)
                require(accepted && capabilities.available)
                require(capabilities.noticeVersion == "food-photo-notice-v1")
                require(capabilities.provider in setOf("mock", "gemini"))
                require(capabilities.imageBytes in 1..IMAGE_BYTES)
                require(image.size in 1..capabilities.imageBytes)
                val extension = when (mime) {
                    "image/jpeg" -> { require(image.size >= 3 && image[0] == 0xff.toByte() && image[1] == 0xd8.toByte() && image[2] == 0xff.toByte()); "jpg" }
                    "image/png" -> { require(image.size >= 8 && image.copyOfRange(0,8).contentEquals(byteArrayOf(0x89.toByte(),0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a))); "png" }
                    "image/webp" -> { require(image.size >= 12 && String(image,0,4,Charsets.US_ASCII) == "RIFF" && String(image,8,4,Charsets.US_ASCII) == "WEBP"); "webp" }
                    else -> throw IllegalArgumentException("Unsupported prepared image type")
                }
                val boundary = "calorie-photo-$key"
                // An image cannot inject an extra part, even with a deliberately chosen key.
                val separator = "\r\n--$boundary".toByteArray(Charsets.US_ASCII)
                require(!contains(image, separator))
                val metadata = StrictJson.canonical(JSONObject().put("consent", JSONObject()
                    .put("accepted",true).put("notice_version",capabilities.noticeVersion)
                    .put("provider",capabilities.provider).put("scope","this_photo")))
                val output = ByteArrayOutputStream(image.size + 1024)
                fun text(value: String) { output.write(value.toByteArray(Charsets.UTF_8)) }
                text("--$boundary\r\nContent-Disposition: form-data; name=\"metadata\"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n$metadata\r\n")
                text("--$boundary\r\nContent-Disposition: form-data; name=\"image\"; filename=\"photo.$extension\"\r\nContent-Type: $mime\r\n\r\n")
                output.write(image)
                text("\r\n--$boundary--\r\n")
                val wire = output.toByteArray()
                require(wire.size <= BODY_BYTES)
                val imageSha = java.security.MessageDigest.getInstance("SHA-256").digest(image).joinToString("") { "%02x".format(it) }
                return Create(key,epoch,capabilities.provider,capabilities.noticeVersion,imageSha,wire,"multipart/form-data; boundary=$boundary")
            }
        }
    }
    class Read(analysisId: String) : PhotoHttpRequest(null,null,"/ai/food-analyses/${uuid(analysisId)}","GET",null) {
        override fun body(): ByteArray? = null
    }
    class Cancel(key: String, epoch: String, analysisId: String, val expectedRevision: Long) :
        PhotoHttpRequest(uuid(key),uuid(epoch),"/ai/food-analyses/${uuid(analysisId)}/cancel","POST","application/json; charset=utf-8") {
        init { require(expectedRevision in 1..2_147_483_647L) }
        override fun body() = "{\"expected_revision\":$expectedRevision}".toByteArray(Charsets.UTF_8)
    }
    companion object {
        const val IMAGE_BYTES = 5_242_880
        const val BODY_BYTES = 6_291_456
        fun uuid(value: String): String { require(BootstrapProtocol.uuid.matches(value)); return value }
        private fun contains(haystack: ByteArray, needle: ByteArray): Boolean {
            for (start in 0..haystack.size - needle.size) {
                if (haystack[start] != needle[0]) continue
                var index = 1
                while (index < needle.size && haystack[start + index] == needle[index]) index++
                if (index == needle.size) return true
            }
            return false
        }
    }
}

internal class PhotoAnalysisProfile(val provider: String, val model: String, val prompt: String,
    val schema: String, val preparation: String, val rest: String, val mockScenario: String?) {
    override fun toString() = "PhotoAnalysisProfile(redacted)"
}
internal class PhotoCreateReceipt(val analysisId: String, val revision: Long, val state: String,
    val queueDeadline: Instant, val profile: PhotoAnalysisProfile) {
    override fun toString() = "PhotoCreateReceipt(redacted)"
}

/** Only create/cancel ACKs here. Full proposals require the separate strict proposal decoder. */
internal object PhotoAnalysisProtocol {
    fun create(bytes: ByteArray, request: PhotoHttpRequest.Create): PhotoCreateReceipt {
        val json = read(bytes)
        exact(json,setOf("analysis_id","revision","state","queue_deadline","profile"))
        val id = PhotoHttpRequest.uuid(text(json,"analysis_id"))
        val revision = revision(json)
        val state = text(json,"state").also { require(it in setOf("queued","running","succeeded","failed")) }
        val deadline = text(json,"queue_deadline").also {
            require(Regex("""\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.[0-9]{1,6})?Z""").matches(it))
            require(LocalDateTime.parse(it.dropLast(1)).year in 1..9999)
        }.let(Instant::parse)
        val profile = json.getJSONObject("profile")
        exact(profile,setOf("provider","model","prompt_version","schema_version","preparation_version","rest_profile_version","mock_scenario"))
        val provider = text(profile,"provider").also { require(it == request.provider) }
        val scenario = if (profile.get("mock_scenario") === JSONObject.NULL) null else text(profile,"mock_scenario")
        require(provider != "gemini" || scenario == null)
        return PhotoCreateReceipt(id,revision,state,deadline,PhotoAnalysisProfile(provider,text(profile,"model"),
            text(profile,"prompt_version"),text(profile,"schema_version"),text(profile,"preparation_version"),text(profile,"rest_profile_version"),scenario))
    }
    fun cancelled(bytes: ByteArray, analysisId: String, expectedRevision: Long): Long {
        val json = read(bytes)
        exact(json,setOf("analysis_id","revision","state","decision_state","error_code"))
        require(text(json,"analysis_id") == PhotoHttpRequest.uuid(analysisId))
        require(text(json,"state") == "failed" && text(json,"decision_state") == "cancelled" && text(json,"error_code") == "analysis_cancelled")
        return revision(json).also { require(it >= expectedRevision) }
    }
    private fun read(bytes: ByteArray): JSONObject { require(bytes.size in 1..65_536); return StrictJson.read(bytes) }
    private fun exact(json: JSONObject, names: Set<String>) { require(json.keys().asSequence().toSet() == names) }
    private fun text(json: JSONObject, key: String) = (json.get(key) as String).also { require(it.length in 1..100 && it.none(Char::isISOControl)) }
    private fun revision(json: JSONObject): Long {
        val value = json.get("revision")
        require(value is Int || value is Long)
        return (value as Number).toLong().also { require(it in 1..2_147_483_647L) }
    }
}
