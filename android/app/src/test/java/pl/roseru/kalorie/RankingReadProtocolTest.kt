package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*

class RankingReadProtocolTest {
    private val token = "rk1." + "A".repeat(43)
    private fun entry(position: Long = 1, points: Long = 10, name: String = "Żołnierz") = JSONObject()
        .put("position", position).put("pseudonym", name).put("points", points)
        .put("rank", if (points < 20) "Rekrut" else if (points < 60) "Szeregowy" else if (points < 120) "Kapral" else "Sierżant").put("active_badges", 2)
    private fun page(rows: List<JSONObject> = listOf(entry()), more: Boolean = false) = JSONObject()
        .put("rule_version", "regularity_v1").put("pagination", "live_keyset_v1").put("as_of", "2026-10-13T10:00:00.123456Z")
        .put("items", JSONArray(rows)).put("has_more", more).put("next_page_token", if (more) token else JSONObject.NULL)
        .put("cursor_expires_at", if (more) "2026-10-13T10:10:00Z" else JSONObject.NULL)
    private fun parse(value: JSONObject) = RankingReadProtocol.parse(value.toString().toByteArray())
    @Test fun tiesKeepServerPositionsAndEqualPseudonymsAreNotDeduplicated() {
        val value = parse(page(listOf(entry(), entry(), entry(3, 8))))
        assertEquals(listOf(1L, 1L, 3L), value.items.map { it.position }); assertEquals(3, value.items.size)
        assertEquals(listOf(10L, 10L, 8L), value.items.map { it.points }); assertFalse(value.hasMore)
        assertFalse(value.toString().contains("Żołnierz")); assertFalse(value.items[0].toString().contains("Żołnierz"))
        assertTrue(parse(page(emptyList())).items.isEmpty())
    }
    @Test fun longCountsDeepPositionsAndUnicodeNamesStayExact() {
        val value = parse(page(listOf(entry(Long.MAX_VALUE, Long.MAX_VALUE, "🪖".repeat(80)))))
        assertEquals(Long.MAX_VALUE, value.items.single().points); assertEquals(Long.MAX_VALUE, value.items.single().position)
        assertEquals("Sierżant", value.items.single().rank)
        assertThrows(Exception::class.java) { parse(page(listOf(entry(name = "🪖".repeat(81))))) }
    }
    @Test fun cursorIsOpaqueBoundToFixedLimitAndCannotLoopOrSurviveTerminalPage() {
        val rows = List(25) { entry() }; val json = page(rows, true)
        val value = parse(json); assertTrue(value.hasMore); assertEquals(token, value.nextPageToken); assertNotNull(value.expiresAt)
        assertEquals("limit=25&page_token=$token", RankingQuery(token).encoded())
        assertFalse(RankingQuery(token).toString().contains(token))
        assertThrows(Exception::class.java) { RankingReadProtocol.parse(json.toString().toByteArray(), RankingQuery(token)) }
        for (bad in listOf("https://evil", "rk1." + "A".repeat(42), token + "&owner=x", " rk1." + "A".repeat(43))) {
            assertThrows(Exception::class.java) { RankingQuery(bad) }
        }
        for (bad in listOf(page(rows, true).put("cursor_expires_at", JSONObject.NULL), page(rows, true).put("cursor_expires_at", "2026-10-13T10:00:00Z"),
            page(rows.take(24), true), page(rows + entry()), page().put("next_page_token", token), page().put("cursor_expires_at", "2026-10-13T10:10:00Z"))) {
            assertThrows(Exception::class.java) { parse(bad) }
        }
    }
    @Test fun malformedFieldsTypesRuleRankAndOrderingAreRejected() {
        for (bad in listOf(page().put("owner_id", "private"), page().put("rule_version", "other"), page().put("pagination", "offset"),
            page().put("has_more", 0), page().put("as_of", "2026-02-30T10:00:00Z"), page().put("as_of", "2026-10-13T10:00:00+00:00"),
            page(listOf(entry().put("active_badges", 5))), page(listOf(entry().put("pseudonym", ""))), page(listOf(entry().put("rank", "Kapral"))),
            page(listOf(entry().put("position", 0))), page(listOf(entry().put("points", "10"))), page(listOf(entry().put("points", -1))),
            page(listOf(entry().put("account_id", "private"))), page(listOf(entry(1, 8), entry(2, 10))),
            page(listOf(entry(1, 10), entry(2, 10))), page(listOf(entry(1, 10), entry(1, 8))))) {
            assertThrows(Exception::class.java) { parse(bad) }
        }
    }
    @Test fun strictWireRejectsDuplicatesFractionalNumbersOverflowAndInvalidEncoding() {
        val wire = page().toString()
        for (bad in listOf(wire.replace("\"points\":10", "\"points\":10.0"), wire.replace("\"points\":10", "\"points\":1e1"),
            wire.replace("\"points\":10", "\"points\":9223372036854775808"), wire.replace("\"has_more\":false", "\"has_more\":false,\"has_more\":true"))) {
            assertThrows(Exception::class.java) { RankingReadProtocol.parse(bad.toByteArray()) }
        }
        assertThrows(Exception::class.java) { RankingReadProtocol.parse(byteArrayOf(0xc3.toByte(), 0x28)) }
        assertThrows(Exception::class.java) { RankingReadProtocol.parse(ByteArray(65_537)) }
    }
}
