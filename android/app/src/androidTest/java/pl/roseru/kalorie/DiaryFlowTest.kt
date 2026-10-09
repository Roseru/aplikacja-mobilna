package pl.roseru.kalorie

import android.view.inputmethod.InputMethodManager
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
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

    @Test fun createPrivateProductAndDeclareDayComplete() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val baseline = runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first()
            .flatMap { it.items }.sumOf { it.consumed().kcal } }
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("open-custom-food").performClick()
        compose.onNodeWithTag("confirm-custom-food").assertIsNotEnabled()
        compose.onNodeWithTag("custom-name").performScrollTo().performTextInput("Kasza własna")
        compose.onNodeWithTag("custom-source").performScrollTo().performTextInput("Etykieta opakowania")
        compose.onNodeWithTag("custom-kcal").performScrollTo().performTextInput("100")
        compose.onNodeWithTag("custom-grams").performScrollTo().performTextReplacement("150,5")
        compose.onNodeWithTag("confirm-custom-food").assertIsEnabled().performClick()
        val expected = (baseline + 150.5).roundToInt().toString()
        compose.waitUntil(10_000) { compose.onAllNodes(hasTestTag("daily-kcal") and hasText(expected)).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("day-complete").performScrollTo()
        compose.onNodeWithTag("day-complete").performClick()
        compose.waitUntil(10_000) { compose.onAllNodesWithText("Dzień kompletny").fetchSemanticsNodes().isNotEmpty() }
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        runBlocking {
            val privateProduct = app.database.dao().products().first().single { it.name == "Kasza własna" }
            assertEquals(DiaryRepository.GUEST, privateProduct.ownerScope)
            assertNull(privateProduct.protein)
            assertTrue(app.database.dao().diaryDay(DiaryRepository.GUEST, LocalDate.now().toString()).first()!!.declaredComplete)
        }
    }

    @Test fun saveLocalProfileAndWeightWithoutResettingCalorieGoal() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val goal = runBlocking { app.database.dao().goal(DiaryRepository.GUEST, LocalDate.now().toString()).first()!!.kcal }
        val previousWeightIds = runBlocking { app.database.dao().weights(DiaryRepository.GUEST).first().map { it.id }.toSet() }
        compose.onNodeWithTag("open-profile").performClick()
        compose.onNodeWithTag("profile-nickname").performTextReplacement("Poligon test")
        compose.onNodeWithTag("profile-height").performScrollTo().performTextReplacement("182,5")
        compose.onNodeWithTag("confirm-profile").performScrollTo().performClick()
        compose.waitUntil(10_000) { runBlocking { app.database.dao().profile(DiaryRepository.GUEST).first()?.nickname == "Poligon test" } }
        compose.onNodeWithTag("profile-content").performScrollToNode(hasTestTag("weight-kg"))
        compose.onNodeWithTag("weight-kg").performScrollTo().performTextReplacement("82,4")
        compose.onNodeWithTag("weight-kg").assertTextContains("82,4")
        // Dismiss the IME before scrolling; its inset animation is outside Compose idling.
        compose.activityRule.scenario.onActivity { activity ->
            activity.getSystemService(InputMethodManager::class.java)
                .hideSoftInputFromWindow(activity.window.decorView.windowToken, 0)
        }
        compose.waitUntil(5_000) {
            ViewCompat.getRootWindowInsets(compose.activity.window.decorView)?.isVisible(WindowInsetsCompat.Type.ime()) != true
        }
        compose.onNodeWithTag("confirm-weight").performScrollTo().assertIsDisplayed().assertIsEnabled().performClick()
        compose.waitUntil(10_000) { runBlocking { app.database.dao().weights(DiaryRepository.GUEST).first().any { it.id !in previousWeightIds && it.kg == 82.4 } } }
        compose.onNodeWithTag("confirm-weight").assertIsNotEnabled()
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("profile-content").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("profile-content").performScrollToNode(hasTestTag("profile-height"))
        compose.onNodeWithTag("profile-height").assertTextContains("182,5")
        runBlocking {
            assertEquals(goal, app.database.dao().goal(DiaryRepository.GUEST, LocalDate.now().toString()).first()!!.kcal, .0)
            assertTrue(app.database.dao().weights(DiaryRepository.GUEST).first().any { it.id !in previousWeightIds && it.kg == 82.4 })
        }
    }
}
