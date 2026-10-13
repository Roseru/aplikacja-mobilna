package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import java.math.BigDecimal
import java.time.*
import java.time.temporal.ChronoUnit

class NemesisReadProtocolTest {
    private val id = "12345678-1234-5678-9234-123456789abc"
    private fun example(name: String) = JSONObject(checkNotNull(javaClass.getResource("/nemesis/$name.json")).readText())
    private fun metadata(days: Int = 7, startDate: LocalDate = LocalDate.parse("2026-10-13"), scope: Boolean = true): JSONObject {
        val zone = ZoneId.of("Europe/Warsaw"); val start = startDate.atStartOfDay(zone).toInstant()
        val accepted = start.minusSeconds(12 * 3600); val invited = accepted.minusSeconds(3600)
        val end = startDate.plusDays(days.toLong()).atStartOfDay(zone).toInstant()
        return JSONObject().put("id", id).put("revision", 1).put("role", "invitee").put("status", "active")
            .put("terms", JSONObject().put("rule_version", "regularity_v1").put("duration_days", days).put("time_zone", zone.id)
                .put("scope", JSONObject().put("regularity", true).put("weight_change", scope).put("mean_deficit", scope)))
            .put("invited_at", invited.toString()).put("expires_at", invited.plusSeconds(86400).toString()).put("accepted_at", accepted.toString())
            .put("start_date", startDate.toString()).put("end_date", startDate.plusDays(days.toLong()).toString())
            .put("start_at", start.toString()).put("end_at", end.toString()).put("deadline", end.plus(720, ChronoUnit.HOURS).toString())
            .put("result_status", "provisional").put("cancel_reason", JSONObject.NULL).put("partner_pseudonym", "Nemesis fixture")
    }
    private fun readMetadata(value: JSONObject = metadata()) = NemesisReadProtocol.detail(value.toString().toByteArray(), id)
    private fun stats(value: JSONObject, scope: Boolean = true) = NemesisReadProtocol.statistics(value.toString().toByteArray(), readMetadata(metadata(scope = scope)))
    @Test fun allPublishedVariantsParseAndPendingContainsNoInventedScore() {
        val pending = stats(example("pending"))
        assertEquals("pending", pending.status); assertNull(pending.self); assertNull(pending.opponent); assertNull(pending.outcome)
        val provisional = stats(example("provisional")); assertEquals("self_wins", provisional.outcome)
        assertEquals(4, provisional.self!!.points); assertEquals(1, provisional.opponent!!.points)
        assertEquals("final", stats(example("final")).status)
        assertSame(NemesisMetric.Hidden, stats(example("hidden"), false).self!!.weight)
        assertThrows(Exception::class.java) { stats(example("pending").put("self", JSONObject())) }
    }
    @Test fun missingHiddenAvailableZeroAndNegativeValuesStayDistinctAndExact() {
        val result = stats(example("provisional"))
        assertEquals(BigDecimal("-15"), (result.self!!.deficit as NemesisMetric.Available).value)
        assertEquals(BigDecimal.ZERO, (result.opponent!!.deficit as NemesisMetric.Available).value)
        assertEquals(1, (result.opponent!!.weight as NemesisMetric.Insufficient).days)
        for (valid in listOf("-0.000000000001", "123456789012345678901234567890")) {
            val json = example("provisional"); json.getJSONObject("self").getJSONObject("mean_deficit").put("value", valid)
            assertEquals(BigDecimal(valid), (stats(json).self!!.deficit as NemesisMetric.Available).value)
        }
        for (invalid in listOf("-0", "0.0", "1.0", "01", "+1", "1e2", "NaN", "1.1234567890123")) {
            val json = example("provisional"); json.getJSONObject("self").getJSONObject("mean_deficit").put("value", invalid)
            assertThrows(Exception::class.java) { stats(json) }
        }
        val numeric = example("provisional"); numeric.getJSONObject("self").getJSONObject("mean_deficit").put("value", -15)
        assertThrows(Exception::class.java) { stats(numeric) }
        val extra = example("hidden"); extra.getJSONObject("self").getJSONObject("weight_change").put("observed_days", 0)
        assertThrows(Exception::class.java) { stats(extra, false) }
        assertThrows(Exception::class.java) { stats(example("provisional"), false) }
    }
    @Test fun readRevisionIs64BitButLifecycleRevisionRemains32Bit() {
        val value = example("provisional").put("revision", Long.MAX_VALUE)
        assertEquals(Long.MAX_VALUE, stats(value).revision)
        assertEquals(Int.MAX_VALUE, readMetadata(metadata().put("revision", Int.MAX_VALUE)).revision)
        assertThrows(Exception::class.java) { readMetadata(metadata().put("revision", Int.MAX_VALUE.toLong() + 1)) }
        assertThrows(Exception::class.java) { stats(value.put("revision", 0)) }
        val integerWire = example("provisional").toString()
        assertTrue(integerWire.contains("\"revision\":8"))
        assertThrows(Exception::class.java) { NemesisReadProtocol.statistics(integerWire.replace("\"revision\":8", "\"revision\":8.0").toByteArray(), readMetadata()) }
    }
    @Test fun outcomeCountsDatesAndFinalizationMustMatchTheAgreedSnapshot() {
        assertThrows(Exception::class.java) { stats(example("provisional").put("outcome", "opponent_wins")) }
        val counts = example("provisional"); counts.getJSONObject("self").getJSONObject("regularity").put("points", 5)
        assertThrows(Exception::class.java) { stats(counts) }
        val days = example("provisional"); days.getJSONObject("opponent").getJSONObject("regularity").put("closed_days", 6)
        assertThrows(Exception::class.java) { stats(days) }
        val date = example("provisional"); date.getJSONObject("self").getJSONObject("weight_change").put("last_date", "2026-10-20")
        assertThrows(Exception::class.java) { stats(date) }
        assertThrows(Exception::class.java) { stats(example("final").put("finalized_at", "2026-11-18T22:00:00Z")) }
        assertThrows(Exception::class.java) { stats(example("final").put("finalized_at", "2026-11-21T00:00:00Z")) }
        assertThrows(Exception::class.java) { stats(example("pending").put("id", "22345678-1234-5678-9234-123456789abc")) }
        assertThrows(Exception::class.java) { stats(example("pending").put("time_zone", "UTC")) }
    }
    @Test fun calendarPeriodsRespectDstAndDeadlineIs720UtcHours() {
        for (duration in listOf(7, 30, 90)) {
            val challenge = readMetadata(metadata(duration, LocalDate.parse("2026-03-25")))
            assertEquals(duration.toLong(), ChronoUnit.DAYS.between(challenge.startDate, challenge.endDate))
            assertEquals(duration * 24L - 1, Duration.between(challenge.startAt, challenge.endAt).toHours())
            assertEquals(720L, Duration.between(challenge.endAt, challenge.deadline).toHours())
        }
        assertThrows(Exception::class.java) { readMetadata(metadata().put("end_at", "2026-10-20T00:00:00Z")) }
    }
    @Test fun cancellationRemovesPartnerAndPagesValidateCursorsWithoutDeduplicatingNames() {
        val cancelled = readMetadata(metadata().put("status", "cancelled").put("cancel_reason", "sharing_revoked"))
        assertNull(cancelled.partner)
        val row = metadata(); val rows = JSONArray(listOf(row, metadata().put("id", "22345678-1234-5678-9234-123456789abc")))
        val page = NemesisReadProtocol.page(JSONObject().put("items", rows).put("next_cursor", JSONObject.NULL).toString().toByteArray(), NemesisQuery.Listing())
        assertEquals(2, page.items.size); assertEquals(page.items[0].partner, page.items[1].partner)
        assertThrows(Exception::class.java) { NemesisQuery.Detail("../me") }
        assertThrows(Exception::class.java) { NemesisQuery.Listing("https://other.example") }
        assertFalse(page.toString().contains("Nemesis fixture")); assertFalse(cancelled.toString().contains(id))
    }
    @Test fun strictUtf8UnknownFieldsDuplicateKeysAndBoundsCannotBecomeSnapshots() {
        val payload = example("pending").toString()
        assertThrows(Exception::class.java) { NemesisReadProtocol.statistics(byteArrayOf(0xc3.toByte(), 0x28), readMetadata()) }
        assertThrows(Exception::class.java) { NemesisReadProtocol.statistics(ByteArray(NemesisReadProtocol.MAX_BYTES + 1), readMetadata()) }
        assertThrows(Exception::class.java) { stats(example("pending").put("partner_uuid", id)) }
        assertThrows(Exception::class.java) { NemesisReadProtocol.statistics(payload.replaceFirst("{", "{\"status\":\"pending\"," ).toByteArray(), readMetadata()) }
    }
}
