package pl.roseru.kalorie

import android.os.ParcelFileDescriptor
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.*

class RankingConsentScreenTest {
    @get:Rule val compose = createComposeRule()
    private val account = SessionBinding(LocalOwnerEntity("fixture", "fixture", "account", "https://identity.example/realm", "A"), OwnerLease("fixture", 1))
    private fun source(id: String = "source-1") = RankingConsentSource(id, ServerConsents(1, true, true, "2026-10-12T12:00:00Z"),
        MotivationRanking(true, false, true, "e1111111-1111-4111-8111-111111111111", null), 1)
    private fun view(state: RankingConsentState) = SessionView(binding = account, serverLinked = true, rankingConsentConfigured = true, rankingConsent = state)
    private fun actions(read: () -> Unit = {}, confirm: (String, Boolean) -> Unit = { _, _ -> }, retry: () -> Unit = {}) =
        SessionActions({}, {}, {}, {}, {}, {}, readRankingConsents = read, confirmRankingConsent = confirm, retryRankingConsent = retry)
    private fun show(state: State<SessionView>, actions: SessionActions = actions(), compact: Boolean = false) {
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, if (compact) 1.5f else 1f)) {
                CalorieTheme(compact) {
                    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                        Box(Modifier.fillMaxSize()) {
                            Box((if (compact) Modifier.width(320.dp).fillMaxHeight() else Modifier.fillMaxSize()).testTag("ranking-consent-preview")) {
                                RankingConsentScreen(state.value, actions, {}, {})
                            }
                        }
                    }
                }
            }
        }
    }
    private fun node(tag: String) = compose.onNodeWithTag(tag).performScrollTo()
    private fun screenshot(name: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        check(instrumentation.targetContext.packageName == "pl.roseru.kalorie.validation")
        check(name in setOf("light", "dark"))
        val path = "/data/local/tmp/calorie-v087-consent-$name.png"
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("screencap -p $path")).use { it.readBytes() }
        val bytes = ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("head -c 8 $path")).use { it.readBytes() }
        assertTrue(bytes.contentEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 13, 10, 26, 10)))
    }
    @Test fun readDoesNotOptInAcknowledgmentStartsOffAndNewSourceResetsIt() {
        var reads = 0; val decisions = mutableListOf<Pair<String, Boolean>>()
        val state = mutableStateOf(view(RankingConsentState.NotRequested))
        show(state, actions(read = { reads++ }, confirm = { id, enabled -> decisions.add(id to enabled) }))
        compose.waitForIdle(); assertEquals(0, reads); assertTrue(decisions.isEmpty())
        node("ranking-consent-read").performClick(); assertEquals(1, reads); assertTrue(decisions.isEmpty())
        compose.runOnIdle { state.value = view(RankingConsentState.Ready(source())) }
        node("ranking-consent-energy").assertTextContains("włączona", substring = true)
        node("ranking-consent-ack").assertIsOff(); node("ranking-consent-enable").assertIsNotEnabled()
        screenshot("light")
        node("ranking-consent-ack").performClick(); node("ranking-consent-enable").assertIsEnabled().performClick()
        assertEquals(listOf("source-1" to true), decisions)
        node("ranking-consent-disable").performClick(); assertEquals("source-1" to false, decisions.last())
        compose.runOnIdle { state.value = view(RankingConsentState.Ready(source("source-2"))) }
        node("ranking-consent-ack").assertIsOff(); node("ranking-consent-enable").assertIsNotEnabled()
        assertEquals(2, decisions.size)
    }
    @Test fun pendingIntentOnlyOffersExactRetryAndTransitionsHidePrivateChoices() {
        var retries = 0
        val state = mutableStateOf(view(RankingConsentState.Pending(true)))
        show(state, actions(retry = { retries++ }))
        compose.waitForIdle(); assertEquals(0, retries); compose.onNodeWithTag("ranking-consent-read").assertDoesNotExist()
        compose.onNodeWithTag("ranking-consent-ack").assertDoesNotExist(); node("ranking-consent-retry").performClick(); assertEquals(1, retries)
        compose.runOnIdle { state.value = state.value.copy(rankingConsentBusy = true) }
        node("ranking-consent-retry").assertIsNotEnabled()
        compose.runOnIdle { state.value = SessionView(rankingConsentConfigured = true, rankingConsent = RankingConsentState.Pending(true)) }
        compose.onNodeWithTag("ranking-consent-retry").assertDoesNotExist(); node("ranking-consent-account").assertIsDisplayed()
        node("ranking-consent-state").assertTextContains("Zaloguj", substring = true)
        compose.runOnIdle { state.value = view(RankingConsentState.Ready(source())).copy(pendingLogin = true) }
        compose.onNodeWithTag("ranking-consent-enable").assertDoesNotExist()
        compose.runOnIdle { state.value = view(RankingConsentState.Ready(source())).copy(busy = true) }
        compose.onNodeWithTag("ranking-consent-ack").assertDoesNotExist(); assertEquals(1, retries)
    }
    @Test fun narrowDarkLargeTextKeepsConsentChoiceAndPublicInformationAccessible() {
        val state = mutableStateOf(view(RankingConsentState.Ready(source())))
        show(state, compact = true)
        val root = compose.onNodeWithTag("ranking-consent-preview").fetchSemanticsNode()
        for (tag in listOf("ranking-consent-state", "ranking-consent-energy", "ranking-consent-ack", "ranking-consent-enable", "ranking-consent-disable", "ranking-consent-read")) {
            val item = node(tag).assertIsDisplayed().fetchSemanticsNode()
            assertTrue(item.boundsInRoot.left >= root.boundsInRoot.left - 1f)
            assertTrue(item.boundsInRoot.right <= root.boundsInRoot.right + 1f)
        }
        node("ranking-consent-ack").performClick(); node("ranking-consent-enable").assertIsEnabled()
        screenshot("dark")
    }
}
