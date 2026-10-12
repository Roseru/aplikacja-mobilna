package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.sync.*

/** Normative schema fixtures, without HTTP, session authentication or Room acceptance. */
class SyncWireSchemaTest {
    private fun bytes(name: String) = javaClass.getResourceAsStream("/sync/$name")!!.use { it.readBytes() }
    private fun schema() = SyncWireSchema(SyncWireSchema.FILES.associateWith(::bytes))
    private fun json(name: String) = JSONObject(String(bytes(name), Charsets.UTF_8))
    private fun validate(value: JSONObject, definition: String) = schema().validate(value.toString().toByteArray(), definition)
    @Test fun realNormativeExamplesValidateWithoutAndroidSpecificFields() {
        for ((name, definition) in listOf("sync-pull-response.json" to "PullResponse", "sync-push-request.json" to "PushRequest",
            "sync-push-response.json" to "PushResponse")) schema().validate(bytes(name), definition)
    }
    @Test fun newWireEntityUsesNullNeverZeroOrLocalRevision() {
        val request = json("sync-push-request.json")
        validate(request, "PushRequest")
        request.getJSONArray("operations").getJSONObject(0).put("base_revision", 0)
        assertThrows(SyncWireException::class.java) { validate(request, "PushRequest") }
        request.getJSONArray("operations").getJSONObject(0).put("base_revision", 1)
        validate(request, "PushRequest") // Existing-entity semantics must additionally be checked against shadow.
    }
    @Test fun snapshotAndCheckpointConditionalBranchesAreEnforced() {
        val page = json("sync-pull-response.json")
        page.put("mode", "snapshot")
        assertThrows(SyncWireException::class.java) { validate(page, "PullResponse") }
        page.put("snapshot_token", "snapshot-fixture"); validate(page, "PullResponse")
        page.put("page_token", "next-fixture")
        assertThrows(SyncWireException::class.java) { validate(page, "PullResponse") }
        page.put("checkpoint", JSONObject.NULL); validate(page, "PullResponse")
        page.put("mode", "incremental")
        assertThrows(SyncWireException::class.java) { validate(page, "PullResponse") }
    }
    @Test fun requestContinuationAndRecoveryIdsCannotBeCombined() {
        val request = JSONObject().put("sync_epoch", "e1111111-1111-4111-8111-111111111111").put("limit", 500)
        validate(request, "PullRequest")
        request.put("page_token", "next-fixture")
        assertThrows(SyncWireException::class.java) { validate(request, "PullRequest") }
        request.put("snapshot_token", "snapshot-fixture"); validate(request, "PullRequest")
        request.put("recovery_operation_ids", JSONArray(listOf("a1111111-1111-4111-8111-111111111111")))
        assertThrows(SyncWireException::class.java) { validate(request, "PullRequest") }
        request.remove("page_token"); request.remove("snapshot_token"); validate(request, "PullRequest")
        request.getJSONArray("recovery_operation_ids").put("a1111111-1111-4111-8111-111111111111")
        assertThrows(SyncWireException::class.java) { validate(request, "PullRequest") }
    }
    @Test fun everyEntityKindAndTombstoneUsesItsOwnPayloadShape() {
        val page = json("sync-pull-response.json")
        for (kind in listOf("profile", "goal", "meal", "weight", "diary_day", "product_draft")) {
            val entity = JSONObject().put("entity_type", kind).put("entity_id", "b1111111-1111-4111-8111-111111111111")
                .put("revision", 1).put("deleted", false).put("payload", json(kind.replace('_', '-') + ".json"))
            page.put("entities", JSONArray().put(entity)); validate(page, "PullResponse")
            entity.put("deleted", true).put("payload", JSONObject.NULL); validate(page, "PullResponse")
            entity.put("payload", JSONObject())
            assertThrows(SyncWireException::class.java) { validate(page, "PullResponse") }
        }
    }
    @Test fun malformedUnicodeDecimalCalendarAndZoneAreRejected() {
        val page = json("sync-pull-response.json")
        val weight = page.getJSONArray("entities").getJSONObject(0).getJSONObject("payload")
        for (amount in listOf("80.0", "80\n", "80\r\n", "0.0000001", "NaN", "-1")) {
            weight.put("weight_kg", amount)
            assertThrows(SyncWireException::class.java) { validate(page, "PullResponse") }
        }
        weight.put("weight_kg", "80").put("time_zone", "Mars/Base")
        assertThrows(SyncWireException::class.java) { validate(page, "PullResponse") }
        weight.put("time_zone", "Europe/Warsaw").put("local_date", "2026-02-30")
        assertThrows(SyncWireException::class.java) { validate(page, "PullResponse") }
        weight.put("local_date", "2026-10-09"); page.put("checkpoint", "token\u0000hidden")
        assertThrows(SyncWireException::class.java) { validate(page, "PullResponse") }
    }
    @Test fun syncErrorsHaveObjectDetailsAndStrictRequiredFields() {
        val error = JSONObject().put("code", "snapshot_expired").put("message", "fixture").put("details", JSONObject())
            .put("request_id", "a1111111-1111-4111-8111-111111111111")
        validate(error, "SyncError")
        error.put("details", JSONArray())
        assertThrows(SyncWireException::class.java) { validate(error, "SyncError") }
    }
    @Test fun boundsDuplicateKeysAndInvalidUtf8AreCheckedBeforeSchema() {
        val example = String(bytes("sync-pull-response.json"), Charsets.UTF_8)
        val duplicate = example.replace("\"mode\": \"incremental\"", "\"mode\":\"incremental\",\"mode\":\"snapshot\"")
        for (value in listOf(ByteArray(0), ByteArray(4 * 1_048_576 + 1), byteArrayOf(0xC3.toByte(), 0x28), duplicate.toByteArray()))
            assertThrows(SyncWireException::class.java) { schema().validate(value, "PullResponse") }
    }
    @Test fun epochErrorRequiresItsNormativeContextBeforeAnyRecoveryDecision() {
        val error = JSONObject().put("code", "sync_epoch_changed").put("message", "fixture").put("details", JSONObject())
            .put("request_id", "a1111111-1111-4111-8111-111111111111")
        assertThrows(SyncWireException::class.java) { validate(error, "SyncError") }
        error.put("details", JSONObject().put("current_sync_epoch", "b1111111-1111-4111-8111-111111111111")
            .put("requested_sync_epoch", "e1111111-1111-4111-8111-111111111111").put("recovery_required", "epoch_recovery"))
        validate(error, "SyncError")
        error.getJSONObject("details").put("recovery_required", "full_snapshot")
        assertThrows(SyncWireException::class.java) { validate(error, "SyncError") }
    }
}
