package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.Instant
import java.time.LocalDateTime

class RankingEntry(val position: Long, val pseudonym: String, val points: Long, val rank: String, val activeBadges: Int) {
    override fun toString() = "RankingEntry(redacted)"
}
class RankingPage(val asOf: Instant, val items: List<RankingEntry>, val nextPageToken: String?, val expiresAt: Instant?) {
    val hasMore get() = nextPageToken != null
    override fun toString() = "RankingPage(redacted)"
}
sealed interface RankingState {
    data object NotRequested : RankingState
    data object Loading : RankingState
    data class Ready(val page: RankingPage) : RankingState
    data class Failed(val message: String, val canRetry: Boolean) : RankingState
}
internal class RankingQuery(val pageToken: String? = null) {
    init { require(pageToken == null || RankingReadProtocol.cursor.matches(pageToken)) }
    fun encoded() = "limit=$LIMIT" + (pageToken?.let { "&page_token=$it" } ?: "")
    override fun toString() = "RankingQuery(redacted)"
    companion object { const val LIMIT = 25 }
}

/** A bounded live page, never a frozen leaderboard, sync checkpoint or local award. */
object RankingReadProtocol {
    internal val cursor = Regex("rk1\\.[A-Za-z0-9_-]{43}")
    internal fun parse(bytes: ByteArray, query: RankingQuery = RankingQuery()): RankingPage {
        require(bytes.size in 1..65_536)
        val json = StrictJson.read(bytes)
        exact(json, "rule_version", "pagination", "as_of", "items", "has_more", "next_page_token", "cursor_expires_at")
        require(json.get("rule_version") == Achievements.RULE && json.get("pagination") == "live_keyset_v1")
        val asOf = timestamp(json.get("as_of") as String)
        val rows = json.getJSONArray("items")
        require(rows.length() <= RankingQuery.LIMIT)
        val items = (0 until rows.length()).map { index ->
            val row = rows.getJSONObject(index)
            exact(row, "position", "pseudonym", "points", "rank", "active_badges")
            val points = integer(row, "points")
            val pseudonym = row.get("pseudonym") as String
            require(pseudonym.codePointCount(0, pseudonym.length) in 1..80)
            val rank = row.get("rank") as String
            require(rank == when { points < 20 -> "Rekrut"; points < 60 -> "Szeregowy"; points < 120 -> "Kapral"; else -> "Sierżant" })
            RankingEntry(integer(row, "position", 1), pseudonym, points, rank, integer(row, "active_badges").also { require(it <= 4) }.toInt())
        }
        // Keep equal names and positions: no disclosed user ID permits safe client deduplication.
        require(items.zipWithNext().all { (a, b) ->
            a.points >= b.points && if (a.points == b.points) a.position == b.position else a.position < b.position
        })
        val hasMore = json.get("has_more") as Boolean
        val token = if (json.get("next_page_token") === JSONObject.NULL) null else (json.get("next_page_token") as String).also {
            require(cursor.matches(it) && it != query.pageToken)
        }
        val expiry = if (json.get("cursor_expires_at") === JSONObject.NULL) null else timestamp(json.get("cursor_expires_at") as String)
        require(if (hasMore) items.size == RankingQuery.LIMIT && token != null && expiry != null && expiry > asOf
            else token == null && expiry == null)
        return RankingPage(asOf, items.toList(), token, expiry)
    }
    private fun exact(json: JSONObject, vararg keys: String) = require(json.keys().asSequence().toSet() == keys.toSet())
    private fun integer(json: JSONObject, key: String, minimum: Long = 0): Long {
        val value = json.get(key)
        require(value is Int || value is Long)
        return (value as Number).toLong().also { require(it >= minimum) }
    }
    private fun timestamp(value: String): Instant {
        require(Regex("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.[0-9]{1,6})?Z").matches(value))
        require(LocalDateTime.parse(value.dropLast(1)).year in 1..9999)
        return Instant.parse(value)
    }
}
