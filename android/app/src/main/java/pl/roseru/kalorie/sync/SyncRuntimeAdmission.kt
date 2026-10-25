package pl.roseru.kalorie.sync

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** Admission surrounds the complete runtime entry, including local ledgers and rescheduling. */
interface SyncRuntimeAdmission {
    val changes: StateFlow<Long>

    /** Called only by a runtime implementing every entry point in contract version 1. */
    fun attach(contractVersion: Int)

    /** A paused result must not write Room, enqueue work, or be retried outside this boundary. */
    suspend fun <T> run(block: suspend () -> T): SyncRuntimeEntry<T>
}

sealed interface SyncRuntimeEntry<out T> {
    data class Admitted<T>(val value: T) : SyncRuntimeEntry<T>
    data object Paused : SyncRuntimeEntry<Nothing>
}

/** The regular application never pauses synchronization for an instrumentation trial. */
object OpenSyncRuntimeAdmission : SyncRuntimeAdmission {
    override val changes: StateFlow<Long> = MutableStateFlow(0L)
    override fun attach(contractVersion: Int) { require(contractVersion == 1) }
    override suspend fun <T> run(block: suspend () -> T) = SyncRuntimeEntry.Admitted(block())
}
