package pl.roseru.kalorie

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import java.math.BigDecimal
import java.time.LocalDate
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class AnalyticsStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val end = LocalDate.now().minusDays(2)
    private val window = AnalyticsWindow(end, AnalyticsPeriod.WEEK)

    @Test fun rangeReadsExcludeOtherOwnersTombstonesAndFutureAndKeepHistoricalGoals() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val dao = db.dao()
            suspend fun meal(id: String, date: LocalDate, owner: String, kcal: Double, deleted: Boolean = false) {
                dao.insertMeal(MealEntity(id, owner, date.toString(), "2026-01-01T12:00:00Z", "Europe/Warsaw", "LUNCH", deleted = deleted))
                dao.insertItem(MealItemEntity("$id-item", id, "source", id, 100.0, kcal, 10.0, 5.0, 20.0))
                dao.saveDiaryDay(DiaryDayEntity("$id-day", owner, date.toString(), true, 1))
            }
            meal("start", window.start, "guest", 1000.0)
            meal("end", end, "guest", 2000.0)
            meal("deleted", end.minusDays(1), "guest", 50.0, true)
            meal("outside", window.start.minusDays(1), "guest", 50.0)
            meal("future", end.plusDays(1), "guest", 50.0)
            meal("other", end, "other", 9000.0)
            dao.saveGoal(GoalEntity("old", "guest", window.start.minusDays(20).toString(), 1000.0, null, null, null))
            dao.saveGoal(GoalEntity("new", "guest", end.toString(), 2000.0, null, null, null))
            dao.saveGoal(GoalEntity("future-goal", "guest", end.plusDays(1).toString(), 8000.0, null, null, null))
            dao.saveGoal(GoalEntity("other-goal", "other", window.start.toString(), 9000.0, null, null, null))
            dao.saveWeight(WeightEntity("live", "guest", end.toString(), "2026-01-01T12:00:00Z", "UTC", 80.0))
            dao.saveWeight(WeightEntity("deleted-weight", "guest", end.toString(), "2026-01-01T13:00:00Z", "UTC", 90.0, deleted = true))
            dao.saveWeight(WeightEntity("other-weight", "other", end.toString(), "2026-01-01T14:00:00Z", "UTC", 50.0))
            val result = AnalyticsRepository(dao).observe("guest", window).first()
            assertEquals(2, result.completeDays); assertEquals(2, result.daysInGoal)
            assertEquals(5, result.days.count { it.status == AnalyticsDayStatus.NO_DATA })
            assertEquals(BigDecimal("1000.0"), result.days.first().goal)
            assertEquals(1, result.weightCount); assertEquals("live", result.days.last().weight!!.id)
            assertEquals(0, dao.operationCount("guest"))
        } finally { db.close() }
    }

    @Test fun changesInvalidateAnalyticsAndRestartRetainsDeletionsAndQueue() = runBlocking {
        val name = "analytics-${UUID.randomUUID()}.db"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            val repository = DiaryRepository(db, context)
            repository.initialize()
            val queue = db.dao().operationCount("guest")
            coroutineScope {
                val states = Channel<AnalyticsResult>(Channel.UNLIMITED)
                val job = launch { AnalyticsRepository(db.dao()).observe("guest", window).collect { states.send(it) } }
                suspend fun awaitState(check: (AnalyticsResult) -> Boolean): AnalyticsResult = withTimeout(15_000) {
                    var value = states.receive()
                    while (!check(value)) value = states.receive()
                    value
                }
                try {
                    awaitState { it.daysWithEntries == 0 }
                    repository.add("basic-banana", 100.0, MealType.LUNCH, end, "live-meal")
                    repository.setDayComplete(end, true)
                    val first = awaitState { it.completeDays == 1 }
                    assertEquals("89", first.days.last().total!!.asExact().energy.canonical)
                    repository.edit("live-meal", 200.0)
                    awaitState { it.days.last().total?.asExact()?.energy?.canonical == "178" }
                    repository.addWeight(82.0, end, "live-weight")
                    awaitState { it.weightCount == 1 }
                    repository.editWeight("live-weight", 81.5)
                    awaitState { it.days.last().weight?.kg?.compareTo(BigDecimal("81.5")) == 0 }
                    repository.delete("live-meal")
                    awaitState { it.daysWithEntries == 0 && it.completeDays == 0 }
                    repository.deleteWeight("live-weight")
                    awaitState { it.weightCount == 0 }
                } finally { job.cancelAndJoin(); states.close() }
            }
            val after = db.dao().operationCount("guest")
            assertEquals(queue + 7, after)
            db.close()
            db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            val result = AnalyticsRepository(db.dao()).observe("guest", window).first()
            assertEquals(0, result.completeDays); assertEquals(0, result.daysWithEntries); assertEquals(0, result.weightCount)
            assertEquals(after, db.dao().operationCount("guest"))
            assertTrue(db.dao().meal("live-meal", "guest")!!.meal.deleted)
            assertTrue(db.dao().weight("live-weight", "guest")!!.deleted)
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun missingEnergyInvalidatesPriorDeclarationAndCannotBeConfirmedAgain() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val repository = DiaryRepository(db, context)
            repository.initialize()
            repository.add("basic-banana", 100.0, MealType.LUNCH, end, "known")
            repository.setDayComplete(end, true)
            val product = JSONObject().put("basis_unit", "g").put("nutrition_per_100", JSONObject()
                .put("energy_kcal", JSONObject.NULL).put("protein_g", "0").put("fat_g", "0").put("carbs_g", "0"))
            val snapshot = JSONObject().put("product", product).put("quantity", JSONObject().put("amount", "100").put("unit", "g")).toString()
            db.dao().insertMeal(MealEntity("unknown", "guest", end.toString(), "2026-01-01T12:00:00Z", "UTC", "LUNCH"))
            db.dao().insertItem(MealItemEntity("unknown-item", "unknown", "unknown-product", "Brak kcal", 100.0, 0.0, 0.0, 0.0, 0.0, snapshotJson = snapshot))
            val result = AnalyticsRepository(db.dao()).observe("guest", window).first()
            assertEquals(0, result.completeDays)
            assertEquals("≥ 89", result.days.last().total!!.energyText())
            assertFalse(DayState(end, db.dao().day("guest", end.toString()).first(), status = db.dao().diaryDay("guest", end.toString()).first()).complete)
            val before = db.dao().operationCount("guest")
            try { repository.setDayComplete(end, true); fail("Unknown energy cannot confirm day") } catch (_: IllegalArgumentException) { }
            assertEquals(before, db.dao().operationCount("guest"))
        } finally { db.close() }
    }
}
