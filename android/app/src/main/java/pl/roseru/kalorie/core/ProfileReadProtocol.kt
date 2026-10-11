package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId

/** Read-only wire values. They are not local ProfileEntity/goal/outbox payloads. */
class ServerProfile(val entityId: String, val revision: Int, val pseudonym: String,
    val heightCm: String?, val activityClass: ActivityClass, val timeZone: String) {
    override fun toString() = "ServerProfile(redacted)"
}
class ServerConsents(val revision: Int, val ranking: Boolean, val automaticEnergyAdjustment: Boolean,
    val updatedAt: String) {
    override fun toString() = "ServerConsents(redacted)"
}
class ProfileRead(val accountId: String, val syncEpoch: String, val profile: ServerProfile?,
    val consents: ServerConsents, val goalTimelineRevision: Int) {
    override fun toString() = "ProfileRead(redacted)"
}

object ProfileReadProtocol {
    fun parse(bytes: ByteArray): ProfileRead {
        require(bytes.size in 1..65_536)
        val json = StrictJson.read(bytes)
        exact(json, "account_id", "sync_epoch", "profile", "consents", "goal_timeline_revision")
        val profile = if (json.get("profile") === JSONObject.NULL) null else {
            val record = json.getJSONObject("profile")
            exact(record, "entity_id", "revision", "payload")
            val payload = record.getJSONObject("payload")
            exact(payload, "pseudonym", "height_cm", "activity_class", "time_zone")
            val pseudonym = text(payload, "pseudonym").also { require(it.codePointCount(0, it.length) in 1..80) }
            val height = if (payload.get("height_cm") === JSONObject.NULL) null else text(payload, "height_cm").also {
                require(Regex("(0|[1-9][0-9]{0,5})(\\.[0-9]{0,5}[1-9])?").matches(it))
                require(BigDecimal(it) > BigDecimal.ZERO && BigDecimal(it) <= BigDecimal(300))
            }
            val activity = when (text(payload, "activity_class")) {
                "stationary" -> ActivityClass.GARRISON
                "line" -> ActivityClass.LINE
                "commando" -> ActivityClass.COMMANDO
                else -> error("Invalid activity class")
            }
            val zone = text(payload, "time_zone").also {
                require(it.length in 1..100 && it in ZoneId.getAvailableZoneIds())
            }
            ServerProfile(uuid(record, "entity_id"), revision(record, "revision"), pseudonym, height, activity, zone)
        }
        val consents = json.getJSONObject("consents")
        exact(consents, "revision", "ranking", "automatic_energy_adjustment", "updated_at")
        val updatedAt = text(consents, "updated_at").also {
            require(Regex("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.[0-9]{1,6})?Z").matches(it))
            require(LocalDateTime.parse(it.dropLast(1)).year in 1..9999)
            Instant.parse(it)
        }
        return ProfileRead(uuid(json, "account_id"), uuid(json, "sync_epoch"), profile,
            ServerConsents(revision(consents, "revision"), consents.get("ranking") as Boolean,
                consents.get("automatic_energy_adjustment") as Boolean, updatedAt),
            revision(json, "goal_timeline_revision", allowZero = true))
    }
    private fun exact(json: JSONObject, vararg keys: String) {
        require(json.keys().asSequence().toSet() == keys.toSet())
    }
    private fun text(json: JSONObject, key: String) = (json.get(key) as String).also { require('\u0000' !in it) }
    private fun uuid(json: JSONObject, key: String) = text(json, key).also { require(BootstrapProtocol.uuid.matches(it)) }
    private fun revision(json: JSONObject, key: String, allowZero: Boolean = false): Int {
        val value = json.get(key)
        require(value is Int || value is Long)
        return (value as Number).toString().toBigDecimal().intValueExact().also { require(it >= if (allowZero) 0 else 1) }
    }
}
