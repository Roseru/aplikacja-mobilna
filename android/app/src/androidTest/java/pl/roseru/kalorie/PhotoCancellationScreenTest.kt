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
import pl.roseru.kalorie.ui.*

class PhotoCancellationScreenTest {
    @get:Rule val compose=createComposeRule()
    private val op="00000000-0000-4000-8000-000000000001"
    private fun view(status:PhotoCancellationStatus)=SessionView(
        binding=SessionBinding(LocalOwnerEntity("account","account","account","https://fixture.example","A"),OwnerLease("account",1)),
        hasSession=true,serverLinked=true,photoUploadConfigured=true,
        photoUpload=PhotoUploadStatus(op,"photo","mock","mock-food-v1",true,true,0,false),photoCancellation=status)

    @Test fun confirmationIsExplicitAndRevisionChangeInvalidatesOpenDialogOnNarrowLargeText() {
        val state=mutableStateOf(view(PhotoCancellationStatus(op,2,true,false,false,false)))
        val sent=mutableListOf<Pair<String,Long>>()
        compose.setContent {CalorieThemeForTest(state.value,{id,rev->sent+=id to rev})}
        compose.onNodeWithTag("photo-cancellation-start").performScrollTo().performClick()
        compose.onNodeWithTag("photo-cancellation-confirm").assertExists();assertTrue(sent.isEmpty())
        compose.onNodeWithTag("photo-cancellation-dismiss").performClick();assertTrue(sent.isEmpty())
        compose.onNodeWithTag("photo-cancellation-start").performScrollTo().performClick()
        compose.runOnIdle {state.value=view(PhotoCancellationStatus(op,3,true,false,false,false))}
        compose.onNodeWithTag("photo-cancellation-confirm").assertDoesNotExist();assertTrue(sent.isEmpty())
        compose.onNodeWithTag("photo-cancellation-start").performScrollTo().performClick()
        compose.onNodeWithTag("photo-cancellation-confirm").performClick()
        compose.runOnIdle {assertEquals(listOf(op to 3L),sent)}
    }
    @Test fun RetryAndReleaseRemainSeparateAndNoLongerOfferNewDecision() {
        val state=mutableStateOf(view(PhotoCancellationStatus(op,2,false,true,false,false)))
        var retries=0;var releases=0;var starts=0
        compose.setContent {CalorieThemeForTest(state.value,{_,_->starts++},{retries++},{releases++})}
        compose.onNodeWithTag("photo-cancellation-start").assertDoesNotExist()
        compose.onNodeWithTag("photo-cancellation-release").assertDoesNotExist()
        compose.onNodeWithTag("photo-cancellation-retry").performScrollTo().performClick()
        compose.runOnIdle {assertEquals(1,retries);assertEquals(0,starts);assertEquals(0,releases)
            state.value=view(PhotoCancellationStatus(op,2,false,false,true,false)).copy(hasSession=false)}
        compose.onNodeWithTag("photo-cancellation-retry").assertDoesNotExist()
        compose.onNodeWithTag("photo-cancellation-release").performScrollTo().performClick()
        compose.runOnIdle {assertEquals(1,releases);assertEquals(0,starts)}
    }
    @Composable private fun CalorieThemeForTest(view:SessionView,start:(String,Long)->Unit,retry:(String)->Unit={},release:(String)->Unit={}) {
        val density=LocalDensity.current
        CompositionLocalProvider(LocalDensity provides Density(density.density,1.5f)) {
            CalorieTheme(true) {Surface {Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                PhotoCancellationPanel(view,start,retry,release)
            }}}
        }
    }
}
