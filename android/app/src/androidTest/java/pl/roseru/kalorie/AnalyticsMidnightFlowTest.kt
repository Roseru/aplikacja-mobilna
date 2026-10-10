package pl.roseru.kalorie

import androidx.activity.compose.setContent
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.room.Room
import kotlinx.coroutines.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.ui.*
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.concurrent.atomic.AtomicReference

class AnalyticsMidnightFlowTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()
    @Test fun preliminaryUiClosesAfterMidnightWithoutNewMeal() {
        val date = LocalDate.now().minusDays(2)
        val zone = ZoneId.of("Europe/Warsaw")
        val now = AtomicReference(date.atTime(23, 59, 59).atZone(zone).toInstant())
        val clock = LocalDayClock({ now.get() }, { zone }, { withContext(Dispatchers.Default) { delay(250) } })
        val db = Room.inMemoryDatabaseBuilder(compose.activity, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val repo = DiaryRepository(db, compose.activity)
        lateinit var model: DiaryViewModel
        var created = false
        try {
            runBlocking {
                repo.initialize(); repo.add("basic-banana", 100.0, MealType.LUNCH, date, "midnight-ui")
                repo.setDayComplete(date, true)
            }
            compose.runOnUiThread {
                model = DiaryViewModel(repo, Preferences(compose.activity), SavedStateHandle(mapOf(
                    "analytics-end" to date.toString(), "analytics-follows-today" to false)), clock)
                created = true
                compose.activity.setContent { CalorieTheme(false) { AnalyticsScreen(model) {} } }
            }
            compose.waitUntil(15_000) { compose.onAllNodesWithTag("average-kcal").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithTag("complete-days").assertTextContains("0 / 7", substring = true)
            compose.onNodeWithTag("average-kcal").assertTextContains("Brak kompletnych dni", substring = true)
            compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("history-$date"))
            compose.onNodeWithTag("history-$date").assertTextContains("Wynik wstępny", substring = true)
            now.set(date.plusDays(1).atStartOfDay(zone).toInstant())
            compose.waitUntil(10_000) { compose.onAllNodes(hasText("Wynik wstępny")).fetchSemanticsNodes().isEmpty() }
            compose.onNodeWithTag("history-$date").assertTextContains("Kompletny", substring = true)
            compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("complete-days"))
            compose.waitUntil(10_000) { compose.onAllNodes(hasTestTag("complete-days") and hasText("1 / 7", substring = true)).fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithTag("average-kcal").assertTextContains("89 kcal", substring = true)
        } finally {
            compose.runOnUiThread { compose.activity.setContent {}; if (created) model.viewModelScope.cancel() }
            compose.waitForIdle(); db.close()
        }
    }
}
