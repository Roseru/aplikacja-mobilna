package pl.roseru.kalorie.sync

import androidx.room.withTransaction
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import pl.roseru.kalorie.core.sync.SyncWireSchema
import pl.roseru.kalorie.data.*
import java.util.UUID

/** Shared manual/background state machine. Authentication and physical-send fences belong to O1. */
class SyncCoordinator(private val db:CalorieDatabase,private val schema:SyncWireSchema,
    private val executor:SyncStepExecutor,private val now:()->Long=System::currentTimeMillis) {
    companion object {
        // One application process, including multiple entry points/coordinator instances.
        private val execution=Mutex()
        private val blocked=setOf("login","reconciliation","not_configured","storage")
    }
    sealed interface Outcome {
        data class Deferred(val epochMillis:Long):Outcome
        data class Stopped(val reason:String):Outcome
        data object Complete:Outcome
        data object Busy:Outcome
        data object Stale:Outcome
    }
    private suspend fun guard(lease:OwnerLease,expected:AccountBindingEntity):AccountBindingEntity {
        LocalOwnerStore(db).requireCurrent(lease)
        check(db.ownerDao().byScope(lease.storageScope)?.kind=="account")
        val binding=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        if(CanonicalMealRows.context(binding)!=CanonicalMealRows.context(expected))throw StaleOwnerException()
        return binding
    }
    private fun matches(state:SyncWorkState,lease:OwnerLease,binding:AccountBindingEntity)=
        state.leaseGeneration==lease.generation && state.wireContext==CanonicalMealRows.context(binding)
    private suspend fun lowerBound(owner:String,state:SyncWorkState)=maxOf(state.retryAtMillis,
        db.pushDao().pending(owner).maxOfOrNull {it.retryAtMillis}?:0)
    private fun initial(lease:OwnerLease,binding:AccountBindingEntity,previous:SyncWorkState?)=SyncWorkState(
        lease.storageScope,lease.generation,CanonicalMealRows.context(binding),UUID.randomUUID().toString(),"pull_before","ready",
        previous?.retryAtMillis?:0,0,previous?.requestedVersion?:0,0,previous?.handledVersion?:0,0,0,now())

    /** Capture a causal boundary once per block; an old completed plan cannot release a new block. */
    private suspend fun blockReconciliation(state:SyncWorkState)=state.copy(status="reconciliation",
        reconciliationBaseline=if(state.status=="reconciliation" && state.reconciliationBaseline!=null)state.reconciliationBaseline
            else db.syncWorkDao().completionSequence(state.ownerScope,state.wireContext))
    private suspend fun recover(state:SyncWorkState,current:AccountBindingEntity):SyncWorkState {
        if(current.requiresRecovery)return blockReconciliation(state)
        val baseline=state.reconciliationBaseline
        // Migrated healthy blocks have no known causal boundary: fail closed until explicit manual action.
        if(state.status!="reconciliation" || baseline==null ||
            !db.syncWorkDao().completedAfter(state.ownerScope,state.wireContext,baseline))return state
        return state.copy(status="ready",phase="pull_before",activeVersion=0,cycleId=UUID.randomUUID().toString(),
            acknowledged=0,refused=0,reconciliationBaseline=null)
    }
    /** Explicit/manual or an eligible-write signal. Neither can shorten a stored Retry-After. */
    suspend fun request(lease:OwnerLease,binding:AccountBindingEntity,resumeBlocked:Boolean=false,resumeReasons:Set<String> = emptySet()):SyncWorkState=db.withTransaction {
        val current=guard(lease,binding);val old=db.syncWorkDao().state(lease.storageScope)
        var state=if(old!=null && matches(old,lease,current))old else initial(lease,current,old)
        state=recover(state,current)
        val status=when {
            current.requiresRecovery->"reconciliation"
            state.status in blocked && !resumeBlocked && (state.status=="reconciliation" || state.status !in resumeReasons)->state.status
            else->"ready"
        }
        state=state.copy(requestedVersion=Math.addExact(state.requestedVersion,1),retryAtMillis=lowerBound(lease.storageScope,state),
            status=status,reconciliationBaseline=if(status=="reconciliation")state.reconciliationBaseline else null,updatedAtMillis=now())
        db.syncWorkDao().save(state);state
    }
    suspend fun state(lease:OwnerLease):SyncWorkState?=db.withTransaction {
        LocalOwnerStore(db).requireCurrent(lease);db.syncWorkDao().state(lease.storageScope)
    }
    private suspend fun remaining(owner:String)=db.syncWorkDao().remaining(owner)
    private suspend fun save(lease:OwnerLease,binding:AccountBindingEntity,change:suspend (SyncWorkState)->SyncWorkState):SyncWorkState=db.withTransaction {
        guard(lease,binding);val state=checkNotNull(db.syncWorkDao().state(lease.storageScope))
        if(!matches(state,lease,binding))throw StaleOwnerException()
        change(state).copy(updatedAtMillis=now()).also {db.syncWorkDao().save(it)}
    }
    private suspend fun stop(lease:OwnerLease,binding:AccountBindingEntity,reason:String):Outcome {
        save(lease,binding){if(reason=="reconciliation")blockReconciliation(it) else it.copy(status=reason,reconciliationBaseline=null)};return Outcome.Stopped(reason)
    }
    private suspend fun defer(lease:OwnerLease,binding:AccountBindingEntity,at:Long,failed:Boolean=false,resumePhase:String?=null):Outcome {
        val state=save(lease,binding){it.copy(status="deferred",phase=resumePhase ?: it.phase,retryAtMillis=maxOf(it.retryAtMillis,at),
            consecutiveFailures=if(failed)(it.consecutiveFailures+1).coerceAtMost(30) else it.consecutiveFailures)}
        return Outcome.Deferred(state.retryAtMillis)
    }
    private fun backoff(failures:Int):Long=10_000L*(1L shl failures.coerceIn(0,11))

    suspend fun run(lease:OwnerLease,binding:AccountBindingEntity):Outcome {
        if(!execution.tryLock())return Outcome.Busy
        try {
            var state=db.withTransaction {
                val current=guard(lease,binding);val old=db.syncWorkDao().state(lease.storageScope)
                if(old==null || !matches(old,lease,current))return@withTransaction null
                val recovered=recover(old,current)
                val value=recovered.copy(retryAtMillis=lowerBound(lease.storageScope,recovered))
                db.syncWorkDao().save(value);value
            } ?: return Outcome.Stale
            if(state.status in blocked)return Outcome.Stopped(state.status)
            if(state.retryAtMillis>now())return Outcome.Deferred(state.retryAtMillis)
            if(state.status=="idle" && state.requestedVersion<=state.handledVersion)return Outcome.Complete
            if(state.activeVersion==0L || state.status=="idle")state=save(lease,binding) {
                it.copy(activeVersion=it.requestedVersion,phase="pull_before",status="running",acknowledged=0,refused=0)
            }
            // Bounded slice; a new durable job continues the exact saved phase, with no busy loop.
            repeat(32) {
                db.withTransaction {guard(lease,binding)}
                val step=if(state.phase=="push")SyncStep.PUSH else SyncStep.PULL
                val result=executor.executeSyncStep(lease,binding,step)
                // A late response for A->B->A cannot move this machine or apply a projection.
                db.withTransaction {guard(lease,binding)}
                when(result) {
                    is SyncStepResult.Completed->{
                        require(result.acknowledged>=0 && result.refused>=0)
                        if(step==SyncStep.PULL) {
                            val run=checkNotNull(result.runId){"Completed pull requires a validated run"}
                            val active=ServerSnapshotStore(db,pl.roseru.kalorie.core.sync.SnapshotProtocol(schema)).active(lease)
                            check(active?.id==run){"Completed pull is not the current complete copy"}
                            ServerDiaryStore(db,schema).apply(lease,run)
                        }
                        state=save(lease,binding) {current->
                            when(current.phase) {
                                "pull_before"->current.copy(phase="push",status="running",consecutiveFailures=0)
                                "push"->current.copy(phase="pull_after",status="running",acknowledged=Math.addExact(current.acknowledged,result.acknowledged),
                                    refused=Math.addExact(current.refused,result.refused))
                                "pull_after"->current.copy(status="running")
                                else->error("Unknown durable sync phase")
                            }
                        }
                        if(step==SyncStep.PULL && state.phase=="pull_after") {
                            val pending=db.withTransaction {guard(lease,binding);remaining(lease.storageScope)}
                            // This completed pull supplies the checkpoint for the next push attempt.
                            if(pending>0 && state.acknowledged==0 && state.refused==0)
                                return defer(lease,binding,Math.addExact(now(),backoff(state.consecutiveFailures)),true,resumePhase="push")
                            state=db.withTransaction {
                                guard(lease,binding)
                                val current=checkNotNull(db.syncWorkDao().state(lease.storageScope))
                                // Queue emptiness and version acknowledgement belong to the same transaction.
                                val again=remaining(lease.storageScope)>0 || current.requestedVersion>current.activeVersion
                                current.copy(phase="pull_before",status=if(again)"running" else "idle",cycleId=if(again)UUID.randomUUID().toString() else current.cycleId,
                                    handledVersion=current.activeVersion,activeVersion=if(again)current.requestedVersion else current.activeVersion,
                                    acknowledged=if(again)0 else current.acknowledged,refused=if(again)0 else current.refused,updatedAtMillis=now())
                                    .also {db.syncWorkDao().save(it)}
                            }
                            if(state.status=="idle")return Outcome.Complete
                        }
                    }
                    is SyncStepResult.RetryAt->return defer(lease,binding,
                        maxOf(result.epochMillis,Math.addExact(now(),backoff(state.consecutiveFailures))),true)
                    SyncStepResult.Busy->return defer(lease,binding,Math.addExact(now(),30_000))
                    SyncStepResult.TransientFailure->return defer(lease,binding,Math.addExact(now(),backoff(state.consecutiveFailures)),true)
                    SyncStepResult.LoginRequired->return stop(lease,binding,"login")
                    is SyncStepResult.ReconciliationRequired->return stop(lease,binding,"reconciliation")
                    SyncStepResult.NotConfigured->return stop(lease,binding,"not_configured")
                    SyncStepResult.StaleContext->return Outcome.Stale
                }
            }
            return defer(lease,binding,Math.addExact(now(),1_000))
        }catch(error:CancellationException){throw error}
        catch(_:StaleOwnerException){return Outcome.Stale}
        catch(_:SnapshotCapacityException){return try{stop(lease,binding,"storage")}catch(_:StaleOwnerException){Outcome.Stale}}
        catch(_:Exception){
            return try {
                val failures=db.syncWorkDao().state(lease.storageScope)?.consecutiveFailures?:0
                defer(lease,binding,Math.addExact(now(),backoff(failures)),true)
            }catch(_:StaleOwnerException){Outcome.Stale}
        }
        finally {execution.unlock()}
    }
}
