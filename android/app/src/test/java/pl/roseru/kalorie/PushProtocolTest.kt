package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.security.MessageDigest
import java.util.UUID

class PushProtocolTest {
    private fun bytes(path: String) = javaClass.getResourceAsStream(path)!!.use { it.readBytes() }
    private val schema = SyncWireSchema(SyncWireSchema.FILES.associateWith { bytes("/sync/$it") })
    private val protocol = PushProtocol(schema)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private val checkpoint = "opaque+/?=&ż😀"
    private fun operation() = StrictJson.read(bytes("/photo/materialized-meal-operation.json"))
    private fun response() = StrictJson.read(bytes("/photo/materialized-meal-push-response.json"))
    private fun batch(vararg rows: JSONObject) = protocol.prepare(epoch, checkpoint, rows.map(StrictJson::canonical))
    private fun read(batch: PushBatch, value: JSONObject = response()) = protocol.response(batch, 200, StrictJson.canonical(value).toByteArray())
    private fun rejected(action: () -> Unit) {
        val error = assertThrows(SyncWireException::class.java, action)
        assertEquals("Niepoprawny kontrakt synchronizacji", error.message)
        assertNull(error.cause)
    }
    private fun another() = operation().put("operation_id", UUID.randomUUID().toString()).put("entity_id", UUID.randomUUID().toString()).apply {
        getJSONObject("payload").getJSONArray("items").getJSONObject(0).put("item_id", UUID.randomUUID().toString())
    }
    private fun twoResponse(first: JSONObject, second: JSONObject) = response().put("results", JSONArray().put(first).put(second))
    private fun result(row: JSONObject) = response().getJSONArray("results").getJSONObject(0)
        .put("operation_id", row.getString("operation_id")).put("entity_id", row.getString("entity_id"))

    @Test fun independentAckAndEnvelopeUseExactBytesWithoutInventingCheckpoint() {
        val row = operation(); val actual = batch(row)
        val expected = StrictJson.canonical(JSONObject().put("protocol_version", 1).put("sync_epoch", epoch)
            .put("checkpoint", checkpoint).put("operations", JSONArray().put(row))).toByteArray()
        assertArrayEquals(expected, actual.body())
        assertEquals(MessageDigest.getInstance("SHA-256").digest(expected).joinToString("") { "%02x".format(it) }, actual.sha256)
        val receipt = protocol.response(actual, 200, bytes("/photo/materialized-meal-push-response.json"))
        assertEquals(actual.sha256, receipt.requestHash)
        assertFalse(receipt.json().has("checkpoint"))
        assertEquals("PushBatch(redacted)", actual.toString()); assertEquals("PushReceipt(redacted)", receipt.toString())
    }
    @Test fun restartAndMutableCopiesPreserveFrozenOperationsAndHash() {
        val input = operation(); val original = batch(input); val wire = original.body(); val hash = original.sha256
        input.put("operation_id", UUID.randomUUID().toString()); original.json().put("checkpoint", "changed")
        original.body().fill(0)
        val restored = protocol.restore(wire)
        assertArrayEquals(wire, restored.body()); assertEquals(hash, restored.sha256); read(restored)
    }
    @Test fun canonicalStoredEnvelopeCannotBeReformattedSilentlyDuringRestore() {
        val request = batch(operation())
        rejected { protocol.restore(request.json().toString(2).toByteArray()) }
        rejected { protocol.restore(request.body() + byteArrayOf(10)) }
    }
    @Test fun emptyQueueBadCheckpointAndWrongEpochCannotProduceSendableBatch() {
        rejected { protocol.prepare(epoch, checkpoint, emptyList()) }
        rejected { protocol.prepare(epoch, "", listOf(operation().toString())) }
        rejected { batch(operation().put("sync_epoch", UUID.randomUUID().toString())) }
    }
    @Test fun contiguousPrefixStopsAtSecondEditWithoutSkippingToItsDependants() {
        val original = operation(); val secondEdit = operation().put("operation_id", UUID.randomUUID().toString())
        val prepared = batch(original, secondEdit, another())
        assertEquals(1, prepared.json().getJSONArray("operations").length())
        assertEquals(original.getString("operation_id"), prepared.json().getJSONArray("operations").getJSONObject(0).getString("operation_id"))
    }
    @Test fun repeatedOperationAndDuplicatedPersistedEntityAreRejected() {
        val a = operation(); val duplicate = operation().put("entity_id", UUID.randomUUID().toString())
        rejected { batch(a, duplicate) }
        val valid = batch(a, another()).json(); val rows = valid.getJSONArray("operations")
        rows.getJSONObject(1).put("entity_id", a.getString("entity_id"))
        rejected { protocol.restore(StrictJson.canonical(valid).toByteArray()) }
    }
    @Test fun maximumHundredOperationsFormsAStablePrefix() {
        val inputs = (0..100).map { another().toString() }
        val prepared = protocol.prepare(epoch, checkpoint, inputs)
        val rows = prepared.json().getJSONArray("operations")
        assertEquals(100, rows.length())
        assertEquals(JSONObject(inputs[99]).getString("operation_id"), rows.getJSONObject(99).getString("operation_id"))
    }
    @Test fun byteLimitIncludesEnvelopeCheckpointAndMultibyteUnicode() {
        fun large(): JSONObject {
            val row = another(); val items = JSONArray()
            repeat(100) {
                val item = operation().getJSONObject("payload").getJSONArray("items").getJSONObject(0)
                    .put("item_id", UUID.randomUUID().toString()).put("name", "😀".repeat(200))
                    .put("density_g_per_ml", "1").put("density_source", "😀".repeat(300))
                items.put(item)
            }
            row.getJSONObject("payload").put("items", items)
            return row
        }
        val inputs = (1..5).map { large().toString() }
        val prepared = protocol.prepare(epoch, "😀".repeat(4096), inputs)
        val value = prepared.json(); val rows = value.getJSONArray("operations"); val count = rows.length()
        assertTrue(count in 1..4); assertTrue(prepared.body().size <= PushProtocol.MAX_REQUEST_BYTES)
        assertTrue(prepared.body().size > prepared.canonical.length)
        rows.put(JSONObject(inputs[count]))
        assertTrue(StrictJson.canonical(value).toByteArray().size > PushProtocol.MAX_REQUEST_BYTES)
        rejected { protocol.restore(StrictJson.canonical(value).toByteArray()) }
    }
    @Test fun wrongHttpStatusAndPartialAckCannotAcknowledgeAnyPrefix() {
        val a = operation(); val b = another(); val request = batch(a, b)
        for (status in listOf(201, 204, 400, 401, 422, 429, 500, 503)) {
            rejected { protocol.response(batch(a), status, bytes("/photo/materialized-meal-push-response.json")) }
        }
        rejected { read(request) }
        rejected { read(batch(a), twoResponse(result(a), result(b))) }
    }
    @Test fun orderOperationIdentityEntityIdentityAndEpochAreBoundToRequest() {
        val a = operation(); val b = another(); val request = batch(a, b)
        rejected { read(request, twoResponse(result(b), result(a))) }
        rejected { read(batch(a), response().put("sync_epoch", UUID.randomUUID().toString())) }
        rejected { read(batch(a), response().apply {getJSONArray("results").getJSONObject(0).put("entity_id", b.getString("entity_id"))}) }
        rejected { read(batch(a), response().apply {getJSONArray("results").getJSONObject(0).put("operation_id", b.getString("operation_id"))}) }
    }
    @Test fun invalidLaterResultPreventsReceiptAndSuccessfulRevisionIsTheOriginalIncrement() {
        val a = operation(); val b = another(); val bad = result(b).put("revision", 0)
        rejected { read(batch(a, b), twoResponse(result(a), bad)) }
        for (revision in listOf(2, 2147483647)) {
            rejected { read(batch(a), response().apply {getJSONArray("results").getJSONObject(0).put("revision", revision)}) }
        }
        val edit = a.put("base_revision", 7)
        read(batch(edit), response().apply {getJSONArray("results").getJSONObject(0).put("revision", 8)})
    }
    @Test fun lostAckReplayAllowsAlreadyAppliedWithoutChangingOriginalRevision() {
        val request = batch(operation()); val first = read(request)
        val replay = read(request, response().apply {getJSONArray("results").getJSONObject(0).put("status", "already_applied")})
        assertTrue(protocol.sameDecision(request, first, replay))
        assertTrue(protocol.sameDecision(request, replay, first))
        val other = batch(another())
        rejected { protocol.sameDecision(other, first, replay) }
    }
    @Test fun conflictAndRejectionRemainExplicitWithoutGrantingRevisionOrOverwritingLocalMeal() {
        val request = batch(operation())
        val conflict = result(operation()).apply {
            remove("revision"); put("status", "conflict"); put("code", "revision_conflict")
            put("message", "fixture"); put("current", JSONObject.NULL); put("details_retained", true)
        }
        val a = read(request, response().put("results", JSONArray().put(conflict)))
        assertFalse(a.json().getJSONArray("results").getJSONObject(0).has("revision"))
        val rejection = JSONObject(conflict.toString()).put("status", "rejected").put("code", "dependency_missing")
        val b = read(request, response().put("results", JSONArray().put(rejection)))
        assertFalse(protocol.sameDecision(request, a, b))
    }
    @Test fun recoveryCannotAccidentallyEnterOrdinaryPush() {
        val row = operation().put("recovery", JSONObject().put("source_epoch", UUID.randomUUID().toString())
            .put("source_entity_id", UUID.randomUUID().toString()).put("source_revision", JSONObject.NULL)
            .put("source_operation_id", JSONObject.NULL).put("decision", "recreate_missing"))
        schema.validate(row.toString().toByteArray(), "Operation")
        rejected { batch(row) }
        val mapping = JSONObject().put("source_epoch", UUID.randomUUID().toString()).put("source_entity_id", UUID.randomUUID().toString())
            .put("target_entity_id", operation().getString("entity_id")).put("target_revision", 1)
        val value = response().apply {getJSONArray("results").getJSONObject(0).put("recovery_mapping", mapping)}
        schema.validate(value.toString().toByteArray(), "PushResponse")
        rejected { read(batch(operation()), value) }
    }
    @Test fun invalidMealSemanticsAndDuplicateJsonKeysAreRejectedBeforeSend() {
        val row = operation(); row.getJSONObject("payload").put("local_date", "2026-10-18")
        rejected { batch(row) }
        val wire = batch(operation()).canonical.replace("\"protocol_version\":1", "\"protocol_version\":1,\"protocol_version\":1")
        rejected { protocol.restore(wire.toByteArray()) }
        rejected { protocol.response(batch(operation()), 200, ByteArray(PushProtocol.MAX_RESPONSE_BYTES + 1)) }
    }
    @Test fun oversizedPayloadIsRejectedEvenWhenWholeEnvelopeFitsRequestLimit() {
        val row = operation(); val items = JSONArray()
        repeat(100) {
            items.put(operation().getJSONObject("payload").getJSONArray("items").getJSONObject(0)
                .put("item_id", UUID.randomUUID().toString()).put("name", "😀".repeat(200))
                .put("density_g_per_ml", "1").put("density_source", "😀".repeat(500)))
        }
        row.getJSONObject("payload").put("items", items)
        schema.validate(row.toString().toByteArray(), "Operation")
        val size = StrictJson.canonical(row.getJSONObject("payload")).toByteArray().size
        assertTrue(size > PushProtocol.MAX_PAYLOAD_BYTES); assertTrue(size < PushProtocol.MAX_REQUEST_BYTES)
        rejected { batch(row) }
    }
}
