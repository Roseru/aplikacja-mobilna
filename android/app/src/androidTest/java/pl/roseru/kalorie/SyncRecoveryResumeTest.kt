package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.*
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.sync.*
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Real B finalization while the watcher is absent, then file Room reopen and fresh runtime. */
class SyncRecoveryResumeTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun uuid()=UUID.randomUUID().toString()
    private fun open(name:String)=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
    private fun page()=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-recovery")
        .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-checkpoint").put("server_time","2026-10-23T14:00:00Z")
        .put("goal_timeline_revision",0).put("entities",JSONArray()).put("operation_receipts",JSONArray())
        .put("recovery_mappings",JSONArray()).toString().toByteArray()
    private data class Fixture(val lease:OwnerLease,val binding:AccountBindingEntity,val plan:String,
        val frozen:SyncPushBatch,val original:OutboxEntity,val privateWeight:WeightEntity)
    private suspend fun prepare(db:CalorieDatabase):Fixture {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val privateWeight=WeightEntity("guest-original","guest","2001-01-02","2001-01-02T12:00:00Z","UTC",70.123456789)
        db.dao().saveWeight(privateWeight)
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/causal",uuid()).id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-23T12:00:00Z"))
        val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));assertNull(snapshots.apply(snapshots.begin(lease),page()))
        DiaryRepository(db,context,lease).addWeight(80.125,LocalDate.of(2001,1,2))
        val push=MealPushStore(db,schema);val request=push.prepare(lease)!!;push.markAttempted(request)
        val original=db.dao().operation(request.operations.single().operationId)!!
        push.requireReconciliation(request)
        val old=db.bootstrapDao().binding(lease.storageScope)!!
        val binding=bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(old.accountId,epoch,1,"2026-10-23T13:00:00Z"))
        assertTrue(binding.requiresRecovery)
        val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->error("Recovery must not send")},networkGate=RuntimeAllowedNetwork) {1000L}
        val blocked=coordinator.request(lease,binding);assertEquals("reconciliation",blocked.status)
        assertEquals(0L,blocked.reconciliationBaseline)
        db.syncWorkDao().save(blocked.copy(retryAtMillis=90000L,phase="push",activeVersion=blocked.requestedVersion))
        val store=ReconciliationStore(db,schema);val plan=store.begin(lease,binding)
        store.approve(lease,binding,plan.planId,plan.account,plan.issuer,plan.subject)
        val proof=store.nextSnapshot(lease,binding,plan.planId)!!;assertNull(snapshots.apply(proof,page()))
        store.acceptCompletedSnapshot(lease,binding,plan.planId,proof.runId)
        val row=db.importDao().sources(plan.planId).single()
        store.decide(lease,binding,plan.planId,row.entityType,row.sourceId,row.sourceHash,"{\"choice\":\"preserve_local\"}")
        return Fixture(lease,binding,plan.planId,db.pushDao().batch(request.id)!!,original,privateWeight)
    }
    private suspend fun preserved(db:CalorieDatabase,f:Fixture) {
        val frozen=db.pushDao().batch(f.frozen.id)!!
        assertEquals(f.frozen.requestJson,frozen.requestJson);assertEquals(f.frozen.requestHash,frozen.requestHash)
        assertEquals("archived_reconciled",frozen.state)
        val operation=db.dao().operation(f.original.operationId)!!
        assertEquals("local_only",operation.status);assertEquals(f.original.wireJson,operation.wireJson)
        assertEquals(f.original.copy(status="local_only"),operation)
        assertEquals(f.privateWeight,db.dao().weight(f.privateWeight.id,"guest"))
        assertEquals(80.125,db.dao().weight(f.original.entityId,f.lease.storageScope)!!.kg,0.0)
        assertEquals("retained",db.importDao().sources(f.plan).single().state)
        assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
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
    private suspend fun state(db:CalorieDatabase,lease:OwnerLease,predicate:(SyncWorkState)->Boolean)=withTimeout(15000) {
        db.syncWorkDao().observe(lease.storageScope).filterNotNull().first(predicate)
    }
    @Test fun realFinishWhileWatcherStoppedResumesAfterFileReopenAndPreservesRetryFloorAndHistory()=runBlocking<Unit> {
        val name="causal-positive-${uuid()}";var db=open(name);val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        lateinit var runtime:SyncWorkRuntime;val work=manager {runtime};val calls=AtomicInteger();var now=1000L
        try {
            val f=prepare(db);val previous=db.syncWorkDao().state(f.lease.storageScope)!!
            ReconciliationStore(db,schema).finish(f.lease,f.binding,f.plan)
            val healthy=db.bootstrapDao().binding(f.lease.storageScope)!!
            assertFalse(healthy.requiresRecovery);assertEquals(CanonicalMealRows.context(f.binding),CanonicalMealRows.context(healthy))
            assertEquals(1L,db.syncWorkDao().completionSequence(f.lease.storageScope,previous.wireContext));preserved(db,f)
            db.close();db=open(name)
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls.incrementAndGet();SyncStepResult.LoginRequired},networkGate=RuntimeAllowedNetwork) {now}
            runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work){now})
            val observer=runtime.observe(scope,flowOf(SyncSessionSignal(f.lease,true,true)))
            val resumed=state(db,f.lease){it.requestedVersion>previous.requestedVersion}
            assertEquals("ready",resumed.status);assertEquals("pull_before",resumed.phase);assertEquals(0L,resumed.activeVersion)
            assertNull(resumed.reconciliationBaseline);assertEquals(90000L,resumed.retryAtMillis);assertEquals(0,calls.get())
            val ticket=SyncWorkTicket(f.lease.storageScope,f.lease.generation,previous.wireContext,policyRevision=1,issuance=RuntimeAllowedNetwork.captureAllowed().issuance)
            withTimeout(15000){work.getWorkInfosForUniqueWorkFlow(ticket.uniqueName()).first {it.isNotEmpty()}}
            assertEquals(SyncCoordinator.Outcome.Deferred(90000L),runtime.execute(ticket));assertEquals(0,calls.get())
            now=90000L
            val job=withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(ticket.uniqueName()).get()}.single()
            val driver=WorkManagerTestInitHelper.getTestDriver(context)!!;driver.setInitialDelayMet(job.id);driver.setAllConstraintsMet(job.id)
            state(db,f.lease){it.status=="login"};assertEquals(1,calls.get());preserved(db,f)
            observer.cancelAndJoin()
        }finally {scope.cancel();work.cancelAllWork().result.get();db.close();context.deleteDatabase(name)}
    }
    @Test fun oldCompletedPlanCannotReleaseNewOrdinaryConflictAfterRestartOrExplicitRecoveryReason()=runBlocking<Unit> {
        val name="causal-negative-${uuid()}";var db=open(name);val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        lateinit var runtime:SyncWorkRuntime;val work=manager {runtime};val calls=AtomicInteger()
        try {
            val f=prepare(db);ReconciliationStore(db,schema).finish(f.lease,f.binding,f.plan)
            val healthy=db.bootstrapDao().binding(f.lease.storageScope)!!
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls.incrementAndGet();SyncStepResult.ReconciliationRequired("conflict")},networkGate=RuntimeAllowedNetwork) {90000L}
            coordinator.request(f.lease,healthy)
            assertEquals(SyncCoordinator.Outcome.Stopped("reconciliation"),coordinator.run(f.lease,healthy))
            val blocked=db.syncWorkDao().state(f.lease.storageScope)!!;assertEquals(1L,blocked.reconciliationBaseline);assertEquals(1,calls.get())
            ReconciliationStore(db,schema).finish(f.lease,healthy,f.plan) // Genuine idempotent B replay must not mint a new sequence.
            assertEquals(1L,db.syncWorkDao().completionSequence(f.lease.storageScope,blocked.wireContext))
            db.close();db=open(name)
            runtime=SyncWorkRuntime(db,SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls.incrementAndGet();SyncStepResult.LoginRequired},networkGate=RuntimeAllowedNetwork) {90000L},SyncWorkScheduler(work){90000L})
            val observer=runtime.observe(scope,flowOf(SyncSessionSignal(f.lease,true,true)))
            val restarted=state(db,f.lease){it.requestedVersion>blocked.requestedVersion};assertEquals("reconciliation",restarted.status)
            runtime.signal(resumeReasons=setOf("reconciliation","login","not_configured"))
            runtime.signal() // The periodic watch uses this same durable entry.
            val ticket=SyncWorkTicket(f.lease.storageScope,f.lease.generation,blocked.wireContext,policyRevision=1,issuance=RuntimeAllowedNetwork.captureAllowed().issuance)
            assertEquals(SyncCoordinator.Outcome.Stopped("reconciliation"),runtime.execute(ticket));assertEquals(1,calls.get())
            assertTrue(withContext(Dispatchers.IO){work.getWorkInfosForUniqueWork(ticket.uniqueName()).get()}.isEmpty())
            assertEquals(1L,db.syncWorkDao().state(f.lease.storageScope)!!.reconciliationBaseline);preserved(db,f)
            observer.cancelAndJoin()
        }finally {scope.cancel();work.cancelAllWork().result.get();db.close();context.deleteDatabase(name)}
    }
}
