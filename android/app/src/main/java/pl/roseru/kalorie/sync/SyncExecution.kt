package pl.roseru.kalorie.sync

import pl.roseru.kalorie.data.AccountBindingEntity
import pl.roseru.kalorie.data.OwnerLease

/** No credentials or UI text in durable orchestration. Session execution remains owned by O1. */
enum class SyncStep { PULL, PUSH }
enum class ReconciliationStep { FULL_SNAPSHOT_RECEIPTS, PUSH_APPROVED }
sealed interface SyncStepResult {
    data class Completed(val runId:String?=null,val batchId:String?=null,val acknowledged:Int=0,val refused:Int=0):SyncStepResult
    data object Busy:SyncStepResult
    data class RetryAt(val epochMillis:Long):SyncStepResult {init {require(epochMillis>=0)}}
    data object TransientFailure:SyncStepResult
    data object NotConfigured:SyncStepResult
    data object LoginRequired:SyncStepResult
    data class ReconciliationRequired(val code:String):SyncStepResult
    data object StaleContext:SyncStepResult
}
fun interface SyncStepExecutor {
    suspend fun executeSyncStep(expectedLease:OwnerLease,expectedContext:AccountBindingEntity,step:SyncStep):SyncStepResult
}
fun interface ReconciliationStepExecutor {
    suspend fun runReconciliationStep(expectedLease:OwnerLease,expectedContext:AccountBindingEntity,
        planId:String,step:ReconciliationStep):SyncStepResult
}
