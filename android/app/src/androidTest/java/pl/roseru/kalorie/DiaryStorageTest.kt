package pl.roseru.kalorie

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.MealType
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class DiaryStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test fun restartPreservesSnapshotAndOutbox() = runBlocking {
        val name = "test-${UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).build()
        try {
            var repo = DiaryRepository(db, context)
            repo.initialize()
            val date = LocalDate.of(2026, 10, 9)
            repo.add("basic-banana", 120.0, MealType.LUNCH, date, "meal-test")
            repo.add("basic-banana", 120.0, MealType.LUNCH, date, "meal-test")
            assertEquals(1, db.dao().operationCount(DiaryRepository.GUEST))
            db.close()
            db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).build()
            repo = DiaryRepository(db, context)
            repo.initialize()
            assertEquals(15, db.dao().products().first().size)
            assertEquals(106.8, db.dao().day(DiaryRepository.GUEST, date.toString()).first().single().items.single().consumed().kcal, .00001)
            assertEquals(1, db.dao().operationCount(DiaryRepository.GUEST))
            repo.edit("meal-test", 200.0)
            assertEquals(178.0, db.dao().day(DiaryRepository.GUEST, date.toString()).first().single().items.single().consumed().kcal, .00001)
            repo.delete("meal-test")
            assertTrue(db.dao().day(DiaryRepository.GUEST, date.toString()).first().isEmpty())
            assertTrue(db.dao().meal("meal-test", DiaryRepository.GUEST)!!.meal.deleted)
            assertEquals(3, db.dao().operationCount(DiaryRepository.GUEST))
            assertTrue(db.dao().day("another-account", date.toString()).first().isEmpty())
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun changingGoalDoesNotRewriteYesterday() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            repo.setGoal(3000.0, null, null, null)
            assertEquals(2800.0, db.dao().goal(DiaryRepository.GUEST, LocalDate.now().minusDays(1).toString()).first()!!.kcal, .0)
            assertEquals(3000.0, db.dao().goal(DiaryRepository.GUEST, LocalDate.now().toString()).first()!!.kcal, .0)
            repo.setGoal(3100.0, 150.0, 90.0, 350.0)
            assertEquals(3100.0, db.dao().goal(DiaryRepository.GUEST, LocalDate.now().toString()).first()!!.kcal, .0)
        } finally { db.close() }
    }

    @Test fun productCorrectionDoesNotChangeRecordedNutrition() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            repo.add("basic-banana", 120.0, MealType.LUNCH, LocalDate.now(), "snapshot-test")
            db.openHelper.writableDatabase.execSQL("UPDATE products SET kcal = 150 WHERE id = 'basic-banana'")
            assertEquals(150.0, db.dao().product("basic-banana")!!.kcal, .0)
            assertEquals(106.8, db.dao().meal("snapshot-test", DiaryRepository.GUEST)!!.items.single().consumed().kcal, .00001)
        } finally { db.close() }
    }

    @Test fun failedQueueWriteRollsBackMealAndItsItems() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).build()
        try {
            val repo = DiaryRepository(db, context)
            repo.initialize()
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_queue BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            var failed = false
            try { repo.add("basic-banana", 120.0, MealType.LUNCH, LocalDate.now(), "rollback-test") }
            catch (_: Exception) { failed = true }
            assertTrue(failed)
            assertNull(db.dao().meal("rollback-test", DiaryRepository.GUEST))
            assertEquals(0, db.dao().operationCount(DiaryRepository.GUEST))
        } finally { db.close() }
    }
}
