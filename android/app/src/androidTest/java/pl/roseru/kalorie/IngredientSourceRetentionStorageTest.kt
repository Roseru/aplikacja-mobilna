package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
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
import java.util.UUID

/** Same-item source retention across real Room conflict decisions and server projection. */
class IngredientSourceRetentionStorageTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get() = CanonicalMealRows.schema(context)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private fun uuid() = UUID.randomUUID().toString()
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private fun payload(itemId: String, amount: String, energy: String, name: String, productId: String? = null): MealWire {
        val item = MealWire.manualIngredient(itemId, MealIngredientInput(name, amount, QuantityUnit.GRAMS, QuantityUnit.GRAMS,
            ExactNutrition(BigDecimal(energy), BigDecimal.ZERO, null, BigDecimal("20"))))
        if (productId != null) item.put("product", JSONObject().put("product_id", productId).put("revision", 9))
            .put("nutrition_origin", "catalog_snapshot")
        val meal = JSONObject().put("occurred_at", "2026-10-29T09:00:00Z").put("time_zone", "UTC").put("local_date", "2026-10-29")
            .put("meal_type", "lunch").put("title", "Synthetic meal").put("goal_id", JSONObject.NULL)
            .put("ration", JSONObject.NULL).put("items", JSONArray().put(item))
        return MealWire.read(StrictJson.canonical(meal), schema)
    }
    private suspend fun snapshot(db: CalorieDatabase, lease: OwnerLease, mealId: String, revision: Int, wire: MealWire,
        time: String = "2026-10-29T10:00:00Z") {
        val entity = JSONObject().put("entity_type", "meal").put("entity_id", mealId).put("revision", revision)
            .put("deleted", false).put("payload", wire.json())
        val page = JSONObject().put("sync_epoch", epoch).put("mode", "snapshot").put("snapshot_token", uuid())
            .put("page_token", JSONObject.NULL).put("checkpoint", uuid()).put("server_time", time).put("goal_timeline_revision", 0)
            .put("entities", JSONArray().put(entity)).put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray())
        val store = ServerSnapshotStore(db, SnapshotProtocol(schema)); val request = store.begin(lease)
        store.apply(request, page.toString().toByteArray()); ServerDiaryStore(db, schema).apply(lease, request.runId)
    }
    private suspend fun account(db: CalorieDatabase, mealId: String, itemId: String): OwnerLease {
        val owners = LocalOwnerStore(db); owners.ensureGuest()
        val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/ingredient-source", uuid()).id)
        val boot = AccountBootstrapStore(db)
        boot.apply(boot.begin(lease), BootstrapResponse(uuid(), epoch, 1, "2026-10-29T10:00:00Z"))
        snapshot(db, lease, mealId, 1, payload(itemId, "100", "100", "Original soup"))
        return lease
    }
    private suspend fun correct(db: CalorieDatabase, lease: OwnerLease, mealId: String, itemId: String): String {
        assertNull(db.dao().meal(mealId, lease.storageScope)!!.items.single().snapshotJson)
        DiaryRepository(db, context, lease).correctIngredient(mealId, itemId, MealIngredientInput("Corrected soup", "125",
            QuantityUnit.GRAMS, QuantityUnit.GRAMS, ExactNutrition(BigDecimal("240"), BigDecimal.ZERO, null, BigDecimal("20"))))
        val item = db.dao().meal(mealId, lease.storageScope)!!.items.single()
        assertEquals("300", item.consumed().asExact().energy.canonical)
        return checkNotNull(item.snapshotJson).also {
            assertTrue(JSONObject(it).has("original_consumption"))
            assertEquals("Original soup", JSONObject(it).getJSONObject("original_consumption").getString("name"))
        }
    }
    private suspend fun response(db: CalorieDatabase, lease: OwnerLease, current: MealWire? = null): MealPushRequest {
        val store = MealPushStore(db, schema); val request = store.prepare(lease)!!; store.markAttempted(request)
        val operation = request.batch.json().getJSONArray("operations").getJSONObject(0)
        val result = JSONObject().put("operation_id", operation.getString("operation_id"))
            .put("entity_id", operation.getString("entity_id")).put("recovery_mapping", JSONObject.NULL)
        if (current == null) result.put("status", "accepted").put("revision", 2)
        else result.put("status", "conflict").put("code", "revision_conflict").put("message", "Synthetic conflict")
            .put("details_retained", true).put("current", JSONObject().put("entity_type", "meal")
                .put("entity_id", operation.getString("entity_id")).put("revision", 4).put("deleted", false).put("payload", current.json()))
        val receipt = JSONObject().put("sync_epoch", epoch).put("server_time", "2026-10-29T11:00:00Z")
            .put("results", JSONArray().put(result)).toString().toByteArray()
        store.applyAck(store.prepareAck(request, 200, receipt)); return request
    }

    @Test fun choosingServerKeepsExactSameItemSourceButUsesServerNutritionAndProductMetadata() = runBlocking<Unit> {
        val db = memory()
        try {
            val mealId = uuid(); val itemId = uuid(); val lease = account(db, mealId, itemId)
            val source = correct(db, lease, mealId, itemId)
            val productId = uuid(); val server = payload(itemId, "200", "80", "Server soup", productId)
            val request = response(db, lease, server); val frozen = db.pushDao().batch(request.id)
            val store = SyncConflictStore(db, schema); val ticket = store.open(lease, request.operations.single().operationId)
            assertTrue(ticket.canChoose); assertNull(store.choose(ticket, ConflictChoice.SERVER))
            val item = db.dao().meal(mealId, lease.storageScope)!!.items.single()
            assertEquals(source, item.snapshotJson); assertEquals(itemId, item.id)
            assertEquals(productId, item.productId); assertEquals("Server soup", item.productName)
            assertEquals("160", item.consumed().asExact().energy.canonical) // 200 g × 80 kcal / 100 g.
            assertEquals("200", item.amountText); assertEquals(frozen, db.pushDao().batch(request.id))
            assertEquals("100", JSONObject(source).getJSONObject("original_consumption").getJSONObject("nutrition_per_100").getString("energy_kcal"))
        } finally { db.close() }
    }

    @Test fun laterPullKeepsExactSameItemSourceButFreshIdentityReceivesNoOtherItemsArchive() = runBlocking<Unit> {
        val db = memory()
        try {
            val mealId = uuid(); val itemId = uuid(); val lease = account(db, mealId, itemId)
            val source = correct(db, lease, mealId, itemId); val acknowledged = response(db, lease)
            val frozen = db.pushDao().batch(acknowledged.id)
            val productId = uuid(); val latest = payload(itemId, "50", "200", "Latest soup", productId).json()
            val newItemId = uuid()
            latest.getJSONArray("items").put(payload(newItemId, "100", "35", "New ingredient").json().getJSONArray("items").getJSONObject(0))
            snapshot(db, lease, mealId, 3, MealWire.read(StrictJson.canonical(latest), schema), "2026-10-29T12:00:00Z")
            val items = db.dao().meal(mealId, lease.storageScope)!!.items
            val same = items.single { it.id == itemId }; val added = items.single { it.id == newItemId }
            assertEquals(source, same.snapshotJson); assertEquals(productId, same.productId); assertEquals("Latest soup", same.productName)
            assertEquals("100", same.consumed().asExact().energy.canonical) // 50 g × 200 kcal / 100 g.
            assertEquals("50", same.amountText); assertNull(added.snapshotJson); assertEquals("35", added.consumed().asExact().energy.canonical)
            assertEquals(frozen, db.pushDao().batch(acknowledged.id))
        } finally { db.close() }
    }
}
