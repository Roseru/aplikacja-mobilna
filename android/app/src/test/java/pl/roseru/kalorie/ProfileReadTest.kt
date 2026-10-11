package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*

class ProfileReadTest {
    private fun example() = javaClass.getResourceAsStream("/profile-read.json")!!.use { it.readBytes() }
    private fun parse(change: (JSONObject) -> Unit): ProfileRead = ProfileReadProtocol.parse(
        JSONObject(String(example(), Charsets.UTF_8)).also(change).toString().toByteArray())
    @Test fun contractExampleKeepsExactValuesAndNullIsNotAnEmptyLocalProfile() {
        val result = ProfileReadProtocol.parse(example())
        assertEquals("Użytkownik demo", result.profile!!.pseudonym)
        assertEquals("180", result.profile.heightCm)
        assertEquals(ActivityClass.LINE, result.profile.activityClass)
        assertEquals(0, result.goalTimelineRevision)
        assertFalse(result.consents.ranking)
        assertEquals("2026-10-09T10:00:00Z", result.consents.updatedAt)
        assertNull(parse { it.put("profile", JSONObject.NULL) }.profile)
        assertNull(parse { it.getJSONObject("profile").getJSONObject("payload").put("height_cm", JSONObject.NULL) }.profile!!.heightCm)
        assertEquals("180.123456", parse { it.getJSONObject("profile").getJSONObject("payload").put("height_cm", "180.123456") }.profile!!.heightCm)
        assertFalse(result.toString().contains(result.accountId))
        assertFalse(result.profile.toString().contains("demo"))
    }
    @Test fun rejectsAmbiguousJsonUnknownFieldsAndCoercedNumbersOrBooleans() {
        val text = String(example(), Charsets.UTF_8)
        assertThrows(Exception::class.java) { ProfileReadProtocol.parse(text.replace("\"goal_timeline_revision\": 0",
            "\"goal_timeline_revision\": 0, \"goal_timeline_revision\": 1").toByteArray()) }
        for (change in listOf<(JSONObject) -> Unit>(
            { it.put("extra", true) }, { it.remove("profile") }, { it.put("goal_timeline_revision", "0") },
            { it.put("goal_timeline_revision", 2147483648L) }, { it.put("goal_timeline_revision", -1) },
            { it.getJSONObject("consents").put("ranking", "false") },
            { it.getJSONObject("profile").put("revision", 0) },
            { it.getJSONObject("profile").getJSONObject("payload").put("height_cm", 180) }))
            assertThrows(Exception::class.java) { parse(change) }
    }
    @Test fun validatesCanonicalDecimalsUnicodeTimezoneAndCivilTimestamp() {
        for ((key, value) in listOf("height_cm" to "180.0", "height_cm" to "0", "height_cm" to "300.000001",
            "height_cm" to "1e2", "height_cm" to "180.1234567", "activity_class" to "unknown",
            "time_zone" to "+02:00", "time_zone" to "Mars/Base", "pseudonym" to "", "pseudonym" to "a\u0000b",
            "pseudonym" to "a".repeat(81)))
            assertThrows(Exception::class.java) { parse { it.getJSONObject("profile").getJSONObject("payload").put(key, value) } }
        for (time in listOf("2026-02-30T10:00:00Z", "2026-10-09T10:00:00+00:00", "2026-10-09T10:00:00.1234567Z", "0000-10-09T10:00:00Z"))
            assertThrows(Exception::class.java) { parse { it.getJSONObject("consents").put("updated_at", time) } }
        assertEquals("😀".repeat(80), parse { it.getJSONObject("profile").getJSONObject("payload").put("pseudonym", "😀".repeat(80)) }.profile!!.pseudonym)
    }
    @Test fun malformedUtf8SizeAndWrongAccountIdentifierAreRejected() {
        for (bytes in listOf(byteArrayOf(0xC3.toByte(), 0x28), ByteArray(65_537), ByteArray(0)))
            assertThrows(Exception::class.java) { ProfileReadProtocol.parse(bytes) }
        assertThrows(Exception::class.java) { parse { it.put("account_id", "not-a-uuid") } }
        assertThrows(Exception::class.java) { parse { it.put("sync_epoch", it.getString("sync_epoch").uppercase()) } }
    }
}
