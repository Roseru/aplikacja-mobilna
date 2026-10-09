package pl.roseru.kalorie

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class RationStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val date = LocalDate.of(2026, 10, 1)

    @Test fun partialRationSurvivesRestartAndItemChangesKeepOtherItems() = runBlocking {
        val name = "rations-${UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).build()
        try {
            var repo = DiaryRepository(db, context)
            repo.initialize()
            val selection = mapOf("demo-a-meat" to 50.0, "demo-a-crackers" to 22.5)
            repo.addRation("demo-ration-a", selection, MealType.DINNER, date, "partial")
            repo.addRation("demo-ration-a", selection, MealType.DINNER, date, "partial")
            assertEquals(1, db.dao().operationCount(DiaryRepository.GUEST))
            db.close()
            db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).build()
            repo = DiaryRepository(db, context)
            repo.initialize()
            assertEquals(2, db.dao().rations().first().size)
            var recorded = db.dao().meal("partial", DiaryRepository.GUEST)!!
            assertEquals("demo-ration-a", recorded.meal.rationId)
            assertEquals(2, recorded.items.size)
            assertEquals(222.0, recorded.items.map { it.consumed() }.total().kcal, .00001)
            val meat = recorded.items.single { it.rationComponentId == "demo-a-meat" }
            val crackers = recorded.items.single { it.rationComponentId == "demo-a-crackers" }
            db.openHelper.writableDatabase.execSQL("UPDATE products SET kcal = 999 WHERE id = 'demo-ration-meat'")
            repo.editItem("partial", meat.id, 25.0)
            recorded = db.dao().meal("partial", DiaryRepository.GUEST)!!
            assertEquals(153.75, recorded.items.map { it.consumed() }.total().kcal, .00001)
            assertEquals(22.5, recorded.items.single { it.id == crackers.id }.grams, .0)
            repo.removeItem("partial", meat.id)
            assertEquals(crackers, db.dao().meal("partial", DiaryRepository.GUEST)!!.items.single())
            repo.removeItem("partial", crackers.id)
            assertTrue(db.dao().day(DiaryRepository.GUEST, date.toString()).first().isEmpty())
            assertTrue(db.dao().meal("partial", DiaryRepository.GUEST)!!.meal.deleted)
            assertEquals(4, db.dao().operationCount(DiaryRepository.GUEST))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun invalidOrEmptySelectionDoesNotCreateAnyMeal() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            val invalid = listOf(emptyMap(), mapOf("demo-b-rice" to 10.0), mapOf("demo-a-meat" to 0.0),
                mapOf("demo-a-meat" to 101.0), mapOf("demo-a-meat" to Double.NaN),
                mapOf("demo-a-meat" to 25.0, "demo-a-crackers" to -1.0))
            invalid.forEachIndexed { i, quantities ->
                try { repo.addRation("demo-ration-a", quantities, MealType.LUNCH, date, "invalid-$i"); fail("Invalid selection accepted") }
                catch (_: IllegalArgumentException) { }
                assertNull(db.dao().meal("invalid-$i", DiaryRepository.GUEST))
            }
            assertEquals(0, db.dao().operationCount(DiaryRepository.GUEST))
        } finally { db.close() }
    }

    @Test fun failedOutboxWriteRollsBackAllRationComponents() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_queue BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            var failed = false
            try { repo.addRation("demo-ration-a", mapOf("demo-a-meat" to 50.0, "demo-a-crackers" to 45.0), MealType.LUNCH, date, "rollback-ration") }
            catch (_: Exception) { failed = true }
            assertTrue(failed)
            assertNull(db.dao().meal("rollback-ration", DiaryRepository.GUEST))
            db.openHelper.readableDatabase.query("SELECT COUNT(*) FROM meal_items").use {
                assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
            }
        } finally { db.close() }
    }

    @Test fun unknownMacrosAndOriginalDateRemainInQueue() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            repo.addRation("demo-ration-b", mapOf("demo-b-rice" to 100.0, "demo-b-soup" to 150.0), MealType.LUNCH, date, "unknown")
            val meal = db.dao().meal("unknown", DiaryRepository.GUEST)!!
            val total = meal.items.map { it.consumed() }.total()
            assertEquals(197.5, total.kcal, .0)
            assertNull(total.protein); assertNull(total.fat); assertNull(total.carbs)
            assertTrue(db.dao().day("other-account", date.toString()).first().isEmpty())
            db.openHelper.readableDatabase.query("SELECT payload FROM outbox WHERE entityId = 'unknown'").use {
                assertTrue(it.moveToFirst())
                val payload = JSONObject(it.getString(0))
                assertEquals(date.toString(), payload.getString("local_date"))
                assertEquals("demo-ration-b", payload.getString("ration_id"))
                assertEquals(2, payload.getJSONArray("items").length())
                assertTrue(payload.getJSONArray("items").getJSONObject(0).has("ration_component_id"))
            }
        } finally { db.close() }
    }

    @Test fun migrationFromV1PreservesExistingDiaryAndQueue() = runBlocking {
        val name = "migration-${UUID.randomUUID()}.db"
        val testContext = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context
        val schema = JSONObject(testContext.assets.open("pl.roseru.kalorie.data.CalorieDatabase/1.json").bufferedReader().use { it.readText() }).getJSONObject("database")
        val file = context.getDatabasePath(name)
        file.parentFile!!.mkdirs()
        SQLiteDatabase.openOrCreateDatabase(file, null).use { old ->
            val entities = schema.getJSONArray("entities")
            for (i in 0 until entities.length()) {
                val entity = entities.getJSONObject(i)
                val table = entity.getString("tableName")
                fun resolve(sql: String) = sql.replace("\${TABLE_NAME}", table)
                old.execSQL(resolve(entity.getString("createSql")))
                val indices = entity.optJSONArray("indices")
                if (indices != null) for (j in 0 until indices.length()) old.execSQL(resolve(indices.getJSONObject(j).getString("createSql")))
            }
            old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY, identity_hash TEXT)")
            old.execSQL("INSERT INTO room_master_table VALUES (42, ?)", arrayOf(schema.getString("identityHash")))
            old.execSQL("INSERT INTO meals VALUES ('old-meal', 'guest', '2026-10-01', '2026-10-01T10:00:00Z', 'Europe/Warsaw', 'LUNCH', 0, 1, 0)")
            old.execSQL("INSERT INTO meal_items VALUES ('old-item', 'old-meal', 'basic-banana', 'Banan', 120, 89, 1.1, 0.3, 22.8)")
            old.execSQL("INSERT INTO goals VALUES ('old-goal', 'guest', '1970-01-01', 2500, 140, 80, 300)")
            old.execSQL("INSERT INTO outbox VALUES ('old-operation', 'guest', 'meal', 'old-meal', 'create', NULL, '{}', '2026-10-01T10:00:00Z', 'pending')")
            old.version = 1
        }
        val db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addMigrations(MIGRATION_1_2).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            val meal = db.dao().day(DiaryRepository.GUEST, date.toString()).first().single()
            assertEquals("old-meal", meal.meal.id)
            assertEquals(106.8, meal.items.single().consumed().kcal, .00001)
            assertNull(meal.meal.rationId)
            assertEquals(2500.0, db.dao().goal(DiaryRepository.GUEST, date.toString()).first()!!.kcal, .0)
            assertEquals(1, db.dao().operationCount(DiaryRepository.GUEST))
            repo.addRation("demo-ration-a", mapOf("demo-a-meat" to 50.0), MealType.LUNCH, date, "new-ration")
            assertEquals(2, db.dao().day(DiaryRepository.GUEST, date.toString()).first().size)
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
