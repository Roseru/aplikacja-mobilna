package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.*
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.sync.*
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Actual Room signals and WorkManager constraints; no sleeps, credentials, or external transport. */
class SyncWakeStorageTest {
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
    private fun manager(runtime:()->SyncWorkRuntime):WorkManager {
        val factory=object:WorkerFactory() {
            override fun createWorker(appContext:android.content.Context,workerClassName:String,parameters:WorkerParameters):ListenableWorker?=when(workerClassName) {
                DiarySyncWorker::class.java.name->DiarySyncWorker(appContext,parameters,runtime())
                DiarySyncWatchWorker::class.java.name->DiarySyncWatchWorker(appContext,parameters,runtime())
                else->null
            }
        }
        WorkManagerTestInitHelper.initializeTestWorkManager(context,Configuration.Builder().setExecutor(SynchronousExecutor()).setTaskExecutor(SynchronousExecutor()).setWorkerFactory(factory).build())
        return WorkManager.getInstance(context)
    }
    private suspend fun state(db:CalorieDatabase,lease:OwnerLease,predicate:(SyncWorkState)->Boolean)=withTimeout(15_000) {
        db.syncWorkDao().observe(lease.storageScope).filterNotNull().first(predicate)
    }
    private suspend fun jobs(work:WorkManager,ticket:SyncWorkTicket,predicate:(List<WorkInfo>)->Boolean)=withTimeout(15_000) {
        work.getWorkInfosForUniqueWorkFlow(ticket.uniqueName()).first(predicate)
    }
    private suspend fun ticket(db:CalorieDatabase,lease:OwnerLease)=SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(db.bootstrapDao().binding(lease.storageScope)!!),policyRevision=1)

    @Test fun restartKeepsOneWatchAndEligibleWriteSchedulesWorkThatWaitsForNetworkConstraint()=runBlocking<Unit> {
        val db=memory();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default);lateinit var runtime:SyncWorkRuntime;val work=manager {runtime}
        try {
            val lease=account(db);val ticket=ticket(db,lease);val calls=AtomicInteger()
            val executor=SyncStepExecutor {_,_,_->calls.incrementAndGet();SyncStepResult.LoginRequired}
            val sessions=MutableStateFlow(SyncSessionSignal(lease,false));val coordinator=SyncCoordinator(db,schema,executor,networkGate=RuntimeAllowedNetwork)
            runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work))
            var observer=runtime.observe(scope,sessions)
            state(db,lease){it.requestedVersion>0};val first=jobs(work,ticket){it.isNotEmpty()}.single()
            assertEquals(WorkInfo.State.ENQUEUED,first.state);assertEquals(0,calls.get())
            val watch=withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(SyncWorkScheduler.WATCH).get()};assertEquals(1,watch.size)
            observer.cancelAndJoin()
            runtime=SyncWorkRuntime(db,SyncCoordinator(db,schema,executor,networkGate=RuntimeAllowedNetwork),SyncWorkScheduler(work));observer=runtime.observe(scope,sessions)
            val restarted=state(db,lease){it.requestedVersion>1}
            assertEquals(1,withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(SyncWorkScheduler.WATCH).get()}.size)
            val restartedJobs=jobs(work,ticket){rows->rows.any {it.id!=first.id && it.state==WorkInfo.State.ENQUEUED}}
            val restartedIds=restartedJobs.map {it.id}.toSet()
            DiaryRepository(db,context,lease).addWeight(80.0,LocalDate.of(2026,10,21))
            state(db,lease){it.requestedVersion>restarted.requestedVersion}
            val afterWrite=jobs(work,ticket){rows->rows.any {it.id !in restartedIds && it.id!=first.id}}
            val successor=afterWrite.single {it.id !in restartedIds && it.id!=first.id}
            // APPEND depends on the still constrained predecessor. It must not become runnable yet.
            println("restart after write: "+afterWrite.joinToString {"${it.id}:${it.state}"})
            assertEquals(WorkInfo.State.BLOCKED,successor.state)
            assertEquals(0,calls.get())
            // APPEND_OR_REPLACE may prune a cancelled predecessor; no surviving old work may run.
            val oldInfo=withContext(Dispatchers.IO){work.getWorkInfoById(first.id).get()}
            assertTrue(oldInfo==null || oldInfo.state==WorkInfo.State.CANCELLED)
            val fresh=afterWrite.first {it.id in restartedIds && it.state==WorkInfo.State.ENQUEUED}
            WorkManagerTestInitHelper.getTestDriver(context)!!.setAllConstraintsMet(fresh.id)
            state(db,lease){it.status=="login"};assertEquals(1,calls.get())
            observer.cancelAndJoin()
        }finally{scope.cancel();work.cancelAllWork().result.get();db.close()}
    }
    @Test fun loginStopsWriteAndPeriodicWakeUntilMatchingSessionEventResumesIt()=runBlocking<Unit> {
        val db=memory();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default);lateinit var runtime:SyncWorkRuntime;val work=manager {runtime}
        try {
            val lease=account(db);val ticket=ticket(db,lease);val calls=AtomicInteger()
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls.incrementAndGet();SyncStepResult.LoginRequired},networkGate=RuntimeAllowedNetwork)
            val sessions=MutableStateFlow(SyncSessionSignal(lease,false));runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work))
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
        }finally{scope.cancel();work.cancelAllWork().result.get();db.close()}
    }
    @Test fun ownerAbaCancelsOldUniqueWorkAndOldManualOrSessionEventCannotTargetNewGeneration()=runBlocking<Unit> {
        val db=memory();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default);lateinit var runtime:SyncWorkRuntime;val work=manager {runtime}
        try {
            val a=account(db);val oldTicket=ticket(db,a);val calls=mutableListOf<OwnerLease>()
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {lease,_,_->calls+=lease;SyncStepResult.LoginRequired},networkGate=RuntimeAllowedNetwork)
            val sessions=MutableStateFlow(SyncSessionSignal(a,false));runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work));runtime.observe(scope,sessions)
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
        }finally{scope.cancel();work.cancelAllWork().result.get();db.close()}
    }
    @Test fun configurationChangeResumesOnlyNotConfiguredAndCannotUnblockLogin()=runBlocking<Unit> {
        for(loginBlocked in listOf(false,true)) {
            val db=memory();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default);lateinit var runtime:SyncWorkRuntime;val work=manager {runtime}
            try {
                val lease=account(db);val ticket=ticket(db,lease);val calls=AtomicInteger()
                val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls.incrementAndGet();if(loginBlocked)SyncStepResult.LoginRequired else SyncStepResult.NotConfigured},networkGate=RuntimeAllowedNetwork)
                val sessions=MutableStateFlow(SyncSessionSignal(lease,loginBlocked,false));runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work));runtime.observe(scope,sessions)
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
            }finally{scope.cancel();work.cancelAllWork().result.get();db.close()}
        }
    }
}
