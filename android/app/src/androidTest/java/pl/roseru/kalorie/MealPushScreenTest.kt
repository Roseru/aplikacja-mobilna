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

class MealPushScreenTest {
    @get:Rule val compose=createComposeRule()
    private fun view()=SessionView(binding=SessionBinding(LocalOwnerEntity("A","A","account","https://fixture.example","A"),OwnerLease("A",1)),
        serverLinked=true,mealPushConfigured=true,mealPush=MealPushStatus(1,1,1,2,true,true))
    @Composable private fun Panel(view:SessionView,send:(OwnerLease)->Unit) {
        val density=LocalDensity.current
        CompositionLocalProvider(LocalDensity provides Density(density.density,1.5f)) {
            CalorieTheme(true){Surface{Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())){MealPushPanel(view,send)}}}
        }
    }
    @Test fun explicitReplayShowsSeparatePendingConflictAndLegacyCountersAndCapturesLease() {
        val state=mutableStateOf(view());val sent=mutableListOf<OwnerLease>()
        compose.setContent {Panel(state.value){sent+=it}}
        compose.onNodeWithTag("meal-push-counts").assertTextEquals("Gotowe: 1 · Czekają na poprzednią zmianę: 1")
        compose.onNodeWithText("Wymagają uzgodnienia: 1. Lokalne dane zachowano.").assertExists()
        compose.onNodeWithText("Starsze lub wymagające konwersji wpisy: 2. Pozostają lokalnie do świadomego uzgodnienia.").assertExists()
        compose.onNodeWithTag("session-send-meals").performScrollTo().assertIsEnabled().assertTextEquals("Ponów zapisaną partię").performClick()
        compose.runOnIdle {assertEquals(listOf(OwnerLease("A",1)),sent);state.value=state.value.copy(mealPushBusy=true)}
        compose.onNodeWithTag("session-send-meals").assertIsNotEnabled()
    }
    @Test fun sixDomainsShowIndependentPendingWaitingAndRefusalCounts() {
        val names = listOf("meal", "weight", "profile", "goal", "diary_day", "product_draft")
        val labels = listOf("Posiłki", "Waga", "Profil", "Cele", "Kompletność dni", "Prywatne produkty")
        val counts = names.mapIndexed { index, type -> type to DomainPushStatus(index, index + 1, index + 2) }.toMap()
        val state = view().copy(mealPush = view().mealPush!!.copy(domains = counts))
        compose.setContent { Panel(state) {} }
        names.forEachIndexed { index, type -> compose.onNodeWithTag("sync-domain-$type").performScrollTo()
            .assertTextEquals("${labels[index]}: gotowe $index, oczekujące ${index + 1}, do uzgodnienia ${index + 2}") }
    }
    @Test fun recoveryMissingSnapshotAndEveryServerOperationDisableSending() {
        val state=mutableStateOf(view());compose.setContent {Panel(state.value){fail("Blocked action sent")}}
        val blocked=listOf(view().copy(requiresRecovery=true),view().copy(mealPush=view().mealPush!!.copy(ready=false)),
            view().copy(busy=true),view().copy(pendingLogin=true),view().copy(bootstrapBusy=true),view().copy(snapshotBusy=true),
            view().copy(profileBusy=true),view().copy(motivationBusy=true),view().copy(rankingBusy=true),view().copy(rankingConsentBusy=true),
            view().copy(nemesisBusy=true),view().copy(nemesisMutationBusy=true),view().copy(photoUploadBusy=true),view().copy(mealPushBusy=true),
            view().copy(mealPushConfigured=false),view().copy(mealPush=view().mealPush!!.copy(pending=0,persistedBatch=false)))
        for(value in blocked){compose.runOnIdle{state.value=value};compose.onNodeWithTag("session-send-meals").assertIsNotEnabled()}
    }
    @Test fun expiredAccessAllowsExplicitRenewalAndSwitchingOwnerUpdatesOrHidesPanel() {
        val state=mutableStateOf(view().copy(hasSession=false));val sent=mutableListOf<OwnerLease>()
        compose.setContent{Panel(state.value){sent+=it}}
        compose.onNodeWithTag("session-send-meals").performScrollTo().assertIsEnabled()
        compose.runOnIdle{state.value=state.value.copy(binding=SessionBinding(LocalOwnerEntity("B","B","account","https://fixture.example","B"),OwnerLease("B",2)))}
        compose.onNodeWithTag("session-send-meals").performScrollTo().performClick()
        compose.runOnIdle{assertEquals(listOf(OwnerLease("B",2)),sent);state.value=state.value.copy(binding=SessionBinding(LocalOwnerEntity("G","G","guest",null,null),OwnerLease("G",3)))}
        compose.onNodeWithTag("meal-push-panel").assertDoesNotExist()
    }
}
