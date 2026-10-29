package pl.roseru.kalorie

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.network.NetworkAccessState
import pl.roseru.kalorie.data.AnalyticsSyncState
import pl.roseru.kalorie.ui.AnalyticsContent
import pl.roseru.kalorie.ui.CalorieTheme
import java.time.LocalDate

/** Synthetic report presentation: account selection must remove previous copy evidence and numbers. */
class AnalyticsSyncFlowTest {
    @get:Rule val compose = createComposeRule()
    private val today = LocalDate.of(2026, 10, 29)
    private val window = AnalyticsWindow(today, AnalyticsPeriod.WEEK)
    private val result = Analytics.build(window, AnalyticsInput(emptyList(), emptyList(), emptySet(), emptyList()), today)
    private fun scrollToText(text: String) = compose.onNodeWithTag("analytics-content").performScrollToNode(hasText(text, substring = true))

    @Test fun accountCopyPendingRejectionAndOfflineAreVisibleWithoutClaimingAcknowledgement() {
        var state: AnalyticsSyncState by mutableStateOf(AnalyticsSyncState.Account("2026-10-29T12:15:00Z", "2026-10-29T12:00:00Z",
            3, 2, 1, 1, true, 0, false, false, "idle"))
        var network: NetworkAccessState by mutableStateOf(NetworkAccessState.Blocked)
        compose.setContent { CalorieTheme(false) { Surface(Modifier.fillMaxSize()) {
            AnalyticsContent(window, today, result, {}, {}, {}, {}, state, network)
        } } }
        scrollToText("Ostatnie ukończone pobranie i zastosowanie:")
        compose.onNodeWithText("Ostatnie ukończone pobranie i zastosowanie:", substring = true).assertIsDisplayed()
        scrollToText("Oczekujące: 3 · Odrzucone: 2 · Konflikty: 1")
        compose.onNodeWithText("Oczekujące: 3 · Odrzucone: 2 · Konflikty: 1", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Czas kopii i dostęp do sieci nie potwierdzają całej kolejki.").assertExists()
        compose.onNodeWithText("Tryb offline · ruch sieciowy zablokowany.", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Synchronizacja zakończona", substring = true).assertDoesNotExist()
        compose.runOnIdle {
            network = NetworkAccessState.Allowed(2)
            state = AnalyticsSyncState.Account(null, null, 0, 0, 0, 0, false, 0, false, false, null)
        }
        scrollToText("Nie ukończono jeszcze pobrania i zastosowania kopii")
        compose.onNodeWithText("Nie ukończono jeszcze pobrania i zastosowania kopii", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Ostatnie ukończone pobranie i zastosowanie:", substring = true).assertDoesNotExist()
        compose.onNodeWithText("Odrzucone: 2", substring = true).assertDoesNotExist()
        compose.onNodeWithText("Tryb offline · ruch sieciowy zablokowany.", substring = true).assertDoesNotExist()
    }

    @Test fun staleOwnerHidesReportNumbersAndGuestNeverDisplaysPreviousAccountTime() {
        var state: AnalyticsSyncState by mutableStateOf(AnalyticsSyncState.Guest)
        compose.setContent { CalorieTheme(false) { Surface(Modifier.fillMaxSize()) {
            AnalyticsContent(window, today, result, {}, {}, {}, {}, state)
        } } }
        scrollToText("Gość · dane tylko na tym urządzeniu")
        compose.onNodeWithText("Gość · dane tylko na tym urządzeniu", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Ostatnie ukończone pobranie", substring = true).assertDoesNotExist()
        compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag("average-kcal"))
        compose.onNodeWithTag("average-kcal").assertTextEquals("Brak kompletnych dni")
        compose.runOnIdle { state = AnalyticsSyncState.Stale }
        scrollToText("Wybrany profil się zmienił")
        compose.onNodeWithText("Wybrany profil się zmienił", substring = true).assertIsDisplayed()
        compose.onNodeWithTag("average-kcal").assertDoesNotExist()
        compose.onNodeWithTag("days-in-goal").assertDoesNotExist()
        compose.onNodeWithTag("weight-count").assertDoesNotExist()
    }
}
