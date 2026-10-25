package pl.roseru.kalorie.sync

import android.content.Context
import androidx.room.withTransaction
import androidx.work.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.data.*
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/** Captured identity fences only; no credentials or request body in persisted work. */
data class SyncWorkTicket(val owner:String,val generation:Long,val wireContext:String,
    val policyRevision:Long?=null,val issuance:NetworkIssuance?=null) {
    init {require(owner.isNotBlank() && generation>0 && wireContext.isNotBlank());require(policyRevision==null || policyRevision>0)}
    override fun toString()="SyncWorkTicket(redacted)"
    fun data():Data=Data.Builder().putString("owner",owner).putLong("generation",generation).putString("context",wireContext)
        .apply {
            policyRevision?.let {putLong("policy_revision",it)}
            issuance?.let {putString("policy_instance",it.instanceId);putLong("policy_generation",it.generation)}
        }.build()
    fun legacyUniqueName():String="diary-sync-"+digest("$owner:$generation")
    fun uniqueName():String=legacyUniqueName()+"-context-"+digest(wireContext)+
        (policyRevision?.let {"-policy-$it"} ?: "")+(issuance?.let {"-issued-${it.instanceId}-${it.generation}"} ?: "")
    companion object {
        private fun digest(value:String)=MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString(""){"%02x".format(it)}
        fun capture(lease:OwnerLease,binding:AccountBindingEntity,permit:NetworkPermit)=
            SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),permit.revision,permit.issuance)
        fun read(data:Data):SyncWorkTicket?=try {
            val keys=data.keyValueMap.keys
            val identity=setOf("owner","generation","context")
            val stamp=setOf("policy_instance","policy_generation")
            if(keys !in setOf(identity,identity+"policy_revision",identity+stamp,identity+stamp+"policy_revision"))null
            else {
                val revision=if("policy_revision" in keys)data.getLong("policy_revision",0).also {require(it>0)} else null
                val issuance=if("policy_instance" in keys)NetworkIssuance(checkNotNull(data.getString("policy_instance")),data.getLong("policy_generation",-1)) else null
                SyncWorkTicket(checkNotNull(data.getString("owner")),data.getLong("generation",0),checkNotNull(data.getString("context")),revision,issuance)
            }
        }catch(_:IllegalArgumentException){null}catch(_:IllegalStateException){null}
    }
}

/** Scheduler operations finish inside the admission entry; no pending enqueue/cancel escapes it. */
class SyncWorkScheduler(private val work:WorkManager,private val now:()->Long=System::currentTimeMillis) {
    companion object {const val WATCH="diary-sync-watch";const val NETWORK_TAG="diary-sync-network"}
    private fun constraints()=Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
    suspend fun enqueue(ticket:SyncWorkTicket,notBeforeMillis:Long=0):OneTimeWorkRequest {
        require(ticket.policyRevision!=null && ticket.issuance!=null){"Network work requires its original issuance"}
        val delay=(notBeforeMillis-now()).coerceAtLeast(0)
        val request=OneTimeWorkRequestBuilder<DiarySyncWorker>().setInputData(ticket.data()).addTag(NETWORK_TAG)
            .setConstraints(constraints()).setInitialDelay(delay,TimeUnit.MILLISECONDS)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build()
        withContext(Dispatchers.IO) {ensureActive();work.enqueueUniqueWork(ticket.uniqueName(),ExistingWorkPolicy.APPEND_OR_REPLACE,request).result.get()}
        return request
    }
    suspend fun cancel(ticket:SyncWorkTicket)=withContext(Dispatchers.IO) {ensureActive();work.cancelUniqueWork(ticket.uniqueName()).result.get();Unit}
    suspend fun revokeScheduled(ticket:SyncWorkTicket?)=withContext(Dispatchers.IO) {
        ensureActive()
        ticket?.let {work.cancelUniqueWork(it.uniqueName()).result.get()}
        ensureActive()
        ticket?.let {work.cancelUniqueWork(it.legacyUniqueName()).result.get()}
    }
    suspend fun cancelWatch()=withContext(Dispatchers.IO) {ensureActive();work.cancelUniqueWork(WATCH).result.get();Unit}
    suspend fun installWatch()=withContext(Dispatchers.IO) {
        ensureActive()
        work.enqueueUniquePeriodicWork(WATCH,ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<DiarySyncWatchWorker>(15,TimeUnit.MINUTES).setConstraints(constraints()).build()).result.get()
        Unit
    }
}

interface SyncWorkRuntimeOwner {val syncWorkRuntime:SyncWorkRuntime}
data class SyncSessionSignal(val lease:OwnerLease?,val available:Boolean,val configured:Boolean=false) {override fun toString()="SyncSessionSignal(redacted)"}

/** All mutations, including local evidence and scheduler commits, are admitted as one entry. */
class SyncWorkRuntime(private val db:CalorieDatabase,val coordinator:SyncCoordinator,private val scheduler:SyncWorkScheduler,
    private val admission:SyncRuntimeAdmission=OpenSyncRuntimeAdmission) {
    init {admission.attach(1)}
    val networkGate:NetworkAccessGate get()=coordinator.networkGate
    private suspend fun <T> enter(block:suspend ()->T):SyncRuntimeEntry<T> = coroutineScope {admission.run(block)}
    private suspend fun outcome(block:suspend ()->SyncCoordinator.Outcome):SyncCoordinator.Outcome=when(val result=enter(block)) {
        is SyncRuntimeEntry.Admitted->result.value
        SyncRuntimeEntry.Paused->SyncCoordinator.Outcome.Stopped("validation_trial")
    }
    suspend fun current():Pair<OwnerLease,AccountBindingEntity>?=when(val result=enter {currentInside()}) {
        is SyncRuntimeEntry.Admitted->result.value
        SyncRuntimeEntry.Paused->null
    }
    private suspend fun currentInside():Pair<OwnerLease,AccountBindingEntity>?=db.withTransaction {
        // Do not initialize a guest merely to inspect background eligibility.
        val active=db.ownerDao().active()?:return@withTransaction null
        val lease=OwnerLease(active.storageScope,active.generation)
        if(db.ownerDao().byScope(lease.storageScope)?.kind!="account")return@withTransaction null
        val binding=db.bootstrapDao().binding(lease.storageScope)?:return@withTransaction null
        lease to binding
    }
    private fun ticket(lease:OwnerLease,binding:AccountBindingEntity,permit:NetworkPermit?)=
        SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),permit?.revision,
            permit?.issuance ?: networkGate.changes.value.issuance)
    private fun matches(ticket:SyncWorkTicket,lease:OwnerLease,binding:AccountBindingEntity)=
        ticket.owner==lease.storageScope && ticket.generation==lease.generation && ticket.wireContext==CanonicalMealRows.context(binding)
    private fun captured(ticket:SyncWorkTicket):NetworkPermit? {
        if(ticket.issuance==null || ticket.issuance!=networkGate.changes.value.issuance)return null
        return coordinator.captureNetworkPermit()?.takeIf {it.issuance==ticket.issuance && it.revision==ticket.policyRevision}
    }
    private suspend fun enqueueCurrent(ticket:SyncWorkTicket,at:Long,permit:NetworkPermit?) {
        if(permit==null || ticket.policyRevision!=permit.revision || ticket.issuance!=permit.issuance)return
        try {
            currentCoroutineContext().ensureActive()
            val (lease,binding)=currentInside()?:return
            if(!matches(ticket,lease,binding))return
            networkGate.requireCurrent(permit)
            scheduler.enqueue(ticket,at)
        }catch(_:NetworkAccessDenied){/* The next issuance schedules its own work. */}
        catch(_:StaleOwnerException){/* Owner changes capture their own ticket. */}
    }
    suspend fun reschedule(ticket:SyncWorkTicket,outcome:SyncCoordinator.Outcome) {enter {rescheduleInside(ticket,outcome)}}
    private suspend fun rescheduleInside(ticket:SyncWorkTicket,outcome:SyncCoordinator.Outcome) {
        val at=when(outcome) {
            is SyncCoordinator.Outcome.Deferred->outcome.epochMillis
            SyncCoordinator.Outcome.Busy->Math.addExact(System.currentTimeMillis(),30_000)
            else->return
        }
        enqueueCurrent(ticket,at,captured(ticket))
    }
    suspend fun signal(resumeBlocked:Boolean=false,expected:SyncWorkTicket?=null,resumeReasons:Set<String> = emptySet()) {
        enter {signalInside(resumeBlocked,expected,resumeReasons)}
    }
    private suspend fun signalInside(resumeBlocked:Boolean=false,expected:SyncWorkTicket?=null,resumeReasons:Set<String> = emptySet()) {
        currentCoroutineContext().ensureActive()
        val permit=coordinator.captureNetworkPermit()
        val frame=networkGate.changes.value
        val (lease,binding)=currentInside()?:return
        if(expected!=null && (!matches(expected,lease,binding) || expected.issuance!=frame.issuance ||
            permit!=null && (expected.policyRevision!=permit.revision || expected.issuance!=permit.issuance)))return
        try {
            val state=coordinator.request(lease,binding,resumeBlocked,resumeReasons,permit)
            if(permit==null)coordinator.run(lease,binding,permit=null)
            else if(state.status in setOf("ready","running","deferred","idle"))
                enqueueCurrent(ticket(lease,binding,permit),state.retryAtMillis,permit)
        }catch(_:StaleOwnerException){/* The next account event captures its own lease. */}
    }
    suspend fun manual(lease:OwnerLease):SyncCoordinator.Outcome=outcome {manualInside(lease)}
    private suspend fun manualInside(lease:OwnerLease):SyncCoordinator.Outcome=try {
        currentCoroutineContext().ensureActive()
        val permit=coordinator.captureNetworkPermit()
        val binding=db.withTransaction {
            LocalOwnerStore(db).requireCurrent(lease);db.bootstrapDao().binding(lease.storageScope)
        }
        if(binding==null)SyncCoordinator.Outcome.Stopped("bootstrap") else {
            coordinator.request(lease,binding,resumeBlocked=true,permit=permit)
            val result=coordinator.run(lease,binding,permit)
            val at=when(result) {
                is SyncCoordinator.Outcome.Deferred->result.epochMillis
                SyncCoordinator.Outcome.Busy->Math.addExact(System.currentTimeMillis(),30_000)
                else->null
            }
            if(at!=null)enqueueCurrent(ticket(lease,binding,permit),at,permit)
            result
        }
    }catch(_:StaleOwnerException){SyncCoordinator.Outcome.Stale}

    @OptIn(FlowPreview::class)
    fun observe(scope:CoroutineScope,sessions:Flow<SyncSessionSignal> = flowOf(SyncSessionSignal(null,false))):Job = scope.launch {
        launch {
            var previous=emptyMap<String,SyncQueueSignal>()
            combine(db.syncWorkDao().wakeups().distinctUntilChanged().debounce(250),admission.changes) {rows,_->rows}
                .collect {rows->
                    try {enter {
                        val current=rows.associateBy {it.operationId}
                        val changed=current.filter {(id,value)->previous[id]!=value}.values
                        val permit=coordinator.captureNetworkPermit();val stamp=permit?.issuance ?: networkGate.changes.value.issuance
                        changed.filter {it.wireContext!=null}.map {SyncWorkTicket(it.ownerScope,it.leaseGeneration,checkNotNull(it.wireContext),permit?.revision,stamp)}
                            .distinct().forEach {signalInside(expected=it)}
                        // A Paused/cancelled entry never consumes an event.
                        previous=current
                    }}catch(error:CancellationException){currentCoroutineContext().ensureActive()}
                }
        }
        var previousSession:SyncSessionSignal?=null
        var previousTicket:SyncWorkTicket?=null
        var previousAccess:NetworkAccessSnapshot?=null
        combine(db.syncWorkDao().contexts(),sessions.distinctUntilChanged(),networkGate.changes,admission.changes) {context,session,access,version->
            Triple(context,session,access) to version
        }.collect { (event,_) ->
            val (context,session,access)=event
            try {enter {
                if(access!=networkGate.changes.value)return@enter
                val permit=coordinator.captureNetworkPermit()?.takeIf {it.issuance==access.issuance}
                val target=context?.let {ticket(it.lease(),it.binding,permit)}
                if(previousAccess!=access || previousTicket?.let {target==null || it!=target}==true) {
                    scheduler.revokeScheduled(previousTicket ?: target)
                    if(permit==null)scheduler.cancelWatch()
                }
                if(access!=networkGate.changes.value)return@enter
                val loginEvent=session.available && (previousSession?.available!=true || previousSession?.lease!=session.lease)
                val configurationEvent=session.configured && previousSession?.configured!=true
                if(permit!=null) {networkGate.requireCurrent(permit);scheduler.installWatch()}
                if(context!=null && target!=null && session.lease==context.lease()) {
                    val reasons=buildSet {if(loginEvent)add("login");if(configurationEvent)add("not_configured")}
                    signalInside(expected=target,resumeReasons=reasons)
                }
                previousSession=session;previousTicket=target;previousAccess=access
            }}catch(error:CancellationException){currentCoroutineContext().ensureActive()}
            catch(_:NetworkAccessDenied){/* A newer frame reevaluates without consuming this one. */}
        }
    }
    suspend fun execute(ticket:SyncWorkTicket):SyncCoordinator.Outcome=outcome {
        currentCoroutineContext().ensureActive()
        val frame=networkGate.changes.value
        val permit=captured(ticket)
        val context=currentInside()
        if(context==null || ticket.issuance!=frame.issuance || !matches(ticket,context.first,context.second) ||
            frame.state is NetworkAccessState.Allowed && permit==null)SyncCoordinator.Outcome.Stale
        else coordinator.run(context.first,context.second,permit)
    }
}

class DiarySyncWorker internal constructor(context:Context,parameters:WorkerParameters,private val suppliedRuntime:SyncWorkRuntime?):CoroutineWorker(context,parameters) {
    constructor(context:Context,parameters:WorkerParameters):this(context,parameters,null)
    override suspend fun doWork():Result {
        val ticket=SyncWorkTicket.read(inputData)?:return Result.failure()
        val runtime=suppliedRuntime?:(applicationContext as SyncWorkRuntimeOwner).syncWorkRuntime
        val outcome=runtime.execute(ticket)
        runtime.reschedule(ticket,outcome)
        // Cancellation propagates. It neither ACKs nor recreates a frozen operation.
        return Result.success()
    }
}
class DiarySyncWatchWorker internal constructor(context:Context,parameters:WorkerParameters,private val suppliedRuntime:SyncWorkRuntime?):CoroutineWorker(context,parameters) {
    constructor(context:Context,parameters:WorkerParameters):this(context,parameters,null)
    override suspend fun doWork():Result {
        val runtime=suppliedRuntime?:(applicationContext as SyncWorkRuntimeOwner).syncWorkRuntime
        runtime.signal()
        return Result.success()
    }
}
