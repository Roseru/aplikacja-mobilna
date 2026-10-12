package pl.roseru.kalorie

import android.os.ParcelFileDescriptor
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.CalorieTheme
import pl.roseru.kalorie.ui.ServerMotivationPanel

/** Synthetic own-account component fixtures; no real login or deployed API. */
class ServerMotivationScreenTest {
    @get:Rule val compose = createComposeRule()
    private val account = SessionBinding(LocalOwnerEntity("fixture-A", "fixture-A", "account", "https://id.example/realm", "A"), OwnerLease("fixture-A", 1))
    private fun read(name: String = "final") = MotivationReadProtocol.parse(InstrumentationRegistry.getInstrumentation().context.assets
        .open("motivation/motivation-$name.json").use { it.readBytes() })
    private fun view(state: MotivationState) = SessionView(binding = account, serverLinked = true, motivationConfigured = true, motivation = state)
    private fun screenshot(name: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        check(instrumentation.targetContext.packageName == "pl.roseru.kalorie.validation")
        check(name in setOf("confirmed", "dark-large-text"))
        val path = "/data/local/tmp/calorie-v086-$name.png"
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("screencap -p $path")).use { it.readBytes() }
        val signature = ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("head -c 8 $path")).use { it.readBytes() }
        assertTrue(signature.contentEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 13, 10, 26, 10)))
    }
    private fun show(state: State<SessionView>, compact: Boolean = false, onRead: () -> Unit = {}, onAccount: () -> Unit = {}) {
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, if (compact) 1.5f else 1f)) {
                CalorieTheme(compact) {
                    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                        Box(Modifier.fillMaxSize()) {
                        Column((if (compact) Modifier.width(320.dp) else Modifier.fillMaxWidth()).fillMaxHeight()
                            .testTag("server-panel-preview").verticalScroll(rememberScrollState()).padding(12.dp)) {
                            ServerMotivationPanel(state.value, onRead, onAccount)
                        }
                        }
                    }
                }
            }
        }
    }
    @Test fun confirmedPointsKeepPendingConsentAndRefreshIsOnlyExplicitAction() {
        var calls = 0
        val state = mutableStateOf(view(MotivationState.Ready(read())))
        show(state, onRead = { calls++ })
        compose.onNodeWithTag("achievement-server-points").assertTextEquals("20 pkt · Szeregowy")
        compose.onNodeWithTag("achievement-server-ranking").assertTextContains("nie odnawia", substring = true)
        compose.onNodeWithTag("achievement-server-updated").assertIsDisplayed()
        assertEquals(0, calls)
        screenshot("confirmed")
        compose.onNodeWithTag("achievement-server-read").performScrollTo().performClick(); assertEquals(1, calls)
        compose.runOnIdle { state.value = state.value.copy(motivationBusy = true, motivation = MotivationState.Loading) }
        compose.onNodeWithTag("achievement-server-read").assertIsNotEnabled()
        compose.onNodeWithTag("achievement-server-points").assertDoesNotExist()
    }
    @Test fun backfillIsUnknownAndRevokedBadgeNeverLooksLikeAnActiveAward() {
        val state = mutableStateOf(view(MotivationState.Ready(read("pending-backfill"))))
        show(state)
        compose.onNodeWithTag("achievement-server-points").assertTextEquals("Punkty i ranga jeszcze niedostępne")
        val unavailable = JSONObject(String(InstrumentationRegistry.getInstrumentation().context.assets
            .open("motivation/motivation-pending-backfill.json").use { it.readBytes() })).apply {
            getJSONObject("ranking").put("pending_consent_refresh", false)
        }
        compose.runOnIdle { state.value = view(MotivationState.Ready(MotivationReadProtocol.parse(unavailable.toString().toByteArray()))) }
        compose.onNodeWithTag("achievement-server-ranking").assertTextContains("Zgoda na ranking jest zapisana", substring = true)
        compose.runOnIdle { state.value = view(MotivationState.Ready(read("revoked"))) }
        compose.onNodeWithTag("achievement-server-details").performScrollTo().performClick()
        compose.onNodeWithTag("server-badge-complete_streak_10").performScrollTo().assertTextEquals("Cofnięta po korekcie · 0 / 10")
        compose.onNodeWithTag("server-badge-ration_days_5").performScrollTo().assertTextEquals("Oczekuje · 0 / 5")
    }
    @Test fun guestRecoveryAndLoginTransitionHidePrivateResultAndOfferAccount() {
        var accounts = 0
        val state = mutableStateOf(view(MotivationState.Ready(read())))
        show(state, onAccount = { accounts++ })
        compose.runOnIdle { state.value = state.value.copy(requiresRecovery = true) }
        compose.onNodeWithTag("achievement-server-points").assertDoesNotExist()
        compose.onNodeWithTag("achievement-server-account").performScrollTo().performClick(); assertEquals(1, accounts)
        compose.runOnIdle { state.value = view(MotivationState.Ready(read())).copy(pendingLogin = true) }
        compose.onNodeWithTag("achievement-server-points").assertDoesNotExist()
        compose.runOnIdle { state.value = SessionView(motivation = MotivationState.Ready(read())) }
        compose.onNodeWithTag("achievement-server-state").assertTextEquals("Jeszcze nie pobrane")
        compose.onNodeWithTag("achievement-server-read").assertDoesNotExist()
    }
    @Test fun dark320dpLargeTextKeepsEveryServerBadgeAndRetryAccessible() {
        var calls = 0
        val state = mutableStateOf(view(MotivationState.Ready(read("pending-materialization"))))
        show(state, compact = true, onRead = { calls++ })
        compose.onNodeWithTag("achievement-server-details").performScrollTo().performClick()
        AchievementCode.entries.forEach { code ->
            val node = compose.onNodeWithTag("server-badge-${code.wire}").performScrollTo().assertIsDisplayed().fetchSemanticsNode()
            val root = compose.onNodeWithTag("server-panel-preview").fetchSemanticsNode()
            assertEquals(320f * InstrumentationRegistry.getInstrumentation().targetContext.resources.displayMetrics.density,
                root.boundsInRoot.width, 1f)
            assertTrue(node.boundsInRoot.right <= root.boundsInRoot.right + 1f)
            assertTrue(node.boundsInRoot.left >= root.boundsInRoot.left)
        }
        screenshot("dark-large-text")
        compose.runOnIdle { state.value = view(MotivationState.Failed("Serwer jest zajęty. Ponów za co najmniej 60 s.")) }
        compose.onNodeWithTag("achievement-server-points").assertDoesNotExist()
        compose.onNodeWithTag("achievement-server-read").performScrollTo().performClick(); assertEquals(1, calls)
    }
}
