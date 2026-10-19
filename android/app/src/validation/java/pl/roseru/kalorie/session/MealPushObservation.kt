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
}
