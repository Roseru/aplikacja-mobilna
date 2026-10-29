package pl.roseru.kalorie

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.CalorieTheme

class SyncConflictScreenTest {
    @get:Rule val compose = createComposeRule()
    private val lease = OwnerLease("A", 1)
    private fun view() = SessionView(binding = SessionBinding(LocalOwnerEntity("A", "A", "account", "https://fixture.example", "A"), lease),
        conflicts = ConflictListView(loaded = true, preview = ConflictPreviewView("held",
            ConflictVersionView("Pomiar wagi", listOf("2026-10-21", "80.125 kg")),
            ConflictVersionView("Wpis usunięty", listOf("Usunięty na serwerze"), true), true, true, false)))
    @Composable private fun Panel(view: SessionView, actions: SessionActions) {
        val density = LocalDensity.current
        CompositionLocalProvider(LocalDensity provides Density(density.density, 1.5f)) {
            CalorieTheme(true) { Surface { Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) { SyncConflictPanel(view, actions) } } }
        }
    }
    @Test fun restoreNeedsExplicitConfirmationAndKeepsTheCapturedLease() {
        val choices = mutableListOf<Triple<OwnerLease, String, ConflictChoice>>()
        compose.setContent { Panel(view(), SessionActions({}, {}, {}, {}, {}, {},
            resolveConflict = { owner, key, choice -> choices += Triple(owner, key, choice) })) }
        compose.onNodeWithTag("conflict-local").assertExists(); compose.onNodeWithTag("conflict-server").assertExists()
        compose.onNodeWithTag("conflict-keep-local").performScrollTo().performClick()
        compose.runOnIdle { assertTrue(choices.isEmpty()) }
        compose.onNodeWithTag("conflict-confirm-choice").performClick()
        compose.runOnIdle { assertEquals(listOf(Triple(lease, "held", ConflictChoice.LOCAL)), choices) }
    }
    @Test fun missingServerVersionBlocksBothChoicesAndAnOwnerSwitchRemovesThePreview() {
        val state = mutableStateOf(view().copy(conflicts = view().conflicts.let { it.copy(preview = it.preview!!.copy(canChoose = false, needsRefresh = true)) }))
        compose.setContent { Panel(state.value, SessionActions({}, {}, {}, {}, {}, {},
            resolveConflict = { _, _, _ -> fail("Unavailable comparison cannot be committed") })) }
        compose.onNodeWithTag("conflict-keep-local").assertIsNotEnabled()
        compose.onNodeWithTag("conflict-keep-server").assertIsNotEnabled()
        compose.onNodeWithTag("conflict-download-fresh").assertIsNotEnabled()
        compose.runOnIdle { state.value = state.value.copy(binding = SessionBinding(LocalOwnerEntity("G", "guest", "guest", null, null), OwnerLease("guest", 2))) }
        compose.onNodeWithTag("sync-conflicts-panel").assertDoesNotExist()
        compose.onNodeWithTag("conflict-local").assertDoesNotExist()
    }
    @Test fun correctedRejectionEnablesOnlyNewLocalIntentAndStillNeedsConfirmation() {
        val choices = mutableListOf<Triple<OwnerLease, String, ConflictChoice>>()
        val initial = view()
        val preview = initial.conflicts.preview!!.copy(canChoose = false, restoresAsCopy = false, needsRefresh = false,
            canRetryCorrected = true, server = ConflictVersionView("Wersja serwera niedostępna", listOf("Poprzednia operacja została odrzucona.")))
        compose.setContent { Panel(initial.copy(conflicts = initial.conflicts.copy(preview = preview)),
            SessionActions({}, {}, {}, {}, {}, {}, resolveConflict = { owner, key, choice -> choices += Triple(owner, key, choice) })) }
        compose.onNodeWithText("Wyślij poprawioną wersję").assertExists()
        compose.onNodeWithTag("conflict-keep-server").assertIsNotEnabled()
        compose.onNodeWithTag("conflict-download-fresh").assertDoesNotExist()
        compose.onNodeWithTag("conflict-keep-local").performScrollTo().assertIsEnabled().performClick()
        compose.runOnIdle { assertTrue(choices.isEmpty()) }
        compose.onNodeWithText("Poprzednia odmowa i wysłana próba pozostaną zachowane.", substring = true).assertExists()
        compose.onNodeWithTag("conflict-confirm-choice").performClick()
        compose.runOnIdle { assertEquals(listOf(Triple(lease, "held", ConflictChoice.LOCAL)), choices) }
    }
}
