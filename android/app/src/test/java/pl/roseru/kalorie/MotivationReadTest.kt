package pl.roseru.kalorie

import org.json.JSONObject
import org.json.JSONArray
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*

class MotivationReadTest {
    private fun bytes(name: String = "final") = javaClass.classLoader!!.getResource("motivation/motivation-$name.json")!!.readBytes()
    private fun json(name: String = "final") = JSONObject(String(bytes(name), Charsets.UTF_8))
    private fun parse(row: JSONObject) = MotivationReadProtocol.parse(row.toString().toByteArray())
    private fun rejected(block: () -> Unit) { assertThrows(Exception::class.java, block) }
    @Test fun fourDeliveredExamplesKeepStatusNullsRevisionAndRankingConsent() {
        listOf("final", "revoked", "pending-materialization", "pending-backfill").forEach { name ->
            val data = MotivationReadProtocol.parse(bytes(name))
            assertEquals(4, data.badges.size)
            assertEquals(1, data.accountGeneration)
            assertEquals(1L, data.revision)
            assertTrue(data.ranking.requested); assertFalse(data.ranking.effective); assertTrue(data.ranking.pendingConsentRefresh)
            assertNull(data.ranking.ownPosition)
        }
        val pending = MotivationReadProtocol.parse(bytes("pending-backfill"))
        assertNull(pending.points); assertNull(pending.rank)
        assertEquals(ServerBadgeStatus.REVOKED, MotivationReadProtocol.parse(bytes("revoked")).badges.first().status)
        assertEquals(20L, MotivationReadProtocol.parse(bytes("pending-materialization")).points)
    }
    @Test fun unknownFieldsCodesRulesAndMissingFieldsAreRejectedAtEveryLevel() {
        listOf<(JSONObject) -> Unit>(
            { it.put("account_id", "injected") }, { it.remove("rank") }, { it.put("rule_version", "next_v2") },
            { it.put("status", "finished") }, { it.getJSONObject("ranking").put("extra", true) },
            { it.getJSONObject("ranking").remove("consent_epoch") },
            { it.getJSONArray("badges").getJSONObject(0).put("extra", false) },
            { it.getJSONArray("badges").getJSONObject(0).put("code", "calories_4000") },
            { it.getJSONArray("badges").getJSONObject(0).put("rule_version", "next_v2") }
        ).forEach { change -> rejected { parse(json().apply(change)) } }
    }
    @Test fun integerTypesBoundsAndNullableCountsAreStrictWithoutDoubleRounding() {
        for (field in listOf("account_generation", "revision", "source_position", "points")) {
            listOf<Any>(true, "1", 1.5, -1).forEach { value -> rejected { parse(json().put(field, value)) } }
        }
        rejected { parse(json().put("account_generation", 0)) }
        rejected { parse(json().put("account_generation", 2147483648L)) }
        assertEquals(Long.MAX_VALUE, parse(json().put("revision", Long.MAX_VALUE)).revision)
        assertEquals(Long.MAX_VALUE, parse(json().put("points", Long.MAX_VALUE).put("rank", "Sierżant")).points)
        val fractional = String(bytes()).replace("\"revision\": 1", "\"revision\": 1.0")
        rejected { MotivationReadProtocol.parse(fractional.toByteArray()) }
        val overflow = String(bytes()).replace("\"revision\": 1", "\"revision\": 9223372036854775808")
        rejected { MotivationReadProtocol.parse(overflow.toByteArray()) }
    }
    @Test fun pendingBackfillDoesNotBecomeZeroAndKnownPointsMustHaveConsistentRank() {
        rejected { parse(json("pending-backfill").put("points", 0)) }
        rejected { parse(json().put("points", JSONObject.NULL)) }
        rejected { parse(json().put("rank", "Rekrut")) }
        rejected { parse(json().put("rank", JSONObject.NULL)) }
        listOf(0L to "Rekrut", 19L to "Rekrut", 20L to "Szeregowy", 59L to "Szeregowy", 60L to "Kapral", 119L to "Kapral", 120L to "Sierżant")
            .forEach { (points, rank) -> assertEquals(rank, parse(json().put("points", points).put("rank", rank)).rank) }
    }
    @Test fun badgesAreExactlyFourUniqueKnownCodesAndProgressCannotExceedItsTarget() {
        rejected { parse(json().apply { getJSONArray("badges").remove(0) }) }
        rejected { parse(json().apply { getJSONArray("badges").put(getJSONArray("badges").getJSONObject(0)) }) }
        rejected { parse(json().apply { getJSONArray("badges").put(1, getJSONArray("badges").getJSONObject(0)) }) }
        rejected { parse(json().apply { getJSONArray("badges").getJSONObject(2).put("required", 10) }) }
        rejected { parse(json().apply { getJSONArray("badges").getJSONObject(2).put("progress", 5) }) }
    }
    @Test fun rankingStateRequiresBooleanTypesAndDoesNotInventPublicationOrPosition() {
        listOf("requested", "effective", "pending_consent_refresh").forEach { key ->
            rejected { parse(json().apply { getJSONObject("ranking").put(key, "true") }) }
        }
        rejected { parse(json().apply { getJSONObject("ranking").put("effective", true) }) }
        rejected { parse(json().apply { getJSONObject("ranking").put("own_position", 1) }) }
        val actual = json().apply { getJSONObject("ranking").put("effective", true).put("pending_consent_refresh", false).put("own_position", 1) }
        assertEquals(1L, parse(actual).ranking.ownPosition)
        rejected { parse(actual.apply { getJSONObject("ranking").put("own_position", 0) }) }
    }
    @Test fun timestampsUuidsMalformedUtf8DuplicatesAndSizeAreRejected() {
        listOf("2026-02-30T00:00:00Z", "2026-10-12T00:00:00+00:00", "2026-10-12T00:00:00.1234567Z", "0000-01-01T00:00:00Z").forEach {
            rejected { parse(json().put("as_of", it)) }
        }
        rejected { parse(json().put("sync_epoch", "invalid")) }
        rejected { MotivationReadProtocol.parse(byteArrayOf(0xc3.toByte(), 0x28)) }
        rejected { MotivationReadProtocol.parse(ByteArray(65_537) { 32 }) }
        rejected { MotivationReadProtocol.parse(("{\"revision\": 1," + String(bytes()).drop(1)).toByteArray()) }
    }
    @Test fun privateDtosToStringAreRedacted() {
        val data = MotivationReadProtocol.parse(bytes())
        assertEquals("MotivationRead(redacted)", data.toString())
        assertEquals("MotivationRanking(redacted)", data.ranking.toString())
        assertTrue(data.badges.all { it.toString() == "ServerAchievement(redacted)" })
    }
    @Test fun finalWitnessDatesMustProveTheExactRuleAndRevokedHasNoActiveWitness() {
        fun awarded(index: Int, dates: List<String>) = json().apply {
            getJSONArray("badges").getJSONObject(index).put("status", "final")
                .put("progress", getJSONArray("badges").getJSONObject(index).getInt("required"))
                .put("witness_dates", JSONArray(dates)).put("first_awarded_at", "2026-10-11T00:00:00Z")
                .put("activated_at", "2026-10-11T00:00:00Z")
        }
        val streak = (1..10).map { "2026-10-${it.toString().padStart(2, '0')}" }
        assertEquals(10, parse(awarded(0, streak)).badges[0].witnessDates.size)
        rejected { parse(awarded(0, streak.dropLast(1))) }
        rejected { parse(awarded(0, streak.dropLast(1) + "2026-10-11")) }
        rejected { parse(awarded(0, streak.reversed())) }
        rejected { parse(awarded(0, streak.dropLast(1) + "2026-10-09")) }
        assertEquals(4, parse(awarded(2, listOf("2026-09-28", "2026-10-01", "2026-10-05", "2026-10-11"))).badges[2].witnessDates.size)
        rejected { parse(awarded(2, listOf("2026-09-27", "2026-10-01", "2026-10-05", "2026-10-11"))) }
        rejected { parse(awarded(0, streak).apply { getJSONArray("badges").getJSONObject(0).put("activated_at", JSONObject.NULL) }) }
        rejected { parse(json("revoked").apply { getJSONArray("badges").getJSONObject(0).put("revoked_at", JSONObject.NULL) }) }
        rejected { parse(json("revoked").apply { getJSONArray("badges").getJSONObject(0).put("witness_dates", JSONArray(streak)) }) }
        val restored = json("pending-backfill").apply {
            getJSONArray("badges").getJSONObject(0).put("first_awarded_at", "2026-10-10T00:00:00Z").put("activated_at", "2026-10-10T00:00:00Z")
        }
        assertNotNull(parse(restored).badges[0].firstAwardedAt)
    }
}
