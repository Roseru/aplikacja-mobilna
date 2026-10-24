package pl.roseru.kalorie.sync

import android.content.Context
import kotlinx.coroutines.CoroutineScope

object SyncRuntimeAdmissionFactory {
    @Suppress("UNUSED_PARAMETER")
    fun create(context: Context, scope: CoroutineScope): SyncRuntimeAdmission = OpenSyncRuntimeAdmission
}
