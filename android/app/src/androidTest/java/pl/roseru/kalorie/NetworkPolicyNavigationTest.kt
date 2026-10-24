package pl.roseru.kalorie

import android.view.inputmethod.InputMethodManager
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.network.*
import java.net.URL
import java.time.LocalDate

/** Exercises the actual Application/MainActivity/root, not a manually assembled Settings fixture. */
class NetworkPolicyNavigationTest {
    @get:Rule val compose=createAndroidComposeRule<MainActivity>()

    @Test fun fieldModeSurvivesActivityAndOwnerChangeWhileGuestCanStillRecordFoodAndOpenSources() {
        compose.waitUntil(15_000){compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty()}
        val app=compose.activity.application as CalorieApplication
        val policy=app.networkPolicy
        val repository=app.catalogUpdates
        val original=runBlocking{policy.state.first{it!=NetworkAccessState.Unavailable}}
        try {
            runBlocking{policy.setBlocked(false);app.sessions.logout()}
            compose.waitUntil(15_000){compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty()}
            val oldLease=checkNotNull(app.sessions.view.value.binding).lease
            compose.onNodeWithTag("open-settings").performClick()
            compose.onNodeWithTag("field-mode-switch").performScrollTo().assertIsOff().performClick()
            compose.waitUntil(10_000){policy.state.value==NetworkAccessState.Blocked}
            compose.onNodeWithTag("catalog-check").performScrollTo().assertIsNotEnabled()
            compose.onNodeWithTag("catalog-sources-demo").performScrollTo().assertIsEnabled().performClick()
            compose.onNodeWithText("Zamknij źródła").assertExists().performClick()
            compose.activityRule.scenario.recreate()
            compose.waitUntil(15_000){compose.onAllNodesWithTag("network-policy-panel").fetchSemanticsNodes().isNotEmpty()}
            assertSame(policy,(compose.activity.application as CalorieApplication).networkPolicy)
            assertSame(repository,(compose.activity.application as CalorieApplication).catalogUpdates)
            compose.onNodeWithTag("field-mode-switch").performScrollTo().assertIsOn()
            try {
                app.networkConnections.open(URL("https://example.invalid/"))
                fail("The actual application's connection factory must stay closed")
            }catch(error:NetworkAccessDenied){assertEquals(NetworkDenial.BLOCKED,error.reason)}

            // Logout changes the diary generation; the shared device setting is retained.
            runBlocking{app.sessions.logout()}
            compose.waitUntil(15_000){compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty()}
            val lease=checkNotNull(app.sessions.view.value.binding).lease
            assertNotEquals(oldLease,lease)
            assertEquals(NetworkAccessState.Blocked,policy.state.value)
            compose.onNodeWithTag("diary-content").performScrollToNode(hasTestTag("diary-network-mode"))
            compose.onNodeWithTag("diary-network-mode").assertTextEquals("Tryb poligonowy · bez połączeń")
            compose.onNodeWithTag("diary-catalog-version").assertTextContains("DEMO v1",substring=true)
            compose.onNodeWithTag("open-profile").performClick()
            compose.onNodeWithTag("open-account").performClick()
            compose.onNodeWithTag("network-mode-notice").assertIsDisplayed()
            compose.onNodeWithTag("network-mode-settings").performClick()
            compose.onNodeWithTag("field-mode-switch").performScrollTo().assertIsOn()
            compose.onNodeWithTag("open-diary").performClick()

            val day=LocalDate.now().toString()
            val before=runBlocking{app.database.dao().day(lease.storageScope,day).first()}.map{it.meal.id}.toSet()
            val operations=runBlocking{app.database.dao().operationCount(lease.storageScope)}
            compose.onNodeWithText("Dodaj posiłek").performClick()
            compose.onNodeWithTag("product-search").performTextInput("banan")
            compose.runOnUiThread {
                val decor=compose.activity.window.decorView
                compose.activity.getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(decor.windowToken,0)
                ViewCompat.getWindowInsetsController(decor)?.hide(WindowInsetsCompat.Type.ime())
                decor.clearFocus()
            }
            compose.onNodeWithTag("food-content").performScrollToNode(hasTestTag("product-basic-banana"))
            compose.onNodeWithTag("product-basic-banana").performClick()
            compose.onNodeWithTag("confirm-food").assertIsEnabled().performClick()
            compose.waitUntil(10_000){compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty()}
            val saved=runBlocking{app.database.dao().day(lease.storageScope,day).first()}.filter{it.meal.id !in before}.single()
            assertEquals("basic-banana",saved.items.single().productId)
            assertTrue(runBlocking{app.database.dao().operationCount(lease.storageScope)}>operations)
            compose.activityRule.scenario.recreate()
            compose.waitUntil(15_000){compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty()}
            assertTrue(runBlocking{app.database.dao().day(lease.storageScope,day).first()}.any{it.meal.id==saved.meal.id})
            assertEquals(NetworkAccessState.Blocked,policy.state.value)
            compose.onNodeWithTag("open-settings").performClick()
            compose.onNodeWithTag("field-mode-switch").performScrollTo().performClick()
            compose.waitUntil(10_000){policy.state.value is NetworkAccessState.Allowed}
            compose.onNodeWithTag("field-mode-switch").assertIsOff()
        }finally {runBlocking{policy.setBlocked(original==NetworkAccessState.Blocked)}}
    }
}
