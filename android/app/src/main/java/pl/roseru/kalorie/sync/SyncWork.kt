package pl.roseru.kalorie.sync

import android.content.Context
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
    fun installWatch() {
        work.enqueueUniquePeriodicWork(WATCH,ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<DiarySyncWatchWorker>(15,TimeUnit.MINUTES).setConstraints(constraints()).build())
    }
}

/** Application DI supplies the real O1 executor through the same coordinator used by manual sync. */
interface SyncWorkRuntimeOwner {val syncWorkRuntime:SyncWorkRuntime}
class SyncWorkRuntime(private val db:CalorieDatabase,val coordinator:SyncCoordinator,val scheduler:SyncWorkScheduler) {
    suspend fun current():Pair<pl.roseru.kalorie.data.OwnerLease,pl.roseru.kalorie.data.AccountBindingEntity>? {
        val lease=LocalOwnerStore(db).currentLease()
        if(db.ownerDao().byScope(lease.storageScope)?.kind!="account")return null
        val binding=db.bootstrapDao().binding(lease.storageScope)?:return null
        return lease to binding
    }
    suspend fun signal(resumeBlocked:Boolean=false) {
        val (lease,binding)=current()?:return
        try {
            val state=coordinator.request(lease,binding,resumeBlocked)
            if(state.status !in setOf("login","reconciliation","not_configured","storage"))
                scheduler.enqueue(SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding)),state.retryAtMillis)
        }catch(_:StaleOwnerException){/* The next account event captures its own new lease. */}
    }
    @OptIn(FlowPreview::class)
    fun observe(scope:CoroutineScope):Job {
        scheduler.installWatch()
        return scope.launch {
            // Conflate a transaction burst. ACK/phase invalidations cannot manufacture new write events.
            var previous=emptyMap<String,SyncQueueSignal>()
            db.syncWorkDao().wakeups().distinctUntilChanged().debounce(250).collect {rows->
                val current=rows.associateBy {it.operationId}
                val changed=current.any {(id,value)->previous[id]!=value}
                previous=current
                if(changed)signal()
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
