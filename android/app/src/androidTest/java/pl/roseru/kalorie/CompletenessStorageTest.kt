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
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

class CompletenessStorageTest {
    @Test fun missingEnergyInvalidatesDeclarationAndSurvivesDatabaseRestart() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val name = "completeness-${UUID.randomUUID()}.db"
        fun open() = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        var db = open()
        val date = LocalDate.now()
        try {
            var repo = DiaryRepository(db, context); repo.initialize()
            repo.add("basic-banana", 100.0, MealType.LUNCH, date, "known")
            repo.setDayComplete(date, true)
            suspend fun state() = DayState(date, db.dao().day("guest", date.toString()).first(),
                status = db.dao().diaryDay("guest", date.toString()).first())
            assertTrue(state().complete)
            insertUnknownEnergy(db, date, "unknown")
            assertEquals("≥ 89", state().totals.energyText())
            assertFalse(state().complete)
            assertTrue(state().status!!.declaredComplete)
            val queued = db.dao().operationCount("guest")
            try { repo.setDayComplete(date, true); fail("Missing energy must be rejected") } catch (_: IllegalArgumentException) { }
            assertEquals(queued, db.dao().operationCount("guest"))
            db.close(); db = open(); repo = DiaryRepository(db, context); repo.initialize()
            assertFalse(state().complete); assertTrue(state().status!!.declaredComplete)
            assertEquals(queued, db.dao().operationCount("guest"))
        } finally { db.close(); context.deleteDatabase(name) }
    }
}

internal suspend fun insertUnknownEnergy(db: CalorieDatabase, date: LocalDate, id: String) {
    val product = JSONObject().put("basis_unit", "g").put("nutrition_per_100", JSONObject()
        .put("energy_kcal", JSONObject.NULL).put("protein_g", "0").put("fat_g", "0").put("carbs_g", "0"))
    val snapshot = JSONObject().put("product", product).put("quantity", JSONObject().put("amount", "100").put("unit", "g")).toString()
    db.dao().insertMeal(MealEntity(id, "guest", date.toString(), "2026-01-01T12:00:00Z", "UTC", "LUNCH"))
    db.dao().insertItem(MealItemEntity("$id-item", id, "unknown-product", "Brak kcal", 100.0, 0.0, 0.0, 0.0, 0.0, snapshotJson = snapshot))
}
