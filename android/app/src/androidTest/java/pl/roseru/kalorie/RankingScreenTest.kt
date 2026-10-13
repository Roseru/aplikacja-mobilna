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
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.*
import java.time.Instant

class RankingScreenTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    private val account = SessionBinding(LocalOwnerEntity("fixture", "fixture", "account", "https://identity.example/realm", "A"), OwnerLease("fixture", 1))
    private fun view(state: RankingState) = SessionView(binding = account, serverLinked = true, rankingConfigured = true, ranking = state)
    private fun page(more: Boolean = false) = RankingPage(Instant.parse("2026-10-13T10:00:00Z"),
        List(if (more) 25 else 3) { RankingEntry(if (it < 2 || more) 1 else 3, "Żołnierz testowy", if (it < 2 || more) 10 else 8, "Rekrut", 2) },
        if (more) "rk1." + "A".repeat(43) else null, if (more) Instant.parse("2026-10-13T10:10:00Z") else null)
    private fun actions(read: () -> Unit = {}, next: () -> Unit = {}, retry: () -> Unit = {}, clear: () -> Unit = {}) = SessionActions({}, {}, {}, {}, {}, {},
        readRanking = read, nextRankingPage = next, retryRankingPage = retry, clearRanking = clear)
    private fun show(state: State<SessionView>, actions: SessionActions = actions(), compact: Boolean = false, visible: State<Boolean> = mutableStateOf(true)) {
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, if (compact) 1.5f else 1f)) {
                CalorieTheme(compact) {
                    Surface(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing), color = MaterialTheme.colorScheme.background) {
                        Box((if (compact) Modifier.width(320.dp).fillMaxHeight() else Modifier.fillMaxSize()).testTag("ranking-preview")) {
                            if (visible.value) RankingScreen(state.value, actions, {}, {}, {})
                        }
                    }
                }
            }
        }
    }
    private fun node(tag: String) = compose.onNodeWithTag("ranking-content").performScrollToNode(hasTestTag(tag)).let { compose.onNodeWithTag(tag) }
    private fun screenshot(name: String) {
        val inst = InstrumentationRegistry.getInstrumentation()
        check(inst.targetContext.packageName == "pl.roseru.kalorie.validation"); check(name in setOf("light", "dark"))
        val path = "/data/local/tmp/calorie-v088-ranking-$name.png"
        ParcelFileDescriptor.AutoCloseInputStream(inst.uiAutomation.executeShellCommand("screencap -p $path")).use { it.readBytes() }
        val bytes = ParcelFileDescriptor.AutoCloseInputStream(inst.uiAutomation.executeShellCommand("head -c 8 $path")).use { it.readBytes() }
        assertTrue(bytes.contentEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 13, 10, 26, 10)))
    }
    @Test fun readsAreExplicitAndServerTiesStayVisibleWithDuplicateNames() {
        var reads = 0; var next = 0; var retries = 0
        val state = mutableStateOf(view(RankingState.NotRequested)); show(state, actions({ reads++ }, { next++ }, { retries++ }))
        compose.waitForIdle(); assertEquals(0, reads); node("ranking-read").performClick(); assertEquals(1, reads)
        compose.runOnIdle { state.value = view(RankingState.Ready(page())) }
        node("ranking-entry-0").assert(hasText("Pozycja 1") or hasAnyDescendant(hasText("Pozycja 1")))
        node("ranking-entry-1").assert(hasText("Pozycja 1") or hasAnyDescendant(hasText("Pozycja 1")))
        node("ranking-entry-2").assert(hasText("Pozycja 3") or hasAnyDescendant(hasText("Pozycja 3")))
        compose.onNodeWithTag("ranking-next").assertDoesNotExist()
        compose.onNodeWithTag("ranking-content").performScrollToIndex(0); screenshot("light")
        compose.runOnIdle { state.value = view(RankingState.Ready(page(true))) }
        node("ranking-next").performClick(); assertEquals(1, next)
        compose.runOnIdle { state.value = view(RankingState.Ready(page())) }
        compose.waitForIdle(); compose.onNodeWithTag("ranking-entry-0").assertIsDisplayed()
        compose.runOnIdle { state.value = view(RankingState.Ready(RankingPage(Instant.parse("2026-10-13T10:00:00Z"), emptyList(), null, null))) }
        node("ranking-empty").assertTextContains("Na tej stronie", substring = true)
        compose.onNodeWithTag("ranking-entry-0").assertDoesNotExist()
        compose.runOnIdle { state.value = view(RankingState.Failed("Utrata odpowiedzi", true)) }
        node("ranking-retry").performClick(); assertEquals(1, retries)
        compose.runOnIdle { state.value = view(RankingState.Failed("Strona wygasła", false)) }
        compose.onNodeWithTag("ranking-retry").assertDoesNotExist(); node("ranking-read").assertIsEnabled()
        assertEquals(1, reads)
    }
    @Test fun guestAndLoginTransitionHidePeersAndStoppingOrLeavingClearsPreview() {
        var clears = 0; val visible = mutableStateOf(true); val state = mutableStateOf(view(RankingState.Ready(page())))
        show(state, actions(clear = { clears++ }), visible = visible)
        compose.runOnIdle { state.value = state.value.copy(busy = true) }
        compose.onNodeWithTag("ranking-entry-0").assertDoesNotExist(); node("ranking-read").assertIsNotEnabled()
        compose.runOnIdle { state.value = SessionView(rankingConfigured = true, ranking = RankingState.Ready(page())) }
        node("ranking-state").assertTextContains("Zaloguj", substring = true)
        compose.onNodeWithTag("ranking-entry-0").assertDoesNotExist(); node("ranking-account").assertIsDisplayed()
        compose.activityRule.scenario.moveToState(Lifecycle.State.CREATED)
        assertTrue(clears > 0); compose.activityRule.scenario.moveToState(Lifecycle.State.RESUMED)
        val before = clears; compose.runOnIdle { visible.value = false }; compose.waitForIdle(); assertTrue(clears > before)
    }
    @Test fun darkNarrowLargeTextAndLongCountsRemainWithinTheViewport() {
        val ready = RankingPage(Instant.parse("2026-10-13T10:00:00Z"), listOf(RankingEntry(Long.MAX_VALUE, "🪖".repeat(80), Long.MAX_VALUE, "Sierżant", 4)), null, null)
        val state = mutableStateOf(view(RankingState.Ready(ready))); show(state, compact = true)
        val root = compose.onNodeWithTag("ranking-preview").fetchSemanticsNode()
        val row = node("ranking-entry-0").assertIsDisplayed().fetchSemanticsNode()
        assertTrue(row.boundsInRoot.left >= root.boundsInRoot.left - 1f); assertTrue(row.boundsInRoot.right <= root.boundsInRoot.right + 1f)
        node("ranking-entry-0").assert(hasText(Long.MAX_VALUE.toString(), substring = true) or hasAnyDescendant(hasText(Long.MAX_VALUE.toString(), substring = true)))
        node("ranking-read").assertIsDisplayed().assertIsEnabled(); screenshot("dark")
    }
}
