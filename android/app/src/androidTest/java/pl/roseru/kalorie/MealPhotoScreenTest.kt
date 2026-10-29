package pl.roseru.kalorie

import android.graphics.Bitmap
import android.graphics.Color
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.room.withTransaction
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.async
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.runBlocking
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.*
import pl.roseru.kalorie.data.LocalOwnerStore
import pl.roseru.kalorie.photo.MealPhotoStore
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.time.LocalDate

class MealPhotoScreenTest {
    @get:Rule val compose=createAndroidComposeRule<MainActivity>()
    private fun ready() {
        val app=compose.activity.application as CalorieApplication
        runBlocking { app.sessions.logout() }
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("daily-kcal").fetchSemanticsNodes().isNotEmpty() }
    }
    private fun open() {
        compose.onNodeWithText("Dodaj posiłek").performClick()
        compose.onNodeWithTag("open-meal-photo").performClick()
        compose.onNodeWithText("Zdjęcie posiłku").assertExists()
    }
    private fun revealPreview() {
        // The selected card is already composed. Wait for its decoded image before
        // scrolling: a whole-list search can recycle it while its height changes.
        try {
            compose.waitUntil(15_000) {
                compose.onAllNodesWithTag("photo-preview").fetchSemanticsNodes().isNotEmpty()
            }
        } catch (timeout:ComposeTimeoutException) {
            compose.onRoot(useUnmergedTree=true).printToLog("PhotoPreviewState")
            throw timeout
        }
        compose.onNodeWithTag("photo-preview").performScrollTo().assertIsDisplayed()
    }
    @Test fun guestPhotoNavigationManualFallbackAndRotationDoNotChangeDiaryOrGrantConsent() {
        ready()
        val app=compose.activity.application as CalorieApplication
        val lease=runBlocking { LocalOwnerStore(app.database).currentLease() }
        val before=runBlocking { app.database.dao().operationCount(lease.storageScope) }
        open()
        compose.onNodeWithTag("photo-gallery").assertIsEnabled()
        compose.onNodeWithTag("photo-camera").assertIsEnabled()
        compose.activityRule.scenario.recreate()
        compose.waitUntil(15_000) { compose.onAllNodesWithTag("photo-content").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-manual"))
        compose.onNodeWithTag("photo-manual").performClick()
        compose.onNodeWithTag("custom-name").assertExists()
        assertEquals(before,runBlocking { app.database.dao().operationCount(lease.storageScope) })
    }
    @Test fun durableSyntheticPreviewSurvivesActivityRecreationAndExplicitDeletionKeepsDiary() {
        ready()
        val app=compose.activity.application as CalorieApplication
        val lease=runBlocking { LocalOwnerStore(app.database).currentLease() }
        val store=MealPhotoStore(app,app.database,lease)
        val before=runBlocking { app.database.dao().operationCount(lease.storageScope) }
        val image=Bitmap.createBitmap(200,120,Bitmap.Config.ARGB_8888).also { it.eraseColor(Color.rgb(80,125,65)) }
        val bytes=ByteArrayOutputStream().also { image.compress(Bitmap.CompressFormat.JPEG,90,it);image.recycle() }.toByteArray()
        val row=runBlocking { store.import(ByteArrayInputStream(bytes),LocalDate.of(2026,10,13),"gallery") }
        try {
            open()
            compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-preview-${row.id}"))
            compose.onNodeWithTag("photo-preview-${row.id}").performClick()
            revealPreview()
            compose.activityRule.scenario.recreate()
            compose.waitUntil(15_000) { compose.onAllNodesWithTag("photo-content").fetchSemanticsNodes().isNotEmpty() }
            // LazyColumn can restore before its asynchronous rows are laid out. Reveal the
            // original row without clicking its toggle: the selected preview must survive.
            compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-preview-${row.id}"))
            compose.onNodeWithTag("photo-preview-${row.id}").assertTextContains("Zwiń")
            revealPreview()
            compose.onNodeWithTag("photo-content").performScrollToIndex(0)
            androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().uiAutomation
                .executeShellCommand("screencap -p /data/local/tmp/calorie-v0812-photo.png").use { descriptor ->
                    java.io.FileInputStream(descriptor.fileDescriptor).use { it.readBytes() }
                }
            compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-draft-${row.id}"))
            compose.onNode(hasText("Usuń") and hasAnyAncestor(hasTestTag("photo-draft-${row.id}"))).performClick()
            compose.onNodeWithTag("photo-confirm-delete").performClick()
            compose.waitUntil(10_000) { compose.onAllNodesWithTag("photo-draft-${row.id}").fetchSemanticsNodes().isEmpty() }
            assertEquals(before,runBlocking { app.database.dao().operationCount(lease.storageScope) })
        } finally {
            runBlocking { if(app.database.photoDao().get(lease.storageScope,row.id)!=null) store.delete(row.id) }
        }
    }

    @Test fun selectedPreviewSurvivesRepeatedRecreationWhileWriterHeldThenLoadsAfterRelease() {
        ready()
        val app=compose.activity.application as CalorieApplication
        val lease=runBlocking {LocalOwnerStore(app.database).currentLease()}
        val store=MealPhotoStore(app,app.database,lease)
        val before=runBlocking {app.database.dao().operationCount(lease.storageScope)}
        val bitmap=Bitmap.createBitmap(200,120,Bitmap.Config.ARGB_8888).also {it.eraseColor(Color.BLUE)}
        val bytes=ByteArrayOutputStream().also {bitmap.compress(Bitmap.CompressFormat.JPEG,90,it);bitmap.recycle()}.toByteArray()
        val row=runBlocking {store.import(ByteArrayInputStream(bytes),LocalDate.of(2026,10,13),"gallery")}
        val holder=CoroutineScope(Dispatchers.IO)
        try {
            open()
            compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-preview-${row.id}"))
            compose.onNodeWithTag("photo-preview-${row.id}").performClick()
            revealPreview()
            val entered=CompletableDeferred<Unit>()
            val release=CompletableDeferred<Unit>()
            val held=holder.async {
                app.database.withTransaction {
                    entered.complete(Unit)
                    // A failing UI assertion must never leave the application writer held.
                    withTimeout(60_000) {release.await()}
                }
            }
            try {
                runBlocking {withTimeout(5_000) {entered.await()}}
                repeat(2) {
                    compose.activityRule.scenario.recreate()
                    compose.waitUntil(15_000) {compose.onAllNodesWithTag("photo-content").fetchSemanticsNodes().isNotEmpty()}
                    compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-preview-${row.id}"))
                    compose.onNodeWithTag("photo-preview-${row.id}").assertTextContains("Zwiń")
                    compose.onNodeWithText("Otwieranie zdjęcia…").assertExists()
                    compose.onNodeWithTag("photo-preview").assertDoesNotExist()
                }
            } finally {
                release.complete(Unit)
                runBlocking {withTimeout(5_000) {held.await()}}
            }
            revealPreview()
            compose.onNode(hasText("Usuń") and hasAnyAncestor(hasTestTag("photo-draft-${row.id}"))).performClick()
            compose.onNodeWithTag("photo-confirm-delete").performClick()
            compose.waitUntil(10_000) {compose.onAllNodesWithTag("photo-draft-${row.id}").fetchSemanticsNodes().isEmpty()}
            assertNull(runBlocking {app.database.photoDao().get(lease.storageScope,row.id)})
            assertEquals(before,runBlocking {app.database.dao().operationCount(lease.storageScope)})
        } finally {
            holder.cancel()
            runBlocking {if(app.database.photoDao().get(lease.storageScope,row.id)!=null) store.delete(row.id)}
        }
    }
}
