package pl.roseru.kalorie

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.importing.ImportViewModel
import pl.roseru.kalorie.sync.*
import pl.roseru.kalorie.ui.*
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Real Room/VM/UI and production reconciliation stores; explicitly synthetic HTTP replies. */
class ImportRecoveryFinishNavigationTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val oldEpoch = "55555555-5555-4555-8555-555555555555"
    private val newEpoch = "66666666-6666-4666-8666-666666666666"

    private fun page(epoch: String, entities: List<JSONObject>, mappings: List<JSONObject>) = JSONObject()
        .put("sync_epoch", epoch).put("mode", "snapshot").put("snapshot_token", "synthetic-finish")
        .put("page_token", JSONObject.NULL).put("checkpoint", "synthetic-finish-checkpoint")
        .put("server_time", "2026-11-02T12:00:00Z").put("goal_timeline_revision", 0)
        .put("entities", JSONArray(entities)).put("recovery_mappings", JSONArray(mappings))
        .put("operation_receipts", JSONArray()).toString().toByteArray()

    @Test fun twoRecoveryPushesAndLaterProofsLeaveThePublicFinishActionAvailable() {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val models = ViewModelStore()
        val schema = CanonicalMealRows.schema(context)
        try {
            val owners = LocalOwnerStore(db)
            val bootstrap = AccountBootstrapStore(db)
            val snapshots = ServerSnapshotStore(db, SnapshotProtocol(schema))
            lateinit var oldAccepted: OutboxEntity
            lateinit var oldBatchId: String
            lateinit var oldRequest: String
            val lease = runBlocking {
                owners.ensureGuest()
                val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/finish", UUID.randomUUID().toString()).id)
                bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(UUID.randomUUID().toString(), oldEpoch, 1, "2026-11-02T10:00:00Z"))
                val initial = snapshots.begin(lease)
                assertNull(snapshots.apply(initial, page(oldEpoch, emptyList(), emptyList())))
                val repository = DiaryRepository(db, context, lease)
                repository.addWeight(80.0, LocalDate.of(2026, 10, 30))
                val ordinary = MealPushStore(db, schema)
                val sent = checkNotNull(ordinary.prepare(lease))
                val operation = sent.operations.single()
                ordinary.markAttempted(sent)
                val reply = JSONObject().put("sync_epoch", oldEpoch).put("server_time", "2026-11-02T10:30:00Z")
                    .put("results", JSONArray().put(JSONObject().put("operation_id", operation.operationId)
                        .put("entity_id", operation.entityId).put("status", "accepted").put("revision", 1)
                        .put("recovery_mapping", JSONObject.NULL)))
                ordinary.applyAck(ordinary.prepareAck(sent, 200, reply.toString().toByteArray()))
                oldAccepted = checkNotNull(db.dao().operation(operation.operationId))
                oldBatchId = sent.id
                oldRequest = checkNotNull(db.pushDao().batch(sent.id)).requestJson
                repository.addWeight(81.0, LocalDate.of(2026, 10, 31))
                lease
            }
            val originalWeights = runBlocking { db.dao().weights(lease.storageScope).first() }
            val restored = runBlocking {
                val before = checkNotNull(db.bootstrapDao().binding(lease.storageScope))
                bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(before.accountId, newEpoch, 1, "2026-11-02T11:00:00Z"))
            }
            val store = ReconciliationStore(db, schema)
            val entities = mutableListOf<JSONObject>()
            val mappings = mutableListOf<JSONObject>()
            val pushes = AtomicInteger()
            val proofs = AtomicInteger()
            val executor = ReconciliationStepExecutor { expectedLease, expectedContext, plan, step ->
                assertEquals(lease, expectedLease); assertEquals(restored, expectedContext)
                when (step) {
                    ReconciliationStep.FULL_SNAPSHOT_RECEIPTS -> {
                        val request = checkNotNull(store.nextSnapshot(lease, restored, plan))
                        assertNull(snapshots.apply(request, page(newEpoch, entities, mappings)))
                        store.acceptCompletedSnapshot(lease, restored, plan, request.runId)
                        proofs.incrementAndGet()
                        SyncStepResult.Completed(runId = request.runId)
                    }
                    ReconciliationStep.PUSH_APPROVED -> {
                        val request = checkNotNull(store.preparePush(lease, restored, plan))
                        val operation = request.operations.single()
                        val source = db.importDao().sources(plan).single { it.operationId == operation.operationId }
                        val mapping = JSONObject().put("source_epoch", oldEpoch).put("source_entity_id", source.sourceId)
                            .put("target_entity_id", operation.entityId).put("target_revision", 1)
                        val response = JSONObject().put("sync_epoch", newEpoch).put("server_time", "2026-11-02T12:00:00Z")
                            .put("results", JSONArray().put(JSONObject().put("operation_id", operation.operationId)
                                .put("entity_id", operation.entityId).put("status", "accepted").put("revision", 1).put("recovery_mapping", mapping)))
                        store.markAttempted(request)
                        store.applyAck(store.prepareAck(request, 200, response.toString().toByteArray()))
                        entities += JSONObject().put("entity_type", "weight").put("entity_id", operation.entityId)
                            .put("revision", 1).put("deleted", false).put("payload", JSONObject(operation.payload))
                        mappings += mapping; pushes.incrementAndGet()
                        SyncStepResult.Completed(batchId = request.id)
                    }
                }
            }
            lateinit var model: ImportViewModel
            compose.runOnUiThread {
                model = ImportViewModel(db, schema, lease, executor, SavedStateHandle(), energySchema = null)
                models.put("finish", model)
            }
            fun act(action: () -> Unit, ready: () -> Boolean) {
                compose.runOnUiThread(action)
                compose.waitUntil(10_000) { !model.state.value.busy && ready() }
            }
            compose.waitUntil(10_000) { !model.state.value.busy }
            act({ model.previewOwn() }) { model.state.value.plan != null }
            act({ model.approve(true) }) { model.state.value.approved }
            act({ model.downloadProof() }) { proofs.get() == 1 && model.state.value.rows.all { it.proofRunId != null } }
            repeat(2) {
                val row = model.state.value.rows.first()
                act({ model.recreate(row) }) { model.state.value.rows.none { it.source.sourceId == row.source.sourceId } }
            }
            compose.setContent { CalorieTheme(false) { ImportScreen(model, {}, {}) } }
            repeat(2) { index ->
                compose.onNodeWithText("Wyślij zatwierdzone decyzje").performScrollTo().assertIsEnabled().performClick()
                compose.waitUntil(10_000) { !model.state.value.busy && pushes.get() == index + 1 }
                compose.onNodeWithText("Pobierz pełną kopię i dowody operacji").performScrollTo().assertIsEnabled().performClick()
                compose.waitUntil(10_000) { !model.state.value.busy && proofs.get() == index + 2 }
                assertEquals(1, model.state.value.proofGroups)
                assertEquals(1, model.state.value.provedGroups)
                compose.onNodeWithText("Pobrane części dowodów: 1/1").performScrollTo().assertExists()
            }
            assertEquals(2, runBlocking { db.importDao().evidence(model.state.value.plan!!.planId).count { it.kind == "receipt_group" } })
            compose.onNodeWithText("Sprawdź i zakończ uzgodnienie").performScrollTo().assertIsEnabled().performClick()
            compose.waitUntil(10_000) { !model.state.value.busy && model.state.value.plan?.state == "complete" }
            compose.onNodeWithTag("import-complete").performScrollTo().assertExists()
            assertFalse(runBlocking { checkNotNull(db.bootstrapDao().binding(lease.storageScope)).requiresRecovery })
            assertEquals(2, pushes.get()); assertEquals(3, proofs.get())
            assertEquals(oldAccepted, runBlocking { db.dao().operation(oldAccepted.operationId) })
            assertEquals(oldRequest, runBlocking { checkNotNull(db.pushDao().batch(oldBatchId)).requestJson })
            assertEquals(originalWeights.map { it.kg }.sorted(), runBlocking { db.dao().weights(lease.storageScope).first() }.map { it.kg }.sorted())
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        } finally {
            compose.runOnUiThread { models.clear() }
            db.close()
        }
    }
}
