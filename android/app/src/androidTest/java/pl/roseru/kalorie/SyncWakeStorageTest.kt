package pl.roseru.kalorie

import android.annotation.SuppressLint
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.*
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import androidx.work.impl.ExecutionListener
import androidx.work.impl.WorkManagerImpl
import androidx.work.impl.model.WorkGenerationalId
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.sync.*
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** Actual Room signals and WorkManager constraints; no sleeps, credentials, or external transport. */
@SuppressLint("RestrictedApi") // Pinned WorkManager2.10.5 execution completion, only in this fixture.
class SyncWakeStorageTest {
    /** Observe the real runtime outcome without replacing a worker or changing admission. */
    private class Probe:SyncRuntimeAdmission,ExecutionListener {
        override val changes:StateFlow<Long> = MutableStateFlow(0L)
        private val monitor=Any()
        private var closing=false
        private val entries=mutableSetOf<Job>()
        data class Created(val runtimeId:Int,val ticket:SyncWorkTicket?)
        val created=ConcurrentHashMap<UUID,Created>()
        val outcomes=ConcurrentLinkedQueue<SyncCoordinator.Outcome>()
        val finished=ConcurrentLinkedQueue<CompletableDeferred<Unit>>()
        private val pending=ConcurrentHashMap<WorkGenerationalId,ConcurrentLinkedQueue<CompletableDeferred<Unit>>>()
        fun constructed(parameters:WorkerParameters,active:SyncWorkRuntime) {
            val done=CompletableDeferred<Unit>()
            finished.add(done)
            pending.computeIfAbsent(WorkGenerationalId(parameters.id.toString(),parameters.generation)) {ConcurrentLinkedQueue()}.add(done)
            // These four fixtures drive each UUID at most once (including the one
            // watch tick). Refuse reuse explicitly instead of overwriting a receipt.
            check(created.putIfAbsent(parameters.id,Created(System.identityHashCode(active),SyncWorkTicket.read(parameters.inputData)))==null) {"SyncWake fixture reused a worker UUID"}
        }
        override fun onExecuted(id:WorkGenerationalId,needsReschedule:Boolean) {pending[id]?.poll()?.complete(Unit)}
        override fun attach(contractVersion:Int) {require(contractVersion==1)}
        override suspend fun <T> run(block:suspend ()->T):SyncRuntimeEntry<T> = coroutineScope {
            // Own a bounded child even if a manual caller is a JUnit runBlocking job.
            val entry=currentCoroutineContext().job
            synchronized(monitor) {
                if(closing)throw CancellationException("SyncWake fixture closing")
                entries.add(entry)
                // run's finally is earlier than completion of this ScopeCoroutine.
                // Completion includes all its children and cancellation/DB finally blocks.
                entry.invokeOnCompletion {synchronized(monitor) {entries.remove(entry)}}
            }
            currentCoroutineContext().ensureActive()
            val value=block()
            if(value is SyncCoordinator.Outcome)outcomes.add(value)
            SyncRuntimeEntry.Admitted(value)
        }
        fun closeEntries():List<Job> = synchronized(monitor) {closing=true;entries.toList()}
    }
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/wakeup",UUID.randomUUID().toString()).id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),"55555555-5555-4555-8555-555555555555",1,"2026-10-23T12:00:00Z"))
        return lease
    }
    private fun manager(probe:Probe,runtime:()->SyncWorkRuntime):WorkManager {
        val factory=object:WorkerFactory() {
            override fun createWorker(appContext:android.content.Context,workerClassName:String,parameters:WorkerParameters):ListenableWorker? {
                if(workerClassName !in setOf(DiarySyncWorker::class.java.name,DiarySyncWatchWorker::class.java.name))return null
                val active=runtime()
                probe.constructed(parameters,active)
                return when(workerClassName) {
                    DiarySyncWorker::class.java.name->DiarySyncWorker(appContext,parameters,active)
                    else->DiarySyncWatchWorker(appContext,parameters,active)
                }
            }
        }
        WorkManagerTestInitHelper.initializeTestWorkManager(context,Configuration.Builder().setExecutor(SynchronousExecutor()).setTaskExecutor(SynchronousExecutor()).setWorkerFactory(factory).build())
        return WorkManager.getInstance(context).also {(it as WorkManagerImpl).processor.addExecutionListener(probe)}
    }
    private suspend fun state(db:CalorieDatabase,lease:OwnerLease,phase:String="state condition",predicate:(SyncWorkState)->Boolean):SyncWorkState {
        try {return withTimeout(15_000) {db.syncWorkDao().observe(lease.storageScope).filterNotNull().first(predicate)}}
        catch(error:TimeoutCancellationException) {
            val last=db.syncWorkDao().state(lease.storageScope)
            throw AssertionError("SyncWake phase=$phase status=${last?.status} requested=${last?.requestedVersion} active=${last?.activeVersion} handled=${last?.handledVersion}",error)
        }
    }
    private suspend fun jobs(work:WorkManager,ticket:SyncWorkTicket,phase:String="work chain condition",predicate:(List<WorkInfo>)->Boolean):List<WorkInfo> {
        try {return withTimeout(15_000) {work.getWorkInfosForUniqueWorkFlow(ticket.uniqueName()).first(predicate)}}
        catch(error:TimeoutCancellationException) {throw AssertionError("SyncWake phase=$phase chain=${chain(work,ticket)}",error)}
    }
    private suspend fun chain(work:WorkManager,ticket:SyncWorkTicket)=withContext(Dispatchers.IO) {
        work.getWorkInfosForUniqueWork(ticket.uniqueName()).get(2,TimeUnit.SECONDS).joinToString {"${it.id}:${it.state}:delay=${it.initialDelayMillis}:attempt=${it.runAttemptCount}"}
    }
    private suspend fun close(scope:CoroutineScope,work:WorkManager,db:CalorieDatabase,probe:Probe) {
        // No observer may enqueue after cancellation, and no WorkManager coroutine may
        // touch either database after it closes. Never close another test's delegate.
        scope.coroutineContext.job.cancelAndJoin()
        // Atomically reject new execute/signal/reschedule entries before snapshotting
        // the actual runtime ScopeCoroutine jobs. Wrapper completion is not their join.
        val entries=probe.closeEntries()
        withContext(Dispatchers.IO) {work.cancelAllWork().result.get(5,TimeUnit.SECONDS)}
        withTimeout(15_000) {entries.forEach {it.join()}}
        // Independently drain wrapper post-processing before its own database closes.
        withTimeout(15_000) {probe.finished.toList().awaitAll()}
        withContext(Dispatchers.IO) {
            check(WorkManager.getInstance(context)===work)
            (work as WorkManagerImpl).processor.removeExecutionListener(probe)
            WorkManagerTestInitHelper.closeWorkDatabase()
        }
        db.close()
    }
    private suspend fun ticket(db:CalorieDatabase,lease:OwnerLease)=SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(db.bootstrapDao().binding(lease.storageScope)!!),policyRevision=1,issuance=RuntimeAllowedNetwork.captureAllowed().issuance)

    @Test fun restartKeepsOneWatchAndEligibleWriteSchedulesWorkThatWaitsForNetworkConstraint()=runBlocking<Unit> {
        val db=memory();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default);val probe=Probe();lateinit var runtime:SyncWorkRuntime;val work=manager(probe) {runtime}
        try {
            val lease=account(db);val ticket=ticket(db,lease);val calls=AtomicInteger()
            val executor=SyncStepExecutor {_,_,_->calls.incrementAndGet();SyncStepResult.LoginRequired}
            val sessions=MutableStateFlow(SyncSessionSignal(lease,false));val coordinator=SyncCoordinator(db,schema,executor,networkGate=RuntimeAllowedNetwork)
            runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work),admission=probe)
            var observer=runtime.observe(scope,sessions)
            state(db,lease,"initial observer request"){it.requestedVersion>0};val first=jobs(work,ticket,"initial constrained work"){it.isNotEmpty()}.single()
            assertEquals(WorkInfo.State.ENQUEUED,first.state);assertEquals(0,calls.get())
            val watch=withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(SyncWorkScheduler.WATCH).get()};assertEquals(1,watch.size)
            observer.cancelAndJoin()
            runtime=SyncWorkRuntime(db,SyncCoordinator(db,schema,executor,networkGate=RuntimeAllowedNetwork),SyncWorkScheduler(work),admission=probe);observer=runtime.observe(scope,sessions)
            val restarted=state(db,lease,"restarted observer request"){it.requestedVersion>1}
            assertEquals(1,withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(SyncWorkScheduler.WATCH).get()}.size)
            val restartedJobs=jobs(work,ticket,"replacement constrained work"){rows->rows.any {it.id!=first.id && it.state==WorkInfo.State.ENQUEUED}}
            val restartedIds=restartedJobs.map {it.id}.toSet()
            DiaryRepository(db,context,lease).addWeight(80.0,LocalDate.of(2026,10,21))
            state(db,lease,"eligible write request"){it.requestedVersion>restarted.requestedVersion}
            val afterWrite=jobs(work,ticket,"eligible write successor"){rows->rows.any {it.id !in restartedIds && it.id!=first.id}}
            val successor=afterWrite.single {it.id !in restartedIds && it.id!=first.id}
            // APPEND depends on the still constrained predecessor. It must not become runnable yet.
            println("restart after write: "+afterWrite.joinToString {"${it.id}:${it.state}"})
            assertEquals(WorkInfo.State.BLOCKED,successor.state)
            assertEquals(0,calls.get())
            // APPEND_OR_REPLACE may prune a cancelled predecessor; no surviving old work may run.
            val oldInfo=withContext(Dispatchers.IO){work.getWorkInfoById(first.id).get()}
            assertTrue(oldInfo==null || oldInfo.state==WorkInfo.State.CANCELLED)
            val fresh=afterWrite.first {it.id in restartedIds && it.state==WorkInfo.State.ENQUEUED}
            assertTrue(probe.outcomes.isEmpty())
            WorkManagerTestInitHelper.getTestDriver(context)!!.setAllConstraintsMet(fresh.id)
            val terminal=try {withTimeout(15_000) {work.getWorkInfoByIdFlow(fresh.id).filterNotNull().first {it.state.isFinished}}}
                catch(error:TimeoutCancellationException) {throw AssertionError("SyncWake phase=fresh worker terminal calls=${calls.get()} outcomes=${probe.outcomes.toList()} chain=${chain(work,ticket)}",error)}
            val created=probe.created[fresh.id]
            val last=db.syncWorkDao().state(lease.storageScope)
            val diagnostic="SyncWake terminal=${terminal.state} calls=${calls.get()} outcomes=${probe.outcomes.toList()} "+
                "ticketMatches=${created?.ticket==ticket} runtimeMatches=${created?.runtimeId==System.identityHashCode(runtime)} "+
                "status=${last?.status} requested=${last?.requestedVersion} retryAt=${last?.retryAtMillis} chain=${chain(work,ticket)}"
            println(diagnostic)
            assertEquals(diagnostic,WorkInfo.State.SUCCEEDED,terminal.state)
            assertEquals(diagnostic,ticket,created?.ticket)
            assertEquals(diagnostic,System.identityHashCode(runtime),created?.runtimeId)
            assertEquals(diagnostic,listOf(SyncCoordinator.Outcome.Stopped("login")),probe.outcomes.toList())
            state(db,lease,"fresh worker login after terminal WorkInfo"){it.status=="login"};assertEquals(diagnostic,1,calls.get())
            observer.cancelAndJoin()
        }finally{close(scope,work,db,probe)}
    }
    @Test fun loginStopsWriteAndPeriodicWakeUntilMatchingSessionEventResumesIt()=runBlocking<Unit> {
        val db=memory();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default);val probe=Probe();lateinit var runtime:SyncWorkRuntime;val work=manager(probe) {runtime}
        try {
            val lease=account(db);val ticket=ticket(db,lease);val calls=AtomicInteger()
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls.incrementAndGet();SyncStepResult.LoginRequired},networkGate=RuntimeAllowedNetwork)
            val sessions=MutableStateFlow(SyncSessionSignal(lease,false));runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work),admission=probe)
            runtime.observe(scope,sessions)
            val first=jobs(work,ticket){it.isNotEmpty()}.single();val driver=WorkManagerTestInitHelper.getTestDriver(context)!!
            driver.setAllConstraintsMet(first.id);val stopped=state(db,lease){it.status=="login"};assertEquals(1,calls.get())
            DiaryRepository(db,context,lease).addWeight(80.0,LocalDate.of(2026,10,21))
            val written=state(db,lease){it.requestedVersion>stopped.requestedVersion}
            assertEquals("login",written.status);assertEquals(1,calls.get())
            assertEquals(1,withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(ticket.uniqueName()).get()}.size)
            val watch=withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(SyncWorkScheduler.WATCH).get()}.single()
            driver.setAllConstraintsMet(watch.id);driver.setPeriodDelayMet(watch.id)
            val watched=state(db,lease){it.requestedVersion>written.requestedVersion};assertEquals("login",watched.status);assertEquals(1,calls.get())
            sessions.value=SyncSessionSignal(lease,true)
            val next=jobs(work,ticket){rows->rows.any {it.id!=first.id && it.state==WorkInfo.State.ENQUEUED}}.single {it.id!=first.id && it.state==WorkInfo.State.ENQUEUED}
            driver.setAllConstraintsMet(next.id)
            state(db,lease){it.status=="login" && it.requestedVersion>watched.requestedVersion};assertEquals(2,calls.get())
        }finally{close(scope,work,db,probe)}
    }
    @Test fun ownerAbaCancelsOldUniqueWorkAndOldManualOrSessionEventCannotTargetNewGeneration()=runBlocking<Unit> {
        val db=memory();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default);val probe=Probe();lateinit var runtime:SyncWorkRuntime;val work=manager(probe) {runtime}
        try {
            val a=account(db);val oldTicket=ticket(db,a);val calls=mutableListOf<OwnerLease>()
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {lease,_,_->calls+=lease;SyncStepResult.LoginRequired},networkGate=RuntimeAllowedNetwork)
            val sessions=MutableStateFlow(SyncSessionSignal(a,false));runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work),admission=probe);runtime.observe(scope,sessions)
            val old=jobs(work,oldTicket){it.isNotEmpty()}.single()
            val b=account(db);val bTicket=ticket(db,b)
            jobs(work,oldTicket){it.single().state==WorkInfo.State.CANCELLED}
            assertNull(db.syncWorkDao().state(b.storageScope));sessions.value=SyncSessionSignal(b,false)
            jobs(work,bTicket){it.isNotEmpty()}
            val owners=LocalOwnerStore(db);val again=owners.select(db.ownerDao().byScope(a.storageScope)!!.id)
            jobs(work,bTicket){it.single().state==WorkInfo.State.CANCELLED}
            sessions.value=SyncSessionSignal(again,false)
            val newTicket=ticket(db,again);val fresh=jobs(work,newTicket){it.isNotEmpty()}.single()
            val before=coordinator.state(again)!!
            runtime.signal(resumeBlocked=true,expected=oldTicket)
            assertEquals(before,coordinator.state(again));assertEquals(SyncCoordinator.Outcome.Stale,runtime.manual(a));assertTrue(calls.isEmpty())
            assertNotEquals(oldTicket.uniqueName(),newTicket.uniqueName())
            val driver=WorkManagerTestInitHelper.getTestDriver(context)!!;driver.setAllConstraintsMet(old.id);assertTrue(calls.isEmpty())
            driver.setAllConstraintsMet(fresh.id);state(db,again){it.status=="login"};assertEquals(listOf(again),calls)
        }finally{close(scope,work,db,probe)}
    }
    @Test fun configurationChangeResumesOnlyNotConfiguredAndCannotUnblockLogin()=runBlocking<Unit> {
        for(loginBlocked in listOf(false,true)) {
            val db=memory();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default);val probe=Probe();lateinit var runtime:SyncWorkRuntime;val work=manager(probe) {runtime}
            try {
                val lease=account(db);val ticket=ticket(db,lease);val calls=AtomicInteger()
                val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls.incrementAndGet();if(loginBlocked)SyncStepResult.LoginRequired else SyncStepResult.NotConfigured},networkGate=RuntimeAllowedNetwork)
                val sessions=MutableStateFlow(SyncSessionSignal(lease,loginBlocked,false));runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work),admission=probe);runtime.observe(scope,sessions)
                val first=jobs(work,ticket){it.isNotEmpty()}.single();val driver=WorkManagerTestInitHelper.getTestDriver(context)!!
                driver.setAllConstraintsMet(first.id)
                val stopped=state(db,lease){it.status in setOf("login","not_configured")};assertEquals(1,calls.get())
                sessions.value=SyncSessionSignal(lease,loginBlocked,true)
                val changed=state(db,lease){it.requestedVersion>stopped.requestedVersion}
                if(loginBlocked) {
                    assertEquals("login",changed.status);assertEquals(1,calls.get())
                    assertEquals(1,withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(ticket.uniqueName()).get()}.size)
                } else {
                    val next=jobs(work,ticket){rows->rows.any {it.id!=first.id && it.state==WorkInfo.State.ENQUEUED}}.single {it.id!=first.id && it.state==WorkInfo.State.ENQUEUED}
                    driver.setAllConstraintsMet(next.id);state(db,lease){it.status=="not_configured" && it.requestedVersion>stopped.requestedVersion};assertEquals(2,calls.get())
                }
            }finally{close(scope,work,db,probe)}
        }
    }
}
