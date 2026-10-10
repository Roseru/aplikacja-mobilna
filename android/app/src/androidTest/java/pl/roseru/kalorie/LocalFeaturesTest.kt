package pl.roseru.kalorie

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
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
class LocalFeaturesTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val date = LocalDate.now().minusDays(3)

    @Test fun privateProductIsReusableIsolatedAndAtomic() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            val draft = CustomProductDraft("Moja kasza", 110.0, null, null, null, "Własny przepis")
            repo.addCustomProduct(draft, 150.0, MealType.LUNCH, date, "custom-meal", "private-product")
            repo.addCustomProduct(draft, 150.0, MealType.LUNCH, date, "custom-meal", "private-product")
            val product = db.dao().product("private-product")!!
            assertEquals(DiaryRepository.GUEST, product.ownerScope)
            assertNull(db.dao().product(product.id, "other-account"))
            assertFalse(db.dao().products("other-account").first().any { it.id == product.id })
            val consumed = db.dao().meal("custom-meal", DiaryRepository.GUEST)!!.items.single().consumed()
            assertEquals(165.0, consumed.kcal, .0); assertNull(consumed.protein)
            assertEquals(2, db.dao().operationCount(DiaryRepository.GUEST))
            repo.add(product.id, 200.0, MealType.DINNER, date, "reuse")
            assertEquals(220.0, db.dao().meal("reuse", DiaryRepository.GUEST)!!.items.single().consumed().kcal, .0)
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_queue BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            var failed = false
            try { repo.addCustomProduct(draft, 150.0, MealType.LUNCH, date, "failed-meal", "failed-product") } catch (_: Exception) { failed = true }
            assertTrue(failed)
            assertNull(db.dao().product("failed-product")); assertNull(db.dao().meal("failed-meal", DiaryRepository.GUEST))
        } finally { db.close() }
    }

    @Test fun profileAndMultipleWeightsPersistWithoutChangingGoal() = runBlocking {
        val name = "local-${UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            var repo = DiaryRepository(db, context)
            repo.initialize()
            repo.setProfile("Poligon", 182.5, ActivityClass.LINE, DietAim.REDUCE)
            repo.addWeight(82.4, date, "weight-one")
            repo.addWeight(82.1, date, "weight-two")
            repo.addWeight(82.1, date, "weight-two")
            db.close()
            db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            repo = DiaryRepository(db, context)
            assertEquals("Poligon", db.dao().profile(DiaryRepository.GUEST).first()!!.nickname)
            assertEquals(2, db.dao().weights(DiaryRepository.GUEST).first().size)
            assertEquals(2800.0, db.dao().goal(DiaryRepository.GUEST, LocalDate.now().toString()).first()!!.kcal, .0)
            assertNull(db.dao().profile("other-account").first())
            assertTrue(db.dao().weights("other-account").first().isEmpty())
            repo.editWeight("weight-one", 82.0)
            assertEquals(date.toString(), db.dao().weight("weight-one", DiaryRepository.GUEST)!!.localDate)
            repo.deleteWeight("weight-two")
            repo.deleteWeight("weight-two")
            assertEquals(1, db.dao().weights(DiaryRepository.GUEST).first().size)
            assertTrue(db.dao().weight("weight-two", DiaryRepository.GUEST)!!.deleted)
            assertEquals(5, db.dao().operationCount(DiaryRepository.GUEST))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun completenessNeedsPositiveDiaryAndStopsAfterLastMealRemoved() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            var rejected = false
            try { repo.setDayComplete(date, true) } catch (_: IllegalArgumentException) { rejected = true }
            assertTrue(rejected)
            assertNull(db.dao().diaryDay(DiaryRepository.GUEST, date.toString()).first())
            repo.add("basic-banana", 120.0, MealType.LUNCH, date, "complete-meal")
            repo.setDayComplete(date, true)
            repo.setDayComplete(date, true)
            val status = db.dao().diaryDay(DiaryRepository.GUEST, date.toString()).first()
            val meals = db.dao().day(DiaryRepository.GUEST, date.toString()).first()
            assertTrue(DayState(date, meals, status = status).complete)
            assertNull(db.dao().diaryDay("other-account", date.toString()).first())
            repo.delete("complete-meal")
            assertFalse(DayState(date, db.dao().day(DiaryRepository.GUEST, date.toString()).first(), status = status).complete)
            repo.setDayComplete(date, false)
            assertFalse(db.dao().diaryDay(DiaryRepository.GUEST, date.toString()).first()!!.declaredComplete)
            assertEquals(4, db.dao().operationCount(DiaryRepository.GUEST))
        } finally { db.close() }
    }

    @Test fun migrationFromV2KeepsCompoundRationAndCreatesNewPrivateTables() = runBlocking {
        val name = "migration-v2-${UUID.randomUUID()}.db"
        val schema = JSONObject(InstrumentationRegistry.getInstrumentation().context.assets
            .open("pl.roseru.kalorie.data.CalorieDatabase/2.json").bufferedReader().use { it.readText() }).getJSONObject("database")
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
            old.execSQL("INSERT INTO meals (id,ownerScope,localDate,occurredAt,zoneId,mealType,serverRevision,localRevision,deleted,rationId,rationName) VALUES ('old-ration-meal','guest','2026-10-01','2026-10-01T10:00:00Z','Europe/Warsaw','LUNCH',0,1,0,'demo-ration-a','Racja zachowana')")
            old.execSQL("INSERT INTO meal_items (id,mealId,productId,productName,grams,kcalPer100,proteinPer100,fatPer100,carbsPer100,rationComponentId) VALUES ('old-ration-item','old-ration-meal','demo-ration-meat','Konserwa',50,273,16,22,2.7,'demo-a-meat')")
            old.version = 2
        }
        val db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addMigrations(MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5, MIGRATION_5_6).addCallback(DATABASE_GUARDS).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            val meal = db.dao().meal("old-ration-meal", DiaryRepository.GUEST)!!
            assertEquals("Racja zachowana", meal.meal.rationName)
            assertEquals("demo-a-meat", meal.items.single().rationComponentId)
            assertEquals(136.5, meal.items.single().consumed().kcal, .0)
            repo.setProfile("Test", 180.0, ActivityClass.GARRISON, DietAim.MAINTAIN)
            repo.addWeight(80.0, date, "new-weight")
            assertEquals(2, db.dao().operationCount(DiaryRepository.GUEST))
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
