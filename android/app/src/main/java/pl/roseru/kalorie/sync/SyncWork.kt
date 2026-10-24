package pl.roseru.kalorie.sync

import android.content.Context
import androidx.room.withTransaction
import androidx.work.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import pl.roseru.kalorie.data.*
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/** The ticket is an identity fence, never authentication. No tokens, payloads or issuer in WorkData. */
data class SyncWorkTicket(val owner:String,val generation:Long,val wireContext:String) {
    init {require(owner.isNotBlank() && generation>0 && wireContext.isNotBlank())}
    override fun toString()="SyncWorkTicket(redacted)"
    fun data():Data=workDataOf("owner" to owner,"generation" to generation,"context" to wireContext)
    fun uniqueName():String="diary-sync-"+MessageDigest.getInstance("SHA-256")
        .digest("$owner:$generation".toByteArray()).joinToString(""){"%02x".format(it)}
    companion object {
        fun read(data:Data):SyncWorkTicket?=try {
            if(data.keyValueMap.keys!=setOf("owner","generation","context"))null
            else SyncWorkTicket(checkNotNull(data.getString("owner")),data.getLong("generation",0),checkNotNull(data.getString("context")))
        }catch(_:IllegalArgumentException){null}catch(_:IllegalStateException){null}
    }
}

/** Append to one unique account/generation chain: an event during final worker commit is never lost. */
class SyncWorkScheduler(private val work:WorkManager,private val now:()->Long=System::currentTimeMillis) {
    companion object {const val WATCH="diary-sync-watch"}
    private fun constraints()=Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
    fun enqueue(ticket:SyncWorkTicket,notBeforeMillis:Long=0):OneTimeWorkRequest {
        val delay=(notBeforeMillis-now()).coerceAtLeast(0)
        val request=OneTimeWorkRequestBuilder<DiarySyncWorker>().setInputData(ticket.data())
            .setConstraints(constraints()).setInitialDelay(delay,TimeUnit.MILLISECONDS)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build()
        work.enqueueUniqueWork(ticket.uniqueName(),ExistingWorkPolicy.APPEND_OR_REPLACE,request)
        return request
    }
    fun cancel(ticket:SyncWorkTicket) {work.cancelUniqueWork(ticket.uniqueName())}
    fun installWatch() {
        work.enqueueUniquePeriodicWork(WATCH,ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<DiarySyncWatchWorker>(15,TimeUnit.MINUTES).setConstraints(constraints()).build())
    }
}

/** Application DI supplies the real O1 executor through the same coordinator used by manual sync. */
interface SyncWorkRuntimeOwner {val syncWorkRuntime:SyncWorkRuntime}
data class SyncSessionSignal(val lease:OwnerLease?,val available:Boolean,val configured:Boolean=false) {override fun toString()="SyncSessionSignal(redacted)"}
class SyncWorkRuntime(private val db:CalorieDatabase,val coordinator:SyncCoordinator,val scheduler:SyncWorkScheduler) {
    suspend fun current():Pair<pl.roseru.kalorie.data.OwnerLease,pl.roseru.kalorie.data.AccountBindingEntity>? {
        val lease=LocalOwnerStore(db).currentLease()
        if(db.ownerDao().byScope(lease.storageScope)?.kind!="account")return null
        val binding=db.bootstrapDao().binding(lease.storageScope)?:return null
        return lease to binding
    }
    suspend fun signal(resumeBlocked:Boolean=false,expected:SyncWorkTicket?=null,resumeReasons:Set<String> = emptySet()) {
        val (lease,binding)=current()?:return
        if(expected!=null && (expected.owner!=lease.storageScope || expected.generation!=lease.generation || expected.wireContext!=CanonicalMealRows.context(binding)))return
        try {
            val state=coordinator.request(lease,binding,resumeBlocked,resumeReasons)
            if(state.status !in setOf("login","reconciliation","not_configured","storage"))
                scheduler.enqueue(SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding)),state.retryAtMillis)
        }catch(_:StaleOwnerException){/* The next account event captures its own new lease. */}
    }
    suspend fun manual(lease:OwnerLease):SyncCoordinator.Outcome {return try {
        val binding=db.withTransaction {
            LocalOwnerStore(db).requireCurrent(lease);db.bootstrapDao().binding(lease.storageScope)
        }?:return SyncCoordinator.Outcome.Stopped("bootstrap")
        coordinator.request(lease,binding,resumeBlocked=true)
        val ticket=SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding))
        coordinator.run(lease,binding).also {result->
            when(result) {
                is SyncCoordinator.Outcome.Deferred->scheduler.enqueue(ticket,result.epochMillis)
                SyncCoordinator.Outcome.Busy->scheduler.enqueue(ticket,System.currentTimeMillis()+30_000)
                else->Unit
            }
        }
    }catch(_:StaleOwnerException){SyncCoordinator.Outcome.Stale}}
    @OptIn(FlowPreview::class)
    fun observe(scope:CoroutineScope,sessions:Flow<SyncSessionSignal> = flowOf(SyncSessionSignal(null,false))):Job {
        scheduler.installWatch()
        return scope.launch {
            launch {
                var previous=emptyMap<String,SyncQueueSignal>()
                db.syncWorkDao().wakeups().distinctUntilChanged().debounce(250).collect {rows->
                    val current=rows.associateBy {it.operationId}
                    val changed=current.any {(id,value)->previous[id]!=value}
                    previous=current
                    if(changed)signal()
                }
            }
            var previousSession:SyncSessionSignal?=null
            var previousTicket:SyncWorkTicket?=null
            combine(db.syncWorkDao().contexts(),sessions.distinctUntilChanged()) {context,session->context to session}
                .distinctUntilChanged().collect {(context,session)->
                    val ticket=context?.let {SyncWorkTicket(it.binding.ownerScope,it.leaseGeneration,CanonicalMealRows.context(it.binding))}
                    if(previousTicket!=null && previousTicket!!.uniqueName()!=ticket?.uniqueName())scheduler.cancel(previousTicket!!)
                    val loginEvent=session.available && (previousSession?.available!=true || previousSession?.lease!=session.lease)
                    val configurationEvent=session.configured && previousSession?.configured!=true
                    previousSession=session;previousTicket=ticket
                    if(context!=null && ticket!=null && session.lease==context.lease()) {
                        val reasons=buildSet {if(loginEvent)add("login");if(configurationEvent)add("not_configured")}
                        signal(expected=ticket,resumeReasons=reasons)
                    }
                }
        }
    }
    suspend fun execute(ticket:SyncWorkTicket):SyncCoordinator.Outcome {
        val (lease,binding)=current()?:return SyncCoordinator.Outcome.Stale
        if(lease.storageScope!=ticket.owner || lease.generation!=ticket.generation || CanonicalMealRows.context(binding)!=ticket.wireContext)
            return SyncCoordinator.Outcome.Stale
        return coordinator.run(lease,binding)
    }
}

class DiarySyncWorker internal constructor(context:Context,parameters:WorkerParameters,private val suppliedRuntime:SyncWorkRuntime?):CoroutineWorker(context,parameters) {
    constructor(context:Context,parameters:WorkerParameters):this(context,parameters,null)
    override suspend fun doWork():Result {
        val ticket=SyncWorkTicket.read(inputData)?:return Result.failure()
        val runtime=suppliedRuntime?:(applicationContext as SyncWorkRuntimeOwner).syncWorkRuntime
        when(val outcome=runtime.execute(ticket)) {
            is SyncCoordinator.Outcome.Deferred->runtime.scheduler.enqueue(ticket,outcome.epochMillis)
            SyncCoordinator.Outcome.Busy->runtime.scheduler.enqueue(ticket,System.currentTimeMillis()+30_000)
            else->Unit
        }
        // Cancellation propagates. It neither ACKs nor recreates a frozen operation.
        return Result.success()
    }
}
class DiarySyncWatchWorker internal constructor(context:Context,parameters:WorkerParameters,private val suppliedRuntime:SyncWorkRuntime?):CoroutineWorker(context,parameters) {
    constructor(context:Context,parameters:WorkerParameters):this(context,parameters,null)
    override suspend fun doWork():Result {
        val runtime=suppliedRuntime?:(applicationContext as SyncWorkRuntimeOwner).syncWorkRuntime
        // Healthy contexts pull periodically; blocked login/reconciliation stay quiet until an explicit event.
        runtime.signal()
        return Result.success()
    }
}
