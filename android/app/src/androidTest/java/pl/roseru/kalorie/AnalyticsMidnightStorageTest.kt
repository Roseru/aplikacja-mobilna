package pl.roseru.kalorie

import android.content.Context
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference

class AnalyticsMidnightStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val date = LocalDate.of(2026, 10, 10)
    private val now = AtomicReference(Instant.parse("2026-10-10T21:59:59Z"))
    private fun clock() = LocalDayClock({ now.get() }, { ZoneId.of("Europe/Warsaw") }, { withContext(Dispatchers.Default) { delay(250) } })
    @Test fun readRefreshesAfterMidnightAndRestartWithoutWritingOutbox() = runBlocking {
        val name = "midnight-${UUID.randomUUID()}.db"
        fun open() = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        var db = open()
        try {
            val repo = DiaryRepository(db, context); repo.initialize()
            repo.add("basic-banana", 100.0, MealType.LUNCH, date, "midnight-meal")
            repo.setDayComplete(date, true)
            val before = db.dao().operationCount("guest")
            coroutineScope {
                val states = Channel<AnalyticsResult>(Channel.UNLIMITED)
                val job = launch { AnalyticsRepository(db.dao(), clock()).observe("guest", AnalyticsWindow(date, AnalyticsPeriod.WEEK)).collect { states.send(it) } }
                try {
                    val first = withTimeout(10_000) { states.receive() }
                    assertFalse(first.days.last().closed); assertEquals(0, first.completeDays)
                    now.set(Instant.parse("2026-10-10T22:00:00Z"))
                    val next = withTimeout(10_000) { states.receive() }
                    assertTrue(next.days.last().closed); assertEquals(1, next.completeDays)
                    assertEquals(1, next.averages[0].dayCount)
                } finally { job.cancelAndJoin(); states.close() }
            }
            assertEquals(before, db.dao().operationCount("guest"))
            db.close(); db = open()
            val restored = AnalyticsRepository(db.dao(), clock()).observe("guest", AnalyticsWindow(date, AnalyticsPeriod.WEEK)).first()
            assertEquals(1, restored.completeDays); assertEquals(before, db.dao().operationCount("guest"))
        } finally { db.close(); context.deleteDatabase(name) }
    }
    @Test fun viewModelFollowsTodayAndRestoresExplicitHistoricalWindow(): Unit = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val saved = SavedStateHandle()
        lateinit var model: DiaryViewModel
        fun create() = InstrumentationRegistry.getInstrumentation().runOnMainSync {
            model = DiaryViewModel(DiaryRepository(db, context), Preferences(context), saved, clock())
        }
        try {
            create()
            val states = Channel<AnalyticsWindow>(Channel.UNLIMITED)
            var job = launch { model.analyticsWindow.collect { states.send(it) } }
            suspend fun awaitEnd(end: LocalDate) = withTimeout(10_000) { var value = states.receive(); while(value.end != end) value = states.receive(); value }
            awaitEnd(date)
            now.set(Instant.parse("2026-10-10T22:00:00Z"))
            awaitEnd(date.plusDays(1))
            withContext(Dispatchers.Main) { model.moveAnalyticsWindow(-1) }
            val historical = date.plusDays(1).minusDays(7)
            awaitEnd(historical)
            job.cancelAndJoin(); withContext(Dispatchers.Main) { model.viewModelScope.cancel() }
            create()
            job = launch { model.analyticsWindow.collect { states.send(it) } }
            awaitEnd(historical)
            now.set(Instant.parse("2026-10-11T22:00:00Z"))
            delay(100)
            assertEquals(historical, model.analyticsWindow.value.end)
            withContext(Dispatchers.Main) { model.analyticsToday() }
            awaitEnd(date.plusDays(2))
            job.cancelAndJoin(); states.close()
        } finally { withContext(Dispatchers.Main) { model.viewModelScope.cancel() }; db.close() }
    }
}
