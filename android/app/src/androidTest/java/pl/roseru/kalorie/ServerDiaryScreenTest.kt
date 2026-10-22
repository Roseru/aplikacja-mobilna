package pl.roseru.kalorie

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.CalorieTheme

class ServerDiaryScreenTest {
    @get:Rule val compose=createComposeRule()
    private val lease=OwnerLease("A",1)
    private fun view()=SessionView(binding=SessionBinding(LocalOwnerEntity("A","A","account","https://fixture.example","A"),lease),
        serverLinked=true,hasSession=false,apiConfigured=false,
        snapshot=SnapshotStatus("2026-10-22T10:00:00Z",6,1,0,0,false),
        diaryApplication=ServerDiaryApplication("run","A","redacted","2026-10-22T10:00:00Z",1,4,2,"2026-10-22T11:00:00Z"))
    @Test fun cachedCopyCanBeAppliedOfflineWithoutASessionAndShowsHeldLocalChanges() {
        val calls=mutableListOf<OwnerLease>()
        compose.setContent{CalorieTheme(false){SessionScreen(view(),SessionActions({},{},{},{},{},{},applyDiaryCopy={calls+=it}),{})}}
        compose.onNodeWithTag("diary-copy-counts").performScrollTo().assertTextContains("2")
        compose.onNodeWithTag("session-apply-diary-copy").performScrollTo().assertIsEnabled().performClick()
        compose.runOnIdle{assertEquals(listOf(lease),calls)}
        compose.onNodeWithTag("session-download-snapshot").assertIsNotEnabled()
    }
    @Test fun busyAndRecoveryStatesPreventReapplyingTheCopy() {
        val state=mutableStateOf(view().copy(snapshotBusy=true,diaryApplying=true))
        compose.setContent{CalorieTheme(true){SessionScreen(state.value,SessionActions({},{},{},{},{},{},applyDiaryCopy={fail("Busy copy cannot be applied")}),{})}}
        compose.onNodeWithTag("session-apply-diary-copy").performScrollTo().assertIsNotEnabled()
        compose.runOnIdle{state.value=state.value.copy(snapshotBusy=false,diaryApplying=false,requiresRecovery=true)}
        compose.onNodeWithTag("session-apply-diary-copy").assertDoesNotExist()
    }
}
