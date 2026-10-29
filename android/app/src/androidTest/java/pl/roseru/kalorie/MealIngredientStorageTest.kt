package pl.roseru.kalorie

import androidx.room.Room
import androidx.room.withTransaction
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.math.BigDecimal
import java.time.LocalDate
import java.util.UUID

/** Real Room persistence/rollback with synthetic server evidence. No HTTP, authentication or AI call. */
class MealIngredientStorageTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get() = CanonicalMealRows.schema(context)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private fun uuid() = UUID.randomUUID().toString()
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private fun fixture(name: String) = InstrumentationRegistry.getInstrumentation().context.assets.open(name).use { it.readBytes() }
    private fun input(name: String, amount: String, kcal: String?, protein: String? = "0", fat: String? = null,
        carbs: String? = "0", unit: String = "g") = MealIngredientInput(name, amount, QuantityUnit.read(unit),
        QuantityUnit.read(unit), ExactNutrition(kcal?.let(::BigDecimal), protein?.let(::BigDecimal), fat?.let(::BigDecimal), carbs?.let(::BigDecimal)))
    private suspend fun refused(action: suspend () -> Unit): Exception {
        try { action() } catch (error: CancellationException) { throw error } catch (error: Exception) { return error }
        throw AssertionError("Expected a stale or atomic refusal; private values suppressed")
    }
    private suspend fun account(db: CalorieDatabase): OwnerLease {
        val owners = LocalOwnerStore(db); owners.ensureGuest()
        val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/ingredients", uuid()).id)
        val bootstrap = AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(uuid(), epoch, 1, "2026-10-17T12:00:00Z"))
        val page = JSONObject().put("sync_epoch", epoch).put("mode", "snapshot").put("snapshot_token", "ingredient-fixture")
            .put("page_token", JSONObject.NULL).put("checkpoint", "ingredient-checkpoint").put("server_time", "2026-10-17T12:00:00Z")
            .put("goal_timeline_revision", 0).put("entities", JSONArray()).put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray())
        val snapshots = ServerSnapshotStore(db, SnapshotProtocol(schema))
        assertNull(snapshots.apply(snapshots.begin(lease), page.toString().toByteArray()))
        return lease
    }
    private suspend fun canonicalMeal(db: CalorieDatabase, lease: OwnerLease): MealWithItems {
        val payload = StrictJson.read(fixture("materialized-meal-operation.json")).getJSONObject("payload")
        payload.getJSONArray("items").getJSONObject(0).put("item_id", uuid())
        val wire = MealWire.read(StrictJson.canonical(payload), schema); val id = uuid(); val operation = uuid()
        val wireContext = CanonicalMealRows.context(checkNotNull(db.bootstrapDao().binding(lease.storageScope)))
        db.withTransaction {
            db.dao().insertMeal(CanonicalMealRows.meal(id, lease.storageScope, wire, wireContext))
            CanonicalMealRows.items(id, wire).forEach { db.dao().insertItem(it) }
            db.dao().enqueue(OutboxEntity(operation, lease.storageScope, "meal", id, "upsert", null, wire.canonical,
                "2026-10-17T12:00:00Z", "pending", "sync-v1", MealWire.operation(operation, id, epoch, null, wire.canonical, schema), wireContext))
        }
        return checkNotNull(db.dao().meal(id, lease.storageScope))
    }
    private suspend fun legacyMeal(db: CalorieDatabase, lease: OwnerLease): MealWithItems {
        val product = ProductEntity(uuid(), "Historical manual", "historical manual", 100.0, 2.0, null, 10.0,
            100.0, "Fixture", "Original recipe", 0, lease.storageScope)
        db.dao().insertProduct(product)
        val id = uuid(); DiaryRepository(db, context, lease).add(product.id, 125.0, MealType.LUNCH, LocalDate.of(2026, 10, 9), id)
        return checkNotNull(db.dao().meal(id, lease.storageScope))
    }
    private fun accepted(request: MealPushRequest): ByteArray {
        val operations = request.batch.json().getJSONArray("operations")
        val results = JSONArray()
        for (i in 0 until operations.length()) {
            val operation = operations.getJSONObject(i)
            results.put(JSONObject().put("operation_id", operation.getString("operation_id")).put("entity_id", operation.getString("entity_id"))
                .put("status", "accepted").put("revision", if (operation.isNull("base_revision")) 1 else operation.getInt("base_revision") + 1)
                .put("recovery_mapping", JSONObject.NULL))
        }
        return JSONObject().put("sync_epoch", epoch).put("server_time", "2026-10-17T12:01:00Z").put("results", results).toString().toByteArray()
    }

    @Test fun guestNullableCorrectionAndExactManualValuesSurviveReopenWithoutRewritingOriginalRows() = runBlocking<Unit> {
        val name = "ingredient-${uuid()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            LocalOwnerStore(db).ensureGuest(); var lease = LocalOwnerStore(db).currentLease()
            val original = legacyMeal(db, lease); val item = original.items.single(); val id = original.meal.id
            val originalOperation = db.serverDiaryDao().unsettled(lease.storageScope).single()
            val product = db.dao().product(checkNotNull(item.productId), lease.storageScope)
            DiaryRepository(db, context, lease).correctIngredient(id, item.id,
                input(item.productName, "150", null, "0", "1.25", "12.5", "ml"))
            val first = db.dao().meal(id, lease.storageScope)!!.items.single()
            assertEquals(1, first.consumed().asExact().energy.missingCount)
            assertEquals("0", first.consumed().asExact().protein.canonical)
            assertEquals("1.875", first.consumed().asExact().fat.canonical)
            assertEquals("18.75", first.consumed().asExact().carbs.canonical)
            assertEquals(item.kcalPer100, first.kcalPer100); assertEquals(item.proteinPer100, first.proteinPer100)
            assertEquals(item.fatPer100, first.fatPer100); assertEquals(item.carbsPer100, first.carbsPer100)
            val anchor = checkNotNull(first.snapshotJson)
            assertEquals("100", JSONObject(anchor).getJSONObject("original_consumption").getJSONObject("nutrition_per_100").getString("energy_kcal"))
            assertEquals(originalOperation, db.dao().operation(originalOperation.operationId))
            db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            lease = LocalOwnerStore(db).currentLease()
            val reopened = db.dao().meal(id, lease.storageScope)!!.items.single()
            assertEquals(first, reopened); assertEquals(1, reopened.consumed().asExact().energy.missingCount)
            val editor = reopened.ingredientInput()
            assertEquals(QuantityUnit.MILLILITRES, editor.unit); assertEquals(editor.unit, editor.basisUnit)
            assertNull(editor.nutrition.energy); assertEquals(BigDecimal.ZERO, editor.nutrition.protein)
            val repository = DiaryRepository(db, context, lease)
            repository.correctIngredient(id, item.id, input(item.productName, "150", "42.125", "0", "1.25", "12.5", "ml"))
            assertEquals(63.1875, db.dao().meal(id, lease.storageScope)!!.items.single().consumed().kcal, 0.00000001)
            repository.editItem(id, item.id, 75.0, "75")
            db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            val saved = db.dao().meal(id, lease.storageScope)!!
            assertEquals(31.59375, saved.items.single().consumed().kcal, 0.00000001)
            assertEquals(anchor, saved.items.single().snapshotJson); assertEquals("75", saved.items.single().amountText)
            assertEquals(original.meal.copy(localRevision = 4), saved.meal)
            assertEquals(product, db.dao().product(checkNotNull(item.productId), lease.storageScope))
            assertEquals(originalOperation, db.dao().operation(originalOperation.operationId))
            val latest = db.serverDiaryDao().unsettled(lease.storageScope).last()
            assertEquals(saved.items.single().wirePayload, JSONObject(latest.payload).getJSONArray("items").getJSONObject(0).getString("wirePayload"))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun catalogueRationCorrectionsAdditionAndReplacementKeepSourcesAndHaveIndependentTotals() = runBlocking<Unit> {
        val db = memory()
        try {
            DiaryRepository(db, context).initialize(); val lease = account(db); val repository = DiaryRepository(db, context, lease)
            val ration = db.dao().rations().first().single { it.ration.catalogJson?.let(::JSONObject)?.optString("ration_id") == "1ed32646-7248-5733-8979-c7cb4f9f25d2" }
            val chosen = ration.components.sortedBy { it.position }.take(2)
            val amounts = chosen.associate { it.id to "10" }; val id = uuid()
            repository.addRation(ration.ration.id, amounts.mapValues { 10.0 }, MealType.DINNER, LocalDate.of(2026, 10, 9), id, amounts)
            val original = db.dao().meal(id, lease.storageScope)!!
            val a = original.items.single { it.rationComponentId == chosen[0].id }; val b = original.items.single { it.rationComponentId == chosen[1].id }
            val productA = db.dao().product(checkNotNull(a.productId), lease.storageScope)
            val productB = db.dao().product(checkNotNull(b.productId), lease.storageScope)
            val firstOperation = db.dao().canonicalMealOperations(lease.storageScope, id).single()
            repository.correctIngredient(id, a.id, input(a.productName, "50", "240", "10", null, "0"))
            repository.correctIngredient(id, b.id, input(b.productName, "25", "40", "4", "0", "8", "ml"))
            val extraId = uuid(); repository.addIngredient(id, input("Extra", "12.5", "400", "8", "0", "12"), extraId)
            val after = db.dao().meal(id, lease.storageScope)!!; val total = after.items.map { it.consumed() }.total().asExact()
            // 50g*240/100 + 25ml*40/100 + 12.5g*400/100 = 180 kcal.
            assertEquals("180", total.energy.canonical); assertEquals("7", total.protein.canonical)
            assertEquals(1, total.fat.missingCount); assertEquals("3.5", total.carbs.canonical)
            assertEquals(a.snapshotJson, after.items.single { it.id == a.id }.snapshotJson)
            assertEquals(b.snapshotJson, after.items.single { it.id == b.id }.snapshotJson)
            assertEquals(a.kcalPer100, after.items.single { it.id == a.id }.kcalPer100)
            assertEquals(a.rationComponentPosition, after.items.single { it.id == a.id }.rationComponentPosition)
            assertNull(after.items.single { it.id == extraId }.rationComponentPosition)
            repository.correctIngredient(id, a.id, input("Replacement", "30", "100", "0", "0", "0"))
            val replaced = db.dao().meal(id, lease.storageScope)!!
            assertEquals(90.0, replaced.items.map { it.consumed() }.total().kcal, 0.00000001)
            val newA = replaced.items.single { it.id == a.id }
            assertEquals(a.snapshotJson, newA.snapshotJson); assertNull(newA.rationComponentPosition)
            assertEquals(a.productId, newA.productId); assertEquals("manual", JSONObject(newA.wirePayload!!).getString("nutrition_origin"))
            assertTrue(JSONObject(newA.wirePayload!!).isNull("product"))
            assertEquals(original.meal.copy(localRevision = 5, wirePayload = replaced.meal.wirePayload), replaced.meal)
            assertEquals(productA, db.dao().product(checkNotNull(a.productId), lease.storageScope))
            assertEquals(productB, db.dao().product(checkNotNull(b.productId), lease.storageScope))
            assertEquals(ration, db.dao().ration(ration.ration.id))
            assertEquals(firstOperation.copy(status = "superseded"), db.dao().operation(firstOperation.operationId))
        } finally { db.close() }
    }

    @Test fun inFlightPhotoMealKeepsFrozenBodyHashIdsAndReceiptThenNewNutritionGetsAcknowledgedBase() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val original = canonicalMeal(db, lease); val id = original.meal.id; val item = original.items.single()
            val operation = db.dao().canonicalMealOperations(lease.storageScope, id).single()
            val receipt = StrictJson.read(fixture("corrected-meal-confirmed.json"))
            receipt.getJSONObject("meal").put("meal_id", id).put("payload", JSONObject(original.meal.wirePayload!!))
            val record = PhotoMaterialization(lease.storageScope, receipt.getString("analysis_id"), id, uuid(), uuid(), uuid(), StrictJson.canonical(receipt),
                String(fixture("analysis-read-succeeded.json"), Charsets.UTF_8), StrictJson.canonical(receipt.getJSONObject("provenance")),
                checkNotNull(original.meal.wireContext), operation.operationId, "2026-10-17T12:00:00Z")
            db.withTransaction { db.materializationDao().insert(record) }
            val push = MealPushStore(db, schema); val request = checkNotNull(push.prepare(lease)); push.markAttempted(request)
            val body = request.batch.body(); val hash = request.batch.sha256; val frozen = db.pushDao().batch(request.id)
            val frozenOperation = db.dao().operation(operation.operationId)
            val repository = DiaryRepository(db, context, lease)
            repository.correctIngredient(id, item.id, input(item.productName, "80", "275.25", "20", null, "0"))
            repository.correctIngredient(id, item.id, input(item.productName, "100", "42.125", "0", "0", null))
            val current = db.dao().meal(id, lease.storageScope)!!
            assertEquals(42.125, current.items.single().consumed().kcal, 0.00000001)
            assertEquals(item.wirePayload, StrictJson.canonical(JSONObject(current.items.single().snapshotJson!!).getJSONObject("original_consumption")))
            val waiting = db.dao().canonicalMealOperations(lease.storageScope, id).last()
            assertEquals("waiting_revision", waiting.status); assertNull(waiting.wireJson); assertNotEquals(operation.operationId, waiting.operationId)
            val retry = checkNotNull(push.prepare(lease))
            assertEquals(request.id, retry.id); assertArrayEquals(body, retry.batch.body()); assertEquals(hash, retry.batch.sha256)
            assertEquals(frozen, db.pushDao().batch(request.id)); assertEquals(frozenOperation, db.dao().operation(operation.operationId))
            assertEquals(record, db.materializationDao().get(lease.storageScope, record.analysisId))
            val rawAck = accepted(request); push.applyAck(push.prepareAck(request, 200, rawAck))
            val released = db.dao().operation(waiting.operationId)!!
            assertEquals("pending", released.status); assertEquals(1, released.baseRevision); assertFalse(released.attempted)
            val oldCompleted = db.pushDao().batch(request.id)!!
            assertEquals(request.batch.canonical, oldCompleted.requestJson); assertEquals(hash, oldCompleted.requestHash)
            assertEquals(StrictJson.canonical(StrictJson.read(rawAck)), oldCompleted.responseJson)
            val next = checkNotNull(push.prepare(lease)); assertNotEquals(request.id, next.id)
            assertEquals(waiting.operationId, next.operations.single().operationId)
            assertEquals("42.125", JSONObject(next.operations.single().payload).getJSONArray("items").getJSONObject(0)
                .getJSONObject("nutrition_per_100").getString("energy_kcal"))
            push.markAttempted(next); push.applyAck(push.prepareAck(next, 200, accepted(next)))
            assertEquals(2, db.dao().meal(id, lease.storageScope)!!.meal.serverRevision)
            assertEquals(oldCompleted, db.pushDao().batch(request.id)); assertEquals(record, db.materializationDao().get(lease.storageScope, record.analysisId))
            assertNull(push.prepare(lease))
        } finally { db.close() }
    }

    @Test fun failedOutboxWriteRollsBackCorrectionAdditionAndPendingSupersessionForGuestAndAccount() = runBlocking<Unit> {
        for (canonical in listOf(false, true)) {
            val db = memory()
            try {
                LocalOwnerStore(db).ensureGuest(); val lease = if (canonical) account(db) else LocalOwnerStore(db).currentLease()
                val original = if (canonical) canonicalMeal(db, lease) else legacyMeal(db, lease)
                val before = db.serverDiaryDao().unsettled(lease.storageScope); val count = db.dao().operationCount(lease.storageScope)
                val repository = DiaryRepository(db, context, lease); val item = original.items.single()
                db.openHelper.writableDatabase.execSQL("CREATE TRIGGER reject_ingredient BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'synthetic ingredient failure'); END")
                refused { repository.correctIngredient(original.meal.id, item.id, input(item.productName, "50", "240")) }
                assertEquals(original, db.dao().meal(original.meal.id, lease.storageScope))
                assertEquals(before, db.serverDiaryDao().unsettled(lease.storageScope)); assertEquals(count, db.dao().operationCount(lease.storageScope))
                refused { repository.addIngredient(original.meal.id, input("Rollback extra", "25", "80")) }
                assertEquals(original, db.dao().meal(original.meal.id, lease.storageScope))
                assertEquals(before, db.serverDiaryDao().unsettled(lease.storageScope)); assertEquals(count, db.dao().operationCount(lease.storageScope))
                assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
            } finally { db.close() }
        }
    }

    @Test fun ownerAbaRejectsHeldEditorWhileCurrentOwnerCanCorrectDuringRecoveryWithoutInventingWireBase() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val original = canonicalMeal(db, lease); val item = original.items.single()
            val held = DiaryRepository(db, context, lease); val owners = LocalOwnerStore(db)
            val b = owners.registerIdentity("https://fixture.example/realms/ingredients", "other-${uuid()}")
            owners.select(b.id); val newer = owners.select(lease.storageScope)
            assertTrue(refused { held.correctIngredient(original.meal.id, item.id, input(item.productName, "20", "250")) } is StaleOwnerException)
            assertTrue(refused { held.addIngredient(original.meal.id, input("Stale addition", "20", "250")) } is StaleOwnerException)
            assertEquals(original, db.dao().meal(original.meal.id, lease.storageScope))
            val binding = db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(binding.copy(requiresRecovery = true, contextRevision = binding.contextRevision + 1))
            DiaryRepository(db, context, newer).correctIngredient(original.meal.id, item.id, input(item.productName, "20", "250"))
            val saved = db.dao().meal(original.meal.id, lease.storageScope)!!
            assertEquals(50.0, saved.items.single().consumed().kcal, 0.00000001)
            val waiting = db.dao().canonicalMealOperations(lease.storageScope, original.meal.id).single()
            assertEquals("waiting_recovery", waiting.status); assertNull(waiting.wireJson); assertNull(waiting.baseRevision)
            assertEquals(original.meal.wireContext, waiting.wireContext)
            assertNull(db.dao().meal(original.meal.id, b.storageScope)); assertNull(db.dao().meal(original.meal.id, DiaryRepository.GUEST))
        } finally { db.close() }
    }

    @Test fun conflictDecisionUsesLatestCorrectedNutrientsAndFreshServerRevisionWithoutChangingOldReceipt() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val original = canonicalMeal(db, lease); val item = original.items.single(); val id = original.meal.id
            val push = MealPushStore(db, schema); val request = checkNotNull(push.prepare(lease)); push.markAttempted(request)
            val old = request.operations.single(); val serverPayload = JSONObject(old.payload)
            serverPayload.getJSONArray("items").getJSONObject(0).getJSONObject("nutrition_per_100").put("energy_kcal", "115")
            val current = JSONObject().put("entity_type", "meal").put("entity_id", id).put("revision", 4).put("deleted", false).put("payload", serverPayload)
            val result = JSONObject().put("operation_id", old.operationId).put("entity_id", id).put("status", "conflict").put("code", "revision_conflict")
                .put("message", "Synthetic ingredient conflict").put("current", current).put("details_retained", true).put("recovery_mapping", JSONObject.NULL)
            val response = JSONObject().put("sync_epoch", epoch).put("server_time", "2026-10-17T12:01:00Z").put("results", JSONArray().put(result)).toString().toByteArray()
            push.applyAck(push.prepareAck(request, 200, response)); val completed = db.pushDao().batch(request.id)
            val repository = DiaryRepository(db, context, lease)
            repository.correctIngredient(id, item.id, input(item.productName, "50", "240", "10"))
            val conflicts = SyncConflictStore(db, schema); val held = conflicts.open(lease, old.operationId)
            repository.correctIngredient(id, item.id, input(item.productName, "80", "275.25", "20", null, "0"))
            refused { conflicts.choose(held, ConflictChoice.LOCAL) }
            val ticket = conflicts.open(lease, old.operationId); val operationId = checkNotNull(conflicts.choose(ticket, ConflictChoice.LOCAL))
            val next = db.dao().operation(operationId)!!
            assertNotEquals(old.operationId, operationId); assertEquals(4, next.baseRevision); assertEquals("pending", next.status)
            val corrected = db.dao().meal(id, lease.storageScope)!!.items.single()
            assertEquals(220.2, corrected.consumed().kcal, 0.00000001); assertEquals("16", corrected.consumed().asExact().protein.canonical)
            assertEquals("275.25", JSONObject(next.payload).getJSONArray("items").getJSONObject(0).getJSONObject("nutrition_per_100").getString("energy_kcal"))
            assertEquals(completed, db.pushDao().batch(request.id)); assertEquals(old.wireJson, db.dao().operation(old.operationId)!!.wireJson)
            assertEquals("superseded", db.dao().operation(old.operationId)!!.status)
            assertEquals(ticket.localPayload, db.conflictDao().decision(old.operationId)!!.localPayload)
            assertEquals(original.items.single().wirePayload, StrictJson.canonical(JSONObject(corrected.snapshotJson!!).getJSONObject("original_consumption")))
            assertEquals(operationId, push.prepare(lease)!!.operations.single().operationId)
        } finally { db.close() }
    }
}
