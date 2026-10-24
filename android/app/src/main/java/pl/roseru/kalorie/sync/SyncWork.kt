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

/** Identity fences only. An old serialized policy revision cannot authorize a new generation. */
data class SyncWorkTicket(val owner:String,val generation:Long,val wireContext:String,val policyRevision:Long?=null) {
    init {require(owner.isNotBlank() && generation>0 && wireContext.isNotBlank());require(policyRevision==null || policyRevision>0)}
    override fun toString()="SyncWorkTicket(redacted)"
    fun data():Data=Data.Builder().putString("owner",owner).putLong("generation",generation).putString("context",wireContext)
        .apply {policyRevision?.let {putLong("policy_revision",it)}}.build()
    fun legacyUniqueName():String="diary-sync-"+MessageDigest.getInstance("SHA-256")
        .digest("$owner:$generation".toByteArray()).joinToString(""){"%02x".format(it)}
    fun uniqueName():String=legacyUniqueName()+"-context-"+MessageDigest.getInstance("SHA-256")
        .digest(wireContext.toByteArray()).joinToString(""){"%02x".format(it)}+(policyRevision?.let {"-policy-$it"} ?: "")
    companion object {
        fun read(data:Data):SyncWorkTicket?=try {
            val keys=data.keyValueMap.keys
            if(keys!=setOf("owner","generation","context") && keys!=setOf("owner","generation","context","policy_revision"))null
            else {
                val revision=if("policy_revision" in keys)data.getLong("policy_revision",0).also {require(it>0)} else null
                SyncWorkTicket(checkNotNull(data.getString("owner")),data.getLong("generation",0),checkNotNull(data.getString("context")),revision)
            }
        }catch(_:IllegalArgumentException){null}catch(_:IllegalStateException){null}
    }
}

/** One account/generation chain per policy revision; revocation cannot cancel a newer chain. */
class SyncWorkScheduler(private val work:WorkManager,private val now:()->Long=System::currentTimeMillis) {
    companion object {const val WATCH="diary-sync-watch";const val NETWORK_TAG="diary-sync-network"}
    private fun constraints()=Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
    fun enqueue(ticket:SyncWorkTicket,notBeforeMillis:Long=0):OneTimeWorkRequest {
        require(ticket.policyRevision!=null){"Network work requires a captured policy revision"}
        val delay=(notBeforeMillis-now()).coerceAtLeast(0)
        val request=OneTimeWorkRequestBuilder<DiarySyncWorker>().setInputData(ticket.data()).addTag(NETWORK_TAG)
            .setConstraints(constraints()).setInitialDelay(delay,TimeUnit.MILLISECONDS)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build()
        work.enqueueUniqueWork(ticket.uniqueName(),ExistingWorkPolicy.APPEND_OR_REPLACE,request)
        return request
    }
    fun cancel(ticket:SyncWorkTicket) {work.cancelUniqueWork(ticket.uniqueName())}
    suspend fun revokeScheduled(ticket:SyncWorkTicket?)=withContext(Dispatchers.IO) {
        // Cancel this captured chain only: a later authorization may already have enqueued work.
        ticket?.let {work.cancelUniqueWork(it.uniqueName()).result.get()}
        ticket?.let {work.cancelUniqueWork(it.legacyUniqueName()).result.get()}
    }
    suspend fun cancelWatch()=withContext(Dispatchers.IO) {work.cancelUniqueWork(WATCH).result.get();Unit}
    fun installWatch() {
        work.enqueueUniquePeriodicWork(WATCH,ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<DiarySyncWatchWorker>(15,TimeUnit.MINUTES).setConstraints(constraints()).build())
    }
}

interface SyncWorkRuntimeOwner {val syncWorkRuntime:SyncWorkRuntime}
data class SyncSessionSignal(val lease:OwnerLease?,val available:Boolean,val configured:Boolean=false) {override fun toString()="SyncSessionSignal(redacted)"}

/** All entries derive the ONE gate from their coordinator. No provider or preference is created here. */
class SyncWorkRuntime(private val db:CalorieDatabase,val coordinator:SyncCoordinator,val scheduler:SyncWorkScheduler) {
    val networkGate:NetworkAccessGate get()=coordinator.networkGate
    suspend fun current():Pair<OwnerLease,AccountBindingEntity>?=db.withTransaction {
        val lease=LocalOwnerStore(db).currentLease()
        if(db.ownerDao().byScope(lease.storageScope)?.kind!="account")return@withTransaction null
        val binding=db.bootstrapDao().binding(lease.storageScope)?:return@withTransaction null
        lease to binding
    }
    private fun ticket(lease:OwnerLease,binding:AccountBindingEntity,permit:NetworkPermit?)=
        SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),permit?.revision)
    private fun matches(ticket:SyncWorkTicket,lease:OwnerLease,binding:AccountBindingEntity)=
        ticket.owner==lease.storageScope && ticket.generation==lease.generation && ticket.wireContext==CanonicalMealRows.context(binding)
    private suspend fun enqueueCurrent(ticket:SyncWorkTicket,at:Long,permit:NetworkPermit?) {
        if(permit==null || ticket.policyRevision!=permit.revision)return
        try {
            currentCoroutineContext().ensureActive()
            val (lease,binding)=current()?:return
            if(!matches(ticket,lease,binding))return
            networkGate.requireCurrent(permit)
            scheduler.enqueue(ticket,at)
        }catch(_:NetworkAccessDenied){/* A new Allowed event captures its own fresh permit. */}
        catch(_:StaleOwnerException){/* Owner changes schedule their own ticket. */}
    }
    suspend fun reschedule(ticket:SyncWorkTicket,outcome:SyncCoordinator.Outcome) {
        val at=when(outcome) {
            is SyncCoordinator.Outcome.Deferred->outcome.epochMillis
            SyncCoordinator.Outcome.Busy->Math.addExact(System.currentTimeMillis(),30_000)
            else->return
        }
        enqueueCurrent(ticket,at,coordinator.captureNetworkPermit())
    }
    suspend fun signal(resumeBlocked:Boolean=false,expected:SyncWorkTicket?=null,resumeReasons:Set<String> = emptySet()) {
        currentCoroutineContext().ensureActive()
        val permit=coordinator.captureNetworkPermit()
        val (lease,binding)=current()?:return
        if(expected!=null && (!matches(expected,lease,binding) || permit!=null && expected.policyRevision!=permit.revision))return
        try {
            val state=coordinator.request(lease,binding,resumeBlocked,resumeReasons,permit)
            if(permit==null) {
                // This path has no CONNECTED prerequisite and can only drain saved local evidence.
                coordinator.run(lease,binding,permit=null)
            } else if(state.status in setOf("ready","running","deferred","idle")) {
                enqueueCurrent(ticket(lease,binding,permit),state.retryAtMillis,permit)
            }
        }catch(_:StaleOwnerException){/* The next account event captures its own lease. */}
    }
    suspend fun manual(lease:OwnerLease):SyncCoordinator.Outcome {return try {
        currentCoroutineContext().ensureActive()
        val permit=coordinator.captureNetworkPermit()
        val binding=db.withTransaction {
            LocalOwnerStore(db).requireCurrent(lease);db.bootstrapDao().binding(lease.storageScope)
        }?:return SyncCoordinator.Outcome.Stopped("bootstrap")
        coordinator.request(lease,binding,resumeBlocked=true,permit=permit)
        coordinator.run(lease,binding,permit).also {result->
            val at=when(result) {
                is SyncCoordinator.Outcome.Deferred->result.epochMillis
                SyncCoordinator.Outcome.Busy->Math.addExact(System.currentTimeMillis(),30_000)
                else->null
            }
            if(at!=null)enqueueCurrent(ticket(lease,binding,permit),at,permit)
        }
    }catch(_:StaleOwnerException){SyncCoordinator.Outcome.Stale}}
    @OptIn(FlowPreview::class)
    fun observe(scope:CoroutineScope,sessions:Flow<SyncSessionSignal> = flowOf(SyncSessionSignal(null,false))):Job = scope.launch {
        launch {
            var previous=emptyMap<String,SyncQueueSignal>()
            db.syncWorkDao().wakeups().distinctUntilChanged().debounce(250).collect {rows->
                val current=rows.associateBy {it.operationId}
                val changed=current.filter {(id,value)->previous[id]!=value}.values
                previous=current
                val revision=coordinator.captureNetworkPermit()?.revision
                changed.filter {it.wireContext!=null}.map {SyncWorkTicket(it.ownerScope,it.leaseGeneration,checkNotNull(it.wireContext),revision)}
                    .distinct().forEach {signal(expected=it)}
            }
        }
        var previousSession:SyncSessionSignal?=null
        var previousTicket:SyncWorkTicket?=null
        var previousAccess:NetworkAccessState?=null
        var previousPermit:NetworkPermit?=null
        combine(db.syncWorkDao().contexts(),sessions.distinctUntilChanged(),networkGate.state) {context,session,access->Triple(context,session,access)}
            .distinctUntilChanged().collect {(context,session,access)->
                val permit=coordinator.captureNetworkPermit()?.takeIf {access is NetworkAccessState.Allowed && it.revision==access.revision}
                val target=context?.let {ticket(it.lease(),it.binding,permit)}
                val revoked=previousPermit?.let {try{networkGate.requireCurrent(it);false}catch(_:NetworkAccessDenied){true}}?:false
                val policyChanged=previousAccess!=access || revoked
                if(policyChanged || previousTicket?.let {target==null || it!=target}==true) {
                    scheduler.revokeScheduled(previousTicket ?: target)
                    if(permit==null)scheduler.cancelWatch()
                }
                val loginEvent=session.available && (previousSession?.available!=true || previousSession?.lease!=session.lease)
                val configurationEvent=session.configured && previousSession?.configured!=true
                previousSession=session;previousTicket=target;previousAccess=access;previousPermit=permit
                if(permit!=null)scheduler.installWatch()
                if(context!=null && target!=null && session.lease==context.lease()) {
                    val reasons=buildSet {if(loginEvent)add("login");if(configurationEvent)add("not_configured")}
                    signal(expected=target,resumeReasons=reasons)
                }
            }
    }
    suspend fun execute(ticket:SyncWorkTicket):SyncCoordinator.Outcome {
        currentCoroutineContext().ensureActive()
        val permit=coordinator.captureNetworkPermit()
        val (lease,binding)=current()?:return SyncCoordinator.Outcome.Stale
        if(!matches(ticket,lease,binding) || permit!=null && ticket.policyRevision!=permit.revision)return SyncCoordinator.Outcome.Stale
        return coordinator.run(lease,binding,permit)
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
