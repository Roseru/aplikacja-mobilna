package pl.roseru.kalorie

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

class MreCatalogueFlowTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val day = LocalDate.of(2026, 10, 26)
    private fun database(name: String) = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
    private suspend fun repository(db: CalorieDatabase, lease: OwnerLease? = null) = DiaryRepository(db, context, lease).also {
        it.initialize(); assertTrue("Actual reference release must load, not quietly fall back", it.mreCatalogue.value is MreCatalogueState.Ready)
    }
    private suspend fun menu(repo: DiaryRepository, number: Int): RationWithComponents {
        val index = context.assets.open("catalog/mre2026/selection-rules.json").use { JSONObject(String(it.readBytes())) }
        val id = index.getJSONArray("menus").objects().single { it.getInt("number") == number }.getString("ration_id")
        return repo.dao.rations().first().single { it.ration.catalogJson?.let(::JSONObject)?.optString("ration_id") == id }
    }

    @Test fun sourceMenusRejectDoubleVariantAndKeepPartialNutritionSnapshotAcrossReopen() = runBlocking {
        val name = "mre-reference-${UUID.randomUUID()}.db"
        var db = database(name)
        try {
            var repo = repository(db)
            assertEquals(27, repo.dao.rations().first().size)
            val first = menu(repo, 1)
            val chili = first.components.single { it.position == 1 }
            repo.addRation(first.ration.id, mapOf(chili.id to 113.5), MealType.LUNCH, day, "partial-mre", mapOf(chili.id to "113.5"))
            val saved = db.dao().meal("partial-mre", DiaryRepository.GUEST)!!
            val snapshot = saved.items.single().snapshotJson
            assertNotNull(snapshot)
            assertEquals("145", saved.items.single().consumed().asExact().energy.display)
            assertTrue(snapshot!!.contains("COMRAD2026/page=1/profile=Nf999ea8e84"))
            val cake = menu(repo, 9)
            val policy = repo.mreCatalogue.value.selectionFor(cake.ration.catalogJson)!!
            val alternatives = cake.components.filter { policy.origins[it.position]?.nutritionStatus == "variant_profiles" }
            assertEquals(3, alternatives.size)
            try {
                repo.addRation(cake.ration.id, alternatives.take(2).associate { it.id to it.packageGrams }, MealType.LUNCH, day, "invalid-variants")
                fail("Both alternative cakes were accepted")
            } catch (_: IllegalArgumentException) { }
            assertNull(db.dao().meal("invalid-variants", DiaryRepository.GUEST))
            assertEquals(1, db.dao().operationCount(DiaryRepository.GUEST))
            db.close(); db = database(name); repo = repository(db)
            val restored = db.dao().meal("partial-mre", DiaryRepository.GUEST)!!
            assertEquals(snapshot, restored.items.single().snapshotJson)
            assertEquals("145", restored.items.single().consumed().asExact().energy.display)
            repo.addRation(first.ration.id, mapOf(chili.id to 113.5), MealType.LUNCH, day, "partial-mre", mapOf(chili.id to "113.5"))
            assertEquals(1, db.dao().operationCount(DiaryRepository.GUEST))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun missingNutritionPersistsAsMissingInGuestDiaryAndOriginalQueueAfterRestart() = runBlocking {
        val name = "mre-unknown-${UUID.randomUUID()}.db"
        var db = database(name)
        try {
            var repo = repository(db)
            val ration = menu(repo, 3)
            val missing = repo.mreCatalogue.value.selectionFor(ration.ration.catalogJson)!!.missing.first { !it.equipment }
            val input = MreManualInput.read("2,5", ExactNutrition.fields.associateWith { "" })
            repo.addUncertainMre(ration.ration.id, missing.locator, input, MealType.DINNER, day, "unknown-mre")
            val before = db.dao().meal("unknown-mre", DiaryRepository.GUEST)!!
            assertEquals(1, before.items.size)
            assertNull(before.items.single().kcalPer100)
            assertEquals("manual", JSONObject(before.items.single().wirePayload!!).getString("nutrition_origin"))
            assertTrue(JSONObject(before.items.single().wirePayload!!).isNull("product"))
            val totals = before.items.single().consumed()
            assertEquals(1, totals.asExact().energy.missingCount)
            assertFalse(completeDiary(true, 1, totals))
            val queue = db.openHelper.readableDatabase.query("SELECT payload FROM outbox WHERE entityId=?", arrayOf("unknown-mre")).use {
                assertTrue(it.moveToFirst()); it.getString(0)
            }
            assertTrue(JSONObject(queue).getJSONArray("items").getJSONObject(0).isNull("kcal_per_100"))
            db.close(); db = database(name); repo = repository(db)
            val after = db.dao().meal("unknown-mre", DiaryRepository.GUEST)!!
            assertEquals(before, after)
            assertEquals(1, db.dao().operationCount(DiaryRepository.GUEST))
            val restored = db.openHelper.readableDatabase.query("SELECT payload FROM outbox WHERE entityId=?", arrayOf("unknown-mre")).use {
                assertTrue(it.moveToFirst()); it.getString(0)
            }
            assertEquals(queue, restored)
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun accountManualSnapshotQueuesExactWireAtomicallyAndRejectsOldOwnerLease() = runBlocking {
        val name = "mre-account-${UUID.randomUUID()}.db"
        val db = database(name)
        try {
            val owners = LocalOwnerStore(db)
            val account = owners.registerIdentity("https://mre-test.invalid/realm", "synthetic-mre-owner")
            val lease = owners.select(account.id)
            val binding = AccountBindingEntity(lease.storageScope, UUID.randomUUID().toString(), 1, UUID.randomUUID().toString(),
                "2026-10-26T12:00:00Z", 1, false)
            db.bootstrapDao().insert(binding)
            val repo = repository(db, lease)
            val ration = menu(repo, 3)
            val missing = repo.mreCatalogue.value.selectionFor(ration.ration.catalogJson)!!.missing.first { !it.equipment }
            val input = MreManualInput.read("2.5", ExactNutrition.fields.associateWith { "" })
            repo.addUncertainMre(ration.ration.id, missing.locator, input, MealType.SNACK, day, "account-mre")
            val saved = db.dao().meal("account-mre", lease.storageScope)!!
            assertNotNull(saved.meal.wirePayload)
            assertEquals(CanonicalMealRows.context(binding), saved.meal.wireContext)
            val op = db.dao().canonicalMealOperations(lease.storageScope, "account-mre").single()
            assertEquals("sync-v1", op.wireFormat)
            assertNotNull(op.wireJson)
            assertEquals(saved.meal.wirePayload, op.payload)
            assertTrue(JSONObject(saved.items.single().wirePayload!!).getJSONObject("nutrition_per_100").isNull("energy_kcal"))
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER mre_fail_queue BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
            try { repo.addUncertainMre(ration.ration.id, missing.locator, input, MealType.SNACK, day, "rolled-back"); fail("Queue failure ignored") }
            catch (_: Exception) { }
            assertNull(db.dao().meal("rolled-back", lease.storageScope))
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER mre_fail_queue")
            owners.select(owners.ensureGuest().id)
            try { repo.addUncertainMre(ration.ration.id, missing.locator, input, MealType.SNACK, day, "stale"); fail("Old owner wrote") }
            catch (_: StaleOwnerException) { }
            assertNull(db.dao().meal("stale", lease.storageScope))
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
