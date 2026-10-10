package pl.roseru.kalorie

import android.view.inputmethod.InputMethodManager
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.semantics.SemanticsActions
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import pl.roseru.kalorie.data.DiaryRepository
import pl.roseru.kalorie.core.*
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
        // Exercise the accessible click action; IME/lazy-list movement can shift touch coordinates.
        compose.onNodeWithTag("confirm-weight").performScrollTo().assertIsDisplayed().assertIsEnabled()
            .performSemanticsAction(SemanticsActions.OnClick) { action -> assertTrue(action()) }
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

    @Test fun importedE2RationPreservesExactQuantityAcrossRecreationAndEdit() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val ration = runBlocking { app.database.dao().rations().first().single { it.ration.catalogJson != null } }
        val part = ration.components.minBy { it.position }
        val product = runBlocking { app.database.dao().product(part.productId)!! }
        val previousIds = runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first().map { it.meal.id }.toSet() }
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("open-rations").performClick()
        compose.onNodeWithTag("ration-${ration.ration.id}").performScrollTo().performClick()
        compose.onNodeWithTag("confirm-ration").assertIsNotEnabled()
        compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("ration-check-${part.id}"))
        compose.onNodeWithTag("ration-check-${part.id}").assertIsOff().performClick()
        compose.onNodeWithTag("ration-grams-${part.id}").performTextReplacement("12,123456789123")
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("ration-grams-${part.id}").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("ration-grams-${part.id}").assertTextContains("12,123456789123")
        compose.onNodeWithTag("confirm-ration").assertIsEnabled().performClick()
        compose.waitUntil(10_000) { runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first().any { it.meal.id !in previousIds } } }
        val meal = runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first().single { it.meal.id !in previousIds } }
        assertEquals(1, meal.items.size); assertEquals("12.123456789123", meal.items.single().amountText)
        compose.onNodeWithTag("diary-content").performScrollToNode(hasContentDescription("Popraw ${product.name}"))
        compose.onNodeWithContentDescription("Popraw ${product.name}").performClick()
        compose.onNodeWithTag("edit-amount").assertTextContains("12,123456789123").performTextReplacement("150")
        compose.onNodeWithText("131 kcal").assertIsDisplayed()
        compose.onNodeWithText("Zapisz").performClick()
        compose.waitUntil(10_000) { runBlocking { app.database.dao().meal(meal.meal.id, DiaryRepository.GUEST)!!.items.single().amountText == "150" } }
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        assertEquals("130.5", runBlocking { app.database.dao().meal(meal.meal.id, DiaryRepository.GUEST)!!.items.single().consumed().asExact().energy.canonical })
    }
}
