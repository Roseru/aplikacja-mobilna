package pl.roseru.kalorie

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.MaintenanceEstimate
import pl.roseru.kalorie.data.LocalOwnerStore
import java.time.LocalDate

class MaintenanceNavigationTest {
    @get:Rule val compose=createAndroidComposeRule<MainActivity>()
    private val app get()=ApplicationProvider.getApplicationContext<CalorieApplication>()
    private fun node(tag:String):SemanticsNodeInteraction {
        if(compose.onAllNodesWithTag("maintenance-screen").fetchSemanticsNodes().isNotEmpty())
            compose.onNodeWithTag("maintenance-screen").performScrollToNode(hasTestTag(tag))
        return compose.onNodeWithTag(tag).performScrollTo()
    }

    @Test fun guestReviewsSeparateMaintenanceAndGoalBeforeAnySaveAndKeepsTheSavedAuditAfterRecreation() {
        compose.waitUntil(20_000){compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty()}
        val lease=runBlocking {LocalOwnerStore(app.database).currentLease()}
        fun currentGoal()=runBlocking {app.database.dao().goalOn(lease.storageScope,LocalDate.now().toString())}
        val before=currentGoal()
        compose.onNodeWithTag("open-settings").performClick()
        node("open-maintenance").performClick()
        node("maintenance-age").performTextReplacement("17")
        node("maintenance-height").performTextReplacement("180")
        node("maintenance-weight").performTextReplacement("80")
        node("calculate-maintenance").assertIsNotEnabled()
        node("maintenance-age").performTextReplacement("30")
        node("equation-plus_5").performClick()
        node("maintenance-activity-LINE").performClick()
        node("calculate-maintenance").assertIsNotEnabled()
        node("maintenance-qualified").performClick()
        node("calculate-maintenance").assertIsEnabled().performClick()
        assertEquals(before,currentGoal())
        node("maintenance-result").assertTextEquals("3204 kcal / dzień")
        node("maintenance-goal").performTextReplacement("2500")
        node("review-calculated-goal").performClick()
        assertEquals(before,currentGoal())
        compose.onNodeWithTag("confirm-calculated-goal").performClick()
        compose.waitUntil(20_000){compose.onAllNodesWithTag("maintenance-screen").fetchSemanticsNodes().isEmpty()}
        val saved=checkNotNull(currentGoal())
        assertEquals(2500.0,saved.kcal,0.0)
        assertEquals("3204",MaintenanceEstimate.read(checkNotNull(saved.estimateJson)).maintenance.stripTrailingZeros().toPlainString())
        compose.activityRule.scenario.recreate()
        compose.waitUntil(20_000){compose.onAllNodesWithTag("settings-content").fetchSemanticsNodes().isNotEmpty()}
        node("saved-maintenance").assertExists()
        assertEquals(saved,currentGoal())
    }
}
