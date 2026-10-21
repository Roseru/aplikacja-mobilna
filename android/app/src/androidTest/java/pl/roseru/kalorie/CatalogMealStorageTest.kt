package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import java.math.BigDecimal
import java.time.LocalDate
import java.util.UUID
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.MealType
import pl.roseru.kalorie.core.sync.MealWire
import pl.roseru.kalorie.data.*

class CatalogMealStorageTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db: CalorieDatabase, bootstrap: Boolean = true): OwnerLease {
        val owners = LocalOwnerStore(db); owners.ensureGuest()
        val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/catalog", UUID.randomUUID().toString()).id)
        if (bootstrap) {
            val store = AccountBootstrapStore(db)
            store.apply(store.begin(lease), BootstrapResponse(UUID.randomUUID().toString(), UUID.randomUUID().toString(), 1, "2026-10-21T12:00:00Z"))
        }
        return lease
    }
    @Test fun productCreatesOneCanonicalMealAndEditingKeepsItsLocalCatalogueAssociation() = runBlocking<Unit> {
        val db = memory()
        try {
            DiaryRepository(db, context).initialize(); val lease = account(db)
            val repo = DiaryRepository(db, context, lease)
            val product = db.dao().products(lease.storageScope).first().first { it.catalogJson != null }
            val id = UUID.randomUUID().toString(); val day = LocalDate.now()
            repo.add(product.id, 25.5, MealType.LUNCH, day, id)
            val saved = db.dao().meal(id, lease.storageScope)!!; val item = saved.items.single()
            val wire = MealWire.read(saved.meal.wirePayload!!, CanonicalMealRows.schema(context)).json()
            val reference = wire.getJSONArray("items").getJSONObject(0).getJSONObject("product")
            assertEquals(JSONObject(product.catalogJson!!).getString("product_id"), reference.getString("product_id"))
            assertEquals(product.id, item.productId); assertNotNull(item.snapshotJson)
            assertEquals(1, db.dao().operationCount(lease.storageScope))
            repo.add(product.id, 25.5, MealType.LUNCH, day, id)
            assertEquals(1, db.dao().operationCount(lease.storageScope))
            repo.editItem(id, item.id, 12.25, "12.25")
            val edited = db.dao().meal(id, lease.storageScope)!!.items.single()
            assertEquals(item.id, edited.id); assertEquals(product.id, edited.productId)
            assertEquals(item.snapshotJson, edited.snapshotJson); assertEquals("12.25", edited.amountText)
        } finally { db.close() }
    }
    @Test fun onlySelectedRationComponentsAreQueuedAndQueueFailureRollsBackTheWholeMeal() = runBlocking<Unit> {
        val db = memory()
        try {
            DiaryRepository(db, context).initialize(); val lease = account(db)
            val repo = DiaryRepository(db, context, lease); val day = LocalDate.now()
            val ration = db.dao().rations().first().first { it.ration.catalogJson != null && it.components.size >= 2 }
            val chosen = ration.components.sortedBy { it.position }.take(2)
            val amounts = chosen.associate { it.id to BigDecimal(it.quantityText!!).divide(BigDecimal("2")).stripTrailingZeros().toPlainString() }
            val quantities = amounts.mapValues { it.value.toDouble() }; val id = UUID.randomUUID().toString()
            repo.addRation(ration.ration.id, quantities, MealType.DINNER, day, id, amounts)
            val meal = db.dao().meal(id, lease.storageScope)!!; val wire = JSONObject(meal.meal.wirePayload!!)
            assertEquals(ration.ration.id, meal.meal.rationId); assertEquals(2, meal.items.size)
            assertEquals(JSONObject(ration.ration.catalogJson!!).getString("ration_id"), wire.getJSONObject("ration").getString("ration_id"))
            assertEquals(chosen.map { it.position }, (0 until 2).map { wire.getJSONArray("items").getJSONObject(it).getInt("ration_component_position") })
            assertEquals(chosen.map { it.id }.toSet(), meal.items.map { it.rationComponentId }.toSet())
            val failedId = UUID.randomUUID().toString()
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER reject_catalog BEFORE INSERT ON outbox WHEN NEW.wireFormat='sync-v1' BEGIN SELECT RAISE(ABORT,'synthetic write failure'); END")
            var rejected = false
            try { repo.addRation(ration.ration.id, quantities, MealType.DINNER, day, failedId, amounts) }
            catch (error: CancellationException) { throw error }
            catch (_: Exception) { rejected = true }
            assertTrue(rejected)
            assertNull(db.dao().meal(failedId, lease.storageScope)); assertEquals(1, db.dao().operationCount(lease.storageScope))
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        } finally { db.close() }
    }
    @Test fun guestUnlinkedRecoveryAndExtraPrecisionKeepTheOriginalLocalSnapshot() = runBlocking<Unit> {
        for (mode in listOf("guest", "unlinked", "recovery", "precision")) {
            val db = memory()
            try {
                DiaryRepository(db, context).initialize()
                val lease = if (mode == "guest") LocalOwnerStore(db).currentLease() else account(db, mode != "unlinked")
                if (mode == "recovery") {
                    val binding = db.bootstrapDao().binding(lease.storageScope)!!
                    db.bootstrapDao().update(binding.copy(requiresRecovery = true))
                }
                val repo = DiaryRepository(db, context, lease)
                val product = db.dao().products(lease.storageScope).first().first { it.catalogJson != null }
                val id = UUID.randomUUID().toString(); val amount = if (mode == "precision") "1.0000001" else "25.5"
                repo.add(product.id, amount.toDouble(), MealType.SNACK, LocalDate.now(), id, amount)
                val meal = db.dao().meal(id, lease.storageScope)!!
                assertNull(meal.meal.wirePayload); assertEquals(amount, meal.items.single().amountText)
                assertTrue(db.dao().canonicalMealOperations(lease.storageScope, id).isEmpty())
                assertEquals(1, db.dao().operationCount(lease.storageScope))
            } finally { db.close() }
        }
    }
}
