package pl.roseru.kalorie

import android.graphics.Bitmap
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Text
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.photo.PhotoPreviewDiagnostics.Phase
import pl.roseru.kalorie.ui.LocalPhotoPreview
import pl.roseru.kalorie.ui.rememberLocalPhotoPreview
import java.util.concurrent.atomic.AtomicInteger

class LocalPhotoPreviewStateTest {
    @get:Rule val compose=createComposeRule()

    @Test fun readyPublicationInvalidatesScreenBeforeFirstLazyRowRead() {
        publicationBeforeLazyRow(fail=false)
    }

    @Test fun failedPublicationInvalidatesScreenBeforeFirstLazyRowRead() {
        publicationBeforeLazyRow(fail=true)
    }

    @Test fun oldDeferredReadDoesNotObservePublicationBeforeFirstLazyRowRead() {
        // Control: the previous screen delegated State.value into the row. Keep exactly
        // that observation order to prove the schedule distinguishes it from the fix.
        publicationBeforeLazyRow(fail=false,deferredControl=true)
    }

    @Test fun lateResultFromPreviousSelectionCannotReplaceCurrentPreview() {
        lateResultCannotReplaceCurrentPreview(replaceOwner=false)
    }

    @Test fun lateResultFromDisposedOwnerCannotReplaceCurrentPreview() {
        lateResultCannotReplaceCurrentPreview(replaceOwner=true)
    }

    private fun publicationBeforeLazyRow(fail:Boolean,deferredControl:Boolean=false) {
        val bitmap=Bitmap.createBitmap(2,2,Bitmap.Config.ARGB_8888)
        val owner=Any()
        val release=CompletableDeferred<Unit>()
        val published=CompletableDeferred<Unit>()
        val started=CompletableDeferred<Unit>()
        val showRow=mutableStateOf(false)
        val visible=mutableStateOf(true)
        val screenCompositions=AtomicInteger()
        val rowReads=AtomicInteger()
        val loads=AtomicInteger()
        try {
            compose.setContent {
                if(!visible.value) return@setContent
                val load:suspend (String)->Bitmap={
                    loads.incrementAndGet()
                    started.complete(Unit)
                    withContext(Dispatchers.IO) {
                        release.await()
                        if(fail) error("Synthetic preview failure")
                        bitmap
                    }
                }
                val read:()->LocalPhotoPreview=if(deferredControl) {
                    val state=produceState<LocalPhotoPreview>(LocalPhotoPreview.Loading) {
                        value=LocalPhotoPreview.Ready(load("restored-photo"))
                        published.complete(Unit)
                    }
                    val deferredRead:()->LocalPhotoPreview={state.value}
                    deferredRead
                } else {
                    val preview=rememberLocalPhotoPreview(owner,"restored-photo",0,load=load,
                        trace={if(it==Phase.ASSIGN_END) published.complete(Unit)})
                    val capturedRead:()->LocalPhotoPreview={preview}
                    capturedRead
                }
                SideEffect {screenCompositions.incrementAndGet()}
                LazyColumn {
                    if(showRow.value) item {
                        rowReads.incrementAndGet()
                        Text(when(read()) {
                            LocalPhotoPreview.Loading->"loading"
                            LocalPhotoPreview.Failed->"failed"
                            is LocalPhotoPreview.Ready->"ready"
                        })
                    }
                }
            }
            runBlocking {withTimeout(5_000) {started.await()}}
            compose.waitForIdle()
            val before=screenCompositions.get()
            assertEquals(0,rowReads.get())
            release.complete(Unit)
            runBlocking {withTimeout(5_000) {published.await()}}
            compose.waitForIdle()
            // No row has ever read preview. Publication itself must invalidate the screen;
            // otherwise an initial layout can keep Loading after the producer has finished.
            if(deferredControl) assertEquals("Deferred control must have no parent observation",before,screenCompositions.get())
            else assertTrue("Preview publication must be observed outside the lazy row",screenCompositions.get()>before)
            assertEquals(0,rowReads.get())
            compose.runOnIdle {showRow.value=true}
            compose.onNodeWithText(if(fail) "failed" else "ready").assertTextEquals(if(fail) "failed" else "ready")
            assertEquals("A late row must use the completed result without another load",1,loads.get())
        } finally {
            release.complete(Unit)
            compose.runOnIdle {visible.value=false}
            compose.waitForIdle()
            bitmap.recycle()
        }
    }

    private fun lateResultCannotReplaceCurrentPreview(replaceOwner:Boolean) {
        val oldBitmap=Bitmap.createBitmap(2,2,Bitmap.Config.ARGB_8888)
        val newBitmap=Bitmap.createBitmap(3,3,Bitmap.Config.ARGB_8888)
        val owner=mutableStateOf(Any())
        val selected=mutableStateOf("old")
        val visible=mutableStateOf(true)
        val started=CompletableDeferred<Unit>()
        val release=CompletableDeferred<Unit>()
        val finished=CompletableDeferred<Unit>()
        val loads=AtomicInteger()
        try {
            compose.setContent {
                if(!visible.value) return@setContent
                val request=loads.get()
                val preview=rememberLocalPhotoPreview(owner.value,selected.value,0,load={
                    if(loads.getAndIncrement()==0) withContext(NonCancellable) {
                        // Simulate an old decoder that returns even after cancellation.
                        started.complete(Unit)
                        release.await()
                        oldBitmap
                    } else newBitmap
                },trace={if(request==0 && it==Phase.PRODUCER_FINALLY) finished.complete(Unit)})
                Text(when(preview) {
                    LocalPhotoPreview.Loading->"loading"
                    LocalPhotoPreview.Failed->"failed"
                    is LocalPhotoPreview.Ready->"ready-${preview.bitmap.width}"
                })
            }
            runBlocking {withTimeout(5_000) {started.await()}}
            compose.runOnIdle {
                if(replaceOwner) owner.value=Any() else selected.value="new"
            }
            compose.onNodeWithText("ready-3").assertTextEquals("ready-3")
            release.complete(Unit)
            runBlocking {withTimeout(5_000) {finished.await()}}
            compose.waitForIdle()
            compose.onNodeWithText("ready-3").assertTextEquals("ready-3")
            assertEquals("Replacing a request must load once for each owner/selection",2,loads.get())
        } finally {
            release.complete(Unit)
            compose.runOnIdle {visible.value=false}
            compose.waitForIdle()
            oldBitmap.recycle()
            newBitmap.recycle()
        }
    }
}
