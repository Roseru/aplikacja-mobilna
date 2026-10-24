package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.*
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.sync.*
import java.util.UUID

/** WorkManager test scheduler plus actual Room; executor never opens a network connection. */
class SyncWorkStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/work",UUID.randomUUID().toString()).id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),"55555555-5555-4555-8555-555555555555",1,"2026-10-23T12:00:00Z"))
        return lease
    }
    private fun manager(runtime:()->SyncWorkRuntime):WorkManager {
        val factory=object:WorkerFactory() {
            override fun createWorker(appContext:android.content.Context,workerClassName:String,workerParameters:WorkerParameters):ListenableWorker?=when(workerClassName) {
                DiarySyncWorker::class.java.name->DiarySyncWorker(appContext,workerParameters,runtime())
                DiarySyncWatchWorker::class.java.name->DiarySyncWatchWorker(appContext,workerParameters,runtime())
                else->null
            }
        }
        WorkManagerTestInitHelper.initializeTestWorkManager(context,Configuration.Builder().setExecutor(SynchronousExecutor())
            .setTaskExecutor(SynchronousExecutor()).setWorkerFactory(factory).build())
        return WorkManager.getInstance(context)
    }
    private suspend fun done(work:WorkManager,id:UUID)=withTimeout(15_000) {
        work.getWorkInfoByIdFlow(id).filterNotNull().first {it.state.isFinished}
    }
    @Test fun workDataContainsOnlyCapturedIdentityAndGenerationsHaveDifferentUniqueChains() {
        val ticket=SyncWorkTicket("synthetic-owner",7,"synthetic-wire-context",policyRevision=1)
        assertEquals(setOf("owner","generation","context","policy_revision"),ticket.data().keyValueMap.keys)
        assertEquals(ticket,SyncWorkTicket.read(ticket.data()))
        assertNotEquals(ticket.uniqueName(),ticket.copy(generation=9).uniqueName())
        assertNotEquals(ticket.uniqueName(),ticket.copy(wireContext="another-context").uniqueName())
        assertNotEquals(ticket.uniqueName(),ticket.copy(policyRevision=2).uniqueName())
        assertFalse(ticket.toString().contains(ticket.owner))
        assertNull(SyncWorkTicket.read(Data.Builder().putAll(ticket.data()).putString("token","must-be-rejected").build()))
    }
    @Test fun earlySchedulerWakeCannotShortenPersistedRetryAfter()=runBlocking<Unit> {
        val db=memory();lateinit var runtime:SyncWorkRuntime;val work=manager {runtime}
        try {
            val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!;var calls=0
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls++;SyncStepResult.RetryAt(90_000)},networkGate=RuntimeAllowedNetwork,now={1_000})
            val scheduler=SyncWorkScheduler(work){1_000};runtime=SyncWorkRuntime(db,coordinator,scheduler)
            coordinator.request(lease,binding);coordinator.run(lease,binding);assertEquals(1,calls)
            val request=scheduler.enqueue(SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),policyRevision=1),90_000)
            assertEquals(89_000,request.workSpec.initialDelay)
            assertEquals(NetworkType.CONNECTED,request.workSpec.constraints.requiredNetworkType)
            val driver=WorkManagerTestInitHelper.getTestDriver(context)!!
            driver.setAllConstraintsMet(request.id);driver.setInitialDelayMet(request.id)
            assertEquals(WorkInfo.State.SUCCEEDED,done(work,request.id).state)
            assertEquals(1,calls);assertEquals(90_000,coordinator.state(lease)!!.retryAtMillis)
            val chain=withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),policyRevision=1).uniqueName()).get()}
            assertTrue(chain.any {it.id!=request.id && it.state==WorkInfo.State.ENQUEUED})
        }finally{work.cancelAllWork().result.get();db.close()}
    }
    @Test fun oldAccountGenerationWorkerCannotInvokeExecutorAfterAba()=runBlocking<Unit> {
        val db=memory();lateinit var runtime:SyncWorkRuntime;val work=manager {runtime}
        try {
            val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!;var calls=0
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls++;SyncStepResult.LoginRequired},networkGate=RuntimeAllowedNetwork)
            val scheduler=SyncWorkScheduler(work);runtime=SyncWorkRuntime(db,coordinator,scheduler)
            coordinator.request(lease,binding)
            val owners=LocalOwnerStore(db);owners.select(owners.ensureGuest().id);owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
            val request=scheduler.enqueue(SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),policyRevision=1))
            WorkManagerTestInitHelper.getTestDriver(context)!!.setAllConstraintsMet(request.id)
            assertEquals(WorkInfo.State.SUCCEEDED,done(work,request.id).state);assertEquals(0,calls)
            assertNull(db.serverDiaryDao().latest(lease.storageScope))
        }finally{work.cancelAllWork().result.get();db.close()}
    }
    @Test fun wakeDuringRunningWorkAppendsSuccessorAndCannotLoseItsRequestVersion()=runBlocking<Unit> {
        val db=memory();lateinit var runtime:SyncWorkRuntime;val work=manager {runtime}
        try {
            val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!;var calls=0
            val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls++;entered.complete(Unit);release.await();SyncStepResult.LoginRequired},networkGate=RuntimeAllowedNetwork)
            val scheduler=SyncWorkScheduler(work);runtime=SyncWorkRuntime(db,coordinator,scheduler)
            coordinator.request(lease,binding)
            val ticket=SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),policyRevision=1)
            val first=scheduler.enqueue(ticket);val driver=WorkManagerTestInitHelper.getTestDriver(context)!!
            driver.setAllConstraintsMet(first.id);withTimeout(15_000){entered.await()}
            coordinator.request(lease,binding);val second=scheduler.enqueue(ticket);driver.setAllConstraintsMet(second.id)
            assertEquals(2,coordinator.state(lease)!!.requestedVersion);assertEquals(1,calls)
            release.complete(Unit)
            assertEquals(WorkInfo.State.SUCCEEDED,done(work,first.id).state)
            assertEquals(WorkInfo.State.SUCCEEDED,done(work,second.id).state)
            assertEquals(1,calls);assertEquals(2,coordinator.state(lease)!!.requestedVersion)
        }finally{work.cancelAllWork().result.get();db.close()}
    }
    @Test fun zeroRetryAfterSchedulesDelayedSuccessorAndRestartCannotExecuteItEarly()=runBlocking<Unit> {
        val db=memory();lateinit var runtime:SyncWorkRuntime;val work=manager {runtime}
        try {
            val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!;var calls=0
            val executor=SyncStepExecutor {_,_,_->calls++;SyncStepResult.RetryAt(0)}
            val coordinator=SyncCoordinator(db,schema,executor,networkGate=RuntimeAllowedNetwork){1_000}
            val scheduler=SyncWorkScheduler(work){1_000};runtime=SyncWorkRuntime(db,coordinator,scheduler)
            coordinator.request(lease,binding)
            val ticket=SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),policyRevision=1)
            val first=scheduler.enqueue(ticket);val driver=WorkManagerTestInitHelper.getTestDriver(context)!!
            driver.setAllConstraintsMet(first.id)
            assertEquals(WorkInfo.State.SUCCEEDED,done(work,first.id).state)
            assertEquals(1,calls);assertEquals(11_000,coordinator.state(lease)!!.retryAtMillis)
            val chain=withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(ticket.uniqueName()).get()}
            val successor=chain.single {it.id!=first.id}
            assertEquals(WorkInfo.State.ENQUEUED,successor.state)
            val restarted=SyncCoordinator(db,schema,executor,networkGate=RuntimeAllowedNetwork){1_000}
            runtime=SyncWorkRuntime(db,restarted,scheduler)
            driver.setAllConstraintsMet(successor.id)
            assertEquals(WorkInfo.State.ENQUEUED,withContext(Dispatchers.IO){work.getWorkInfoById(successor.id).get()!!.state})
            assertEquals(1,calls)
            // Even a premature scheduler wake must respect the persisted Room deadline.
            driver.setInitialDelayMet(successor.id)
            assertEquals(WorkInfo.State.SUCCEEDED,done(work,successor.id).state)
            assertEquals(1,calls);assertEquals(11_000,restarted.state(lease)!!.retryAtMillis)
            val resumedChain=withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(ticket.uniqueName()).get()}
            assertTrue(resumedChain.any {it.id!=first.id && it.id!=successor.id && it.state==WorkInfo.State.ENQUEUED})
        }finally{work.cancelAllWork().result.get();db.close()}
    }
}
