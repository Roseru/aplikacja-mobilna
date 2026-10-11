package pl.roseru.kalorie

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.CalorieTheme

/** UI fixture only: this component test does not authenticate an account or contact an API. */
class ServerProfileScreenTest {
    @get:Rule val compose = createComposeRule()
    private val account = SessionBinding(LocalOwnerEntity("fixture-A", "fixture-A", "account",
        "https://id.example/realm", "fixture-A"), OwnerLease("fixture-A", 1))
    private fun preview(profile: ServerProfile?) = ProfileRead("a1111111-1111-4111-8111-111111111111",
        "e1111111-1111-4111-8111-111111111111", profile, ServerConsents(1, false, false, "2026-10-11T10:00:00Z"), 0)
    @Test fun emptyServerProfileIsVisibleAndRecoveryDisablesRead() {
        var calls = 0
        val view = mutableStateOf(SessionView(binding = account, configured = true, apiConfigured = true,
            serverLinked = true, serverProfile = preview(null)))
        compose.setContent { CalorieTheme(true) { SessionScreen(view.value, SessionActions({}, {}, {}, {}, {}, { calls++ }), {}) } }
        compose.onNodeWithTag("server-profile-empty").performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("session-read-profile").performScrollTo().assertIsEnabled().performClick()
        assertEquals(1, calls)
        compose.runOnIdle { view.value = view.value.copy(requiresRecovery = true, serverProfile = null) }
        compose.onNodeWithTag("server-profile-empty").assertDoesNotExist()
        compose.onNodeWithTag("session-read-profile").performScrollTo().assertIsNotEnabled()
    }
    @Test fun privateServerPreviewDisappearsWhenGuestReplacesAccount() {
        val profile = ServerProfile("b1111111-1111-4111-8111-111111111111", 1, "Profil serwera", null, ActivityClass.GARRISON, "Europe/Warsaw")
        val view = mutableStateOf(SessionView(binding = account, apiConfigured = true, serverLinked = true, serverProfile = preview(profile)))
        compose.setContent { CalorieTheme(true) { SessionScreen(view.value, SessionActions({}, {}, {}, {}, {}, {}), {}) } }
        compose.onNodeWithTag("server-profile-name").performScrollTo().assertTextEquals("Profil serwera")
        compose.onNodeWithText("Wzrost: brak danych").performScrollTo().assertIsDisplayed()
        compose.runOnIdle {
            view.value = SessionView(binding = SessionBinding(LocalOwnerEntity("fixture-guest", "guest", "guest", null, null), OwnerLease("guest", 2)))
        }
        compose.onNodeWithTag("server-profile-name").assertDoesNotExist()
        compose.onNodeWithTag("session-read-profile").assertDoesNotExist()
    }
    @Test fun savedCopyAndProgressAreVisibleAndRecoveryAllowsFullRead() {
        var calls = 0
        val view = mutableStateOf(SessionView(binding = account, configured = true, apiConfigured = true, serverLinked = true,
            requiresRecovery = true, snapshot = SnapshotStatus("2026-10-11T10:00:00Z", 42, 2, 10, 1, false)))
        compose.setContent { CalorieTheme(true) { SessionScreen(view.value, SessionActions({}, {}, {}, {}, {}, {}, { calls++ }), {}) } }
        compose.onNodeWithTag("snapshot-complete").performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("snapshot-progress").performScrollTo().assertTextContains("10 rekordów")
        compose.onNodeWithTag("session-download-snapshot").performScrollTo().assertIsEnabled().performClick()
        assertEquals(1, calls)
        compose.runOnIdle { view.value = view.value.copy(snapshotBusy = true) }
        compose.onNodeWithTag("session-download-snapshot").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithTag("session-bootstrap").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithTag("session-read-profile").performScrollTo().assertIsNotEnabled()
    }
    @Test fun deletionBlockDisablesDownloadAndGuestHasNoServerCopyCard() {
        val view = mutableStateOf(SessionView(binding = account, configured = true, apiConfigured = true, serverLinked = true,
            snapshot = SnapshotStatus(null, 0, 0, 0, 0, true)))
        compose.setContent { CalorieTheme(true) { SessionScreen(view.value, SessionActions({}, {}, {}, {}, {}, {}), {}) } }
        compose.onNodeWithTag("session-download-snapshot").performScrollTo().assertIsNotEnabled()
        compose.runOnIdle { view.value = SessionView(binding = SessionBinding(LocalOwnerEntity("fixture-guest", "guest", "guest", null, null), OwnerLease("guest", 2))) }
        compose.onNodeWithTag("session-download-snapshot").assertDoesNotExist()
    }
}
