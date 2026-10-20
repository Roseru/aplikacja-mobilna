package pl.roseru.kalorie.session

import android.util.Log
import java.time.Instant

/** Explicitly armed from instrumentation; never exposes batch IDs, hashes, bodies or identity. */
internal object MealPushObservation {
    const val ENABLED = true
    val ack = MealPushAckGate(event = { name, run ->
        try { Log.i("O1MealPushAckGate", "event=$name run=$run utc=${Instant.now()}") }
        catch (_: RuntimeException) { }
    })

    suspend fun beforeApplyAck(batchId: String, requestHash: String) {
        ack.beforeApplyAck(batchId, requestHash)
    }

    fun record(requestHash: String, method: String, path: String, status: Int, cacheControl: String?, requestId: String?) {
        val receipt = MealPushHttpReceipt.read(method, path, status, cacheControl, requestId, Instant.now()) ?: return
        val run = ack.received(requestHash, receipt) ?: return
        try { Log.i("O1MealPushHttp", "run=$run ${receipt.format()}") } catch (_: RuntimeException) { }
    }
}
