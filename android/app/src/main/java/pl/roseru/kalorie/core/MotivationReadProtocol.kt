package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime

enum class MotivationStatus { PENDING_BACKFILL, PENDING_MATERIALIZATION, FINAL }
enum class ServerBadgeStatus { PENDING, FINAL, REVOKED }
class ServerAchievement(val code: AchievementCode, val status: ServerBadgeStatus, val progress: Int,
    val witnessDates: List<LocalDate>, val firstAwardedAt: Instant?, val activatedAt: Instant?, val revokedAt: Instant?) {
    override fun toString() = "ServerAchievement(redacted)"
}
class MotivationRanking(val requested: Boolean, val effective: Boolean, val pendingConsentRefresh: Boolean,
    val consentEpoch: String, val ownPosition: Long?) {
    override fun toString() = "MotivationRanking(redacted)"
}
class MotivationRead(val accountGeneration: Int, val syncEpoch: String, val asOf: Instant,
    val revision: Long, val sourcePosition: Long, val status: MotivationStatus, val points: Long?, val rank: String?,
    val badges: List<ServerAchievement>, val ranking: MotivationRanking) {
    override fun toString() = "MotivationRead(redacted)"
}
sealed interface MotivationState {
    data object NotRequested : MotivationState
    data object Loading : MotivationState
    data class Ready(val read: MotivationRead) : MotivationState
    class Saved(val read:MotivationRead,val fetchedAtMillis:Long,val warning:String?=null):MotivationState
    data class Failed(val message: String) : MotivationState
}

/** Strict read-only E8 DTO. Revisions never become a sync checkpoint or local award. */
object MotivationReadProtocol {
    fun parse(bytes: ByteArray): MotivationRead {
        require(bytes.size in 1..65_536)
        val json = StrictJson.read(bytes)
        exact(json, "account_generation", "sync_epoch", "as_of", "rule_version", "revision", "source_position",
            "status", "points", "rank", "badges", "ranking")
        rule(json)
        val generation = integer(json, "account_generation", 1).also { require(it <= Int.MAX_VALUE) }.toInt()
        val status = when (text(json, "status")) {
            "pending_backfill" -> MotivationStatus.PENDING_BACKFILL
            "pending_materialization" -> MotivationStatus.PENDING_MATERIALIZATION
            "final" -> MotivationStatus.FINAL
            else -> error("Invalid motivation status")
        }
        val points = optionalInteger(json, "points")
        val rank = optionalText(json, "rank")
        if (status == MotivationStatus.PENDING_BACKFILL) require(points == null && rank == null)
        else {
            require(points != null)
            require(rank == when { points < 20 -> "Rekrut"; points < 60 -> "Szeregowy"; points < 120 -> "Kapral"; else -> "Sierżant" })
        }
        val rows = json.getJSONArray("badges")
        require(rows.length() == 4)
        val badges = (0 until rows.length()).map { index ->
            val row = rows.getJSONObject(index)
            exact(row, "code", "rule_version", "status", "progress", "required", "witness_dates",
                "first_awarded_at", "activated_at", "revoked_at")
            rule(row)
            val code = AchievementCode.entries.single { it.wire == text(row, "code") }
            require(integer(row, "required", 1) == code.required.toLong())
            val progress = integer(row, "progress").also { require(it <= code.required) }.toInt()
            val badgeStatus = when (text(row, "status")) {
                "pending" -> ServerBadgeStatus.PENDING
                "final" -> ServerBadgeStatus.FINAL
                "revoked" -> ServerBadgeStatus.REVOKED
                else -> error("Invalid badge status")
            }
            val dates = row.getJSONArray("witness_dates")
            require(dates.length() <= code.required)
            val witness = (0 until dates.length()).map { dateIndex ->
                val value = dates.get(dateIndex) as String
                require(Regex("\\d{4}-\\d{2}-\\d{2}").matches(value))
                LocalDate.parse(value).also { require(it.year in 1..9999) }
            }
            require(witness.zipWithNext().all { (a, b) -> a < b })
            val first = optionalTimestamp(row, "first_awarded_at")
            val activated = optionalTimestamp(row, "activated_at")
            val revoked = optionalTimestamp(row, "revoked_at")
            if (badgeStatus == ServerBadgeStatus.FINAL) {
                require(progress == code.required && witness.size == code.required && first != null && activated != null)
                when (code) {
                    AchievementCode.COMPLETE_STREAK, AchievementCode.IN_GOAL_STREAK -> require(witness.zipWithNext().all { (a, b) -> a.plusDays(1) == b })
                    AchievementCode.WEIGHT_DAYS -> require(witness.last() <= witness.first().plusDays(13))
                    AchievementCode.RATION_DAYS -> Unit
                }
            } else require(witness.isEmpty())
            // Backfill can return pending while retaining historical award timestamps.
            if (badgeStatus == ServerBadgeStatus.REVOKED) require(first != null && activated != null && revoked != null)
            ServerAchievement(code, badgeStatus, progress, witness, first, activated, revoked)
        }
        require(badges.map { it.code }.toSet().size == 4)
        val ranking = json.getJSONObject("ranking")
        exact(ranking, "requested", "effective", "pending_consent_refresh", "consent_epoch", "own_position")
        val requested = ranking.get("requested") as Boolean
        val effective = ranking.get("effective") as Boolean
        val refresh = ranking.get("pending_consent_refresh") as Boolean
        val position = optionalInteger(ranking, "own_position", 1)
        require(!effective || requested && !refresh)
        require(!refresh || requested && !effective)
        require(position == null || effective)
        return MotivationRead(generation, uuid(json, "sync_epoch"), timestamp(json, "as_of"),
            integer(json, "revision"), integer(json, "source_position"), status, points, rank,
            badges.sortedBy { it.code.ordinal }, MotivationRanking(requested, effective, refresh, uuid(ranking, "consent_epoch"), position))
    }

    private fun exact(json: JSONObject, vararg keys: String) = require(json.keys().asSequence().toSet() == keys.toSet())
    private fun text(json: JSONObject, key: String) = json.get(key) as String
    private fun optionalText(json: JSONObject, key: String) = if (json.get(key) === JSONObject.NULL) null else text(json, key)
    private fun rule(json: JSONObject) = require(text(json, "rule_version") == Achievements.RULE)
    private fun uuid(json: JSONObject, key: String) = text(json, key).also { require(BootstrapProtocol.uuid.matches(it)) }
    private fun integer(json: JSONObject, key: String, minimum: Long = 0): Long {
        val value = json.get(key)
        require(value is Int || value is Long)
        return (value as Number).toString().toBigDecimal().longValueExact().also { require(it >= minimum) }
    }
    private fun optionalInteger(json: JSONObject, key: String, minimum: Long = 0) =
        if (json.get(key) === JSONObject.NULL) null else integer(json, key, minimum)
    private fun timestamp(json: JSONObject, key: String): Instant {
        val value = text(json, key)
        require(Regex("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.[0-9]{1,6})?Z").matches(value))
        require(LocalDateTime.parse(value.dropLast(1)).year in 1..9999)
        return Instant.parse(value)
    }
    private fun optionalTimestamp(json: JSONObject, key: String) = if (json.get(key) === JSONObject.NULL) null else timestamp(json, key)
}
