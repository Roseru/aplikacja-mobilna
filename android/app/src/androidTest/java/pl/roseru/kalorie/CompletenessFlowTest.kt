package pl.roseru.kalorie

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import kotlinx.coroutines.runBlocking
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

class CompletenessFlowTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()
    @Test fun completedDayBecomesIncompleteImmediatelyAndAfterActivityRecreation() {
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
        val app = compose.activity.application as CalorieApplication
        val repo = DiaryRepository(app.database, app)
        val date = LocalDate.now()
        val known = "known-${UUID.randomUUID()}"; val unknown = "unknown-${UUID.randomUUID()}"
        try {
            runBlocking { repo.add("basic-banana", 100.0, MealType.LUNCH, date, known); repo.setDayComplete(date, true) }
            compose.onNodeWithTag("day-complete").performScrollTo()
            compose.waitUntil(10_000) { compose.onAllNodesWithText("Dzień kompletny").fetchSemanticsNodes().isNotEmpty() }
            runBlocking { insertUnknownEnergy(app.database, date, unknown) }
            compose.waitUntil(10_000) { compose.onAllNodesWithText("Dziennik niekompletny").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText("Uzupełnij brakujące kcal przed potwierdzeniem dnia.").assertExists()
            compose.activityRule.scenario.recreate()
            compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithTag("day-complete").performScrollTo()
            compose.waitUntil(10_000) { compose.onAllNodesWithText("Dziennik niekompletny").fetchSemanticsNodes().isNotEmpty() }
        } finally { runBlocking { repo.delete(unknown); repo.delete(known); repo.setDayComplete(date, false) } }
    }
}
