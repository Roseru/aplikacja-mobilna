package pl.roseru.kalorie

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.PhotoCapabilitiesPanel
import pl.roseru.kalorie.ui.CalorieTheme

class PhotoCapabilitiesScreenTest {
    @get:Rule val compose = createComposeRule()
    private fun account() = SessionView(binding = SessionBinding(
        LocalOwnerEntity(id = "photo-fixture-account", storageScope = "account:photo-fixture", kind = "account",
            issuer = "https://identity.example", subject = "fixture"),
        OwnerLease("account:photo-fixture", 1)), hasSession = true, serverLinked = true, photoCapabilitiesConfigured = true)
    private fun read(provider: String = "gemini", available: Boolean = true) = PhotoCapabilitiesState.Ready(
        PhotoCapabilitiesRead(provider, if (provider == "mock") "mock-food-v1" else "gemini-3.5-flash-lite",
            "food-photo-notice-v1", available, if (available) null else "ai_storage_unavailable", 5242880, 10))

    @Test fun guestHidesOldProviderAndMockIsExplicitWithSingleReadAction() {
        val state = mutableStateOf(SessionView(photoCapabilities = read()))
        var calls = 0
        compose.setContent { CalorieTheme(false) { Surface { Column(Modifier.verticalScroll(rememberScrollState())) {
            PhotoCapabilitiesPanel(state.value) { calls++ }
        } } } }
        compose.onNodeWithTag("photo-provider").assertDoesNotExist()
        compose.onNodeWithTag("photo-check-capabilities").assertDoesNotExist()
        compose.runOnIdle { state.value = account().copy(photoCapabilities = read("mock")) }
        compose.onNodeWithTag("photo-provider").assertTextEquals("Scenariusz testowy serwera — bez rozpoznawania przez Gemini.")
        compose.onNodeWithTag("photo-check-capabilities").performScrollTo().performClick()
        assertEquals(1, calls)
        compose.runOnIdle { state.value = state.value.copy(photoCapabilitiesBusy = true) }
        compose.onNodeWithTag("photo-check-capabilities").assertIsNotEnabled()
    }

    @Test fun unavailableExplainsManualFallbackAndRecoveryHidesOldProvider() {
        val state = mutableStateOf(account().copy(photoCapabilities = read(available = false)))
        compose.setContent { CalorieTheme(true) { Surface { Column(Modifier.verticalScroll(rememberScrollState())) {
            PhotoCapabilitiesPanel(state.value) {}
        } } } }
        compose.onNodeWithTag("photo-availability").assertTextEquals("Usługa jest chwilowo niedostępna. Dodaj posiłek ręcznie.")
        compose.onNodeWithTag("photo-provider").assertTextEquals("Dostawca: Google Gemini · gemini-3.5-flash-lite")
        compose.runOnIdle { state.value = state.value.copy(requiresRecovery = true) }
        compose.onNodeWithTag("photo-provider").assertDoesNotExist()
        compose.onNodeWithTag("photo-check-capabilities").assertDoesNotExist()
    }
}
