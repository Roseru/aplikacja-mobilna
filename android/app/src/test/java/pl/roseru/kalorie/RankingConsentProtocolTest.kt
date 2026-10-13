package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*

class RankingConsentProtocolTest {
    private val key = "a1111111-1111-4111-8111-111111111111"
    private val scope = "b1111111-1111-4111-8111-111111111111"
    private val account = "c1111111-1111-4111-8111-111111111111"
    private val epoch = "e1111111-1111-4111-8111-111111111111"
    private fun request(enabled: Boolean = true, energy: Boolean = true) = RankingConsentAttempt(key, scope, 2,
        account, 1, epoch, 3, 7, enabled, energy, if (enabled) epoch else null)
    private fun receipt(change: (JSONObject) -> Unit = {}) = JSONObject().put("ranking", true).put("automatic_energy_adjustment", true)
        .put("revision", 8).put("updated_at", "2026-10-12T12:00:00.123456Z").also(change).toString().toByteArray()
    @Test fun exactBodyPreservesBothBooleanValuesAndOptOutOmitsAffirmation() {
        for (energy in listOf(true, false)) for (enabled in listOf(true, false)) {
            val req = request(enabled, energy)
            val json = JSONObject(String(req.body(), Charsets.UTF_8))
            assertEquals(setOf("ranking", "automatic_energy_adjustment"), json.keys().asSequence().toSet())
            assertEquals(enabled, json.get("ranking")); assertEquals(energy, json.get("automatic_energy_adjustment"))
            assertEquals(if (enabled) epoch else null, req.consentEpoch)
            assertFalse(req.toString().contains(key)); assertFalse(req.toString().contains(scope))
        }
    }
    @Test fun durableJournalRestoresTheSameKeyBodyRevisionAndEpoch() {
        val initial = request()
        val restored = RankingConsentAttempt.restore(JSONObject(initial.journal().toString()))
        assertEquals(initial.key, restored.key); assertEquals(initial.baseRevision, restored.baseRevision)
        assertEquals(initial.consentEpoch, restored.consentEpoch); assertArrayEquals(initial.body(), restored.body())
        assertEquals(initial.journal().toString(), restored.journal().toString())
    }
    @Test fun malformedJournalCannotBeReplayedWithCoercionsOrDifferentEpoch() {
        for (change in listOf<(JSONObject) -> Unit>(
            { it.put("extra", true) }, { it.remove("key") }, { it.put("key", key.uppercase()) },
            { it.put("leaseGeneration", "2") }, { it.put("leaseGeneration", 2.0) }, { it.put("contextRevision", 0) },
            { it.put("accountGeneration", 2147483648L) }, { it.put("baseRevision", Int.MAX_VALUE) },
            { it.put("ranking", "true") }, { it.put("automaticEnergyAdjustment", 1) },
            { it.put("consentEpoch", account) }, { it.put("consentEpoch", JSONObject.NULL) },
            { it.put("ranking", false) })) {
            assertThrows(Exception::class.java) { RankingConsentAttempt.restore(request().journal().also(change)) }
        }
    }
    @Test fun receiptMustConfirmExactlyTheApprovedOperationAndNextRevision() {
        val approved = request().parseReceipt(receipt())
        assertEquals(8, approved.revision); assertTrue(approved.ranking); assertTrue(approved.automaticEnergyAdjustment)
        for (change in listOf<(JSONObject) -> Unit>(
            { it.put("revision", 7) }, { it.put("revision", 9) }, { it.put("revision", "8") },
            { it.put("ranking", false) }, { it.put("automatic_energy_adjustment", false) }, { it.put("ranking", "true") },
            { it.put("updated_at", "2026-02-30T00:00:00Z") }, { it.put("updated_at", "2026-10-12T00:00:00+00:00") },
            { it.put("extra", false) })) assertThrows(Exception::class.java) { request().parseReceipt(receipt(change)) }
        // JSONObject serializes Double(8.0) as integer 8; retain the actual invalid wire lexeme.
        assertThrows(Exception::class.java) { request().parseReceipt(String(receipt()).replace("\"revision\":8", "\"revision\":8.0").toByteArray()) }
    }
    @Test fun receiptRejectsAmbiguousJsonMalformedUtf8AndUnboundedPayload() {
        val ambiguous = "{\"ranking\":true,\"ranking\":false,\"automatic_energy_adjustment\":true,\"revision\":8,\"updated_at\":\"2026-10-12T00:00:00Z\"}"
        for (bytes in listOf(ambiguous.toByteArray(), byteArrayOf(0xc3.toByte(), 0x28), ByteArray(65_537), ByteArray(0)))
            assertThrows(Exception::class.java) { request().parseReceipt(bytes) }
    }
}
