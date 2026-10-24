package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.util.UUID

class RecoveryProtocolTest {
    private fun bytes(path: String) = javaClass.getResourceAsStream(path)!!.use { it.readBytes() }
    private val schema = SyncWireSchema(SyncWireSchema.FILES.associateWith { bytes("/sync/$it") })
    private val protocol = RecoveryProtocol(schema)
    private val epoch = "00000000-0000-4000-8000-000000000064"
    private val oldEpoch = "00000000-0000-4000-8000-000000000063"
    private val checkpoint = "opaque+/?=&ż😀"
    private fun uuid() = UUID.randomUUID().toString()
    private fun row(type: String = "weight") = JSONObject().put("operation_id", uuid()).put("entity_type", type)
        .put("entity_id", uuid()).put("action", "upsert").put("base_revision", JSONObject.NULL)
        .put("sync_epoch", epoch).put("payload", JSONObject(String(bytes("/sync/${if (type == "diary_day") "diary-day" else if (type == "product_draft") "product-draft" else type}.json"))))
        .put("recovery", JSONObject().put("source_epoch", oldEpoch).put("source_entity_id", uuid())
            .put("source_revision", 1).put("source_operation_id", uuid()).put("decision", "recreate_missing"))
    private fun batch(vararg rows: JSONObject) = protocol.prepare(epoch, checkpoint, rows.map(StrictJson::canonical))
    private fun result(row: JSONObject) = JSONObject().put("operation_id", row.getString("operation_id"))
        .put("entity_id", row.getString("entity_id")).put("status", "accepted")
        .put("revision", if (row.isNull("base_revision")) 1 else row.getInt("base_revision") + 1)
        .put("recovery_mapping", JSONObject().put("source_epoch", row.getJSONObject("recovery").getString("source_epoch"))
            .put("source_entity_id", row.getJSONObject("recovery").getString("source_entity_id"))
            .put("target_entity_id", row.getString("entity_id"))
            .put("target_revision", if (row.isNull("base_revision")) 1 else row.getInt("base_revision") + 1))
    private fun response(vararg results: JSONObject) = JSONObject().put("sync_epoch", epoch)
        .put("server_time", "2026-10-23T12:00:00Z").put("results", JSONArray(results.toList()))
    private fun read(request: PushBatch, value: JSONObject) = protocol.response(request, 200, StrictJson.canonical(value).toByteArray())
    private fun rejected(action: () -> Unit) {
        val error = assertThrows(SyncWireException::class.java, action)
        assertEquals("Niepoprawny kontrakt synchronizacji", error.message)
        assertNull(error.cause)
    }

    @Test fun sixDomainsRecoverWithoutChangingCanonicalPayloadsOrFrozenEnvelope() {
        val rows = listOf("profile", "goal", "meal", "weight", "diary_day", "product_draft").map(::row)
        val prepared = batch(*rows.toTypedArray())
        val wire = prepared.body(); val hash = prepared.sha256
        rows[0].put("operation_id", uuid())
        val restored = protocol.restore(wire)
        assertArrayEquals(wire, restored.body()); assertEquals(hash, restored.sha256)
        val saved = restored.json().getJSONArray("operations")
        val receipt = read(restored, response(*(0 until saved.length()).map { result(saved.getJSONObject(it)) }.toTypedArray()))
        assertEquals(hash, receipt.requestHash)
        assertFalse(restored.toString().contains(checkpoint))
        rejected { protocol.restore(restored.json().toString(2).toByteArray()) }
    }
    @Test fun builderAndStandaloneValidatorUseSameCanonicalWireAndKeepRequiredNulls() {
        val value = row(); val source = value.getJSONObject("recovery").put("source_revision", JSONObject.NULL).put("source_operation_id", JSONObject.NULL)
        val built = protocol.operation(value.getString("operation_id"), "weight", value.getString("entity_id"), epoch,
            null, value.getJSONObject("payload").toString(), source.toString())
        assertEquals(protocol.operation(value.toString()), built)
        assertTrue(JSONObject(built).getJSONObject("recovery").isNull("source_revision"))
        rejected { protocol.operation(uuid(), "weight", uuid(), epoch, null, "bad-json", source.toString()) }
    }
    @Test fun sameEpochDeleteMissingSourceAndReusedOperationIdCannotBecomeRecovery() {
        val ordinary = row().apply { remove("recovery") }
        rejected { batch(ordinary) }
        rejected { batch(row().apply { getJSONObject("recovery").put("source_epoch", epoch) }) }
        rejected { batch(row().put("action", "delete").put("payload", JSONObject.NULL).put("base_revision", 1)) }
        rejected { batch(row().apply { getJSONObject("recovery").put("source_operation_id", getString("operation_id")) }) }
        rejected { batch(row().apply { getJSONObject("recovery").remove("source_revision") }) }
    }
    @Test fun recreateAndResolveHaveDifferentTargetAndBaseRequirements() {
        rejected { batch(row().put("base_revision", 1)) }
        rejected { batch(row().apply { getJSONObject("recovery").put("source_entity_id", getString("entity_id")) }) }
        rejected { batch(row().apply { getJSONObject("recovery").put("decision", "resolve_existing") }) }
        val resolve = row().put("base_revision", 7).apply { getJSONObject("recovery").put("decision", "resolve_existing") }
        read(batch(resolve), response(result(resolve)))
    }
    @Test fun schemaAndSemanticPayloadValidationApplyToAllSixDomains() {
        val invalid = listOf(
            row("profile").apply { getJSONObject("payload").put("height_cm", "301") },
            row("goal").apply { getJSONObject("payload").put("effective_from", "2026-10-08") },
            row("meal").apply { getJSONObject("payload").put("local_date", "2026-10-08") },
            row("weight").apply { getJSONObject("payload").put("local_date", "2026-10-08") },
            row("diary_day").apply { getJSONObject("payload").put("declared_complete", "true") },
            row("product_draft").apply { getJSONObject("payload").put("density_g_per_ml", "1").put("density_source", JSONObject.NULL) })
        invalid.forEach { value -> rejected { batch(value) } }
        rejected { batch(row().apply { getJSONObject("payload").put("weight_kg", "80.0000001") }) }
    }
    @Test fun malformedLaterAckReturnsNoReceiptAndCannotConfirmPrefix() {
        val a = row(); val b = row(); var receipt: PushReceipt? = null
        val bad = result(b).apply { getJSONObject("recovery_mapping").put("source_entity_id", uuid()) }
        rejected { receipt = read(batch(a, b), response(result(a), bad)) }
        assertNull(receipt)
        rejected { read(batch(a, b), response(result(a))) }
        rejected { read(batch(a, b), response(result(b), result(a))) }
    }
    @Test fun wrongEpochIdentityMappingSourceAndAcceptedTargetAreRejected() {
        val a = row(); val prepared = batch(a)
        rejected { read(prepared, response(result(a)).put("sync_epoch", oldEpoch)) }
        for (key in listOf("operation_id", "entity_id")) rejected { read(prepared, response(result(a).put(key, uuid()))) }
        for (key in listOf("source_epoch", "source_entity_id", "target_entity_id")) {
            rejected { read(prepared, response(result(a).apply { getJSONObject("recovery_mapping").put(key, uuid()) })) }
        }
        rejected { read(prepared, response(result(a).put("recovery_mapping", JSONObject.NULL))) }
        rejected { read(prepared, response(result(a).put("revision", 2))) }
        rejected { read(prepared, response(result(a).apply { getJSONObject("recovery_mapping").put("target_revision", 2) })) }
    }
    @Test fun otherDevicesMappingIsAuthoritativeAndCompactReceiptRetainsOriginalRevision() {
        val a = row(); val proposed = a.getString("entity_id"); val actual = uuid()
        val mapped = result(a).put("status", "already_applied").put("revision", 4).apply {
            getJSONObject("recovery_mapping").put("target_entity_id", actual).put("target_revision", 7)
        }
        val receipt = read(batch(a), response(mapped))
        val saved = receipt.json().getJSONArray("results").getJSONObject(0)
        assertEquals(proposed, saved.getString("entity_id"))
        assertEquals(actual, saved.getJSONObject("recovery_mapping").getString("target_entity_id"))
        assertEquals(4, saved.getInt("revision")); assertEquals(7, saved.getJSONObject("recovery_mapping").getInt("target_revision"))
        // A prior resolve_existing may have mapped to the original UUID before this device proposed recreate.
        mapped.getJSONObject("recovery_mapping").put("target_entity_id", a.getJSONObject("recovery").getString("source_entity_id"))
        read(batch(a), response(mapped))
        mapped.getJSONObject("recovery_mapping").put("target_revision", 3)
        rejected { read(batch(a), response(mapped)) }
    }
    @Test fun conflictCurrentMustMatchDomainAndMappedTargetWithoutInventingAck() {
        val a = row(); val current = JSONObject().put("entity_type", "weight").put("entity_id", a.getString("entity_id"))
            .put("revision", 1).put("deleted", false).put("payload", a.getJSONObject("payload"))
        val conflict = result(a).apply { remove("revision") }.put("status", "conflict").put("code", "recovery_content_conflict")
            .put("message", "fixture").put("current", current).put("details_retained", true)
        val receipt = read(batch(a), response(conflict))
        assertEquals("conflict", receipt.json().getJSONArray("results").getJSONObject(0).getString("status"))
        current.put("entity_id", uuid())
        rejected { read(batch(a), response(conflict)) }
        current.put("entity_id", a.getString("entity_id")).put("entity_type", "meal")
        current.put("payload", JSONObject(String(bytes("/sync/meal.json"))))
        rejected { read(batch(a), response(conflict)) }
    }
    @Test fun boundedPrefixCannotSkipSecondEditOrDuplicateRecoverySource() {
        val a = row(); val second = row().put("entity_id", a.getString("entity_id"))
        assertEquals(1, batch(a, second, row()).json().getJSONArray("operations").length())
        val sameSource = row().apply { put("recovery", JSONObject(a.getJSONObject("recovery").toString())) }
        assertEquals(1, batch(a, sameSource, row()).json().getJSONArray("operations").length())
        val values = (1..101).map { row() }
        assertEquals(100, batch(*values.toTypedArray()).json().getJSONArray("operations").length())
        rejected { batch(a, row().put("operation_id", a.getString("operation_id"))) }
        val persisted = batch(a, row()).json(); persisted.getJSONArray("operations").getJSONObject(1).put("recovery", a.getJSONObject("recovery"))
        rejected { protocol.restore(StrictJson.canonical(persisted).toByteArray()) }
    }
    @Test fun invalidHttpMalformedJsonAndOversizedResponseNeverProduceReceipt() {
        val a = row(); val prepared = batch(a)
        for (status in listOf(201, 204, 401, 409, 410, 422, 429, 503)) {
            rejected { protocol.response(prepared, status, StrictJson.canonical(response(result(a))).toByteArray()) }
        }
        rejected { protocol.response(prepared, 200, ByteArray(PushProtocol.MAX_RESPONSE_BYTES + 1)) }
        rejected { protocol.restore(prepared.canonical.replace("\"protocol_version\":1", "\"protocol_version\":1,\"protocol_version\":1").toByteArray()) }
        rejected { protocol.prepare(epoch, checkpoint, emptyList()) }
        rejected { protocol.prepare(epoch, "", listOf(a.toString())) }
        rejected { protocol.prepare(oldEpoch, checkpoint, listOf(a.toString())) }
        val ordinary = PushProtocol(schema).prepare(epoch, checkpoint, listOf(row().apply { remove("recovery") }.toString()))
        rejected { protocol.response(ordinary, 200, StrictJson.canonical(response(result(a))).toByteArray()) }
    }
    @Test fun payloadAndUtf8EnvelopeLimitsAreIndependentAndCheckpointIsCounted() {
        fun large(sourceLength: Int): JSONObject {
            val template = JSONObject(String(bytes("/photo/materialized-meal-operation.json")))
            val items = JSONArray()
            repeat(100) {
                items.put(JSONObject(template.getJSONObject("payload").getJSONArray("items").getJSONObject(0).toString())
                    .put("item_id", uuid()).put("name", "😀".repeat(200))
                    .put("density_g_per_ml", "1").put("density_source", "😀".repeat(sourceLength)))
            }
            return row("meal").put("payload", template.getJSONObject("payload").put("items", items))
        }
        val tooLarge = large(500)
        schema.validate(tooLarge.toString().toByteArray(), "Operation")
        assertTrue(StrictJson.canonical(tooLarge.getJSONObject("payload")).toByteArray().size > PushProtocol.MAX_PAYLOAD_BYTES)
        rejected { batch(tooLarge) }
        val rows = (1..5).map { large(300).toString() }
        val prepared = protocol.prepare(epoch, "😀".repeat(4096), rows)
        val values = prepared.json().getJSONArray("operations")
        assertTrue(values.length() in 1..4)
        assertTrue(prepared.body().size <= PushProtocol.MAX_REQUEST_BYTES)
        assertTrue(prepared.body().size > prepared.canonical.length)
        val oversized = prepared.json().put("operations", JSONArray(values.toString()).put(JSONObject(rows[values.length()])))
        assertTrue(StrictJson.canonical(oversized).toByteArray().size > PushProtocol.MAX_REQUEST_BYTES)
        rejected { protocol.restore(StrictJson.canonical(oversized).toByteArray()) }
    }
}