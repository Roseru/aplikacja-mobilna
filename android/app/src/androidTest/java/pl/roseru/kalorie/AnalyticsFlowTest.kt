package pl.roseru.kalorie

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.*
import java.time.LocalDate

@RunWith(AndroidJUnit4::class)
class AnalyticsFlowTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()
    private fun open() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("open-analytics").performClick()
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("average-kcal").fetchSemanticsNodes().isNotEmpty() }
    }
    @Test fun periodMetricAndOlderWindowSurviveRecreationThenOpenDailyHistory() {
        open()
        compose.onNodeWithTag("period-30").performClick()
        compose.onNodeWithTag("period-30").assertIsSelected()
        compose.onNodeWithTag("period-90").performClick()
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("analytics-loaded-${LocalDate.now()}-90").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("metric-1"))
        compose.onNodeWithTag("metric-1").performClick()
        compose.activityRule.scenario.recreate()
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("analytics-content").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("period-90"))
        compose.onNodeWithTag("period-90").assertIsSelected()
        compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("metric-1"))
        compose.onNodeWithTag("metric-1").assertIsSelected()
        compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("analytics-previous"))
        compose.onNodeWithTag("analytics-previous").performClick()
        val end = LocalDate.now().minusDays(90)
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("analytics-loaded-$end-90").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("history-$end"))
        compose.onNodeWithTag("history-$end").assertTextContains("Brak danych o spożyciu", substring = true)
        compose.onNodeWithTag("history-$end").performClick()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        assertNotNull(app.database)
        // A history day opens the real diary, where the date stays after activity recreation.
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("daily-kcal").assertTextEquals("0")
    }
    @Test fun actualHistoricalEntriesAndWeightsAppearOfflineInOlderPeriod() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val date = LocalDate.now().minusDays(100)
        runBlocking {
            app.repository.add("basic-banana", 100.0, MealType.LUNCH, date, "analytics-ui-historical")
            app.repository.setDayComplete(date, true)
            app.repository.addWeight(82.4, date, "analytics-ui-weight")
        }
        compose.onNodeWithTag("open-analytics").performClick()
        compose.onNodeWithTag("period-90").performClick()
        compose.onNodeWithTag("analytics-previous").performClick()
        val end = LocalDate.now().minusDays(90)
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("analytics-loaded-$end-90").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("history-$date"))
        compose.onNodeWithTag("history-$date").assertTextContains("89 kcal", substring = true)
        compose.onNodeWithTag("history-$date").assertTextContains("Kompletny", substring = true)
        compose.onNodeWithTag("history-$date").assertTextContains("Waga: 82,4 kg", substring = true)
        compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("weight-chart"))
        compose.onNodeWithTag("weight-chart").assertExists()
    }
}
