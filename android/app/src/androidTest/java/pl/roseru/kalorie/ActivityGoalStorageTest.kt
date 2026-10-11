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
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate

@RunWith(AndroidJUnit4::class)
class ActivityGoalStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test fun modeUpdatesGoalAndOutboxButPreservesHistoryMacrosAndManualOverride() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val repo = DiaryRepository(db, context); repo.initialize()
            val today = LocalDate.now().toString()
            val yesterday = LocalDate.now().minusDays(1).toString()
            val before = db.dao().goal("guest", yesterday).first()!!
            repo.setProfileAndActivityGoal("Poligon", 180.0, ActivityClass.LINE, DietAim.MAINTAIN)
            val line = db.dao().goal("guest", today).first()!!
            assertEquals(3500.0, line.kcal, 0.0)
            assertEquals(before.protein, line.protein); assertEquals(before.fat, line.fat); assertEquals(before.carbs, line.carbs)
            assertEquals(before, db.dao().goal("guest", yesterday).first())
            assertEquals(2, db.dao().operationCount("guest"))
            repo.setProfileAndActivityGoal("Nowy pseudonim", 182.0, ActivityClass.LINE, DietAim.REDUCE)
            assertEquals(line, db.dao().goal("guest", today).first())
            repo.setGoal(3000.0, 150.0, null, null, "manual-target")
            repo.setProfileAndActivityGoal("Poligon", 182.0, ActivityClass.COMMANDO, DietAim.REDUCE)
            val commando = db.dao().goal("guest", today).first()!!
            assertEquals(3600.0, commando.kcal, 0.0)
            assertEquals("manual-target", commando.correctionOf)
            assertEquals(150.0, commando.protein!!, 0.0); assertNull(commando.fat); assertNull(commando.carbs)
            repo.initialize()
            assertEquals(commando, db.dao().goal("guest", today).first())
            assertEquals(before, db.dao().goal("guest", yesterday).first())
        } finally { db.close() }
    }

    @Test fun failedGoalQueueRollsBackProfileGoalAndAllOperations() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val repo = DiaryRepository(db, context); repo.initialize()
            val before = db.dao().goal("guest", LocalDate.now().toString()).first()
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_activity_goal BEFORE INSERT ON outbox WHEN NEW.entityType = 'goal' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            var rejected = false
            try { repo.setProfileAndActivityGoal("Poligon", 180.0, ActivityClass.LINE, DietAim.MAINTAIN) }
            catch (_: Exception) { rejected = true }
            assertTrue(rejected); assertNull(db.dao().currentProfile("guest"))
            assertEquals(before, db.dao().goal("guest", LocalDate.now().toString()).first())
            assertEquals(0, db.dao().operationCount("guest"))
        } finally { db.close() }
    }
}
