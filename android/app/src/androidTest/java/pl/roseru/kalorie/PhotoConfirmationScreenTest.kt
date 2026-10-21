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
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.*
import java.time.Instant
import java.time.ZoneId

class PhotoConfirmationScreenTest {
    @get:Rule val compose=createComposeRule()
    private val op="00000000-0000-4000-8000-000000000001"
    private fun view(edit:Long=1,retry:Boolean=false,rejected:Boolean=false,reopen:Boolean=false):SessionView {
        val assets=InstrumentationRegistry.getInstrumentation().context.assets
        val ack=assets.open("create-accepted.json").bufferedReader().use {it.readText()}
        val source=PhotoAnalysisSnapshot.read(ack,"mock").withRead(assets.open("analysis-read-succeeded.json").use {it.readBytes()})
        var draft=PhotoMealDraft.create(source.latest!!,"00000000-0000-4000-8000-000000000002",
            listOf("00000000-0000-4000-8000-000000000003"),Instant.parse("2026-10-18T12:00:00Z"),ZoneId.of("Europe/Warsaw"))
        val initial=source.withMealDraft(draft,0)
        if(edit==2L)draft=draft.rename("Nowsza poprawka")
        return SessionView(binding=SessionBinding(LocalOwnerEntity("A","A","account","https://fixture.example","A"),OwnerLease("A",1)),
            hasSession=true,serverLinked=true,photoUploadConfigured=true,photoCanEditProposal=!retry && !rejected,
            photoUpload=PhotoUploadStatus(op,"photo","mock","mock-food-v1",true,true,0,false),
            photoMealDraft=PhotoMealDraftPreview.from(op,if(edit==1L)initial else initial.withMealDraft(draft,1)),
            photoConfirmation=PhotoConfirmationStatus(op,2,edit,!retry && !rejected,retry,rejected,reopen))
    }
    @Composable private fun Panel(view:SessionView,actions:PhotoDraftActions) {
        val density=LocalDensity.current
        CompositionLocalProvider(LocalDensity provides Density(density.density,1.5f)) {
            CalorieTheme(true) {Surface {Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                PhotoConfirmationPanel(view,actions)
            }}}
        }
    }
    @Test fun approvalIsExplicitAndEditingOrChangingAccountClosesOldDialog() {
        val state=mutableStateOf(view());val calls=mutableListOf<Triple<String,Long,Long>>()
        compose.setContent {Panel(state.value,PhotoDraftActions(confirm={id,rev,edit->calls+=Triple(id,rev,edit)}))}
        compose.onNodeWithTag("photo-confirmation-start").performScrollTo().performClick()
        compose.onNodeWithTag("photo-confirmation-approve").assertExists();assertTrue(calls.isEmpty())
        compose.onNodeWithTag("photo-confirmation-dismiss").performClick();assertTrue(calls.isEmpty())
        compose.onNodeWithTag("photo-confirmation-start").performClick()
        compose.runOnIdle {state.value=view(2)}
        compose.onNodeWithTag("photo-confirmation-approve").assertDoesNotExist()
        compose.onNodeWithTag("photo-confirmation-start").performClick()
        compose.runOnIdle {state.value=state.value.copy(binding=SessionBinding(LocalOwnerEntity("B","B","account","https://fixture.example","B"),OwnerLease("B",2)))}
        compose.onNodeWithTag("photo-confirmation-approve").assertDoesNotExist()
        compose.onNodeWithTag("photo-confirmation-start").performClick()
        compose.onNodeWithTag("photo-confirmation-approve").performClick()
        compose.runOnIdle {assertEquals(listOf(Triple(op,2L,2L)),calls)}
    }
    @Test fun retryHasNoNewApprovalAndRejectedIntentCannotBeRetried() {
        val state=mutableStateOf(view(retry=true));var starts=0;var retries=0
        compose.setContent {Panel(state.value,PhotoDraftActions(confirm={_,_,_->starts++},retryConfirmation={retries++}))}
        compose.onNodeWithTag("photo-confirmation-start").assertDoesNotExist()
        compose.onNodeWithTag("photo-confirmation-retry").performScrollTo().performClick()
        compose.runOnIdle {assertEquals(1,retries);assertEquals(0,starts);state.value=view(rejected=true)}
        compose.onNodeWithTag("photo-confirmation-retry").assertDoesNotExist()
        compose.onNodeWithTag("photo-confirmation-start").assertDoesNotExist()
        compose.onNodeWithTag("photo-confirmation-rejected").assertExists()
    }
    @Test fun offlineBusyAndRecoveryDisableSendingAndNeverTriggerImplicitRequests() {
        val state=mutableStateOf(view().copy(hasSession=false));var sent=0
        compose.setContent {Panel(state.value,PhotoDraftActions(confirm={_,_,_->sent++}))}
        compose.onNodeWithTag("photo-confirmation-start").assertIsNotEnabled()
        compose.runOnIdle {state.value=view().copy(photoConfirmBusy=true,photoUploadBusy=true)}
        compose.onNodeWithTag("photo-confirmation-start").assertIsNotEnabled()
        compose.runOnIdle {state.value=view().copy(requiresRecovery=true)}
        compose.onNodeWithTag("photo-confirmation-start").assertIsNotEnabled()
        compose.runOnIdle {assertEquals(0,sent)}
    }

    @Test fun reopenedReviewRequiresProofAndSeparateLocalApprovalEvenWithExpiredAccess() {
        val state=mutableStateOf(view(rejected=true));val calls=mutableListOf<Triple<String,Long,Long>>()
        compose.setContent {Panel(state.value,PhotoDraftActions(reopen={id,rev,edit->calls+=Triple(id,rev,edit)}))}
        compose.onNodeWithTag("photo-confirmation-reopen").assertDoesNotExist()
        compose.runOnIdle {state.value=view(rejected=true,reopen=true).copy(hasSession=false)}
        compose.onNodeWithTag("photo-confirmation-start").assertDoesNotExist()
        compose.onNodeWithTag("photo-confirmation-reopen").assertIsEnabled().performScrollTo().performClick()
        compose.onNodeWithTag("photo-confirmation-reopen-approve").assertExists();assertTrue(calls.isEmpty())
        compose.onNodeWithTag("photo-confirmation-reopen-dismiss").performClick();assertTrue(calls.isEmpty())
        compose.onNodeWithTag("photo-confirmation-reopen").performClick()
        compose.onNodeWithTag("photo-confirmation-reopen-approve").performClick()
        compose.runOnIdle {assertEquals(listOf(Triple(op,2L,1L)),calls)}
    }
    @Test fun reopenedReviewDialogExpiresWithAnotherEditAndRecoveryDisablesTheAction() {
        val state=mutableStateOf(view(rejected=true,reopen=true));var calls=0
        compose.setContent {Panel(state.value,PhotoDraftActions(reopen={_,_,_->calls++}))}
        compose.onNodeWithTag("photo-confirmation-reopen").performClick()
        compose.runOnIdle {state.value=view(edit=2,rejected=true,reopen=true)}
        compose.onNodeWithTag("photo-confirmation-reopen-approve").assertDoesNotExist()
        compose.runOnIdle {state.value=state.value.copy(requiresRecovery=true)}
        compose.onNodeWithTag("photo-confirmation-reopen").assertIsNotEnabled()
        compose.runOnIdle {assertEquals(0,calls)}
    }
}
