package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.time.*
import java.time.temporal.ChronoUnit
import java.util.UUID

class NemesisTerms(val days: Int, val zone: ZoneId, val weight: Boolean, val deficit: Boolean) {
    override fun toString() = "NemesisTerms(redacted)"
}
class NemesisChallenge(val id: String, val revision: Int, val role: String, val status: String, val terms: NemesisTerms,
    val invitedAt: Instant, val expiresAt: Instant, val acceptedAt: Instant?, val startDate: LocalDate?, val endDate: LocalDate?,
    val startAt: Instant?, val endAt: Instant?, val deadline: Instant?, val resultStatus: String?, val cancelReason: String?, val partner: String?) {
    override fun toString() = "NemesisChallenge(redacted)"
}
class NemesisPage(val items: List<NemesisChallenge>, val nextCursor: String?) {
    override fun toString() = "NemesisPage(redacted)"
}
sealed interface NemesisMetric {
    data object Hidden : NemesisMetric
    class Insufficient(val days: Int) : NemesisMetric { override fun toString() = "NemesisMetric(insufficient)" }
    class Available(val value: BigDecimal, val days: Int, val first: LocalDate? = null, val last: LocalDate? = null) : NemesisMetric {
        override fun toString() = "NemesisMetric(available,redacted)"
    }
}
class NemesisParticipant(val points: Int, val closedDays: Int, val completeDays: Int, val daysInGoal: Int,
    val weight: NemesisMetric, val deficit: NemesisMetric) {
    override fun toString() = "NemesisParticipant(redacted)"
}
class NemesisStatistics(val revision: Long, val asOf: Instant, val status: String, val self: NemesisParticipant?,
    val opponent: NemesisParticipant?, val outcome: String?, val finalizedAt: Instant?) {
    override fun toString() = "NemesisStatistics(redacted)"
}
sealed interface NemesisState {
    data object NotRequested : NemesisState
    data object Loading : NemesisState
    class ListReady(val page: NemesisPage) : NemesisState
    class DetailReady(val challenge: NemesisChallenge, val statistics: NemesisStatistics?) : NemesisState
    sealed interface Saved:NemesisState {val fetchedAtMillis:Long;val warning:String?}
    class ListSaved(val page:NemesisPage,override val fetchedAtMillis:Long,val cachedDetails:Set<String>,override val warning:String?=null):Saved
    class DetailSaved(val challenge:NemesisChallenge,val statistics:NemesisStatistics?,override val fetchedAtMillis:Long,override val warning:String?=null):Saved
    data class Failed(val message: String, val canRetry: Boolean) : NemesisState
}
internal sealed class NemesisQuery {
    class Listing(val cursor: String? = null) : NemesisQuery() {
        init { cursor?.let(NemesisReadProtocol::uuid) }
        override fun path() = "/me/nemesis?limit=$LIMIT" + (cursor?.let { "&cursor=$it" } ?: "")
    }
    class Detail(val id: String) : NemesisQuery() {
        init { NemesisReadProtocol.uuid(id) }
        override fun path() = "/nemesis/$id"
    }
    class Statistics(val id: String) : NemesisQuery() {
        init { NemesisReadProtocol.uuid(id) }
        override fun path() = "/nemesis/$id/statistics"
    }
    abstract fun path(): String
    final override fun toString() = "NemesisQuery(redacted)"
    companion object { const val LIMIT = 25 }
}

/** Transient, scoped server reads. None of these objects is a sync entity or a local award. */
object NemesisReadProtocol {
    const val MAX_BYTES = 1_048_576
    internal fun uuid(value: String) { require(UUID.fromString(value).toString() == value) }
    private fun read(bytes: ByteArray) = StrictJson.read(bytes.also { require(it.size in 1..MAX_BYTES) })
    internal fun page(bytes: ByteArray, query: NemesisQuery.Listing): NemesisPage {
        val json = read(bytes); exact(json, "items", "next_cursor")
        val rows = json.getJSONArray("items"); require(rows.length() <= NemesisQuery.LIMIT)
        val items = (0 until rows.length()).map { challenge(rows.getJSONObject(it)) }
        require(items.map { it.id }.distinct().size == items.size)
        val cursor = nullable(json, "next_cursor") { (it as String).also(::uuid) }
        require(cursor == null || (items.size == NemesisQuery.LIMIT && cursor != query.cursor))
        return NemesisPage(items.toList(), cursor)
    }
    internal fun detail(bytes: ByteArray, id: String) = challenge(read(bytes)).also { require(it.id == id) }
    internal fun metadata(bytes: ByteArray) = challenge(read(bytes))
    private fun challenge(json: JSONObject): NemesisChallenge {
        exact(json, "id", "revision", "role", "status", "terms", "invited_at", "expires_at", "accepted_at", "start_date", "end_date",
            "start_at", "end_at", "deadline", "result_status", "cancel_reason", "partner_pseudonym")
        val id = (json.get("id") as String).also(::uuid)
        val revision = integer(json, "revision", 1, Int.MAX_VALUE.toLong()).toInt()
        val role = choice(json, "role", "inviter", "invitee")
        val status = choice(json, "status", "invited", "active", "finished", "cancelled")
        val terms = terms(json.getJSONObject("terms"))
        val invited = timestamp(json.get("invited_at") as String); val expires = timestamp(json.get("expires_at") as String)
        require(expires > invited)
        val accepted = nullable(json, "accepted_at") { timestamp(it as String) }
        val startDate = nullable(json, "start_date") { date(it as String) }; val endDate = nullable(json, "end_date") { date(it as String) }
        val start = nullable(json, "start_at") { timestamp(it as String) }; val end = nullable(json, "end_at") { timestamp(it as String) }
        val deadline = nullable(json, "deadline") { timestamp(it as String) }
        val result = nullable(json, "result_status") { (it as String).also { value -> require(value in setOf("provisional", "final")) } }
        val reason = nullable(json, "cancel_reason") { (it as String).also { value -> require(value in setOf("withdrawn", "declined", "sharing_revoked", "expired", "deleted", "restore")) } }
        val partner = nullable(json, "partner_pseudonym") { (it as String).also { value -> require(value.codePointCount(0, value.length) <= 80) } }
        require((status == "cancelled") == (reason != null))
        if (accepted == null) {
            require(listOf(startDate, endDate, start, end, deadline, result).all { it == null })
            require(status in setOf("invited", "cancelled"))
        } else {
            require(status != "invited" && accepted >= invited && accepted < expires)
            require(startDate != null && endDate != null && start != null && end != null && deadline != null)
            require(ChronoUnit.DAYS.between(startDate, endDate) == terms.days.toLong())
            require(start == startDate.atStartOfDay(terms.zone).toInstant() && end == endDate.atStartOfDay(terms.zone).toInstant())
            require(start > accepted && deadline == end.plus(720, ChronoUnit.HOURS))
        }
        // Expiry may be exposed as a virtual cancelled state before the lifecycle worker runs.
        // Never retain the former partner name in a cancelled preview.
        return NemesisChallenge(id, revision, role, status, terms, invited, expires, accepted, startDate, endDate, start, end,
            deadline, result, reason, if (status == "cancelled") null else partner)
    }
    internal fun terms(json: JSONObject): NemesisTerms {
        exact(json, "rule_version", "duration_days", "time_zone", "scope")
        require(json.get("rule_version") == Achievements.RULE)
        val days = integer(json, "duration_days", 7, 90).toInt(); require(days in setOf(7, 30, 90))
        val name = json.get("time_zone") as String
        require(name in ZoneId.getAvailableZoneIds())
        val scope = json.getJSONObject("scope"); exact(scope, "regularity", "weight_change", "mean_deficit")
        require(scope.get("regularity") == true)
        return NemesisTerms(days, ZoneId.of(name), scope.get("weight_change") as Boolean, scope.get("mean_deficit") as Boolean)
    }
    internal fun statistics(bytes: ByteArray, challenge: NemesisChallenge): NemesisStatistics {
        require(challenge.status in setOf("active", "finished"))
        val json = read(bytes); val status = choice(json, "status", "pending", "provisional", "final")
        val common = arrayOf("id", "revision", "rule_version", "as_of", "time_zone", "start_date", "end_date", "deadline", "status")
        exact(json, *(common + when (status) { "pending" -> emptyArray(); "provisional" -> arrayOf("self", "opponent", "outcome"); else -> arrayOf("self", "opponent", "outcome", "finalized_at") }))
        require(json.get("id") == challenge.id && json.get("rule_version") == Achievements.RULE && json.get("time_zone") == challenge.terms.zone.id)
        require(date(json.get("start_date") as String) == challenge.startDate && date(json.get("end_date") as String) == challenge.endDate)
        require(timestamp(json.get("deadline") as String) == challenge.deadline)
        val revision = integer(json, "revision", 1); val asOf = timestamp(json.get("as_of") as String)
        if (status == "pending") return NemesisStatistics(revision, asOf, status, null, null, null, null)
        val self = participant(json.getJSONObject("self"), challenge); val opponent = participant(json.getJSONObject("opponent"), challenge)
        require(self.closedDays == opponent.closedDays)
        val outcome = choice(json, "outcome", "self_wins", "opponent_wins", "tie")
        require(outcome == when { self.points > opponent.points -> "self_wins"; self.points < opponent.points -> "opponent_wins"; else -> "tie" })
        val finalized = if (status == "final") timestamp(json.get("finalized_at") as String).also {
            require(it > checkNotNull(challenge.deadline) && it <= asOf && self.closedDays == challenge.terms.days)
        } else null
        return NemesisStatistics(revision, asOf, status, self, opponent, outcome, finalized)
    }
    private fun participant(json: JSONObject, challenge: NemesisChallenge): NemesisParticipant {
        exact(json, "regularity", "weight_change", "mean_deficit")
        val score = json.getJSONObject("regularity"); exact(score, "points", "closed_days", "complete_days", "days_in_goal")
        val closed = integer(score, "closed_days", 1, challenge.terms.days.toLong()).toInt()
        val complete = integer(score, "complete_days", 0, closed.toLong()).toInt()
        val goal = integer(score, "days_in_goal", 0, complete.toLong()).toInt()
        val points = integer(score, "points", 0, 180).toInt(); require(points == complete + goal)
        val weight = metric(json.getJSONObject("weight_change"), true, challenge.terms.weight, closed, challenge)
        val deficit = metric(json.getJSONObject("mean_deficit"), false, challenge.terms.deficit, complete, challenge)
        return NemesisParticipant(points, closed, complete, goal, weight, deficit)
    }
    private fun metric(json: JSONObject, weight: Boolean, permitted: Boolean, limit: Int, challenge: NemesisChallenge): NemesisMetric {
        val state = choice(json, "state", "hidden", "insufficient_data", "available")
        if (state == "hidden") { exact(json, "state"); return NemesisMetric.Hidden }
        require(permitted)
        val countKey = if (weight) "observed_days" else "eligible_days"
        if (state == "insufficient_data") {
            exact(json, "state", "value", countKey); require(json.get("value") === JSONObject.NULL)
            return NemesisMetric.Insufficient(integer(json, countKey, 0, minOf(limit, if (weight) 1 else 0).toLong()).toInt())
        }
        exact(json, *(arrayOf("state", "value", countKey) + if (weight) arrayOf("first_date", "last_date") else emptyArray()))
        val value = json.get("value") as String
        require(value != "-0" && Regex("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]{0,11}[1-9])?").matches(value))
        val days = integer(json, countKey, if (weight) 2 else 1, limit.toLong()).toInt()
        val first = if (weight) date(json.get("first_date") as String) else null
        val last = if (weight) date(json.get("last_date") as String) else null
        if (weight) {
            require(first!! >= checkNotNull(challenge.startDate) && last!! < checkNotNull(challenge.endDate) && first < last)
            require(days <= ChronoUnit.DAYS.between(first, last) + 1)
        }
        return NemesisMetric.Available(BigDecimal(value), days, first, last)
    }
    private fun exact(json: JSONObject, vararg keys: String) = require(json.keys().asSequence().toSet() == keys.toSet())
    private fun integer(json: JSONObject, key: String, min: Long = 0, max: Long = Long.MAX_VALUE): Long {
        val value = json.get(key); require(value is Int || value is Long)
        return (value as Number).toLong().also { require(it in min..max) }
    }
    private fun choice(json: JSONObject, key: String, vararg values: String) = (json.get(key) as String).also { require(it in values) }
    private fun <T> nullable(json: JSONObject, key: String, parse: (Any) -> T): T? = if (json.get(key) === JSONObject.NULL) null else parse(json.get(key))
    private fun date(value: String) = LocalDate.parse(value.also { require(Regex("\\d{4}-\\d{2}-\\d{2}").matches(it)) }).also { require(it.year in 1..9999) }
    internal fun timestamp(value: String): Instant {
        require(Regex("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.[0-9]{1,6})?Z").matches(value))
        require(LocalDateTime.parse(value.dropLast(1)).year in 1..9999)
        return Instant.parse(value)
    }
}
