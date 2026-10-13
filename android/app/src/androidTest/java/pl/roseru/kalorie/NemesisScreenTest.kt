package pl.roseru.kalorie

import android.os.ParcelFileDescriptor
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.*

class NemesisScreenTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    private val account = SessionBinding(LocalOwnerEntity("fixture", "fixture", "account", "https://identity.example/realm", "A"), OwnerLease("fixture", 1))
    private fun json(name: String) = JSONObject(InstrumentationRegistry.getInstrumentation().context.assets.open("nemesis/$name.json").bufferedReader().use { it.readText() })
    private fun challenge(scope: Boolean = true, longName: Boolean = false): NemesisChallenge {
        val value = json("metadata"); val scopes = value.getJSONObject("terms").getJSONObject("scope")
        scopes.put("weight_change", scope).put("mean_deficit", scope)
        if (longName) value.put("partner_pseudonym", "🪖".repeat(80))
        return NemesisReadProtocol.detail(value.toString().toByteArray(), value.getString("id"))
    }
    private fun detail(name: String = "provisional", scope: Boolean = true, longName: Boolean = false): NemesisState.DetailReady {
        val challenge = challenge(scope, longName)
        return NemesisState.DetailReady(challenge, NemesisReadProtocol.statistics(json(name).toString().toByteArray(), challenge))
    }
    private fun view(state: NemesisState) = SessionView(binding = account, serverLinked = true, nemesisConfigured = true, nemesis = state)
    private fun actions(read: () -> Unit = {}, open: (String) -> Unit = {}, clear: () -> Unit = {}) = SessionActions({}, {}, {}, {}, {}, {},
        readNemesis = read, readNemesisChallenge = open, clearNemesis = clear)
    private fun show(state: State<SessionView>, actions: SessionActions = actions(), compact: Boolean = false, visible: State<Boolean> = mutableStateOf(true)) {
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, if (compact) 1.5f else 1f)) {
                CalorieTheme(compact) {
                    Surface(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing), color = MaterialTheme.colorScheme.background) {
                        Box(Modifier.fillMaxSize()) {
                            Box((if (compact) Modifier.width(320.dp).fillMaxHeight() else Modifier.fillMaxSize()).testTag("nemesis-preview")) {
                                if (visible.value) NemesisScreen(state.value, actions, {}, {})
                            }
                        }
                    }
                }
            }
        }
    }
    private fun node(tag: String) = compose.onNodeWithTag("nemesis-content").performScrollToNode(hasTestTag(tag)).let { compose.onNodeWithTag(tag) }
    private fun screenshot(name: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        check(instrumentation.targetContext.packageName == "pl.roseru.kalorie.validation"); check(name in setOf("light", "dark"))
        val path = "/data/local/tmp/calorie-v0810-nemesis-$name.png"
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("screencap -p $path")).use { it.readBytes() }
        val bytes = ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("head -c 8 $path")).use { it.readBytes() }
        assertTrue(bytes.contentEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 13, 10, 26, 10)))
    }
    @Test fun pendingShowsWaitingAndNeverInventsScoresOrAResult() {
        val state = mutableStateOf(view(detail("pending"))); show(state)
        node("nemesis-result-state").assertTextContains("Czekamy", substring = true)
        compose.onNodeWithTag("nemesis-outcome").assertDoesNotExist(); compose.onNodeWithTag("nemesis-score-self").assertDoesNotExist()
        compose.onNodeWithTag("nemesis-score-opponent").assertDoesNotExist()
        compose.onAllNodesWithText("0 pkt").assertCountEquals(0)
    }
    @Test fun signedZeroMissingHiddenAndWinnerRemainDistinct() {
        val state = mutableStateOf(view(detail())); show(state)
        node("nemesis-outcome").assertTextContains("Prowadzisz", substring = true)
        node("nemesis-deficit-self").assertTextContains("-15% · 2 dni", substring = true)
        node("nemesis-deficit-opponent").assertTextContains("0% · 1 dzień", substring = true)
        node("nemesis-weight-opponent").assertTextContains("Za mało danych · 1 dzień", substring = true)
        compose.onNodeWithTag("nemesis-content").performScrollToNode(hasTestTag("nemesis-outcome")); screenshot("light")
        compose.runOnIdle { state.value = view(detail("hidden", false)) }
        node("nemesis-weight-self").assertTextContains("Nieudostępniane", substring = true)
        node("nemesis-deficit-opponent").assertTextContains("Nieudostępniane", substring = true)
    }
    @Test fun guestTransitionHidesPeerAndResumeRevalidatesWhileStopOrLeaveClears() {
        var reads = 0; var clears = 0; val visible = mutableStateOf(true)
        val state = mutableStateOf(SessionView(nemesisConfigured = true, nemesis = detail()))
        show(state, actions(read = { reads++ }, open = { reads++ }, clear = { clears++ }), visible = visible)
        node("nemesis-state").assertTextContains("Zaloguj", substring = true); assertEquals(0, reads)
        compose.onNodeWithTag("nemesis-partner").assertDoesNotExist()
        compose.runOnIdle { state.value = view(NemesisState.ListReady(NemesisPage(listOf(challenge()), null))) }
        compose.waitUntil(10_000) { reads > 0 }; node("nemesis-open-0").assertIsEnabled().performClick()
        compose.runOnIdle { state.value = view(detail()).copy(busy = true) }
        compose.onNodeWithTag("nemesis-partner").assertDoesNotExist(); compose.onNodeWithTag("nemesis-score-self").assertDoesNotExist()
        compose.runOnIdle { state.value = view(detail()) }
        val before = reads; compose.activityRule.scenario.moveToState(Lifecycle.State.CREATED)
        assertTrue(clears > 0); compose.activityRule.scenario.moveToState(Lifecycle.State.RESUMED)
        compose.waitUntil(10_000) { reads > before }
        val beforeLeave = clears; compose.runOnIdle { visible.value = false }; compose.waitForIdle(); assertTrue(clears > beforeLeave)
    }
    @Test fun narrowDarkLargeTextKeepsRulesAndBothParticipantsWithinTheViewport() {
        val state = mutableStateOf(view(detail(longName = true))); show(state, compact = true)
        val root = compose.onNodeWithTag("nemesis-preview").fetchSemanticsNode()
        assertEquals(with(compose.density) { 320.dp.toPx() }, root.boundsInRoot.width, 1f)
        for (tag in listOf("nemesis-partner", "nemesis-result-state", "nemesis-score-self", "nemesis-score-opponent", "nemesis-deficit-self", "nemesis-deficit-opponent", "nemesis-refresh")) {
            val element = node(tag).assertIsDisplayed().fetchSemanticsNode()
            assertTrue(element.boundsInRoot.left >= root.boundsInRoot.left - 1f); assertTrue(element.boundsInRoot.right <= root.boundsInRoot.right + 1f)
        }
        node("nemesis-score-self"); screenshot("dark")
    }
}
