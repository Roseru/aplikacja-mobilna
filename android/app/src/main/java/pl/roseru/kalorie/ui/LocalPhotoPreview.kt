package pl.roseru.kalorie.ui

import android.graphics.Bitmap
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.runtime.produceState
import kotlinx.coroutines.CancellationException
import pl.roseru.kalorie.photo.PhotoPreviewDiagnostics.Phase

internal sealed interface LocalPhotoPreview {
    data object Loading:LocalPhotoPreview
    data object Failed:LocalPhotoPreview
    data class Ready(val bitmap:Bitmap):LocalPhotoPreview
}

/** Observe in the screen composition before the producer starts, including when its lazy row
 * is not composed yet. Returning a value keeps a late subcomposition from being the first
 * observer of a state that a fast restored preview has already updated. */
@Composable
internal fun rememberLocalPhotoPreview(owner:Any,selected:String?,attempt:Int,
    load:suspend (String)->Bitmap,trace:(Phase)->Unit={}):LocalPhotoPreview {
    val state=key(owner,selected,attempt) {
        produceState<LocalPhotoPreview>(LocalPhotoPreview.Loading) {
            trace(Phase.PRODUCER_START)
            try {
                if(selected==null) trace(Phase.NO_SELECTION)
                else {
                    val result=try {
                        val bitmap=load(selected)
                        trace(Phase.PRODUCER_RETURN)
                        LocalPhotoPreview.Ready(bitmap)
                    } catch(error:CancellationException) {trace(Phase.PRODUCER_CANCEL);throw error}
                    catch(_:Exception) {trace(Phase.PRODUCER_FAILED);LocalPhotoPreview.Failed}
                    trace(Phase.ASSIGN_BEGIN)
                    value=result
                    trace(Phase.ASSIGN_END)
                }
            } finally {
                trace(Phase.PRODUCER_FINALLY)
            }
        }
    }
    // Do not delegate this read into LazyColumn's item lambda. The screen must observe it
    // before apply starts the producer, and pass the resulting immutable value to the row.
    return state.value
}
