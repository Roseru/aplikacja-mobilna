package pl.roseru.kalorie.data

import androidx.room.withTransaction
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** Local facts, not a claim that queued operations have reached the server. */
data class AccountSyncOverview(val queued:Int,val waiting:Int,val attention:Int,val legacy:Int,
    val domains:Map<String,Int>,val linked:Boolean,val requiresRecovery:Boolean,val accountBlocked:Boolean,
    val work:SyncWorkState?,val lastAppliedAt:String?,val unconfirmedWrite:Boolean,
    val retryAtMillis:Long,val unfinishedCopies:Int,val restartableCopies:Int) {
    override fun toString()="AccountSyncOverview(queued=$queued, attention=$attention)"
}

/** One owner-fenced read transaction; opening the screen performs no preparation, ACK or HTTP. */
class AccountSyncOverviewStore(private val db:CalorieDatabase) {
    fun changes():Flow<Unit> = db.invalidationTracker.createFlow("local_active_owner","account_bindings",
        "outbox","sync_work_state","server_snapshot_runs","server_diary_applications","sync_push_batches",
        "server_snapshot_access","reconciliation_pulls","snapshot_archive_receipts","reconciliation_evidence",
        "import_plans","reconciliation_batches","server_diary_records","sync_conflict_decisions")
        .map {Unit}

    suspend fun read(lease:OwnerLease):AccountSyncOverview=db.withTransaction {
        LocalOwnerStore(db).requireCurrent(lease)
        require(db.ownerDao().byScope(lease.storageScope)?.kind=="account")
        val binding=db.bootstrapDao().binding(lease.storageScope)
        val wireContext=binding?.let(CanonicalMealRows::context)
        val queue=db.serverDiaryDao().unsettled(lease.storageScope)
        val work=db.syncWorkDao().state(lease.storageScope)?.takeIf {
            wireContext!=null && it.leaseGeneration==lease.generation && it.wireContext==wireContext
        }
        val last=db.serverDiaryDao().latest(lease.storageScope)?.takeIf {it.wireContext==wireContext}
        val batches=db.pushDao().pending(lease.storageScope)
        val unfinished=db.snapshotArchiveDao().rawRuns(lease.storageScope).count {
            it.state=="pending" && db.importDao().pull(it.id)==null
        }
        AccountSyncOverview(queued=queue.size,
            waiting=queue.count {it.status in setOf("waiting_revision","waiting_timeline","waiting_profile","waiting_recovery")},
            attention=queue.count {it.status in setOf("conflict","rejected")},legacy=queue.count {it.wireFormat!="sync-v1"},
            domains=queue.groupingBy {it.entityType}.eachCount(),linked=binding!=null,requiresRecovery=binding?.requiresRecovery==true,
            accountBlocked=db.snapshotDao().access(lease.storageScope)?.blocked==true,
            work=work,lastAppliedAt=last?.appliedAt,unconfirmedWrite=batches.any {it.attempted},
            retryAtMillis=maxOf(work?.retryAtMillis?:0,batches.maxOfOrNull {it.retryAtMillis}?:0),
            unfinishedCopies=unfinished,restartableCopies=if(binding==null)0 else SnapshotMaintenanceStore(db).review(lease)?.count?:0)
    }
}
