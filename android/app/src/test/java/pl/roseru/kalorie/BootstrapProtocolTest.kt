package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*

class BootstrapProtocolTest {
    private fun fixture() = javaClass.classLoader!!.getResourceAsStream("e3/bootstrap.json")!!.use { it.readBytes() }
    private fun rejected(bytes: ByteArray) {
        val error = try { BootstrapProtocol.parse(bytes); null } catch (error: Exception) { error }
        assertNotNull("Expected invalid bootstrap response", error)
    }
    private fun changed(key: String, value: Any) = JSONObject(fixture().toString(Charsets.UTF_8)).put(key, value).toString().toByteArray()

    @Test fun normativeFixtureRoundTripsWithoutChangingTimestamp() {
        val value = BootstrapProtocol.parse(fixture())
        assertEquals("a1111111-1111-4111-8111-111111111111", value.accountId)
        assertEquals(1, value.accountGeneration)
        assertEquals(value, BootstrapProtocol.parse(value.canonical().toByteArray()))
        val fractional = BootstrapProtocol.parse(changed("server_time", "2026-10-09T10:00:00.1Z"))
        assertEquals("2026-10-09T10:00:00.1Z", fractional.serverTime)
    }
    @Test fun missingExtraNullableAndCoercedValuesAreRejected() {
        val missing = JSONObject(fixture().toString(Charsets.UTF_8)); missing.remove("account_id")
        rejected(missing.toString().toByteArray())
        rejected(changed("unexpected", true))
        rejected(changed("account_id", JSONObject.NULL))
        rejected(changed("account_generation", "1"))
        rejected(changed("account_generation", true))
        rejected(changed("server_time", 123))
    }
    @Test fun revisionsHaveExactIntegerAndE0Bounds() {
        listOf<Any>(0, -1, 1.5, 2147483648L).forEach { rejected(changed("account_generation", it)) }
        assertEquals(Int.MAX_VALUE, BootstrapProtocol.parse(changed("account_generation", Int.MAX_VALUE)).accountGeneration)
    }
    @Test fun uuidRequiresCompleteLowercaseCanonicalForm() {
        listOf("a1111111-1111-4111-8111-11111111111", "A1111111-1111-4111-8111-111111111111", "x", "1-1-1-1-1").forEach {
            rejected(changed("account_id", it)); rejected(changed("sync_epoch", it))
        }
    }
    @Test fun utcDateAndMicrosecondsAreValidatedSemantically() {
        listOf("2026-02-30T10:00:00Z", "2026-10-09T25:00:00Z", "2026-10-09T10:00:00+00:00",
            "2026-10-09T10:00:00.1234567Z", "0000-10-09T10:00:00Z").forEach { rejected(changed("server_time", it)) }
    }
    @Test fun ambiguousJsonInvalidUtf8AndOversizeAreRejected() {
        rejected(fixture().toString(Charsets.UTF_8).replace("\"account_generation\": 1", "\"account_generation\": 1, \"account_generation\": 2").toByteArray())
        rejected(byteArrayOf(0xc3.toByte(), 0x28))
        rejected(ByteArray(65_537) { 32 })
    }
    @Test fun callbacksAreExactAndSeparateForValidationApk() {
        assertEquals("pl.roseru.kalorie:/oauth2redirect", AuthReturn.redirect("pl.roseru.kalorie"))
        assertEquals("pl.roseru.kalorie.validation:/oauth2redirect", AuthReturn.redirect("pl.roseru.kalorie.validation"))
        val error = try { AuthReturn.redirect("other.app"); null } catch (error: IllegalArgumentException) { error }
        assertNotNull(error)
    }
}
