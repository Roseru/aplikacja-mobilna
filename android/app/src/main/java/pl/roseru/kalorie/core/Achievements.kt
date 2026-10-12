package pl.roseru.kalorie.core

import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

enum class AchievementCode(val wire: String, val required: Int) {
    COMPLETE_STREAK("complete_streak_10", 10), IN_GOAL_STREAK("in_goal_streak_10", 10),
    WEIGHT_DAYS("weight_days_4_14", 4), RATION_DAYS("ration_days_5", 5)
}

data class AchievementPortion(val nutrients: Nutrients, val amount: BigDecimal, val rationPosition: Int? = null)
data class AchievementMeal(val date: LocalDate, val zoneId: String, val ration: Boolean, val items: List<AchievementPortion>)
data class AchievementWeight(val date: LocalDate, val zoneId: String)
data class AchievementInput(val meals: List<AchievementMeal>, val goals: List<AnalyticsGoal>,
    val declarations: Set<LocalDate>, val weights: List<AchievementWeight>)
data class LocalAchievement(val code: AchievementCode, val progress: Int, val closedProgress: Int,
    val witness: List<LocalDate>) {
    val satisfied get() = witness.isNotEmpty()
    val preliminary get() = progress > closedProgress
}
data class AchievementPreview(val badges: List<LocalAchievement>, val asOf: Instant, val zoneId: String,
    val legacyRationMeals: Int)

/** A recalculated local preview, never an authoritative award, rank or public score. */
object Achievements {
    const val RULE = "regularity_v1"

    fun build(input: AchievementInput, now: Instant, zone: ZoneId): AchievementPreview {
        val today = now.atZone(zone).toLocalDate()
        fun mature(date: LocalDate, sourceZone: String) = runCatching {
            now >= date.plusDays(1).atStartOfDay(ZoneId.of(sourceZone)).toInstant()
        }.getOrDefault(false)
        val meals = input.meals.groupBy { it.date }
        val weightDays = input.weights.filter { mature(it.date, it.zoneId) }.map { it.date }.toSet()
        val rationDays = input.meals.filter { meal -> meal.ration && mature(meal.date, meal.zoneId) &&
            meal.items.any { (it.rationPosition ?: 0) > 0 && it.amount > BigDecimal.ZERO }
        }.map { it.date }.toSet()
        // Sparse chronological dates preserve real gaps without a 7/30/90-day history cutoff.
        val dates = (meals.keys + input.declarations + weightDays + rationDays).sorted()
        val goals = input.goals.sortedWith(compareBy<AnalyticsGoal> { it.from }.thenBy { it.localSequence }.thenBy { it.id })
        var goalIndex = 0
        var goal: BigDecimal? = null
        val complete = Streak(10)
        val inGoal = Streak(10)
        val weights = ArrayDeque<LocalDate>()
        var weightProgress = 0
        var weightWitness = emptyList<LocalDate>()
        val rations = mutableListOf<LocalDate>()
        for (date in dates) {
            while (goalIndex < goals.size && goals[goalIndex].from <= date) {
                goal = goals[goalIndex++].kcal.takeIf { it > BigDecimal.ZERO }
            }
            val items = meals[date].orEmpty().flatMap { it.items }.map { it.nutrients }
            val total = items.total()
            val qualifies = date <= today && completeDiary(date in input.declarations, items.size, total)
            val target = goal
            val energy = total.asExact().energy.knownSum
            val matches = qualifies && target != null && energy >= target * (BigDecimal.ONE - Analytics.TOLERANCE) &&
                energy <= target * (BigDecimal.ONE + Analytics.TOLERANCE)
            complete.add(date, qualifies, date < today)
            inGoal.add(date, matches, date < today)
            if (date in weightDays) {
                while (weights.isNotEmpty() && weights.first() < date.minusDays(13)) weights.removeFirst()
                weights.addLast(date)
                while (weights.size > 4) weights.removeFirst()
                weightProgress = maxOf(weightProgress, weights.size)
                if (weights.size == 4 && weightWitness.isEmpty()) weightWitness = weights.toList()
            }
            if (date in rationDays && rations.size < 5) rations += date
        }
        return AchievementPreview(listOf(
            complete.result(AchievementCode.COMPLETE_STREAK), inGoal.result(AchievementCode.IN_GOAL_STREAK),
            LocalAchievement(AchievementCode.WEIGHT_DAYS, weightProgress, weightProgress, weightWitness),
            LocalAchievement(AchievementCode.RATION_DAYS, rations.size, rations.size, rations.toList().takeIf { it.size == 5 }.orEmpty())
        ), now, zone.id, input.meals.count { meal -> meal.ration && meal.items.any { it.amount > BigDecimal.ZERO } &&
            meal.items.none { (it.rationPosition ?: 0) > 0 && it.amount > BigDecimal.ZERO } })
    }

    private class Streak(private val required: Int) {
        private var previous: LocalDate? = null
        private var run = 0
        private var progress = 0
        private var closedProgress = 0
        private val closedDates = ArrayDeque<LocalDate>()
        private var witness = emptyList<LocalDate>()
        fun add(date: LocalDate, qualifies: Boolean, closed: Boolean) {
            val adjacent = previous?.plusDays(1) == date
            run = if (qualifies) (if (adjacent) run + 1 else 1).coerceAtMost(required) else 0
            progress = maxOf(progress, run)
            if (!qualifies || !closed || !adjacent) closedDates.clear()
            if (qualifies && closed) {
                closedDates.addLast(date)
                if (closedDates.size > required) closedDates.removeFirst()
                closedProgress = maxOf(closedProgress, closedDates.size)
                if (closedDates.size == required && witness.isEmpty()) witness = closedDates.toList()
            }
            previous = date
        }
        fun result(code: AchievementCode) = LocalAchievement(code, progress, closedProgress, witness)
    }
}
