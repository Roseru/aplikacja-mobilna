package pl.roseru.kalorie.data

import androidx.room.withTransaction

/** Captured decision; identifiers, page tokens and account metadata never reach presentation/logging. */
class SnapshotRestartReview internal constructor(
    internal val lease:OwnerLease,
    internal val binding:AccountBindingEntity,
    internal val runs:List<ServerSnapshotRun>
) {
    val count:Int get()=runs.size
    override fun toString()="SnapshotRestartReview(count=$count)"
}

class SnapshotMaintenanceChangedException:IllegalStateException("Stan pobierania się zmienił. Sprawdź ponownie.")

/** Local metadata only. Never acknowledges a write, clears an outbox, or starts transport. */
class SnapshotMaintenanceStore(private val db:CalorieDatabase) {
    private val owners=LocalOwnerStore(db)

    suspend fun review(lease:OwnerLease):SnapshotRestartReview?=db.withTransaction {
        owners.requireCurrent(lease)
        require(db.ownerDao().byScope(lease.storageScope)?.kind=="account")
        val binding=db.bootstrapDao().binding(lease.storageScope) ?: return@withTransaction null
        SnapshotRestartReview(lease,binding,eligible(lease,binding))
    }

    /** All captured rows are rechecked together. A changed proof or owner rolls back the whole decision. */
    suspend fun confirm(review:SnapshotRestartReview):Int=db.withTransaction {
        owners.requireCurrent(review.lease)
        val current=db.bootstrapDao().binding(review.lease.storageScope)
        if(current!=review.binding)throw SnapshotMaintenanceChangedException()
        val eligible=eligible(review.lease,review.binding).associateBy {it.id}
        if(review.runs.isEmpty() || review.runs.map {it.id}.distinct().size!=review.count ||
            review.runs.any {eligible[it.id]!=it})throw SnapshotMaintenanceChangedException()
        for(run in review.runs)db.snapshotDao().update(run.copy(state="expired"))
        // Keep pages, identities, wire queries and original rows. Normal pressure-driven archival
        // may later retain their exact digests; no eager deletion or change to conservative reserve().
        review.count
    }

    private suspend fun eligible(lease:OwnerLease,binding:AccountBindingEntity):List<ServerSnapshotRun> {
        val protected=SnapshotArchiveStore(db).requiredEvidence(lease.storageScope).toMutableSet()
        // Even draft/historical recovery evidence is excluded from this ordinary-read operation.
        for(plan in db.importDao().plans(lease.storageScope)) {
            protected+=db.snapshotArchiveDao().evidenceOrigins(plan.id)
            protected+=db.importDao().batches(plan.id).map {it.snapshotRunId}
        }
        return db.snapshotArchiveDao().rawRuns(lease.storageScope).filter {run->
            run.state=="pending" && run.id !in protected && db.importDao().pull(run.id)==null &&
                (run.leaseGeneration!=lease.generation || run.accountId!=binding.accountId ||
                    run.accountGeneration!=binding.accountGeneration || run.syncEpoch!=binding.syncEpoch ||
                    run.contextRevision!=binding.contextRevision)
        }
    }
}
