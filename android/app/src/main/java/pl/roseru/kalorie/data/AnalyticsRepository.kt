package pl.roseru.kalorie.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.*
import pl.roseru.kalorie.core.*
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate

class AnalyticsRepository(private val dao: CalorieDao, private val clock: LocalDayClock = LocalDayClock()) {
    fun observe(owner: String, window: AnalyticsWindow): Flow<AnalyticsResult> {
        val inputs = combine(
            dao.mealsBetween(owner, window.start.toString(), window.end.toString()),
            dao.goalsThrough(owner, window.end.toString()),
            dao.daysBetween(owner, window.start.toString(), window.end.toString()),
            dao.weightsBetween(owner, window.start.toString(), window.end.toString())
        ) { meals, goals, days, weights ->
            AnalyticsInput(
                meals.map { AnalyticsMeal(LocalDate.parse(it.meal.localDate), it.items.map(MealItemEntity::consumed)) },
                goals.map { AnalyticsGoal(LocalDate.parse(it.validFrom), BigDecimal.valueOf(it.kcal), it.localSequence, it.id) },
                days.filter { it.declaredComplete }.map { LocalDate.parse(it.localDate) }.toSet(),
                weights.map { AnalyticsWeight(it.id, LocalDate.parse(it.localDate), Instant.parse(it.occurredAt), BigDecimal.valueOf(it.kg)) }
            )
        }
        return combine(inputs, clock.dates()) { input, today -> Analytics.build(window, input, today) }
            .flowOn(Dispatchers.Default)
    }
}
