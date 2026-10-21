package pl.roseru.kalorie

import android.os.ParcelFileDescriptor
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
import java.time.LocalDate
import java.time.ZoneId

class PhotoMealDraftScreenTest {
    @get:Rule val compose=createComposeRule()
    private val op="00000000-0000-4000-8000-000000000001"
    private val meal="00000000-0000-4000-8000-000000000002"
    private val item="00000000-0000-4000-8000-000000000003"
    private fun source():PhotoAnalysisSnapshot {
        val assets=InstrumentationRegistry.getInstrumentation().context.assets
        val ack=assets.open("create-accepted.json").bufferedReader().use {it.readText()}
        val read=assets.open("analysis-read-succeeded.json").use {it.readBytes()}
        return PhotoAnalysisSnapshot.read(ack,"mock").withRead(read)
    }
    private fun draft()=PhotoMealDraft.create(source().latest!!,meal,listOf(item),Instant.parse("2026-10-17T12:00:00Z"),ZoneId.of("Europe/Warsaw"))
    private fun view(value:PhotoMealDraft?)=SessionView(
        binding=SessionBinding(LocalOwnerEntity("A","A","account","https://fixture.example","A"),OwnerLease("A",1)),
        hasSession=false,serverLinked=true,photoUploadConfigured=true,photoCanEditProposal=true,
        photoUpload=PhotoUploadStatus(op,"photo","mock","mock-food-v1",true,true,0,false),
        photoAnalysis=PhotoAnalysisPreview.from(source().latest!!),photoMealDraft=value?.let {PhotoMealDraftPreview.from(op,source().withMealDraft(it,0))})
    private fun snapshot(name:String) {
        compose.waitForIdle()
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        instrumentation.waitForIdleSync()
        check(instrumentation.targetContext.packageName=="pl.roseru.kalorie.validation")
        check(name in setOf("corrections-dark-large-text","edit-dialog-dark-large-text"))
        val path="/data/local/tmp/calorie-v0818-$name.png"
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("screencap -p $path")).use {it.readBytes()}
        val bytes=ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("head -c 8 $path")).use {it.readBytes()}
        assertTrue(bytes.contentEquals(byteArrayOf(0x89.toByte(),0x50,0x4e,0x47,13,10,26,10)))
    }
    @Composable private fun content(view:SessionView,actions:PhotoDraftActions) {
        val density=LocalDensity.current
        CompositionLocalProvider(LocalDensity provides Density(density.density,1.5f)) {
            CalorieTheme(true){Surface{Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                PhotoMealDraftPanel(view,LocalDate.of(2026,10,17),actions)
            }}}
        }
    }
    @Test fun validationKeepsInvalidInputAndOnlySaveDispatchesExactLocalCorrectionsAtLargeFont() {
        val state=mutableStateOf(view(draft()));var calls=0;var sent:PhotoDraftInput?=null
        compose.setContent {content(state.value,PhotoDraftActions(replace={id,revision,itemId,input->
            assertEquals(op,id);assertEquals(1L,revision);assertEquals(item,itemId);calls++;sent=input
        }))}
        compose.onNodeWithTag("photo-meal-draft-edit-$item").performScrollTo().performClick()
        snapshot("edit-dialog-dark-large-text")
        compose.onNodeWithTag("photo-draft-input-amount").performScrollTo().performTextReplacement("0")
        compose.onNodeWithTag("photo-draft-input-save").performClick()
        compose.onNodeWithTag("photo-draft-input-error").assertExists();assertEquals(0,calls)
        compose.onNodeWithTag("photo-draft-input-amount").performScrollTo().performTextReplacement("150,5")
        compose.onNodeWithTag("photo-draft-input-energy").performScrollTo().performTextReplacement("91,2")
        compose.onNodeWithTag("photo-draft-input-protein").performScrollTo().performTextReplacement("0")
        compose.onNodeWithTag("photo-draft-input-fat").performScrollTo().performTextClearance()
        compose.onNodeWithTag("photo-draft-input-save").performClick()
        compose.runOnIdle {assertEquals(1,calls);assertEquals("150,5",sent!!.amount);assertEquals("",sent!!.fat);assertEquals("0",sent!!.protein)}
        compose.onNodeWithTag("photo-draft-input-save").assertDoesNotExist()
        snapshot("corrections-dark-large-text")
    }
    @Test fun offlineStartAddAndDiscardAreExplicitAndLastIngredientCannotBeRemoved() {
        val state=mutableStateOf(view(null));var starts=0;var additions=0;var discards=0
        compose.setContent {content(state.value,PhotoDraftActions(start={id,revision,date->
            assertEquals(op,id);assertEquals(2L,revision);assertEquals(LocalDate.of(2026,10,17),date);starts++
        },add={id,revision,input->assertEquals(op,id);assertEquals(1L,revision);assertEquals("ml",input.unit);additions++},
            discard={id,revision->assertEquals(op,id);assertEquals(1L,revision);discards++}))}
        compose.onNodeWithTag("photo-meal-draft-start").performScrollTo().performClick();assertEquals(1,starts)
        compose.runOnIdle {state.value=view(draft())}
        compose.onNodeWithTag("photo-meal-draft-remove-$item").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithTag("photo-meal-draft-add").performScrollTo().performClick()
        compose.onNodeWithTag("photo-draft-input-name").performScrollTo().performTextReplacement("Woda")
        compose.onNodeWithTag("photo-draft-unit-ml").performScrollTo().performClick()
        compose.onNodeWithTag("photo-draft-input-save").performClick();assertEquals(1,additions)
        compose.onNodeWithTag("photo-meal-draft-discard").performScrollTo().performClick()
        compose.onNodeWithTag("photo-meal-draft-discard-dismiss").performClick();assertEquals(0,discards)
        compose.onNodeWithTag("photo-meal-draft-discard").performScrollTo().performClick()
        compose.onNodeWithTag("photo-meal-draft-discard-confirm").performClick();assertEquals(1,discards)
    }
    @Test fun accountChangeAndCancelStateCloseTheEditorAndFreezeThePreservedDraft() {
        val state=mutableStateOf(view(draft()));var writes=0
        compose.setContent {content(state.value,PhotoDraftActions(replace={_,_,_,_->writes++}))}
        compose.onNodeWithTag("photo-meal-draft-edit-$item").performScrollTo().performClick()
        compose.runOnIdle {val binding=state.value.binding!!;state.value=state.value.copy(binding=binding.copy(lease=OwnerLease("A",2)))}
        compose.onNodeWithTag("photo-draft-input-save").assertDoesNotExist()
        compose.onNodeWithTag("photo-meal-draft-edit-$item").performScrollTo().performClick()
        compose.runOnIdle {state.value=state.value.copy(photoCanEditProposal=false)}
        compose.onNodeWithTag("photo-draft-input-save").assertDoesNotExist()
        compose.onNodeWithTag("photo-meal-draft-edit-$item").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithTag("photo-meal-draft-panel").assertExists();assertEquals(0,writes)
    }
}
