package pl.roseru.kalorie.photo

import android.content.Context
import android.content.pm.ApplicationInfo
import android.util.Log
import java.util.concurrent.atomic.AtomicLong

/** Debug-only phase markers. Tokens are process-local counters, never photo or owner IDs. */
internal object PhotoPreviewDiagnostics {
    enum class Phase {
        COMPOSITION_ENTER, COMPOSITION_DISPOSE, PRODUCER_START, NO_SELECTION,
        STORE_START, TX1_WAIT, TX1_ENTER, TX1_END, READ_START, READ_END,
        DECODE_START, DECODE_END, TX2_WAIT, TX2_ENTER, TX2_END, STORE_RETURN,
        STORE_CANCEL, STORE_FAILED, STORE_FINALLY, PRODUCER_RETURN,
        ASSIGN_BEGIN, ASSIGN_END, PRODUCER_CANCEL, PRODUCER_FAILED, PRODUCER_FINALLY,
        OBSERVED_LOADING, OBSERVED_READY, OBSERVED_FAILED
    }

    private val sequence = AtomicLong()
    private fun enabled(context: Context) =
        context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0

    fun request(context: Context): Long? = if (enabled(context)) sequence.incrementAndGet() else null

    fun record(context: Context, request: Long?, phase: Phase) {
        if (request != null && enabled(context)) {
            Log.d("LocalPhotoPreview", "request=$request phase=${phase.name}")
        }
    }
}
