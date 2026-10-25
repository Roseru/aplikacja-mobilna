package pl.roseru.kalorie.sync

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import java.io.File

object SyncRuntimeAdmissionFactory {
    fun create(context: Context, scope: CoroutineScope): SyncRuntimeAdmission =
        ReplayRuntimeIsolation(File(context.noBackupFilesDir, "e4-replay/runtime-fence.json"), scope)
}
