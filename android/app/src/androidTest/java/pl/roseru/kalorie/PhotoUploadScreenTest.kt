package pl.roseru.kalorie

import android.app.Application
import android.graphics.Bitmap
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
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.photo.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.time.LocalDate

/** Synthetic photo and session only; UI clicks never call Google or the application API. */
class PhotoUploadScreenTest {
    @get:Rule val compose=createComposeRule()
    private fun caps(model:String="mock-food-v1")=PhotoCapabilitiesState.Ready(
        PhotoCapabilitiesRead("mock",model,"food-photo-notice-v1",true,null,5_242_880,10))

    private fun screenshot(name:String) {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        check(instrumentation.targetContext.packageName=="pl.roseru.kalorie.validation")
        check(name in setOf("consent-light","queue-dark-large-text"))
        val path="/data/local/tmp/calorie-v0815-$name.png"
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("screencap -p $path")).use {it.readBytes()}
        val signature=ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("head -c 8 $path")).use {it.readBytes()}
        assertTrue(signature.contentEquals(byteArrayOf(0x89.toByte(),0x50,0x4e,0x47,13,10,26,10)))
    }

    @Test fun perPhotoConsentStartsUncheckedCancelAndProviderChangeResetItAndOnlyConfirmDispatches() {
        val app=InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as Application
        val db=Room.inMemoryDatabaseBuilder(app,CalorieDatabase::class.java).build()
        var model:MealPhotoViewModel?=null
        var store:MealPhotoStore?=null
        var photoId:String?=null
        val show=mutableStateOf(true)
        try {
            val owners=LocalOwnerStore(db)
            val lease=runBlocking {owners.ensureGuest();owners.select(owners.registerIdentity("https://fixture.example","consent-ui").id)}
            store=MealPhotoStore(app,db,lease)
            val bitmap=Bitmap.createBitmap(48,32,Bitmap.Config.ARGB_8888)
            val bytes=ByteArrayOutputStream().also {bitmap.compress(Bitmap.CompressFormat.JPEG,95,it);bitmap.recycle()}.toByteArray()
            photoId=runBlocking {store.import(ByteArrayInputStream(bytes),LocalDate.of(2026,10,15),"gallery").id}
            val id=photoId
            val photoModel=MealPhotoViewModel(app,store,SavedStateHandle());model=photoModel
            val session=mutableStateOf(SessionView(binding=SessionBinding(runBlocking {checkNotNull(db.ownerDao().byScope(lease.storageScope))},lease),hasSession=true,
                serverLinked=true,photoUploadConfigured=true,photoCapabilities=caps()))
            var count=0
            var approved:PhotoUploadConsent?=null
            compose.setContent {CalorieTheme(false) {Surface {if(show.value) MealPhotoScreen(photoModel,LocalDate.of(2026,10,15),{},{},
                session=session.value,onUpload={selected,consent,accepted->
                    assertEquals(id,selected);assertTrue(accepted);approved=consent;count++
                })}}}
            compose.waitUntil(10_000) {photoModel.drafts.value.any {it.id==id}}
            fun open() {
                compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-analyze-$id"))
                compose.onNodeWithTag("photo-analyze-$id").assertIsEnabled().performClick()
                compose.onNodeWithTag("photo-consent-send").assertIsNotEnabled()
                compose.onNodeWithTag("photo-consent-accept").assertIsOff()
            }
            open()
            screenshot("consent-light")
            compose.onNodeWithTag("photo-consent-accept").performScrollTo().performClick()
            compose.onNodeWithTag("photo-consent-send").assertIsEnabled()
            compose.onNodeWithTag("photo-consent-cancel").performClick()
            assertEquals(0,count)
            open()
            compose.onNodeWithTag("photo-consent-accept").performScrollTo().performClick()
            compose.runOnIdle {session.value=session.value.copy(photoCapabilities=caps("mock-food-v2"))}
            compose.onNodeWithTag("photo-consent-send").assertDoesNotExist()
            assertEquals(0,count)
            open()
            compose.onNodeWithTag("photo-consent-provider").assertTextEquals("Scenariusz testowy serwera — bez rozpoznawania przez Gemini.")
            compose.onNodeWithTag("photo-consent-accept").performScrollTo().performClick()
            compose.onNodeWithTag("photo-consent-send").performClick()
            compose.onNodeWithTag("photo-consent-send").assertDoesNotExist()
            assertEquals(1,count);assertEquals("mock",approved!!.provider);assertEquals("mock-food-v2",approved!!.model)
            assertEquals("food-photo-notice-v1",approved!!.noticeVersion)
            assertEquals(0,runBlocking {db.dao().operationCount(lease.storageScope)})
            assertTrue(runBlocking {db.dao().achievementMeals(lease.storageScope).isEmpty()})
        } finally {
            compose.runOnIdle {show.value=false};compose.waitForIdle()
            compose.runOnIdle {model?.viewModelScope?.cancel()}
            runBlocking {photoId?.let {store?.delete(it)}}
            db.close()
        }
    }

    @Test fun uncertainQueueNeverOffersDiscardAndBusyOrAcknowledgedStatesPreventAnotherSendAtLargeFont() {
        val state=mutableStateOf(SessionView(photoUpload=PhotoUploadStatus("op","photo","mock","mock-food-v1",true,false,0,false)))
        var retried=0;var discarded=0
        compose.setContent {CalorieTheme(true) {Surface {
            val density=LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density,1.5f)) {
                Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                    PhotoUploadPanel(state.value,{retried++},{discarded++})
                }
            }
        }}}
        compose.onNodeWithTag("photo-upload-discard").assertDoesNotExist()
        compose.onNodeWithTag("photo-upload-retry").performScrollTo().assertIsDisplayed().performClick()
        assertEquals(1,retried)
        screenshot("queue-dark-large-text")
        compose.runOnIdle {state.value=state.value.copy(photoUploadBusy=true)}
        compose.onNodeWithTag("photo-upload-retry").assertIsNotEnabled()
        compose.runOnIdle {state.value=state.value.copy(photoUploadBusy=false,
            photoUpload=PhotoUploadStatus("op","photo","mock","mock-food-v1",true,true,0,false))}
        compose.onNodeWithTag("photo-upload-retry").assertDoesNotExist()
        compose.onNodeWithTag("photo-upload-discard").assertDoesNotExist()
        compose.onNodeWithTag("photo-upload-state").assertTextContains("Posiłek nie został jeszcze zapisany.")
        compose.runOnIdle {state.value=state.value.copy(photoUpload=PhotoUploadStatus("new","photo","mock","mock-food-v1",false,false,0,false))}
        compose.onNodeWithTag("photo-upload-discard").performScrollTo().performClick()
        assertEquals(1,discarded)
    }
}
