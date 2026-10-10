package pl.roseru.kalorie.core

import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Instant
import java.time.LocalDate

enum class AnalyticsPeriod(val days: Int) { WEEK(7), MONTH(30), QUARTER(90) }
data class AnalyticsWindow(val end: LocalDate, val period: AnalyticsPeriod) {
    val start: LocalDate get() = end.minusDays(period.days.toLong() - 1)
    fun contains(date: LocalDate) = date >= start && date <= end
}
data class AnalyticsMeal(val date: LocalDate, val items: List<Nutrients>)
data class AnalyticsGoal(val from: LocalDate, val kcal: BigDecimal, val localSequence: Int = 0, val id: String = "")
data class AnalyticsWeight(val id: String, val date: LocalDate, val at: Instant, val kg: BigDecimal)
data class AnalyticsInput(val meals: List<AnalyticsMeal>, val goals: List<AnalyticsGoal>,
    val declarations: Set<LocalDate>, val weights: List<AnalyticsWeight>)

enum class AnalyticsDayStatus(val label: String) { NO_DATA("Brak wpisów"), INCOMPLETE("Niekompletny"), COMPLETE("Kompletny") }
data class AnalyticsDay(val date: LocalDate, val total: Nutrients?, val goal: BigDecimal?, val status: AnalyticsDayStatus,
    val inGoal: Boolean?, val weight: AnalyticsWeight?, val weightCount: Int,
    val closed: Boolean, val preliminaryInGoal: Boolean?)
data class AnalyticsAverage(val value: BigDecimal?, val dayCount: Int)
data class AnalyticsResult(val window: AnalyticsWindow, val days: List<AnalyticsDay>, val averages: List<AnalyticsAverage>,
    val weightCount: Int, val weightChange: BigDecimal?) {
    val completeDays get() = days.count { it.closed && it.status == AnalyticsDayStatus.COMPLETE }
    val daysWithEntries get() = days.count { it.total != null }
    val daysInGoal get() = days.count { it.inGoal == true }
    val daysWithGoal get() = days.count { it.inGoal != null }
}

object Analytics {
    const val GOAL_RULE = "goal_band_v1"
    val TOLERANCE = BigDecimal("0.10")
    fun build(window: AnalyticsWindow, input: AnalyticsInput, today: LocalDate = LocalDate.now()): AnalyticsResult {
        val meals = input.meals.filter { window.contains(it.date) }.groupBy { it.date }
        val weights = input.weights.filter { window.contains(it.date) }.groupBy { it.date }
        val days = (0 until window.period.days).map { offset ->
            val date = window.start.plusDays(offset.toLong())
            val items = meals[date].orEmpty().flatMap { it.items }
            val total = items.takeIf { it.isNotEmpty() }?.total()
            val complete = total != null && completeDiary(date in input.declarations, items.size, total)
            val goal = input.goals.filter { it.from <= date }.maxWithOrNull(
                compareBy<AnalyticsGoal> { it.from }.thenBy { it.localSequence }.thenBy { it.id })?.kcal?.takeIf { it > BigDecimal.ZERO }
            val closed = date < today
            val targetMatch = if (complete && goal != null) {
                val energy = total!!.asExact().energy.knownSum
                energy >= goal.multiply(BigDecimal.ONE - TOLERANCE) && energy <= goal.multiply(BigDecimal.ONE + TOLERANCE)
            } else null
            val points = weights[date].orEmpty()
            val latest = points.maxWithOrNull(compareBy<AnalyticsWeight> { it.at }.thenBy { it.id })
            AnalyticsDay(date, total, goal, if (total == null) AnalyticsDayStatus.NO_DATA
                else if (complete) AnalyticsDayStatus.COMPLETE else AnalyticsDayStatus.INCOMPLETE,
                targetMatch.takeIf { closed }, latest, points.size, closed, targetMatch.takeIf { date == today })
        }
        val averages = (0..3).map { index ->
            val values = days.filter { it.closed && it.status == AnalyticsDayStatus.COMPLETE }
                .mapNotNull { it.total?.asExact()?.fields()?.get(index)?.takeIf { field -> field.complete }?.knownSum }
            AnalyticsAverage(if (values.isEmpty()) null else values.fold(BigDecimal.ZERO, BigDecimal::add)
                .divide(BigDecimal(values.size), 12, RoundingMode.HALF_UP), values.size)
        }
        // One actual, latest measurement per date. Never fill days without a measurement.
        val dailyWeights = days.mapNotNull { it.weight }
        val change = if (dailyWeights.size < 2) null else dailyWeights.last().kg - dailyWeights.first().kg
        return AnalyticsResult(window, days, averages, weights.values.sumOf { it.size }, change)
    }
}
