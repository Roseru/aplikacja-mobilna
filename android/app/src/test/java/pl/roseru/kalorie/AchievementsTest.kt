package pl.roseru.kalorie

import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import java.math.BigDecimal
import java.time.*

class AchievementsTest {
    private val today = LocalDate.of(2026, 10, 12)
    private val now = today.atTime(12, 0).toInstant(ZoneOffset.UTC)
    private fun meal(date: LocalDate, kcal: Double = 2000.0, position: Int? = null, ration: Boolean = false,
        zone: String = "UTC", amount: String = "100") = AchievementMeal(date, zone, ration,
        listOf(AchievementPortion(Nutrients(kcal, null, null, null), BigDecimal(amount), position)))
    private fun input(meals: List<AchievementMeal>, goals: List<AnalyticsGoal> = listOf(AnalyticsGoal(today.minusYears(2), BigDecimal("2000"))),
        declared: Set<LocalDate> = meals.map { it.date }.toSet(), weights: List<AchievementWeight> = emptyList()) =
        AchievementInput(meals, goals, declared, weights)
    private fun preview(input: AchievementInput, at: Instant = now, zone: ZoneId = ZoneOffset.UTC) = Achievements.build(input, at, zone)
    private fun AchievementPreview.badge(code: AchievementCode) = badges.single { it.code == code }
    private val dates = (10L downTo 1L).map(today::minusDays)

    @Test fun historicalWitnessSurvivesLongGapAndIsIndependentOfInputOrder() {
        val old = dates.map { it.minusYears(1) }
        val data = input(old.map { meal(it) } + meal(today.minusDays(1), 1000.0))
        val a = preview(data); val b = preview(data.copy(meals = data.meals.reversed()))
        assertEquals(a, b)
        assertEquals(old, a.badge(AchievementCode.COMPLETE_STREAK).witness)
        assertEquals(old, a.badge(AchievementCode.IN_GOAL_STREAK).witness)
    }
    @Test fun todayCanReachTenProvisionallyButCannotSupplyClosedWitness() {
        val run = (9L downTo 0L).map(today::minusDays)
        val data = input(run.map { meal(it) })
        val badge = preview(data).badge(AchievementCode.COMPLETE_STREAK)
        assertEquals(10, badge.progress); assertEquals(9, badge.closedProgress)
        assertTrue(badge.preliminary); assertFalse(badge.satisfied)
        assertEquals(run, preview(data, today.plusDays(1).atStartOfDay().toInstant(ZoneOffset.UTC)).badge(AchievementCode.COMPLETE_STREAK).witness)
    }
    @Test fun missingDateOrWithdrawnDeclarationBreaksStreakAndRevokesWitness() {
        val full = input(dates.map { meal(it) })
        assertTrue(preview(full).badge(AchievementCode.COMPLETE_STREAK).satisfied)
        val omitted = dates[4]
        val missing = preview(full.copy(meals = full.meals.filterNot { it.date == omitted }))
        val withdrawn = preview(full.copy(declarations = full.declarations - omitted))
        assertEquals(5, missing.badge(AchievementCode.COMPLETE_STREAK).progress)
        assertFalse(missing.badge(AchievementCode.COMPLETE_STREAK).satisfied)
        assertEquals(missing.badges, withdrawn.badges)
    }
    @Test fun missingMacrosKeepKnownEnergyButMissingEnergyRemovesCompleteness() {
        val full = input(dates.map { meal(it) })
        assertTrue(preview(full).badge(AchievementCode.COMPLETE_STREAK).satisfied)
        val unknown = Nutrients.fromExact(ExactTotals(FieldAggregate(BigDecimal.ZERO, 1, 0),
            FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1)))
        val corrected = full.copy(meals = full.meals + AchievementMeal(dates[4], "UTC", false,
            listOf(AchievementPortion(unknown, BigDecimal("100")))))
        assertFalse(preview(corrected).badge(AchievementCode.COMPLETE_STREAK).satisfied)
        assertFalse(preview(corrected).badge(AchievementCode.IN_GOAL_STREAK).satisfied)
    }
    @Test fun historicalGoalChangesInclusiveBandAndSameDayCorrectionAreApplied() {
        val meals = dates.mapIndexed { index, date -> meal(date, if (index < 5) 1800.0 else 3300.0) }
        val goals = listOf(AnalyticsGoal(dates[0], BigDecimal("2000")), AnalyticsGoal(dates[5], BigDecimal("3000"), 2, "new"),
            AnalyticsGoal(dates[5], BigDecimal("4000"), 1, "old"), AnalyticsGoal(today, BigDecimal("9000")))
        val full = input(meals, goals.reversed())
        assertEquals(dates, preview(full).badge(AchievementCode.IN_GOAL_STREAK).witness)
        val outside = full.copy(meals = meals.dropLast(1) + meal(dates.last(), 3300.00001))
        assertFalse(preview(outside).badge(AchievementCode.IN_GOAL_STREAK).satisfied)
        assertTrue(preview(outside).badge(AchievementCode.COMPLETE_STREAK).satisfied)
    }
    @Test fun absentGoalDoesNotPreventCompleteBadgeAndExtraConsumptionDoesNotImproveInGoal() {
        val noGoal = preview(input(dates.map { meal(it) }, emptyList()))
        assertTrue(noGoal.badge(AchievementCode.COMPLETE_STREAK).satisfied)
        assertEquals(0, noGoal.badge(AchievementCode.IN_GOAL_STREAK).progress)
        val surplus = preview(input(dates.map { meal(it, 4001.0) }))
        assertEquals(noGoal.badges, surplus.badges)
    }
    @Test fun multipleMealsAndMeasurementsInOneDayDoNotCreateDistinctDays() {
        val data = input(List(10) { meal(today.minusDays(1), 200.0, 1, true) }, weights = List(4) { AchievementWeight(today.minusDays(1), "UTC") })
        val badges = preview(data)
        assertEquals(1, badges.badge(AchievementCode.COMPLETE_STREAK).progress)
        assertEquals(1, badges.badge(AchievementCode.WEIGHT_DAYS).progress)
        assertEquals(1, badges.badge(AchievementCode.RATION_DAYS).progress)
    }
    @Test fun fourWeightDatesFitInclusiveFourteenDaysAndFifteenthDayFallsOutside() {
        val days = listOf(today.minusDays(14), today.minusDays(12), today.minusDays(8), today.minusDays(1))
        val data = input(emptyList(), weights = days.map { AchievementWeight(it, "UTC") })
        assertEquals(days, preview(data).badge(AchievementCode.WEIGHT_DAYS).witness)
        val outside = preview(data.copy(weights = listOf(AchievementWeight(days.first().minusDays(1), "UTC")) + data.weights.drop(1)))
        assertEquals(3, outside.badge(AchievementCode.WEIGHT_DAYS).progress)
        assertFalse(outside.badge(AchievementCode.WEIGHT_DAYS).satisfied)
    }
    @Test fun independentSourceZonesMatureBeforeOrAfterDeviceDateAndInvalidZoneIsExcluded() {
        val at = Instant.parse("2026-10-12T10:30:00Z")
        val data = input(emptyList(), weights = listOf(AchievementWeight(today, "Pacific/Kiritimati"),
            AchievementWeight(today.minusDays(1), "Pacific/Honolulu"), AchievementWeight(today.minusDays(2), "invalid")))
        assertEquals(2, preview(data, at).badge(AchievementCode.WEIGHT_DAYS).progress)
        assertEquals(0, preview(data, Instant.parse("2026-10-12T09:59:59Z")).badge(AchievementCode.WEIGHT_DAYS).progress)
    }
    @Test fun weightClosureUsesCalendarMidnightAcrossDaylightSavingChange() {
        val date = LocalDate.of(2026, 10, 25)
        val data = input(emptyList(), weights = listOf(AchievementWeight(date, "Europe/Warsaw")))
        assertEquals(0, preview(data, Instant.parse("2026-10-25T22:59:59Z")).badge(AchievementCode.WEIGHT_DAYS).progress)
        assertEquals(1, preview(data, Instant.parse("2026-10-25T23:00:00Z")).badge(AchievementCode.WEIGHT_DAYS).progress)
    }
    @Test fun rationNeedsSavedPositivePositionAndPositiveAmountButNotKnownEnergy() {
        val days = dates.take(5)
        val valid = input(days.map { meal(it, 0.0, 1, true) })
        assertEquals(days, preview(valid).badge(AchievementCode.RATION_DAYS).witness)
        val legacy = preview(valid.copy(meals = valid.meals.map { it.copy(items = it.items.map { part -> part.copy(rationPosition = null) }) }))
        assertEquals(5, legacy.legacyRationMeals); assertEquals(0, legacy.badge(AchievementCode.RATION_DAYS).progress)
        assertEquals(0, preview(input(days.map { meal(it, position = 1, ration = false) })).badge(AchievementCode.RATION_DAYS).progress)
        assertEquals(0, preview(input(days.map { meal(it, position = 1, ration = true, amount = "0") })).badge(AchievementCode.RATION_DAYS).progress)
    }
    @Test fun futureAndUndeclaredDaysCannotCreatePreliminaryStreakAndEmptyHistoryHasFourZeroBadges() {
        val future = preview(input((0L..11L).map { meal(today.plusDays(it)) }))
        assertEquals(1, future.badge(AchievementCode.COMPLETE_STREAK).progress)
        val undeclared = preview(input(dates.map { meal(it) }, declared = emptySet()))
        assertTrue(undeclared.badges.all { it.progress == 0 && !it.satisfied })
        val empty = preview(input(emptyList()))
        assertEquals(4, empty.badges.size); assertTrue(empty.badges.all { it.progress == 0 && !it.satisfied })
    }
}
