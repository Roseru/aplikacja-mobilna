package pl.roseru.kalorie

import androidx.activity.ComponentActivity
import android.os.ParcelFileDescriptor
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.*

class NemesisMutationScreenTest {
    @get:Rule val compose=createAndroidComposeRule<ComponentActivity>()
    private fun source(id:String="source-1"):NemesisDecisionSource {
        val value=JSONObject(InstrumentationRegistry.getInstrumentation().context.assets.open("nemesis/metadata.json").bufferedReader().use {it.readText()}).put("status","invited")
        listOf("accepted_at","start_date","end_date","start_at","end_at","deadline","result_status").forEach {value.put(it,JSONObject.NULL)}
        return NemesisDecisionSource(id,NemesisReadProtocol.detail(value.toString().toByteArray(),value.getString("id")),System.currentTimeMillis())
    }
    private fun actions(issue:()->Unit={},create:(String,Int,String,Boolean,Boolean,Boolean)->Unit={_,_,_,_,_,_->},
        accept:(String,Boolean,Boolean,Boolean)->Unit={_,_,_,_->},retry:()->Unit={})=SessionActions({}, {}, {}, {}, {}, {},
        issueNemesisCode=issue,createNemesis=create,acceptNemesis=accept,retryNemesisMutation=retry)
    private fun show(view:State<SessionView>,actions:SessionActions=actions(),busy:State<Boolean> = mutableStateOf(false)) {
        compose.setContent {CalorieTheme(false) {Surface {Column(Modifier.fillMaxSize()) {NemesisMutationPanel(view.value,actions,busy.value)} }}}
    }
    private fun screenshot(name:String) {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        check(instrumentation.targetContext.packageName=="pl.roseru.kalorie.validation");check(name in setOf("create","accept"))
        val path="/data/local/tmp/calorie-v0811-$name.png"
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("screencap -p $path")).use {it.readBytes()}
        val bytes=ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("head -c 8 $path")).use {it.readBytes()}
        assertTrue(bytes.contentEquals(byteArrayOf(0x89.toByte(),0x50,0x4e,0x47,13,10,26,10)))
    }
    @Test fun issuingCodeNeedsAnExplicitConfirmationAndNeverRunsFromComposition() {
        var issued=0;show(mutableStateOf(SessionView()),actions(issue={issued++}))
        compose.waitForIdle();assertEquals(0,issued)
        compose.onNodeWithTag("nemesis-issue-code").performClick();assertEquals(0,issued)
        compose.onNodeWithTag("nemesis-confirm-code").performClick();assertEquals(1,issued)
    }
    @Test fun createScopesStartOffAndChangesResetTheFullTermsAcknowledgment() {
        var recorded:List<Any>?=null
        show(mutableStateOf(SessionView()),actions(create={code,days,zone,weight,deficit,ack->recorded=listOf(code,days,zone,weight,deficit,ack)}))
        compose.onNodeWithTag("nemesis-create").performClick()
        compose.onNodeWithTag("nemesis-create-weight").performScrollTo().assertIsOff();compose.onNodeWithTag("nemesis-create-deficit").performScrollTo().assertIsOff()
        compose.onNodeWithTag("nemesis-create-ack").performScrollTo().assertIsOff();compose.onNodeWithTag("nemesis-confirm-create").assertIsNotEnabled()
        compose.onNodeWithTag("nemesis-destination-code").performScrollTo().performTextInput("A".repeat(43))
        compose.onNodeWithTag("nemesis-time-zone").performScrollTo().performTextReplacement("Europe/Warsaw")
        compose.onNodeWithTag("nemesis-create-ack").performScrollTo().performClick()
        compose.onNodeWithTag("nemesis-days-7").performScrollTo().performClick()
        compose.onNodeWithTag("nemesis-create-ack").performScrollTo().assertIsOff();compose.onNodeWithTag("nemesis-confirm-create").assertIsNotEnabled()
        compose.onNodeWithTag("nemesis-create-ack").performClick();compose.onNodeWithTag("nemesis-confirm-create").assertIsEnabled().assertIsDisplayed()
        compose.onNodeWithTag("nemesis-time-zone").performScrollTo().performImeAction()
        compose.onNodeWithTag("nemesis-create-ack").performScrollTo();compose.onNodeWithTag("nemesis-confirm-create").assertIsDisplayed();screenshot("create")
        compose.onNodeWithTag("nemesis-confirm-create").performTouchInput {click()}
        assertEquals(listOf("A".repeat(43),7,"Europe/Warsaw",false,false,true),recorded)
    }
    @Test fun acceptRequiresEveryProposedScopeAndAChangedSourceDisablesTheOldDialog() {
        val view=mutableStateOf(SessionView(nemesisDecision=source()));var accepted=0
        show(view,actions(accept={_,_,_,_->accepted++}))
        compose.onNodeWithTag("nemesis-accept").performClick()
        for(tag in listOf("nemesis-accept-ack","nemesis-accept-weight","nemesis-accept-deficit")) compose.onNodeWithTag(tag).performScrollTo().assertIsOff()
        compose.onNodeWithTag("nemesis-confirm-accept").assertIsNotEnabled()
        compose.onNodeWithTag("nemesis-accept-ack").performScrollTo().performClick();compose.onNodeWithTag("nemesis-accept-weight").performScrollTo().performClick()
        compose.onNodeWithTag("nemesis-confirm-accept").assertIsNotEnabled()
        compose.onNodeWithTag("nemesis-accept-deficit").performScrollTo().performClick();compose.onNodeWithTag("nemesis-confirm-accept").assertIsEnabled()
        screenshot("accept")
        compose.runOnIdle {view.value=SessionView(nemesisDecision=source("source-2"))}
        compose.onNodeWithTag("nemesis-confirm-accept").assertIsNotEnabled();assertEquals(0,accepted)
    }
    @Test fun pendingDecisionOnlyOffersExactRetryAndBusyOrCorruptStateCannotStartAnotherOne() {
        val view=mutableStateOf(SessionView(nemesisMutation=NemesisMutationState.Pending(NemesisAction.CREATE,null)))
        val busy=mutableStateOf(false);var retries=0;show(view,actions(retry={retries++}),busy)
        compose.onNodeWithTag("nemesis-create").assertDoesNotExist();compose.onNodeWithTag("nemesis-issue-code").assertDoesNotExist()
        compose.onNodeWithTag("nemesis-mutation-retry").performClick();assertEquals(1,retries)
        compose.runOnIdle {busy.value=true};compose.onNodeWithTag("nemesis-mutation-retry").assertIsNotEnabled()
        compose.runOnIdle {view.value=SessionView(nemesisMutation=NemesisMutationState.Blocked);busy.value=false}
        compose.onNodeWithTag("nemesis-create").assertDoesNotExist();compose.onNodeWithTag("nemesis-mutation-retry").assertDoesNotExist()
    }
}
