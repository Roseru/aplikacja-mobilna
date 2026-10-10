package pl.roseru.kalorie

import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

class AnalyticsMidnightTest {
    private val date = LocalDate.of(2026, 10, 10)
    private val window = AnalyticsWindow(date, AnalyticsPeriod.WEEK)
    private val input = AnalyticsInput(listOf(AnalyticsMeal(date, listOf(Nutrients(2800.0, 100.0, null, 0.0)))),
        listOf(AnalyticsGoal(date, BigDecimal("2800"))), setOf(date), emptyList())
    @Test fun todayIsPreliminaryThenClosesWithoutChangingInput() {
        val before = Analytics.build(window, input, date)
        assertFalse(before.days.last().closed); assertTrue(before.days.last().preliminaryInGoal!!)
        assertNull(before.days.last().inGoal); assertEquals(0, before.completeDays)
        assertEquals(0, before.daysInGoal); assertEquals(0, before.daysWithGoal)
        assertEquals(0, before.averages[0].dayCount); assertNull(before.averages[0].value)
        val after = Analytics.build(window, input, date.plusDays(1))
        assertTrue(after.days.last().closed); assertNull(after.days.last().preliminaryInGoal)
        assertEquals(1, after.completeDays); assertEquals(1, after.daysInGoal); assertEquals(1, after.daysWithGoal)
        assertEquals(1, after.averages[0].dayCount); assertEquals(0, after.averages[2].dayCount)
    }
    @Test fun incompleteDayStaysUnassessedAfterMidnight() {
        val incomplete = input.copy(declarations = emptySet())
        listOf(date, date.plusDays(1)).forEach { today ->
            val result = Analytics.build(window, incomplete, today)
            assertNull(result.days.last().inGoal); assertNull(result.days.last().preliminaryInGoal)
            assertEquals(0, result.daysWithGoal); assertNull(result.averages[0].value)
        }
    }
    @Test fun WarsawSpringAndAutumnUseCalendarMidnightNotTwentyFourHours() {
        val zone = ZoneId.of("Europe/Warsaw")
        val spring = LocalDayClock({ Instant.parse("2026-03-28T23:00:00Z") }, { zone })
        val autumn = LocalDayClock({ Instant.parse("2026-10-24T22:00:00Z") }, { zone })
        assertEquals(23 * 60 * 60 * 1000L, spring.untilNextDayMillis())
        assertEquals(25 * 60 * 60 * 1000L, autumn.untilNextDayMillis())
    }
    @Test fun datesRefreshAtLocalBoundaryWithoutAnyDataWrite() = runBlocking {
        var now = Instant.parse("2026-10-10T21:59:59.900Z")
        val clock = LocalDayClock({ now }, { ZoneId.of("Europe/Warsaw") }, { milliseconds -> now = now.plusMillis(milliseconds) })
        assertEquals(listOf(date, date.plusDays(1)), clock.dates().take(2).toList())
    }
    @Test fun zoneChangeIsNotConfusedWithUtcDate() {
        var zone = ZoneId.of("Europe/Warsaw")
        val clock = LocalDayClock({ Instant.parse("2026-10-10T22:30:00Z") }, { zone })
        assertEquals(date.plusDays(1), clock.today())
        zone = ZoneId.of("UTC")
        assertEquals(date, clock.today())
    }
}
