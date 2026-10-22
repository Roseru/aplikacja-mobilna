package pl.roseru.kalorie.data

import androidx.room.withTransaction
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.*
import pl.roseru.kalorie.core.*
import java.math.BigDecimal
import java.time.LocalDate

sealed interface AchievementState {
    data object Loading : AchievementState
    data class Ready(val preview: AchievementPreview) : AchievementState
    data object Unavailable : AchievementState
}

class AchievementRepository(private val db: CalorieDatabase, private val clock: LocalDayClock = LocalDayClock()) {
    fun observe(owner: String): Flow<AchievementState> = combine(
        db.invalidationTracker.createFlow("meals", "meal_items", "goals", "diary_days", "weights", "server_diary_records"), clock.instants()
    ) { _, now ->
        // One transaction avoids mixing declarations, goals and meals from different revisions.
        val input = db.withTransaction {
            val dao = db.dao()
            AchievementInput(
                dao.achievementMeals(owner).map { row -> AchievementMeal(LocalDate.parse(row.meal.localDate), row.meal.zoneId,
                    row.meal.rationId != null, row.items.map { item ->
                        AchievementPortion(item.consumed(), BigDecimal(item.amountText), item.rationComponentPosition)
                    }) },
                dao.achievementGoals(owner).map { AnalyticsGoal(LocalDate.parse(it.validFrom), BigDecimal.valueOf(it.kcal), it.localSequence, it.id) },
                dao.achievementDeclarations(owner).map { LocalDate.parse(it.localDate) }.toSet(),
                dao.achievementWeights(owner).map { AchievementWeight(LocalDate.parse(it.localDate), it.zoneId) }
            )
        }
        AchievementState.Ready(Achievements.build(input, now, clock.currentZone())) as AchievementState
    }.onStart { emit(AchievementState.Loading) }.catch { error ->
        if (error is CancellationException) throw error
        emit(AchievementState.Unavailable)
    }.flowOn(Dispatchers.Default)
}
