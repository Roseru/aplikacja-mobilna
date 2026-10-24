package pl.roseru.kalorie

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import org.junit.Rule
import org.junit.Test

/** Actual root route in the isolated application; no login, network or fabricated public data. */
class CommunityNavigationTest {
    @get:Rule val compose=createAndroidComposeRule<MainActivity>()
    @Test fun guestCanReachCommunityAndReturnToPrivateOfflineFoodAfterRecreation() {
        compose.waitUntil(20_000){compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty()}
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("open-community").performScrollTo().performClick()
        compose.onNodeWithTag("community-search").assertIsNotEnabled()
        compose.onNodeWithText("Otwórz konto").assertExists()
        compose.activityRule.scenario.recreate()
        compose.waitUntil(20_000){compose.onAllNodesWithTag("community-content").fetchSemanticsNodes().isNotEmpty()}
        compose.onNodeWithTag("community-search").assertIsNotEnabled()
        compose.onNodeWithText("Dodaj prywatny produkt").performScrollTo().performClick()
        compose.onNodeWithTag("custom-name").assertExists()
    }
}
