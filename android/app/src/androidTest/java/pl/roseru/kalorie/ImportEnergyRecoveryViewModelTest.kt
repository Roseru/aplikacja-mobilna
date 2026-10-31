package pl.roseru.kalorie

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.core.sync.SyncProtocolScope
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.energy.EnergySchema
import pl.roseru.kalorie.importing.ImportSideState
import pl.roseru.kalorie.importing.ImportViewModel
import pl.roseru.kalorie.sync.*
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Public ViewModel callbacks and real Room with explicitly synthetic proof, not live D2 acceptance. */
class ImportEnergyRecoveryViewModelTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val schema get() = CanonicalMealRows.schema(context)
    private val energy get() = EnergySchema(context.assets.open("energy/energy.schema.json").use { it.readBytes() })
    private val oldEpoch = "55555555-5555-4555-8555-555555555555"
    private val restoredEpoch = "66666666-6666-4666-8666-666666666666"
    private val sharedId = "22222222-2222-4222-8222-222222222222"

    private fun version() = EnergyFixture.sample("version").put("entity_id", sharedId).put("revision", 1).also {
        it.getJSONObject("payload").getJSONObject("audit").put("goal_timeline_revision", 1)
    }

    private fun goal() = JSONObject().put("entity_type", "goal").put("entity_id", sharedId)
        .put("revision", 1).put("deleted", false).put("payload", JSONObject()
            .put("effective_from", "2026-10-01").put("decided_at", "2026-10-01T09:00:00Z")
            .put("time_zone", "UTC").put("goal_type", "maintain").put("energy_kcal", "2500")
            .put("protein_g", JSONObject.NULL).put("fat_g", JSONObject.NULL).put("carbs_g", JSONObject.NULL)
            .put("activity_class", "line")
            .put("estimate", version().getJSONObject("payload").getJSONObject("audit").getJSONObject("estimate"))
            .put("timeline_base_revision", 0).put("reason", "user_decision").put("correction_of", JSONObject.NULL))

    private fun page(epoch: String) = StrictJson.canonical(JSONObject()
        .put("sync_epoch", epoch).put("mode", "snapshot").put("snapshot_token", "synthetic-energy-recovery")
        .put("page_token", JSONObject.NULL).put("checkpoint", "synthetic-energy-checkpoint")
        .put("server_time", "2026-10-31T12:00:00Z").put("goal_timeline_revision", 1)
        .put("entities", JSONArray().put(goal()).put(version()))
        .put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray())).toByteArray()

    private fun model(db: CalorieDatabase, lease: OwnerLease, models: ViewModelStore,
        executor: ReconciliationStepExecutor): ImportViewModel {
        lateinit var value: ImportViewModel
        instrumentation.runOnMainSync {
            val factory = object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T =
                    ImportViewModel(db, schema, lease, executor, SavedStateHandle()) as T
            }
            value = ViewModelProvider(models, factory)[ImportViewModel::class.java]
        }
        return value
    }

    private suspend fun await(model: ImportViewModel) {
        withTimeout(5_000) { model.state.first { !it.busy } }
    }

    private suspend fun act(model: ImportViewModel, block: () -> Unit) {
        instrumentation.runOnMainSync(block)
        await(model)
    }

    @Test fun completeEnergyProofReachesPublicGoalDecisionAndFinishWithoutChangingTheOriginal() = runBlocking<Unit> {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val models = ViewModelStore()
        try {
            val owners = LocalOwnerStore(db)
            owners.ensureGuest()
            val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/energy-recovery", UUID.randomUUID().toString()).id)
            val bootstrap = AccountBootstrapStore(db)
            bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(UUID.randomUUID().toString(), oldEpoch, 1, "2026-10-31T10:00:00Z"))
            SyncProtocolStore(db).readScope(lease, checkNotNull(db.bootstrapDao().binding(lease.storageScope)), true)
            val snapshots = ServerSnapshotStore(db, SnapshotProtocol(schema, energy))
            val initial = snapshots.beginRead(lease, SyncProtocolScope.ENERGY_V1)
            assertNull(snapshots.apply(initial, page(oldEpoch)))
            ServerDiaryStore(db, schema, energy).apply(lease, initial.runId)
            val original = checkNotNull(db.dao().goalById(lease.storageScope, sharedId))
            val before = checkNotNull(db.bootstrapDao().binding(lease.storageScope))
            val restored = bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(before.accountId, restoredEpoch, 1, "2026-10-31T11:00:00Z"))
            assertTrue(restored.requiresRecovery)
            val reconciliation = ReconciliationStore(db, schema, energy)
            val calls = AtomicInteger()
            var proofRun: String? = null
            val executor = ReconciliationStepExecutor { expectedLease, expectedContext, planId, step ->
                assertEquals(lease, expectedLease)
                assertEquals(restored, expectedContext)
                assertEquals(ReconciliationStep.FULL_SNAPSHOT_RECEIPTS, step)
                calls.incrementAndGet()
                val request = checkNotNull(reconciliation.nextSnapshot(lease, restored, planId))
                assertEquals(SyncProtocolScope.ENERGY_V1, request.query.protocolScope)
                assertNull(snapshots.apply(request, page(restoredEpoch)))
                reconciliation.acceptCompletedSnapshot(lease, restored, planId, request.runId)
                proofRun = request.runId
                SyncStepResult.Completed(runId = request.runId)
            }
            val model = model(db, lease, models, executor)
            await(model)
            act(model) { model.previewOwn() }
            assertEquals(1, model.state.value.plan!!.total)
            act(model) { model.approve(true) }
            assertEquals(ImportSideState.UNVERIFIED, model.state.value.rows.single().server.state)
            act(model) { model.downloadProof() }

            // First prove that a complete, accepted ENERGY_V1 copy exists independently of the UI parser.
            val run = checkNotNull(db.snapshotDao().run(checkNotNull(proofRun)))
            val pages = db.snapshotDao().pages(run.id)
            assertEquals("complete", run.state)
            assertEquals(SyncProtocolScope.ENERGY_V1.installationId, run.protocolScope)
            assertEquals(1, pages.size)
            assertEquals(2, run.itemCount)
            val validated = reconciliation.latestCopy(lease, restored, model.state.value.plan!!.planId).second
            assertEquals(sharedId, validated.entities.single().id)
            assertEquals(sharedId, validated.energyVersions.single().id)
            assertEquals(original, db.dao().goalById(lease.storageScope, sharedId))
            assertEquals(1, calls.get())

            val row = model.state.value.rows.single()
            assertTrue("Complete ENERGY_V1 proof was lost by public VM: state=${row.server.state}, proof=${row.proofRunId}",
                row.server.state == ImportSideState.PRESENT && row.proofRunId == run.id)
            assertTrue(row.server.values.any { it.value == "2500 kcal" })
            assertTrue(db.importDao().decisions(row.source.planId).isEmpty())
            act(model) { model.acceptServer(row) }
            assertEquals("accept_server", db.importDao().source(row.source.planId, "goal", sharedId)!!.state)
            assertEquals(pages, db.snapshotDao().pages(run.id))
            act(model) { model.finish() }
            assertEquals("complete", model.state.value.plan!!.state)
            assertFalse(checkNotNull(db.bootstrapDao().binding(lease.storageScope)).requiresRecovery)
            val projected = checkNotNull(db.dao().goalById(lease.storageScope, sharedId))
            assertEquals(original.id, projected.id)
            assertEquals(original.kcal, projected.kcal, 0.0)
            assertEquals(original.estimateJson, projected.estimateJson)
            assertEquals(0, db.dao().operationCount(lease.storageScope))
            assertEquals(1, calls.get())
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        } finally {
            instrumentation.runOnMainSync { models.clear() }
            db.close()
        }
    }
}
