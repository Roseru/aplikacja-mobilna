package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.PhotoCapabilitiesProtocol

class PhotoCapabilitiesProtocolTest {
    private fun json() = JSONObject(checkNotNull(javaClass.getResource("/photo/photo-capabilities.json")).readText())
    private fun parse(value: JSONObject) = PhotoCapabilitiesProtocol.parse(value.toString().toByteArray())
    private fun invalid(value: JSONObject) { assertThrows(Exception::class.java) { parse(value) } }
    @Test fun availableAndUnavailableHaveExplicitProviderLimitsAndReason() {
        val read = parse(json())
        assertTrue(read.available); assertEquals("gemini", read.provider); assertEquals(10, read.dailyPhotos)
        val unavailable = parse(json().put("available", false).put("unavailable_reason", "ai_live_confirmation_required"))
        assertFalse(unavailable.available); assertEquals("ai_live_confirmation_required", unavailable.unavailableReason)
        val mock = json().put("provider", "mock")
        mock.getJSONObject("profile").put("provider", "mock").put("model", "mock-food-v1").put("mock_scenario", "balanced_meal")
        assertEquals("mock", parse(mock).provider)
    }
    @Test fun unknownNoticeProviderAndInconsistentAvailabilityAreRejected() {
        invalid(json().put("notice_version", "food-photo-notice-v2"))
        invalid(json().put("provider", "other"))
        invalid(json().put("available", false))
        invalid(json().put("unavailable_reason", "unavailable"))
        val wrong = json(); wrong.getJSONObject("profile").put("provider", "mock"); invalid(wrong)
    }
    @Test fun MissingNullFieldsAndUnexpectedFieldsCannotSilentlyGrantAvailability() {
        invalid(json().put("secret", "not-a-real-secret"))
        val missing = json(); missing.remove("unavailable_reason"); invalid(missing)
        val badProfile = json(); badProfile.getJSONObject("profile").put("pool_scope", "unexpected"); invalid(badProfile)
        invalid(json().put("manual_entry_available", false))
        invalid(json().put("available", "true"))
    }
    @Test fun NumericBoundsRejectStringsDecimalsZeroAndExcessiveLimits() {
        for (value in listOf<Any>("10", 1.5, 0, 11, true)) invalid(json().put("daily_photos", value))
        invalid(json().put("image_bytes", 5242881))
        invalid(json().put("max_generate_attempts", 3))
    }
    @Test fun DuplicateKeysMalformedUtf8AndOversizedBodiesAreRejected() {
        val duplicate = json().toString().dropLast(1) + ",\"available\":true}"
        assertThrows(Exception::class.java) { PhotoCapabilitiesProtocol.parse(duplicate.toByteArray()) }
        assertThrows(Exception::class.java) { PhotoCapabilitiesProtocol.parse(byteArrayOf(0xc3.toByte(), 0x28)) }
        assertThrows(Exception::class.java) { PhotoCapabilitiesProtocol.parse(ByteArray(65537)) }
    }
}
