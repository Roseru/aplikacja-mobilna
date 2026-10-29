package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.conflictPreview
import java.math.BigDecimal
import java.time.LocalDate
import java.util.UUID

/** Local Room plus synthetic final receipts; a corrected intent never changes the rejected attempt. */
class CorrectedRejectionStorageTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get() = CanonicalMealRows.schema(context)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private fun uuid() = UUID.randomUUID().toString()
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun refused(action: suspend () -> Unit) {
        var failed = false
        try { action() } catch (error: CancellationException) { throw error } catch (_: Exception) { failed = true }
        assertTrue("Expected refusal without a changed decision or receipt", failed)
    }
    private suspend fun account(db: CalorieDatabase): OwnerLease {
        val owners = LocalOwnerStore(db); owners.ensureGuest()
        val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/corrected-rejection", uuid()).id)
        val boot = AccountBootstrapStore(db)
        boot.apply(boot.begin(lease), BootstrapResponse(uuid(), epoch, 1, "2026-10-29T10:00:00Z"))
        val page = JSONObject().put("sync_epoch", epoch).put("mode", "snapshot").put("snapshot_token", uuid())
            .put("page_token", JSONObject.NULL).put("checkpoint", uuid()).put("server_time", "2026-10-29T10:00:00Z")
            .put("goal_timeline_revision", 0).put("entities", JSONArray()).put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray())
        val snapshots = ServerSnapshotStore(db, SnapshotProtocol(schema))
        snapshots.apply(snapshots.begin(lease), page.toString().toByteArray())
        return lease
    }
    private suspend fun create(db: CalorieDatabase, lease: OwnerLease): String {
        val product = ProductEntity(uuid(), "Synthetic soup", "synthetic soup", 100.0, 2.0, null, 10.0,
            100.0, "Fixture", "fixture", 0, lease.storageScope)
        db.dao().insertProduct(product)
        return uuid().also { DiaryRepository(db, context, lease).add(product.id, 150.0, MealType.LUNCH, LocalDate.now(), it) }
    }
    private suspend fun send(db: CalorieDatabase, lease: OwnerLease, accepted: Boolean = false,
        currentRevision: Int? = null): MealPushRequest {
        val push = MealPushStore(db, schema); val request = push.prepare(lease)!!; push.markAttempted(request)
        val operation = request.batch.json().getJSONArray("operations").getJSONObject(0)
        val result = JSONObject().put("operation_id", operation.getString("operation_id"))
            .put("entity_id", operation.getString("entity_id")).put("recovery_mapping", JSONObject.NULL)
        if (accepted) result.put("status", "accepted").put("revision", operation.optInt("base_revision", 0) + 1)
        else {
            val current = currentRevision?.let { JSONObject().put("entity_type", "meal").put("entity_id", operation.getString("entity_id"))
                .put("revision", it).put("deleted", false).put("payload", operation.getJSONObject("payload")) }
            result.put("status", "rejected").put("code", "dependency_missing").put("message", "Synthetic missing product")
                .put("current", current ?: JSONObject.NULL).put("details_retained", true)
        }
        val response = JSONObject().put("sync_epoch", epoch).put("server_time", "2026-10-29T11:00:00Z")
            .put("results", JSONArray().put(result)).toString().toByteArray()
        push.applyAck(push.prepareAck(request, 200, response))
        return request
    }
    private suspend fun correct(db: CalorieDatabase, lease: OwnerLease, id: String) {
        val item = db.dao().meal(id, lease.storageScope)!!.items.single()
        // Independent oracle: 125 g × 240 kcal / 100 g = 300 kcal; protein=0, fat unknown, carbs=25 g.
        DiaryRepository(db, context, lease).correctIngredient(id, item.id, MealIngredientInput("Corrected soup", "125",
            QuantityUnit.GRAMS, QuantityUnit.GRAMS, ExactNutrition(BigDecimal("240"), BigDecimal.ZERO, null, BigDecimal("20"))))
    }

    @Test fun correctedRejectedCreateNeedsExplicitDecisionAndNewUuidWithNullBaseWithoutChangingReceipt() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val id = create(db, lease); val request = send(db, lease)
            val frozen = db.pushDao().batch(request.id)!!; val old = db.dao().operation(request.operations.single().operationId)!!
            val store = SyncConflictStore(db, schema); val unchanged = store.open(lease, old.operationId)
            assertFalse(unchanged.canChoose); assertFalse(unchanged.canRetryCorrected)
            refused { store.choose(unchanged, ConflictChoice.LOCAL) }; refused { store.choose(unchanged, ConflictChoice.SERVER) }
            assertEquals(old, db.dao().operation(old.operationId)); assertNull(db.conflictDao().decision(old.operationId))
            correct(db, lease, id)
            val corrected = db.dao().meal(id, lease.storageScope)!!
            val waiting = db.dao().canonicalMealOperations(lease.storageScope, id).single { !it.attempted }
            assertEquals("waiting_revision", waiting.status); assertNull(MealPushStore(db, schema).prepare(lease))
            val ticket = store.open(lease, old.operationId)
            assertFalse(ticket.canChoose); assertTrue(ticket.canRetryCorrected)
            assertEquals(ConflictServerState.UNAVAILABLE, ticket.serverState); assertNull(ticket.serverRevision)
            val preview = conflictPreview("synthetic", ticket)
            assertTrue(preview.canRetryCorrected); assertFalse(preview.canChoose); assertFalse(preview.needsRefresh)
            assertEquals("Wersja serwera niedostępna", preview.server.title)
            refused { store.choose(ticket, ConflictChoice.SERVER) }
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_corrected_decision BEFORE INSERT ON sync_conflict_decisions BEGIN SELECT RAISE(ABORT,'synthetic decision failure'); END")
            refused { store.choose(ticket, ConflictChoice.LOCAL) }
            assertEquals(corrected, db.dao().meal(id, lease.storageScope)); assertEquals(old, db.dao().operation(old.operationId))
            assertEquals(waiting, db.dao().operation(waiting.operationId)); assertEquals(frozen, db.pushDao().batch(request.id))
            assertNull(db.conflictDao().decision(old.operationId))
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_corrected_decision")
            val newId = store.choose(ticket, ConflictChoice.LOCAL)!!; val next = db.dao().operation(newId)!!
            assertNotEquals(old.operationId, newId); assertNotEquals(waiting.operationId, newId)
            assertEquals(id, next.entityId); assertNull(next.baseRevision); assertEquals("pending", next.status); assertFalse(next.attempted)
            assertEquals(ticket.localPayload, next.payload); assertEquals(frozen, db.pushDao().batch(request.id))
            assertEquals(old.copy(status = "superseded"), db.dao().operation(old.operationId))
            assertEquals(waiting.copy(status = "superseded"), db.dao().operation(waiting.operationId))
            val decision = db.conflictDao().decision(old.operationId)!!
            assertEquals(newId, decision.newOperationId); assertNull(decision.serverPayload); assertNull(decision.serverRevision)
            assertEquals("UNAVAILABLE", decision.serverState); assertEquals(ticket.evidence.resultJson, decision.resultJson)
            val totals = db.dao().meal(id, lease.storageScope)!!.items.single().consumed().asExact()
            assertEquals("300", totals.energy.canonical); assertEquals("0", totals.protein.canonical)
            assertEquals(1, totals.fat.missingCount); assertEquals("25", totals.carbs.canonical)
            val prepared = MealPushStore(db, schema).prepare(lease)!!
            assertEquals(newId, prepared.operations.single().operationId)
            assertEquals("240", prepared.batch.json().getJSONArray("operations").getJSONObject(0).getJSONObject("payload")
                .getJSONArray("items").getJSONObject(0).getJSONObject("nutrition_per_100").getString("energy_kcal"))
            assertEquals(frozen, db.pushDao().batch(request.id))
            refused { store.choose(ticket, ConflictChoice.LOCAL) }
        } finally { db.close() }
    }

    @Test fun correctedRejectedUpdateUsesOriginalOrObservedBaseAndStaleEditCannotCommit() = runBlocking<Unit> {
        for (observed in listOf<Int?>(null, 4)) {
            val db = memory()
            try {
                val lease = account(db); val id = create(db, lease); send(db, lease, accepted = true)
                val repo = DiaryRepository(db, context, lease); val itemId = db.dao().meal(id, lease.storageScope)!!.items.single().id
                repo.editItem(id, itemId, 160.0, "160")
                val request = send(db, lease, currentRevision = observed)
                val old = db.dao().operation(request.operations.single().operationId)!!; val frozen = db.pushDao().batch(request.id)
                assertEquals(1, old.baseRevision)
                correct(db, lease, id)
                val store = SyncConflictStore(db, schema); val held = store.open(lease, old.operationId)
                assertTrue(held.canRetryCorrected); assertFalse(held.canChoose)
                repo.editItem(id, itemId, 130.0, "130")
                refused { store.choose(held, ConflictChoice.LOCAL) }; assertNull(db.conflictDao().decision(old.operationId))
                val current = store.open(lease, old.operationId)
                val next = db.dao().operation(store.choose(current, ConflictChoice.LOCAL)!!)!!
                assertEquals(observed ?: 1, next.baseRevision); assertEquals(id, next.entityId)
                assertEquals("pending", next.status); assertEquals(frozen, db.pushDao().batch(request.id))
                assertEquals(old.copy(status = "superseded"), db.dao().operation(old.operationId))
                assertEquals("312", db.dao().meal(id, lease.storageScope)!!.items.single().consumed().asExact().energy.canonical)
            } finally { db.close() }
        }
    }
}
