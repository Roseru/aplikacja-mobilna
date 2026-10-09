package pl.roseru.kalorie

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import pl.roseru.kalorie.data.DiaryRepository
import java.time.LocalDate
import kotlin.math.roundToInt

@RunWith(AndroidJUnit4::class)
class DiaryFlowTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    @Test fun addFoodThroughUiAndRecreateActivity() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val baseline = runBlocking {
            app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first()
                .flatMap { it.items }.sumOf { it.consumed().kcal }
        }
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("product-search").performTextInput("banan")
        compose.onNodeWithTag("product-basic-banana").performClick()
        compose.onNodeWithTag("portion-grams").performTextReplacement("120,5")
        compose.onNodeWithTag("confirm-food").performClick()
        val expected = (baseline + 89 * 1.205).roundToInt().toString()
        compose.waitUntil(10_000) { compose.onAllNodes(hasTestTag("daily-kcal") and hasText(expected)).fetchSemanticsNodes().isNotEmpty() }
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodes(hasTestTag("daily-kcal") and hasText(expected)).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("daily-kcal").assertTextEquals(expected)
    }

    @Test fun choosePartialRationAndRestoreSelectionBeforeSaving() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val baseline = runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first()
            .flatMap { it.items }.sumOf { it.consumed().kcal } }
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("open-rations").performClick()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("ration-demo-ration-a").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("ration-demo-ration-a").performClick()
        compose.onNodeWithTag("confirm-ration").assertIsNotEnabled()
        compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("ration-check-demo-a-meat"))
        compose.onNodeWithTag("ration-check-demo-a-meat").performClick()
        compose.onNodeWithTag("ration-grams-demo-a-meat").performTextReplacement("101")
        compose.onNodeWithTag("confirm-ration").assertIsNotEnabled()
        compose.onNodeWithTag("ration-grams-demo-a-meat").performTextReplacement("50")
        compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("ration-check-demo-a-crackers"))
        compose.onNodeWithTag("ration-check-demo-a-crackers").performClick()
        compose.onNodeWithTag("ration-grams-demo-a-crackers").performTextReplacement("22,5")
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("ration-grams-demo-a-crackers").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("ration-grams-demo-a-crackers").assertTextContains("22,5")
        compose.onNodeWithTag("confirm-ration").assertIsEnabled().performClick()
        val expected = (baseline + 222.0).roundToInt().toString()
        compose.waitUntil(10_000) { compose.onAllNodes(hasTestTag("daily-kcal") and hasText(expected)).fetchSemanticsNodes().isNotEmpty() }
        runBlocking {
            val meal = app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first().last { it.meal.rationId == "demo-ration-a" }
            assertEquals(2, meal.items.size)
            assertEquals(setOf("demo-a-meat", "demo-a-crackers"), meal.items.map { it.rationComponentId }.toSet())
        }
    }
}
