package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate

class AnalyticsTest {
    private val end = LocalDate.of(2026, 3, 2)
    private val window = AnalyticsWindow(end, AnalyticsPeriod.WEEK)
    private fun goal(from: LocalDate, kcal: String) = AnalyticsGoal(from, BigDecimal(kcal))
    private fun food(date: LocalDate, kcal: Double, protein: Double? = 10.0) = AnalyticsMeal(date, listOf(Nutrients(kcal, protein, 5.0, 20.0)))
    private fun build(meals: List<AnalyticsMeal> = emptyList(), goals: List<AnalyticsGoal> = emptyList(),
        declared: Set<LocalDate> = emptySet(), weights: List<AnalyticsWeight> = emptyList(), range: AnalyticsWindow = window) =
        Analytics.build(range, AnalyticsInput(meals, goals, declared, weights))

    @Test fun periodsIncludeExactlyCalendarDaysAcrossMonthAndLeapYear() {
        AnalyticsPeriod.entries.forEach { period ->
            val range = AnalyticsWindow(LocalDate.of(2024, 3, 1), period)
            val result = build(range = range)
            assertEquals(period.days, result.days.size)
            assertEquals(range.start, result.days.first().date)
            assertEquals(range.end, result.days.last().date)
            assertTrue(result.days.any { it.date == LocalDate.of(2024, 2, 29) })
        }
    }
    @Test fun absentAndUndeclaredDaysAreNotZeroOrDeficitAndNotInAverage() {
        val result = build(listOf(food(end, 100.0)), listOf(goal(window.start, "200")))
        assertEquals(6, result.days.count { it.status == AnalyticsDayStatus.NO_DATA })
        assertNull(result.days.first().total)
        assertEquals(AnalyticsDayStatus.INCOMPLETE, result.days.last().status)
        assertEquals(0, result.completeDays); assertEquals(0, result.daysWithGoal)
        assertNull(result.averages[0].value)
    }
    @Test fun goalChangesUseHistoricalVersionAndCarryForwardBeforeWindow() {
        val earlier = end.minusDays(1)
        val result = build(listOf(food(earlier, 1000.0), food(end, 2000.0)),
            listOf(goal(end.plusDays(1), "3000"), goal(end, "2000"), goal(window.start.minusDays(50), "1000")), setOf(earlier, end))
        assertEquals(BigDecimal("1000"), result.days.first().goal)
        assertEquals(2, result.daysInGoal)
        assertEquals(BigDecimal("2000"), result.days.last().goal)
    }
    @Test fun toleranceIncludesExactBoundariesAndDoesNotRoundBeforeAssessment() {
        listOf("899.999999" to false, "900" to true, "1100" to true, "1100.000001" to false).forEach { (energy, expected) ->
            val totals = ExactTotals(FieldAggregate(BigDecimal(energy), 0, 0), FieldAggregate(BigDecimal.ZERO, 0, 1),
                FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1))
            val result = build(listOf(AnalyticsMeal(end, listOf(Nutrients.fromExact(totals)))), listOf(goal(end, "1000")), setOf(end))
            assertEquals(energy, expected, result.days.last().inGoal)
        }
        assertEquals("goal_band_v1", Analytics.GOAL_RULE)
    }
    @Test fun completeDiaryWithoutGoalHasAverageButNoTargetAssessment() {
        val result = build(listOf(food(end, 123.0)), declared = setOf(end))
        assertEquals(1, result.completeDays); assertEquals(0, result.daysWithGoal)
        assertEquals(0, result.daysInGoal); assertNull(result.days.last().inGoal)
        assertEquals(0, result.averages[0].value!!.compareTo(BigDecimal("123")))
    }
    @Test fun averagesUsePerFieldDenominatorAndKnownZeroMacros() {
        val yesterday = end.minusDays(1)
        val result = build(listOf(food(yesterday, 100.0, null), food(end, 200.0, 0.0)), declared = setOf(end, yesterday))
        assertEquals(2, result.averages[0].dayCount)
        assertEquals(0, result.averages[0].value!!.compareTo(BigDecimal("150")))
        assertEquals(1, result.averages[1].dayCount)
        assertEquals(0, result.averages[1].value!!.compareTo(BigDecimal.ZERO))
        assertFalse(result.days[result.days.lastIndex - 1].total!!.asExact().protein.complete)
    }
    @Test fun unknownEnergyRemainsKnownLowerBoundButExcludesDeclaredDay() {
        val missing = Nutrients.fromExact(ExactTotals(FieldAggregate(BigDecimal.ZERO, 1, 0),
            FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1)))
        val result = build(listOf(AnalyticsMeal(end, listOf(Nutrients(100.0, 1.0, 2.0, 3.0), missing))),
            listOf(goal(end, "100")), setOf(end))
        assertEquals("≥ 100", result.days.last().total!!.energyText())
        assertEquals(0, result.completeDays); assertNull(result.days.last().inGoal)
        assertNull(result.averages[0].value)
    }
    @Test fun exactSumIsAveragedBeforeDisplayRounding() {
        val small = Nutrients.fromExact(ExactTotals(FieldAggregate(BigDecimal("0.49"), 0, 0),
            FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1)))
        val result = build(listOf(AnalyticsMeal(end, listOf(small, small))), declared = setOf(end))
        assertEquals("0.98", result.days.last().total!!.asExact().energy.canonical)
        assertEquals(0, result.averages[0].value!!.compareTo(BigDecimal("0.98")))
    }
    @Test fun windowExcludesOutsideMealsWeightsAndDeclarations() {
        val result = build(listOf(food(window.start.minusDays(1), 1.0), food(end.plusDays(1), 2.0), food(end, 3.0)),
            declared = setOf(window.start.minusDays(1), end.plusDays(1)))
        assertEquals(1, result.daysWithEntries); assertEquals(0, result.completeDays)
    }
    @Test fun weightUsesLatestActualMeasurementPerDateWithNoInterpolation() {
        fun point(id: String, date: LocalDate, at: String, kg: String) = AnalyticsWeight(id, date, Instant.parse(at), BigDecimal(kg))
        val first = window.start
        val result = build(weights = listOf(
            point("morning", first, "2026-02-24T08:00:00Z", "85"), point("evening", first, "2026-02-24T20:00:00Z", "84"),
            point("last", end, "2026-03-02T08:00:00Z", "82.5"), point("outside", end.plusDays(1), "2026-03-03T08:00:00Z", "20")))
        assertEquals(3, result.weightCount)
        assertEquals("evening", result.days.first().weight!!.id)
        assertEquals(5, result.days.count { it.weight == null })
        assertEquals(0, result.weightChange!!.compareTo(BigDecimal("-1.5")))
    }
    @Test fun singleDayWeightCannotSuggestMultiDayProgressAndTieIsDeterministic() {
        val at = Instant.parse("2026-03-02T08:00:00Z")
        val result = build(weights = listOf(AnalyticsWeight("a", end, at, BigDecimal("84")), AnalyticsWeight("z", end, at, BigDecimal("83"))))
        assertEquals("z", result.days.last().weight!!.id)
        assertNull(result.weightChange)
    }
    @Test fun completeDiaryMatchesAllNormativeDayVectors() {
        val source = javaClass.getResourceAsStream("/contracts/nutrition-v1.json")!!.bufferedReader().use { it.readText() }
        val cases = JSONObject(source).getJSONArray("day_cases")
        for (index in 0 until cases.length()) {
            val row = cases.getJSONObject(index)
            val totals = ExactTotals(FieldAggregate(BigDecimal(row.getString("known_energy")), row.getInt("missing_energy_count"), 0),
                FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1))
            assertEquals(row.getString("id"), row.getBoolean("expected_complete"), completeDiary(row.getBoolean("declared_complete"),
                row.getInt("meal_count"), Nutrients.fromExact(totals)))
        }
    }
}
