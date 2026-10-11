package pl.roseru.kalorie

import android.view.inputmethod.InputMethodManager
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.text.AnnotatedString
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

    @Test fun accountScreenKeepsGuestOfflineAndRestoresNavigation() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("open-profile").performClick()
        compose.onNodeWithTag("open-account").performClick()
        compose.onNodeWithTag("session-owner").assertTextEquals("Gość poligonowy")
        compose.onNodeWithTag("session-login").assertIsNotEnabled()
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("session-owner").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("session-owner").assertTextEquals("Gość poligonowy")
        compose.onNodeWithText("Wróć do profilu").performClick()
        compose.onNodeWithTag("profile-content").assertIsDisplayed()
    }

    @Test fun changingLeaseDiscardsPrivateEditorAndPreservesDiary() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val before = runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first() }
        val oldLease = app.sessions.view.value.binding!!.lease
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("open-custom-food").performClick()
        compose.onNodeWithTag("custom-name").performScrollTo().performTextInput("Niezapisany prywatny formularz")
        runBlocking { app.sessions.logout() }
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        assertNotEquals(oldLease, app.sessions.view.value.binding!!.lease)
        compose.onAllNodesWithText("Niezapisany prywatny formularz").assertCountEquals(0)
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("open-custom-food").performClick()
        compose.onNodeWithTag("custom-name").performScrollTo().assert(SemanticsMatcher.expectValue(SemanticsProperties.EditableText, AnnotatedString("")))
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("custom-name").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("custom-name").performScrollTo().assert(SemanticsMatcher.expectValue(SemanticsProperties.EditableText, AnnotatedString("")))
        assertEquals(before, runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first() })
    }

    @Test fun addFoodThroughUiAndRecreateActivity() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val baseline = runBlocking {
            app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first()
                .flatMap { it.items }.sumOf { it.consumed().kcal }
        }
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("product-search").performTextInput("banan")
        compose.onNodeWithTag("food-content").performScrollToNode(hasTestTag("product-basic-banana"))
        compose.onNodeWithTag("product-basic-banana").performClick()
        compose.onNodeWithTag("portion-grams").performTextReplacement("120,5")
        finishQuantityInput("portion-grams", "confirm-food")
        compose.onNodeWithTag("confirm-food").assertIsDisplayed()
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
        compose.onNodeWithTag("ration-grams-demo-a-crackers").assertTextContains("22,5")
        compose.waitForIdle()
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("ration-grams-demo-a-crackers").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("ration-grams-demo-a-crackers").assertTextContains("22,5")
        finishQuantityInput("ration-grams-demo-a-crackers", "confirm-ration")
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
        finishQuantityInput("custom-grams", "confirm-custom-food")
        compose.onNodeWithTag("confirm-custom-food").assertIsEnabled().performClick()
        val expected = (baseline + 150.5).roundToInt().toString()
        compose.waitUntil(10_000) { compose.onAllNodes(hasTestTag("daily-kcal") and hasText(expected)).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("diary-content").performScrollToNode(hasTestTag("day-complete"))
        compose.onNodeWithTag("day-complete").assertIsDisplayed().assertIsEnabled()
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

    @Test fun selectActivityPreviewAndSaveDailyCalorieGoal() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        runBlocking {
            app.repository.setProfile("Tryby test", 180.0, ActivityClass.GARRISON, DietAim.MAINTAIN)
            app.repository.setGoal(2800.0, 160.0, 90.0, 330.0)
        }
        compose.onNodeWithTag("open-profile").performClick()
        val modes = listOf(ActivityClass.LINE to 3500.0, ActivityClass.COMMANDO to 4200.0, ActivityClass.GARRISON to 2800.0)
        var savedGoal = 2800.0
        for ((mode, kcal) in modes) {
            compose.onNodeWithTag("profile-content").performScrollToNode(hasTestTag("activity-${mode.name}"))
            compose.onNodeWithTag("activity-${mode.name}").assertIsDisplayed().performClick()
            compose.onNodeWithTag("profile-content").performScrollToNode(hasTestTag("activity-goal-preview"))
            compose.onNodeWithTag("activity-goal-preview").assertTextEquals("Cel po zapisaniu: ${kcal.roundToInt()} kcal")
            runBlocking { assertEquals(savedGoal, app.database.dao().goal("guest", LocalDate.now().toString()).first()!!.kcal, 0.0) }
            compose.onNodeWithTag("profile-content").performScrollToNode(hasTestTag("confirm-profile"))
            compose.onNodeWithTag("confirm-profile").assertIsEnabled().performClick()
            compose.waitUntil(10_000) { runBlocking {
                app.database.dao().currentProfile("guest")?.activityClass == mode.name &&
                    app.database.dao().goal("guest", LocalDate.now().toString()).first()?.kcal == kcal
            } }
            // The save feedback overlays the bottom of the list. Finish that interaction before the next tap.
            compose.waitUntil(5_000) { compose.onAllNodesWithText("Profil i cel zapisane na urządzeniu.").fetchSemanticsNodes().isNotEmpty() }
            compose.waitUntil(10_000) { compose.onAllNodesWithText("Profil i cel zapisane na urządzeniu.").fetchSemanticsNodes().isEmpty() }
            compose.waitForIdle()
            savedGoal = kcal
        }
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("profile-content").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("profile-content").performScrollToNode(hasTestTag("activity-GARRISON"))
        compose.onNodeWithTag("activity-GARRISON").assertIsSelected().assertTextContains(ActivityClass.GARRISON.label)
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
        compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("ration-${ration.ration.id}"))
        compose.onNodeWithTag("ration-${ration.ration.id}").assertIsDisplayed().performClick()
        compose.onNodeWithTag("confirm-ration").assertIsNotEnabled()
        compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("ration-check-${part.id}"))
        compose.onNodeWithTag("ration-check-${part.id}").assertIsOff().performClick()
        compose.onNodeWithTag("ration-grams-${part.id}").performTextReplacement("12,123456789123")
        compose.onNodeWithTag("ration-grams-${part.id}").assertTextContains("12,123456789123")
        compose.waitForIdle()
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("ration-grams-${part.id}").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("ration-grams-${part.id}").assertTextContains("12,123456789123")
        finishQuantityInput("ration-grams-${part.id}", "confirm-ration")
        compose.onNodeWithTag("confirm-ration").assertIsEnabled().performClick()
        compose.waitUntil(10_000) { runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first().any { it.meal.id !in previousIds } } }
        val meal = runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first().single { it.meal.id !in previousIds } }
        assertEquals(1, meal.items.size); assertEquals("12.123456789123", meal.items.single().amountText)
        compose.onNodeWithTag("diary-content").performScrollToNode(hasContentDescription("Popraw ${product.name}"))
        compose.onNodeWithContentDescription("Popraw ${product.name}").performClick()
        compose.onNodeWithTag("edit-amount").assertTextContains("12,123456789123").performTextReplacement("150")
        finishQuantityInput("edit-amount", "confirm-edit-item")
        compose.onNodeWithText("131 kcal").assertIsDisplayed()
        compose.onNodeWithTag("confirm-edit-item").performClick()
        compose.onNodeWithTag("edit-amount").assertDoesNotExist()
        compose.waitUntil(10_000) { runBlocking { app.database.dao().meal(meal.meal.id, DiaryRepository.GUEST)!!.items.single().amountText == "150" } }
        compose.activityRule.scenario.recreate()
        compose.waitUntil(10_000) { compose.onAllNodesWithTag("diary-content").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("diary-content").performScrollToNode(hasTestTag("daily-kcal"))
        compose.onNodeWithTag("daily-kcal").assertIsDisplayed()
        assertEquals("130.5", runBlocking { app.database.dao().meal(meal.meal.id, DiaryRepository.GUEST)!!.items.single().consumed().asExact().energy.canonical })
    }

    @Test fun switchProductWhileEditingPortionWithoutSaving() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val previousIds = runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first().map { it.meal.id }.toSet() }
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("food-content").performScrollToNode(hasTestTag("product-basic-banana"))
        compose.onNodeWithTag("product-basic-banana").assertIsDisplayed().performClick()
        compose.onNodeWithTag("portion-grams").performTextReplacement("120,5")
        // The list, including its header, must remain scrollable with the editor and IME.
        compose.onNodeWithTag("food-content").performScrollToNode(hasTestTag("product-basic-apple"))
        compose.onNodeWithTag("product-basic-apple").assertIsDisplayed().performClick()
        compose.onNodeWithTag("portion-grams").assertTextContains("180")
        compose.onNodeWithTag("portion-grams").performTextReplacement("80,125")
        finishQuantityInput("portion-grams", "confirm-food")
        compose.onNodeWithTag("portion-grams").assertTextContains("80,125")
        compose.onNodeWithTag("confirm-food").assertIsDisplayed().assertIsEnabled()
        // Done closes the keyboard; it must never silently add a meal.
        assertEquals(previousIds, runBlocking { app.database.dao().day(DiaryRepository.GUEST, LocalDate.now().toString()).first().map { it.meal.id }.toSet() })
    }

    private fun finishQuantityInput(tag: String, buttonTag: String) {
        compose.onNodeWithTag(tag).performClick().performImeAction()
        compose.onNodeWithTag(tag).assertIsNotFocused()
        compose.waitUntil(5_000) {
            ViewCompat.getRootWindowInsets(compose.activity.window.decorView)?.isVisible(WindowInsetsCompat.Type.ime()) != true
        }
        compose.waitForIdle()
        compose.onNodeWithTag(buttonTag).assertIsDisplayed().assertIsEnabled()
    }
}
