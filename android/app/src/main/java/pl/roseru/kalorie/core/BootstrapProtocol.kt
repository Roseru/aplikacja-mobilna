package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.Instant
import java.time.LocalDateTime

/** E0 Bootstrap response, without credentials or HTTP/session authentication. */
data class BootstrapResponse(val accountId: String, val syncEpoch: String, val accountGeneration: Int, val serverTime: String) {
    init {
        require(BootstrapProtocol.uuid.matches(accountId) && BootstrapProtocol.uuid.matches(syncEpoch))
        require(accountGeneration > 0)
        require(Regex("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.[0-9]{1,6})?Z").matches(serverTime))
        require(LocalDateTime.parse(serverTime.dropLast(1)).year in 1..9999)
        Instant.parse(serverTime)
    }
    fun canonical(): String = StrictJson.canonical(JSONObject().put("account_id", accountId).put("sync_epoch", syncEpoch)
        .put("account_generation", accountGeneration).put("server_time", serverTime))
}

object BootstrapProtocol {
    val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    fun parse(bytes: ByteArray): BootstrapResponse {
        require(bytes.size in 1..65_536)
        val json = StrictJson.read(bytes)
        require(json.keys().asSequence().toSet() == setOf("account_id", "sync_epoch", "account_generation", "server_time"))
        fun string(key: String) = requireNotNull(json.get(key) as? String)
        val number = requireNotNull(json.get("account_generation") as? Number)
        val generation = number.toString().toBigDecimal().intValueExact()
        return BootstrapResponse(string("account_id"), string("sync_epoch"), generation, string("server_time"))
    }
}

/** Exact future APK callbacks agreed with O2; the OIDC handler is a separate integration. */
object AuthReturn {
    fun redirect(applicationId: String): String = when (applicationId) {
        "pl.roseru.kalorie", "pl.roseru.kalorie.validation" -> "$applicationId:/oauth2redirect"
        else -> throw IllegalArgumentException("Unsupported mobile application")
    }
}
