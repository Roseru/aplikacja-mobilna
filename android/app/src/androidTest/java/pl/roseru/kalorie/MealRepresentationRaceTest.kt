package pl.roseru.kalorie

import androidx.room.Room
import androidx.room.withTransaction
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.math.BigDecimal
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Queue a canonical promotion between the legacy probe and fallback, without a production hook. */
class MealRepresentationRaceTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private fun uuid() = UUID.randomUUID().toString()

    @Test fun correctionCannotWriteLegacyAfterConcurrentCanonicalPromotion() = runBlocking { race(add = false) }
    @Test fun additionCannotWriteLegacyAfterConcurrentCanonicalPromotion() = runBlocking { race(add = true) }

    private suspend fun race(add: Boolean) {
        val transactionExecutor = Executors.newSingleThreadExecutor()
        val armed = AtomicBoolean(false); val queued = CountDownLatch(1); val promoted = CountDownLatch(1)
        val promotionFailure = AtomicReference<Throwable?>()
        val id = uuid(); var promote: (() -> Unit)? = null
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS)
            .setTransactionExecutor(transactionExecutor)
            .setQueryCallback({ sql, arguments ->
                if (sql.startsWith("SELECT") && sql.contains("FROM meals WHERE id =") && arguments.firstOrNull() == id && armed.compareAndSet(true, false)) {
                    // The probe still owns the transaction. This raw task is queued before Room can
                    // schedule its fallback transaction; waiting here would deadlock the probe.
                    transactionExecutor.execute {
                        try { checkNotNull(promote).invoke() } catch (error: Throwable) { promotionFailure.set(error) }
                        finally { promoted.countDown() }
                    }
                    queued.countDown()
                }
            }, Executor { it.run() }).build()
        try {
            val owners = LocalOwnerStore(db); owners.ensureGuest()
            val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/representation", uuid()).id)
            val epoch = uuid(); val bootstrap = AccountBootstrapStore(db)
            bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(uuid(), epoch, 1, "2026-10-17T12:00:00Z"))
            val schema = CanonicalMealRows.schema(context); val itemId = uuid(); val operationId = uuid()
            val wire = ManualMealWire.create("Original", itemId, "100", "g", ExactNutrition(BigDecimal("100"), BigDecimal("2"), null, BigDecimal("10")),
                "2026-10-17T12:00:00Z", "UTC", "lunch", schema)
            val wireContext = CanonicalMealRows.context(checkNotNull(db.bootstrapDao().binding(lease.storageScope)))
            val meal = CanonicalMealRows.meal(id, lease.storageScope, wire, wireContext)
            val item = CanonicalMealRows.items(id, wire).single()
            val originalOperation = OutboxEntity(uuid(), lease.storageScope, "meal", id, "create", null, "{}", "2026-10-17T12:00:00Z")
            val canonicalOperation = OutboxEntity(operationId, lease.storageScope, "meal", id, "upsert", null, wire.canonical,
                "2026-10-17T12:00:00Z", "pending", "sync-v1", MealWire.operation(operationId, id, epoch, null, wire.canonical, schema), wireContext)
            db.withTransaction {
                db.dao().insertMeal(meal.copy(wirePayload = null, wireContext = null))
                db.dao().insertItem(item.copy(wirePayload = null)); db.dao().enqueue(originalOperation)
            }
            promote = {
                val sql = db.openHelper.writableDatabase
                sql.beginTransaction()
                try {
                    sql.execSQL("UPDATE meals SET wirePayload=?,wireContext=? WHERE id=?", arrayOf(wire.canonical, wireContext, id))
                    sql.execSQL("UPDATE meal_items SET wirePayload=? WHERE id=?", arrayOf(item.wirePayload, itemId))
                    sql.execSQL("INSERT INTO outbox (operationId,ownerScope,entityType,entityId,action,baseRevision,payload,createdAt,status,wireFormat,wireJson,wireContext,attempted) VALUES (?,?,?,?,?,NULL,?,?,?,?,?,?,0)",
                        arrayOf(operationId, lease.storageScope, "meal", id, "upsert", wire.canonical, canonicalOperation.createdAt,
                            "pending", "sync-v1", canonicalOperation.wireJson, wireContext))
                    sql.setTransactionSuccessful()
                } finally { sql.endTransaction() }
            }
            val repository = DiaryRepository(db, context, lease)
            val correction = MealIngredientInput("Changed", "50", QuantityUnit.GRAMS, QuantityUnit.GRAMS,
                ExactNutrition(BigDecimal("240"), BigDecimal.ZERO, BigDecimal.ZERO, null))
            armed.set(true)
            val refused = withTimeout(10_000) {
                try {
                    if (add) repository.addIngredient(id, correction) else repository.correctIngredient(id, itemId, correction)
                    null
                } catch (error: CancellationException) { throw error } catch (error: IllegalStateException) { error }
            }
            assertTrue("Canonical probe was not observed", queued.await(10, TimeUnit.SECONDS))
            assertTrue("Canonical promotion did not finish", promoted.await(10, TimeUnit.SECONDS))
            promotionFailure.get()?.let { throw AssertionError("Synthetic promotion failed", it) }
            assertNotNull("Fallback overwrote a canonical representation", refused)
            assertTrue(checkNotNull(refused).message.orEmpty().startsWith("Meal representation changed"))
            assertEquals(MealWithItems(meal, listOf(item)), db.dao().meal(id, lease.storageScope))
            assertEquals(originalOperation, db.dao().operation(originalOperation.operationId))
            assertEquals(canonicalOperation, db.dao().operation(operationId))
            assertEquals(2, db.dao().operationCount(lease.storageScope))
            assertEquals(wire.canonical, db.dao().meal(id, lease.storageScope)!!.meal.wirePayload)
            assertEquals("100", db.dao().meal(id, lease.storageScope)!!.items.single().consumed().asExact().energy.canonical)
        } finally {
            db.close(); transactionExecutor.shutdownNow()
            check(transactionExecutor.awaitTermination(10, TimeUnit.SECONDS))
        }
    }
}
