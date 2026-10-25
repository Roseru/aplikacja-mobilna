package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.withTransaction
import kotlinx.coroutines.flow.Flow
import pl.roseru.kalorie.core.sync.SyncProtocolScope
import java.util.UUID

@Entity(tableName="sync_protocol_states",primaryKeys=["ownerScope","wireContext"],
    foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT),
        ForeignKey(entity=ServerSnapshotRun::class,parentColumns=["id"],childColumns=["runId"],onDelete=ForeignKey.RESTRICT)],
    indices=[Index("runId")])
data class SyncProtocolState(val ownerScope:String,val wireContext:String,val activeScope:String,
    val phase:String,val transitionId:String,val runId:String?,val updatedAt:Long) {
    override fun toString()="SyncProtocolState(phase=$phase)"
}

@Dao interface SyncProtocolDao {
    @Query("SELECT * FROM sync_protocol_states WHERE ownerScope=:owner AND wireContext=:context")
    suspend fun state(owner:String,context:String):SyncProtocolState?
    @Query("SELECT * FROM sync_protocol_states WHERE ownerScope=:owner AND wireContext=:context")
    fun observe(owner:String,context:String):Flow<SyncProtocolState?>
    @Insert suspend fun insert(row:SyncProtocolState)
    @Update suspend fun update(row:SyncProtocolState)

    @Query("SELECT count(*) FROM sync_push_batches WHERE ownerScope=:owner AND wireContext=:context AND protocolScope='calorie-app' AND state='pending'")
    suspend fun ordinaryLegacyPending(owner:String,context:String):Int
    @Query("SELECT count(*) FROM reconciliation_batches b JOIN import_plans p ON p.id=b.planId WHERE p.targetScope=:owner AND b.wireContext=:context AND b.protocolScope='calorie-app' AND b.state IN ('pending','awaiting_snapshot')")
    suspend fun recoveryLegacyPending(owner:String,context:String):Int
    @Query("SELECT count(*) FROM server_snapshot_runs WHERE ownerScope=:owner AND accountId=:account AND accountGeneration=:generation AND syncEpoch=:epoch AND contextRevision=:revision AND leaseGeneration=:lease AND protocolScope='calorie-app' AND state='pending'")
    suspend fun legacyReadPending(owner:String,account:String,generation:Int,epoch:String,revision:Long,lease:Long):Int
    @Query("SELECT count(*) FROM server_snapshot_access a JOIN server_snapshot_runs r ON r.id=a.activeRunId WHERE a.ownerScope=:owner AND r.protocolScope='calorie-app' AND r.state='complete' AND NOT EXISTS (SELECT 1 FROM server_diary_applications d WHERE d.runId=r.id)")
    suspend fun legacyProjectionPending(owner:String):Int
    @Query("SELECT count(*) FROM import_plans WHERE id=(SELECT id FROM import_plans WHERE targetScope=:owner AND wireContext=:context AND approvedAt IS NOT NULL ORDER BY rowid DESC LIMIT 1) AND state!='complete'")
    suspend fun approvedReconciliationPending(owner:String,context:String):Int
    @Query("SELECT count(*) FROM reconciliation_pulls p JOIN server_snapshot_runs r ON r.id=p.runId WHERE p.planId=:plan AND r.protocolScope='calorie-app' AND r.state IN ('pending','complete')")
    suspend fun legacyPlanReads(plan:String):Int
}

/** Transition metadata only: never deletes/rekeys outbox, archived requests or a checkpoint. */
class SyncProtocolStore(private val db:CalorieDatabase,private val now:()->Long=System::currentTimeMillis) {
    private val owners=LocalOwnerStore(db)
    private val dao get()=db.syncProtocolDao()
    private suspend fun guard(lease:OwnerLease,expected:AccountBindingEntity) {
        owners.requireCurrent(lease)
        check(db.ownerDao().byScope(lease.storageScope)?.kind=="account")
        if(db.bootstrapDao().binding(lease.storageScope)!=expected)throw StaleOwnerException()
    }
    private fun checked(row:SyncProtocolState):SyncProtocolState {
        val scope=SyncProtocolScope.parse(row.activeScope)
        check(row.phase in setOf("draining","snapshot","active"))
        check(UUID.fromString(row.transitionId).toString()==row.transitionId)
        check((scope==SyncProtocolScope.ENERGY_V1)==(row.phase=="active"))
        check(row.phase!="active" || row.runId!=null)
        return row
    }
    suspend fun current(lease:OwnerLease,expected:AccountBindingEntity):SyncProtocolState?=db.withTransaction {
        guard(lease,expected);dao.state(lease.storageScope,CanonicalMealRows.context(expected))?.let(::checked)
    }
    private suspend fun legacyPending(lease:OwnerLease,expected:AccountBindingEntity):Boolean {
        val context=CanonicalMealRows.context(expected)
        return dao.ordinaryLegacyPending(lease.storageScope,context)>0 || dao.recoveryLegacyPending(lease.storageScope,context)>0 ||
            dao.legacyReadPending(lease.storageScope,expected.accountId,expected.accountGeneration,expected.syncEpoch,expected.contextRevision,lease.generation)>0 ||
            dao.legacyProjectionPending(lease.storageScope)>0 || dao.approvedReconciliationPending(lease.storageScope,context)>0
    }

    /** Called from the serialized sync operation, after saved local evidence has been drained.
     * Legacy pending bodies finish under their stored scope. Unfrozen outbox remains untouched.
     */
    suspend fun readScope(lease:OwnerLease,expected:AccountBindingEntity,supportsEnergy:Boolean,
        recoveryPlanId:String?=null):SyncProtocolScope=db.withTransaction {
        guard(lease,expected)
        val context=CanonicalMealRows.context(expected)
        var row=dao.state(lease.storageScope,context)?.let(::checked)
        if(row?.phase=="active" || row?.phase=="snapshot") {
            check(supportsEnergy) {"The selected protocol requires an energy-capable client"}
            return@withTransaction SyncProtocolScope.ENERGY_V1
        }
        if(!supportsEnergy)return@withTransaction SyncProtocolScope.LEGACY
        val recovery=if(expected.requiresRecovery)recoveryPlanId?.let {id->
            checkNotNull(db.importDao().plan(id)).also {plan->
                check(plan.targetScope==lease.storageScope && plan.targetAccountId==expected.accountId &&
                    plan.wireContext==context && plan.approvedAt!=null && plan.state!="complete")
            }
        }else null
        if(expected.requiresRecovery && recovery==null)return@withTransaction SyncProtocolScope.LEGACY
        if(row==null) {
            row=SyncProtocolState(lease.storageScope,context,SyncProtocolScope.LEGACY.installationId,
                "draining",UUID.randomUUID().toString(),null,now())
            dao.insert(row)
        }
        // An already started legacy reconciliation finishes as legacy. A newly approved full
        // recovery has no reusable checkpoint; it can select seven domains for its first run.
        // Its older frozen envelopes remain archived under their original scope and context.
        if(if(recovery!=null)dao.legacyPlanReads(recovery.id)>0 || dao.recoveryLegacyPending(lease.storageScope,context)>0
            else legacyPending(lease,expected))return@withTransaction SyncProtocolScope.LEGACY
        dao.update(row.copy(phase="snapshot",updatedAt=now()))
        SyncProtocolScope.ENERGY_V1
    }

    /** A legacy late page cannot become active after the transition has started its new snapshot. */
    suspend fun requireReadScope(lease:OwnerLease,expected:AccountBindingEntity,scope:SyncProtocolScope)=db.withTransaction {
        guard(lease,expected)
        val state=dao.state(lease.storageScope,CanonicalMealRows.context(expected))?.let(::checked)
        when(scope) {
            SyncProtocolScope.LEGACY->check(state==null || state.phase=="draining")
            SyncProtocolScope.ENERGY_V1->check(state?.phase in setOf("snapshot","active"))
        }
    }
    suspend fun captureRun(lease:OwnerLease,expected:AccountBindingEntity,run:ServerSnapshotRun)=db.withTransaction {
        requireReadScope(lease,expected,SyncProtocolScope.parse(run.protocolScope))
        if(run.protocolScope==SyncProtocolScope.LEGACY.installationId)return@withTransaction
        check(run.ownerScope==lease.storageScope && run.leaseGeneration==lease.generation)
        check(db.snapshotDao().run(run.id)==run && run.accountId==expected.accountId &&
            run.accountGeneration==expected.accountGeneration && run.syncEpoch==expected.syncEpoch && run.contextRevision==expected.contextRevision)
        val row=checked(checkNotNull(dao.state(lease.storageScope,CanonicalMealRows.context(expected))))
        if(row.phase=="snapshot" && row.runId!=run.id) {
            val previous=row.runId?.let {db.snapshotDao().run(it)}
            check(previous==null || previous.state!="pending" || previous.leaseGeneration!=lease.generation)
            dao.update(row.copy(runId=run.id,updatedAt=now()))
        }
    }
    /** Must share the transaction that commits the complete six-domain projection and immutable E. */
    internal suspend fun acceptProjection(lease:OwnerLease,expected:AccountBindingEntity,run:ServerSnapshotRun)=db.withTransaction {
        guard(lease,expected)
        if(run.protocolScope==SyncProtocolScope.LEGACY.installationId)return@withTransaction
        requireReadScope(lease,expected,SyncProtocolScope.ENERGY_V1)
        check(run.state=="complete" && run.ownerScope==lease.storageScope && db.snapshotDao().run(run.id)==run &&
            run.accountId==expected.accountId && run.accountGeneration==expected.accountGeneration &&
            run.syncEpoch==expected.syncEpoch && run.contextRevision==expected.contextRevision)
        val application=checkNotNull(db.serverDiaryDao().application(run.id))
        check(application.ownerScope==lease.storageScope && application.wireContext==CanonicalMealRows.context(expected))
        val row=checked(checkNotNull(dao.state(lease.storageScope,application.wireContext)))
        check(row.phase=="active" || row.runId==run.id)
        dao.update(row.copy(activeScope=SyncProtocolScope.ENERGY_V1.installationId,phase="active",runId=run.id,updatedAt=now()))
    }
}
