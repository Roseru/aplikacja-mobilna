package pl.roseru.kalorie

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.core.Preferences
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.*
import androidx.work.testing.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.sync.*
import java.io.File
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger

/** Real DeviceNetworkPolicy/DataStore, Room and WorkerFactory. No socket, API or OIDC service. */
class SyncNetworkPolicyStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun uuid()=UUID.randomUUID().toString()
    private class UnreadStore:DataStore<Preferences> {
        override val data:Flow<Preferences> = flow {awaitCancellation()}
        override suspend fun updateData(transform:suspend (Preferences)->Preferences):Preferences=error("Unread fixture")
    }
    private inner class PolicyFixture(val folder:File=File(context.cacheDir,"runtime-policy-${uuid()}").apply {mkdirs()},unavailable:Boolean=false) {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
        val store:DataStore<Preferences> = if(unavailable)UnreadStore() else PreferenceDataStoreFactory.create(scope=scope,produceFile={File(folder,"device.preferences_pb")})
        val policy=DeviceNetworkPolicy(store,scope)
        suspend fun ready() {withTimeout(10_000){policy.state.first {it is NetworkAccessState.Allowed}}}
        suspend fun close(delete:Boolean=true) {scope.coroutineContext.job.cancelAndJoin();if(delete)folder.deleteRecursively()}
    }
    private fun page(entities:List<JSONObject> = emptyList())=JSONObject().put("sync_epoch",epoch).put("mode","snapshot")
        .put("snapshot_token","synthetic-${uuid()}").put("page_token",JSONObject.NULL).put("checkpoint","synthetic-${uuid()}")
        .put("server_time","2026-10-24T12:00:00Z").put("goal_timeline_revision",0).put("entities",JSONArray(entities))
        .put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray()).toString().toByteArray()
    private inner class Harness(val gate:NetworkAccessGate,val name:String?=null,val admission:SyncRuntimeAdmission=OpenSyncRuntimeAdmission) {
        val db=if(name==null)Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
            else Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val calls=AtomicInteger();val localCalls=AtomicInteger();val steps=CopyOnWriteArrayList<SyncStep>()
        var clock=1000L
        var answer:suspend (OwnerLease,AccountBindingEntity,SyncStep)->SyncStepResult={_,_,_->SyncStepResult.LoginRequired}
        var drain:suspend (OwnerLease,AccountBindingEntity)->SavedSyncEvidenceResult={_,_->SavedSyncEvidenceResult.NO_LOCAL_WORK}
        lateinit var lease:OwnerLease;lateinit var binding:AccountBindingEntity
        lateinit var coordinator:SyncCoordinator;lateinit var runtime:SyncWorkRuntime
        lateinit var sessions:MutableStateFlow<SyncSessionSignal>
        val factory=object:WorkerFactory() {
            override fun createWorker(appContext:android.content.Context,workerClassName:String,parameters:WorkerParameters):ListenableWorker?=when(workerClassName) {
                DiarySyncWorker::class.java.name->DiarySyncWorker(appContext,parameters,runtime)
                DiarySyncWatchWorker::class.java.name->DiarySyncWatchWorker(appContext,parameters,runtime)
                else->null
            }
        }
        val work:WorkManager
        init {
            WorkManagerTestInitHelper.initializeTestWorkManager(context,Configuration.Builder().setExecutor(SynchronousExecutor()).setTaskExecutor(SynchronousExecutor()).setWorkerFactory(factory).build())
            work=WorkManager.getInstance(context)
        }
        suspend fun start(reuse:Boolean=false) {
            if(!reuse) {
                val owners=LocalOwnerStore(db);owners.ensureGuest()
                lease=owners.select(owners.registerIdentity("https://fixture.example/realms/policy-runtime",uuid()).id)
                val bootstrap=AccountBootstrapStore(db)
                binding=bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-24T12:00:00Z"))
                val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));assertNull(snapshots.apply(snapshots.begin(lease),page()))
            } else {lease=LocalOwnerStore(db).currentLease();binding=db.bootstrapDao().binding(lease.storageScope)!!}
            val executor=SyncStepExecutor {l,b,s->calls.incrementAndGet();steps+=s;answer(l,b,s)}
            coordinator=SyncCoordinator(db,schema,executor,networkGate=gate,savedEvidence=SavedSyncEvidenceDrainer {l,b->localCalls.incrementAndGet();drain(l,b)}) {clock}
            runtime=SyncWorkRuntime(db,coordinator,SyncWorkScheduler(work){clock},admission)
            sessions=MutableStateFlow(SyncSessionSignal(lease,true,true))
            assertSame(gate,coordinator.networkGate);assertSame(gate,runtime.networkGate)
        }
        fun observe()=runtime.observe(scope,sessions)
        fun ticket(revision:Long?=coordinator.captureNetworkPermit()?.revision)=SyncWorkTicket(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),revision,gate.changes.value.issuance)
        suspend fun state(predicate:(SyncWorkState)->Boolean)=withTimeout(15_000){db.syncWorkDao().observe(lease.storageScope).filterNotNull().first(predicate)}
        suspend fun jobs(ticket:SyncWorkTicket,predicate:(List<WorkInfo>)->Boolean)=withTimeout(15_000){work.getWorkInfosForUniqueWorkFlow(ticket.uniqueName()).first(predicate)}
        suspend fun worker(ticket:SyncWorkTicket)=TestListenableWorkerBuilder<DiarySyncWorker>(context).setWorkerFactory(factory).setInputData(ticket.data()).build().doWork()
        suspend fun watch()=TestListenableWorkerBuilder<DiarySyncWatchWorker>(context).setWorkerFactory(factory).build().doWork()
        suspend fun frozen():MealPushRequest {
            DiaryRepository(db,context,lease).addWeight(82.125,LocalDate.of(2001,1,2))
            val push=MealPushStore(db,schema);val request=push.prepare(lease)!!;push.markAttempted(request,clock);return request
        }
        suspend fun checkpoint(phase:String="push",deadline:Long=0,status:String="ready"):SyncWorkState {
            val s=coordinator.request(lease,binding)
            return s.copy(phase=phase,status=status,activeVersion=s.requestedVersion,retryAtMillis=deadline,consecutiveFailures=2).also {db.syncWorkDao().save(it)}
        }
        suspend fun close() {scope.coroutineContext.job.cancelAndJoin();work.cancelAllWork().result.get();db.close()}
    }
    private fun denied(action:()->Unit) {try{action();fail("Expected revoked permit")}catch(_:NetworkAccessDenied){}}

    private class ReusedRevisionGate:ObservableNetworkAccessGate() {
        init {publish(NetworkAccessState.Allowed(7))}
        fun aba() {publish(NetworkAccessState.Blocked);publish(NetworkAccessState.Allowed(7))}
    }
    @Test fun sameRevisionAbaCannotPromoteOldTicketOrReschedule()=runBlocking<Unit> {
        val gate=ReusedRevisionGate();val h=Harness(gate)
        try {
            h.start();h.checkpoint();val old=h.ticket();val permit=gate.captureAllowed()
            gate.aba();denied {gate.requireCurrent(permit)}
            assertEquals(SyncCoordinator.Outcome.Stale,h.runtime.execute(old))
            h.runtime.reschedule(old,SyncCoordinator.Outcome.Deferred(90000))
            assertTrue(withContext(Dispatchers.IO){h.work.getWorkInfosForUniqueWork(old.uniqueName()).get()}.isEmpty())
            assertEquals(0,h.calls.get())
        }finally{h.close()}
    }
    @Test fun staleRescheduleCannotEnqueueAfterSameRevisionAbaOrProviderRecreation()=runBlocking<Unit> {
        val gate=ReusedRevisionGate();val h=Harness(gate)
        try {
            h.start();h.checkpoint();val old=h.ticket();gate.aba()
            h.runtime.reschedule(old,SyncCoordinator.Outcome.Deferred(90000))
            assertTrue(withContext(Dispatchers.IO){h.work.getWorkInfosForUniqueWork(old.uniqueName()).get()}.isEmpty())
            val fresh=h.ticket();assertNotEquals(old.uniqueName(),fresh.uniqueName())
            val scheduler=SyncWorkScheduler(h.work){h.clock}
            val oldJob=scheduler.enqueue(old,90000);val newJob=scheduler.enqueue(fresh,90000)
            scheduler.revokeScheduled(old)
            assertEquals(WorkInfo.State.ENQUEUED,withContext(Dispatchers.IO){h.work.getWorkInfoById(newJob.id).get()}!!.state)
            val oldInfo=withContext(Dispatchers.IO){h.work.getWorkInfoById(oldJob.id).get()}
            assertTrue(oldInfo==null || oldInfo.state==WorkInfo.State.CANCELLED)
            val other=ReusedRevisionGate()
            val restarted=SyncWorkRuntime(h.db,SyncCoordinator(h.db,schema,SyncStepExecutor {_,_,_->fail("Old provider ticket must be stale");SyncStepResult.LoginRequired},networkGate=other),scheduler)
            assertEquals(SyncCoordinator.Outcome.Stale,restarted.execute(fresh))
            restarted.reschedule(fresh,SyncCoordinator.Outcome.Deferred(90000))
            assertEquals(0,h.calls.get())
        }finally{h.close()}
    }
    @Test fun ownerAndWireContextChangesCancelSuspendedStepAndReleaseMutex()=runBlocking<Unit> {
        for(changeOwner in listOf(false,true)) {
            val gate=ReusedRevisionGate();val h=Harness(gate)
            val entered=CompletableDeferred<Unit>();val done=CompletableDeferred<Unit>();var active:Deferred<SyncCoordinator.Outcome>?=null
            try {
                h.start();val frozen=h.frozen();val before=h.checkpoint();val oldBinding=h.binding
                h.answer={_,_,_->entered.complete(Unit);try{awaitCancellation()}finally{done.complete(Unit)}}
                active=async {h.runtime.manual(h.lease)};withTimeout(10000){entered.await()}
                if(changeOwner) {
                    val owners=LocalOwnerStore(h.db);val a=h.db.ownerDao().byScope(h.lease.storageScope)!!
                    owners.select(owners.ensureGuest().id);h.lease=owners.select(a.id)
                } else {
                    val next=oldBinding.copy(accountGeneration=oldBinding.accountGeneration+1)
                    h.db.bootstrapDao().update(next);h.binding=next
                }
                withTimeout(10000){done.await()};assertEquals(SyncCoordinator.Outcome.Stale,withTimeout(10000){active.await()})
                val state=h.db.syncWorkDao().state(h.lease.storageScope)!!
                assertEquals(before.phase,state.phase);assertEquals(0,state.acknowledged)
                assertArrayEquals(frozen.batch.body(),h.db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
                h.answer={_,_,_->SyncStepResult.LoginRequired}
                assertEquals(SyncCoordinator.Outcome.Stopped("login"),h.runtime.manual(h.lease));assertEquals(2,h.calls.get())
            }finally{active?.cancelAndJoin();h.close()}
        }
    }
    @Test fun sameRevisionFrameAutomaticallyReplacesOnlyOldChainAndHonorsFutureDeadline()=runBlocking<Unit> {
        val gate=ReusedRevisionGate();val h=Harness(gate)
        try {
            h.start();val frozen=h.frozen();MealPushStore(h.db,schema).defer(frozen,90000);h.checkpoint(deadline=90000)
            h.observe();val old=h.ticket();val original=h.jobs(old){it.isNotEmpty()}.first()
            gate.aba();val fresh=h.ticket();assertNotEquals(old.uniqueName(),fresh.uniqueName())
            val job=h.jobs(fresh){rows->rows.any {it.state==WorkInfo.State.ENQUEUED}}.first {it.state==WorkInfo.State.ENQUEUED}
            val previous=withContext(Dispatchers.IO){h.work.getWorkInfoById(original.id).get()}
            assertTrue(previous==null || previous.state==WorkInfo.State.CANCELLED)
            h.runtime.reschedule(old,SyncCoordinator.Outcome.Deferred(90000))
            assertEquals(SyncCoordinator.Outcome.Stale,h.runtime.execute(old));assertEquals(0,h.calls.get())
            val state=h.coordinator.state(h.lease)!!;assertEquals("push",state.phase);assertEquals(90000L,state.retryAtMillis)
            h.clock=90000;val driver=WorkManagerTestInitHelper.getTestDriver(context)!!
            driver.setAllConstraintsMet(job.id);driver.setInitialDelayMet(job.id)
            h.state {it.status=="login"};assertEquals(listOf(SyncStep.PUSH),h.steps.toList())
            assertArrayEquals(frozen.batch.body(),h.db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
        }finally{h.close()}
    }
    @Test fun coalescedSameRevisionAbaCancelsSuspendedExecutorAndReleasesMutex()=runBlocking<Unit> {
        val gate=ReusedRevisionGate();val h=Harness(gate);val entered=CompletableDeferred<Unit>();val cancelled=CompletableDeferred<Unit>()
        var pending:Deferred<SyncCoordinator.Outcome>?=null
        try {
            h.start();h.checkpoint()
            h.answer={_,_,_->entered.complete(Unit);try{awaitCancellation()}finally{cancelled.complete(Unit)}}
            pending=async {h.runtime.manual(h.lease)};withTimeout(10000){entered.await()}
            // Both writes run on the collector thread without yielding, guaranteeing conflation.
            gate.aba()
            withTimeout(2000){cancelled.await()}
            assertEquals(SyncCoordinator.Outcome.Stopped("network_changed"),withTimeout(2000){pending.await()})
            h.answer={_,_,_->SyncStepResult.LoginRequired};h.runtime.manual(h.lease)
            assertEquals(2,h.calls.get())
        }finally{pending?.cancelAndJoin();h.close()}
    }
    @Test fun delayedOldChainRevocationMustPreserveNewlyEnqueuedChain()=runBlocking<Unit> {
        val gate=ReusedRevisionGate();val h=Harness(gate)
        val beforeCancel=CompletableDeferred<Unit>();val allowCancel=CompletableDeferred<Unit>()
        try {
            h.start();val old=h.ticket(7);val fresh=h.ticket(8)
            val scheduler=SyncWorkScheduler(h.work){h.clock}
            val oldJob=scheduler.enqueue(old,90000)
            val late=async {beforeCancel.complete(Unit);allowCancel.await();scheduler.revokeScheduled(old)}
            beforeCancel.await();val newJob=scheduler.enqueue(fresh,90000)
            val newContext=old.copy(wireContext="new-synthetic-binding-context")
            assertNotEquals(old.uniqueName(),newContext.uniqueName())
            val contextJob=scheduler.enqueue(newContext,90000)
            allowCancel.complete(Unit);late.await()
            val info=withContext(Dispatchers.IO){h.work.getWorkInfoById(newJob.id).get()}
            assertEquals(WorkInfo.State.ENQUEUED,checkNotNull(info).state)
            assertEquals(WorkInfo.State.ENQUEUED,withContext(Dispatchers.IO){h.work.getWorkInfoById(contextJob.id).get()}!!.state)
            val oldInfo=withContext(Dispatchers.IO){h.work.getWorkInfoById(oldJob.id).get()}
            assertTrue(oldInfo==null || oldInfo.state==WorkInfo.State.CANCELLED)
        }finally{allowCancel.complete(Unit);h.close()}
    }
    @Test fun blockedAndUnavailableProtectManualWorkerWatchAndOutboxButLocalDiaryStillWrites()=runBlocking<Unit> {
        for(unavailable in listOf(false,true)) {
            val p=PolicyFixture(unavailable=unavailable);val h=Harness(p.policy)
            try {
                if(!unavailable){p.ready();p.policy.setBlocked(true)}
                h.start();val reason=if(unavailable)"network_unavailable" else "network_blocked"
                // Exercise these three entries before the independent observer can occupy the mutex.
                assertEquals(SyncCoordinator.Outcome.Stopped(reason),h.runtime.manual(h.lease))
                h.worker(h.ticket());h.watch()
                val beforeObserve=h.coordinator.state(h.lease)!!.requestedVersion
                h.observe();h.state {it.status==reason && it.requestedVersion>beforeObserve}
                val before=h.coordinator.state(h.lease)!!.requestedVersion
                DiaryRepository(h.db,context,h.lease).addWeight(80.125,LocalDate.of(2001,1,3))
                h.state {it.requestedVersion>before}
                assertEquals(0,h.calls.get());assertEquals(1,h.db.dao().operationCount(h.lease.storageScope))
                assertEquals(80.125,h.db.dao().weights(h.lease.storageScope).first().single().kg,0.0)
                assertTrue(withContext(Dispatchers.IO){h.work.getWorkInfosByTag(SyncWorkScheduler.NETWORK_TAG).get()}.none {!it.state.isFinished})
            }finally{h.close();p.close()}
        }
    }
    @Test fun persistedBlockSurvivesProviderRuntimeAndFileRoomReopenWithFrozenBytesAndDeadline()=runBlocking<Unit> {
        val p=PolicyFixture();p.ready();val name="network-restart-${uuid()}";var h=Harness(p.policy,name);var second:PolicyFixture?=null
        try {
            h.start();val frozen=h.frozen();MealPushStore(h.db,schema).defer(frozen,90000)
            h.checkpoint(deadline=90000);p.policy.setBlocked(true)
            h.runtime.manual(h.lease);val row=h.db.pushDao().batch(frozen.id)!!;val op=h.db.dao().operation(frozen.operations.single().operationId)!!
            h.close();p.close(delete=false)
            second=PolicyFixture(p.folder);withTimeout(10_000){second.policy.state.first {it==NetworkAccessState.Blocked}}
            h=Harness(second.policy,name);h.start(reuse=true);h.observe();h.state {it.status=="network_blocked"}
            assertEquals(SyncCoordinator.Outcome.Stopped("network_blocked"),h.runtime.manual(h.lease))
            val state=h.coordinator.state(h.lease)!!;assertEquals("push",state.phase);assertEquals(90000L,state.retryAtMillis);assertEquals(2,state.consecutiveFailures)
            assertEquals(row,h.db.pushDao().batch(frozen.id));assertEquals(op,h.db.dao().operation(op.operationId));assertEquals(0,h.calls.get())
            assertArrayEquals(frozen.batch.body(),h.db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
        }finally{h.close();second?.close()?:p.close();context.deleteDatabase(name)}
    }
    @Test fun revocationAndRapidAbaDiscardLateCompletionWithoutAckOrPhaseReset()=runBlocking<Unit> {
        val p=PolicyFixture();p.ready();val h=Harness(p.policy);val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>();var pending:Deferred<SyncCoordinator.Outcome>?=null
        try {
            h.start();val frozen=h.frozen();val operation=h.db.dao().operation(frozen.operations.single().operationId)!!;h.checkpoint()
            val oldPermit=p.policy.captureAllowed();val oldTicket=h.ticket()
            h.answer={_,_,_->entered.complete(Unit);withContext(NonCancellable){release.await()};SyncStepResult.Completed(acknowledged=1)}
            pending=async {h.runtime.manual(h.lease)};withTimeout(10_000){entered.await()}
            p.policy.setBlocked(true);p.policy.setBlocked(false);denied{p.policy.requireCurrent(oldPermit)};release.complete(Unit)
            assertEquals(SyncCoordinator.Outcome.Stopped("network_changed"),withTimeout(10_000){pending.await()})
            val state=h.coordinator.state(h.lease)!!;assertEquals("push",state.phase);assertEquals(0,state.acknowledged)
            assertEquals(operation,h.db.dao().operation(operation.operationId));assertNull(h.db.pushDao().batch(frozen.id)!!.responseJson)
            assertEquals(frozen.batch.sha256,h.db.pushDao().batch(frozen.id)!!.requestHash);assertArrayEquals(frozen.batch.body(),h.db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
            assertEquals(SyncCoordinator.Outcome.Stale,h.runtime.execute(oldTicket));assertEquals(1,h.calls.get())
            h.answer={_,_,_->SyncStepResult.LoginRequired};h.runtime.manual(h.lease);assertEquals(listOf(SyncStep.PUSH,SyncStep.PUSH),h.steps.toList())
        }finally{release.complete(Unit);pending?.cancelAndJoin();h.close();p.close()}
    }
    @Test fun queuedOldRevisionIsCancelledAndNewAllowedResumesSamePhaseOnlyAfterFutureDeadline()=runBlocking<Unit> {
        val p=PolicyFixture();p.ready();val h=Harness(p.policy)
        try {
            h.start();val frozen=h.frozen();MealPushStore(h.db,schema).defer(frozen,90000);h.checkpoint(deadline=90000)
            h.observe();val old=h.ticket();val first=h.jobs(old){it.isNotEmpty()}.first()
            p.policy.setBlocked(true);h.state {it.status=="network_blocked"}
            h.jobs(old){rows->rows.any {it.id==first.id && it.state==WorkInfo.State.CANCELLED}}
            p.policy.setBlocked(false);val fresh=h.ticket();assertNotEquals(old.uniqueName(),fresh.uniqueName())
            val next=h.jobs(fresh){rows->rows.any {it.state==WorkInfo.State.ENQUEUED}}.first {it.state==WorkInfo.State.ENQUEUED}
            assertEquals(SyncCoordinator.Outcome.Stale,h.runtime.execute(old))
            assertEquals(SyncCoordinator.Outcome.Deferred(90000),h.runtime.execute(fresh));assertEquals(0,h.calls.get())
            val waiting=h.coordinator.state(h.lease)!!;assertEquals("push",waiting.phase);assertEquals(90000L,waiting.retryAtMillis);assertEquals(2,waiting.consecutiveFailures)
            h.clock=90000;val driver=WorkManagerTestInitHelper.getTestDriver(context)!!;driver.setAllConstraintsMet(next.id);driver.setInitialDelayMet(next.id)
            h.state {it.status=="login"};assertEquals(listOf(SyncStep.PUSH),h.steps.toList());assertEquals(frozen.batch.sha256,h.db.pushDao().batch(frozen.id)!!.requestHash)
        }finally{h.close();p.close()}
    }
    @Test fun networkChangesCannotClearLoginReconciliationStorageConfigurationOrLocalEvidenceBlock()=runBlocking<Unit> {
        for(reason in listOf("login","reconciliation","storage","not_configured","local_evidence")) {
            val p=PolicyFixture();p.ready();p.policy.setBlocked(true);val h=Harness(p.policy)
            try {
                h.start();val old=h.checkpoint(deadline=90000,status=reason).copy(reconciliationBaseline=if(reason=="reconciliation")0L else null);h.db.syncWorkDao().save(old)
                h.observe();h.state {it.requestedVersion>old.requestedVersion}
                assertEquals(reason,h.coordinator.state(h.lease)!!.status)
                p.policy.setBlocked(false);h.state {it.requestedVersion>old.requestedVersion+1}
                val state=h.coordinator.state(h.lease)!!;assertEquals(reason,state.status);assertEquals("push",state.phase)
                assertEquals(90000L,state.retryAtMillis);assertEquals(old.reconciliationBaseline,state.reconciliationBaseline);assertEquals(0,h.calls.get())
                assertTrue(withContext(Dispatchers.IO){h.work.getWorkInfosByTag(SyncWorkScheduler.NETWORK_TAG).get()}.none {!it.state.isFinished})
            }finally{h.close();p.close()}
        }
    }
    @Test fun ownerAbaAndOldPolicyWakeCannotInvokeExecutorForFreshGeneration()=runBlocking<Unit> {
        val p=PolicyFixture();p.ready();val h=Harness(p.policy)
        try {
            h.start();val original=h.lease;val old=h.ticket();p.policy.setBlocked(true);h.observe();h.state {it.status=="network_blocked"}
            val owners=LocalOwnerStore(h.db);val a=h.db.ownerDao().byScope(original.storageScope)!!
            owners.select(owners.registerIdentity("https://fixture.example/realms/other",uuid()).id)
            val again=owners.select(a.id);assertNotEquals(original.generation,again.generation);h.lease=again
            h.binding=h.db.bootstrapDao().binding(again.storageScope)!!;h.sessions.value=SyncSessionSignal(again,true,true)
            p.policy.setBlocked(false);val fresh=h.ticket();h.jobs(fresh){it.isNotEmpty()}
            val before=h.coordinator.state(again)!!;h.runtime.signal(resumeBlocked=true,expected=old)
            assertEquals(before,h.coordinator.state(again));assertEquals(SyncCoordinator.Outcome.Stale,h.runtime.execute(old))
            assertEquals(SyncCoordinator.Outcome.Stale,h.runtime.execute(fresh.copy(policyRevision=old.policyRevision)));assertEquals(0,h.calls.get())
            h.worker(fresh);assertEquals(1,h.calls.get());assertEquals("login",h.coordinator.state(again)!!.status)
        }finally{h.close();p.close()}
    }
    @Test fun savedAckReplayAndRawApplicationAreLocalBeforeDeadlineAndNeverCompleteFreshCycle()=runBlocking<Unit> {
        for(unavailable in listOf(false,true)) {
            val p=PolicyFixture(unavailable=unavailable);if(!unavailable)p.ready();val h=Harness(p.policy)
            try {
                h.start();val frozen=h.frozen();val push=MealPushStore(h.db,schema)
                val results=JSONArray().put(JSONObject().put("operation_id",frozen.operations.single().operationId).put("entity_id",frozen.operations.single().entityId)
                    .put("status","accepted").put("revision",1).put("recovery_mapping",JSONObject.NULL))
                val response=JSONObject().put("sync_epoch",epoch).put("server_time","2026-10-24T12:00:00Z").put("results",results).toString().toByteArray()
                push.applyAck(push.prepareAck(frozen,200,response)) // A genuine previously saved proof, not a manufactured ACK during blocking.
                val saved=h.db.pushDao().batch(frozen.id)!!;val remote=uuid()
                val entity=JSONObject().put("entity_type","weight").put("entity_id",remote).put("revision",1).put("deleted",false)
                    .put("payload",WeightWire.create(83.125,"2001-01-04T12:00:00Z","UTC","2001-01-04",schema).json())
                val known=JSONObject().put("entity_type","weight").put("entity_id",frozen.operations.single().entityId)
                    .put("revision",1).put("deleted",false)
                    .put("payload",frozen.batch.json().getJSONArray("operations").getJSONObject(0).getJSONObject("payload"))
                val snapshots=ServerSnapshotStore(h.db,SnapshotProtocol(schema));val raw=snapshots.begin(h.lease);assertNull(snapshots.apply(raw,page(listOf(known,entity))))
                h.checkpoint(deadline=90000)
                if(!unavailable)p.policy.setBlocked(true)
                h.drain={lease,binding->
                    LocalOwnerStore(h.db).requireCurrent(lease);assertEquals(h.binding,binding)
                    val request=push.open(lease,saved.id);assertTrue(push.applyAck(push.prepareAck(request,200,saved.responseJson!!.toByteArray())).replay)
                    ServerDiaryStore(h.db,schema).apply(lease,raw.runId);SavedSyncEvidenceResult.APPLIED
                }
                val expected=if(unavailable)"network_unavailable" else "network_blocked"
                assertEquals(SyncCoordinator.Outcome.Stopped(expected),h.runtime.manual(h.lease));h.worker(h.ticket());h.watch()
                assertEquals(0,h.calls.get());assertTrue(h.localCalls.get()>=3)
                assertEquals(82.125,h.db.dao().weight(frozen.operations.single().entityId,h.lease.storageScope)!!.kg,0.0)
                assertEquals(saved,h.db.pushDao().batch(frozen.id));assertEquals(83.125,h.db.dao().weight(remote,h.lease.storageScope)!!.kg,0.0)
                val state=h.coordinator.state(h.lease)!!;assertEquals("push",state.phase);assertEquals(90000L,state.retryAtMillis);assertEquals(0,state.acknowledged)
                assertNotEquals("idle",state.status);assertEquals(raw.runId,h.db.serverDiaryDao().latest(h.lease.storageScope)!!.runId)
            }finally{h.close();p.close()}
        }
    }
    @Test fun defaultClosedWrongProviderPermitAndLegacyTicketCannotAuthorizeNetwork()=runBlocking<Unit> {
        val p=PolicyFixture();p.ready();val h=Harness(p.policy)
        try {
            h.start();val default=SyncCoordinator(h.db,schema,SyncStepExecutor {_,_,_->fail("Missing DI must be closed");SyncStepResult.Completed()})
            default.request(h.lease,h.binding);assertEquals(SyncCoordinator.Outcome.Stopped("network_unavailable"),default.run(h.lease,h.binding))
            val other=object:ObservableNetworkAccessGate(){init {publish(NetworkAccessState.Allowed(1))}}
            h.coordinator.request(h.lease,h.binding)
            assertEquals(SyncCoordinator.Outcome.Stopped("network_changed"),h.coordinator.run(h.lease,h.binding,other.captureAllowed()))
            val legacy=SyncWorkTicket(h.lease.storageScope,h.lease.generation,CanonicalMealRows.context(h.binding))
            assertEquals(legacy,SyncWorkTicket.read(legacy.data()));assertEquals(SyncCoordinator.Outcome.Stale,h.runtime.execute(legacy));assertEquals(0,h.calls.get())
        }finally{h.close();p.close()}
    }
    @Test fun localBusyStaleAndFailureAreHonestAndNeverEnterMixedExecutor()=runBlocking<Unit> {
        for(result in listOf(SavedSyncEvidenceResult.BUSY,SavedSyncEvidenceResult.STALE_CONTEXT,SavedSyncEvidenceResult.FAILURE)) {
            val p=PolicyFixture();p.ready();p.policy.setBlocked(true);val h=Harness(p.policy)
            try {
                h.start();h.checkpoint(status="storage",deadline=90000);h.drain={_,_->result}
                val outcome=h.runtime.manual(h.lease)
                assertEquals(when(result){SavedSyncEvidenceResult.BUSY->SyncCoordinator.Outcome.Busy;SavedSyncEvidenceResult.STALE_CONTEXT->SyncCoordinator.Outcome.Stale;else->SyncCoordinator.Outcome.Stopped("storage")},outcome)
                assertEquals("storage",h.coordinator.state(h.lease)!!.status);assertEquals(90000L,h.coordinator.state(h.lease)!!.retryAtMillis);assertEquals(0,h.calls.get())
            }finally{h.close();p.close()}
        }
    }
    @Test fun policyAbaDuringPureLocalAwaitRequiresFreshInvocationBeforeAnyNetwork()=runBlocking<Unit> {
        val p=PolicyFixture();p.ready();val h=Harness(p.policy);val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>();var pending:Deferred<SyncCoordinator.Outcome>?=null
        try {
            h.start();val before=h.checkpoint();var first=true
            h.drain={_,_->if(first){first=false;entered.complete(Unit);release.await();SavedSyncEvidenceResult.APPLIED}else SavedSyncEvidenceResult.NO_LOCAL_WORK}
            pending=async {h.runtime.manual(h.lease)};withTimeout(10_000){entered.await()}
            p.policy.setBlocked(true);p.policy.setBlocked(false);release.complete(Unit)
            assertEquals(SyncCoordinator.Outcome.Stopped("network_changed"),withTimeout(10_000){pending.await()});assertEquals(0,h.calls.get())
            val after=h.coordinator.state(h.lease)!!;assertEquals(before.phase,after.phase);assertEquals(before.handledVersion,after.handledVersion)
            h.runtime.manual(h.lease);assertEquals(1,h.calls.get())
        }finally{release.complete(Unit);pending?.cancelAndJoin();h.close();p.close()}
    }
    /** Delays only legacy state delivery until after the burst, exactly modelling conflation.
     * value remains the real gate value, and the new generation stream is the real gate stream. */
    @OptIn(kotlinx.coroutines.InternalCoroutinesApi::class)
    private class CoalescedLegacyGate(private val source:NetworkAccessGate,val release:CompletableDeferred<Unit>):NetworkAccessGate by source {
        override val state:StateFlow<NetworkAccessState> = object:StateFlow<NetworkAccessState> {
            override val value get()=source.state.value
            override val replayCache get()=listOf(value)
            override suspend fun collect(collector:FlowCollector<NetworkAccessState>):Nothing {
                var previous=value;collector.emit(previous);release.await()
                source.state.collect {next->if(next!=previous){previous=next;collector.emit(next)}}
                error("StateFlow cannot complete")
            }
        }
    }
    private class BlockingConnection(val entered:CompletableDeferred<Unit>):javax.net.ssl.HttpsURLConnection(java.net.URL("https://fixture.example/synthetic")) {
        private val released=java.util.concurrent.CountDownLatch(1)
        private val closed=java.util.concurrent.atomic.AtomicBoolean(false)
        val disconnects=AtomicInteger()
        override fun getInputStream()=object:java.io.InputStream() {
            override fun read():Int {entered.complete(Unit);released.await();return -1}
        }
        override fun disconnect(){if(closed.compareAndSet(false,true)){disconnects.incrementAndGet();released.countDown()}}
        override fun connect()=Unit
        override fun usingProxy()=false
        override fun getCipherSuite()="synthetic"
        override fun getLocalCertificates():Array<java.security.cert.Certificate>?=null
        override fun getServerCertificates():Array<java.security.cert.Certificate> = emptyArray()
    }
    @Test fun coalescedAbaDisconnectsActualBlockingConnectionCancelsExecutorAndReleasesMutex()=runBlocking<Unit> {
        val source=ReusedRevisionGate();val deliverLegacy=CompletableDeferred<Unit>()
        val gate=CoalescedLegacyGate(source,deliverLegacy);val h=Harness(gate)
        val entered=CompletableDeferred<Unit>();val connection=BlockingConnection(entered)
        val sockets=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        var pending:Deferred<SyncCoordinator.Outcome>?=null
        try {
            h.start();val frozen=h.frozen();h.checkpoint()
            val factory=PolicyConnectionFactory(sockets,gate){connection}
            h.answer={_,_,_->
                withContext(Dispatchers.IO){factory.open(java.net.URL("https://fixture.example/synthetic")).inputStream.read()}
                SyncStepResult.Completed(acknowledged=1)
            }
            pending=async {h.runtime.manual(h.lease)};withTimeout(10000){entered.await()}
            source.aba();deliverLegacy.complete(Unit)
            assertEquals(SyncCoordinator.Outcome.Stopped("network_changed"),withTimeout(3000){pending.await()})
            assertEquals(1,connection.disconnects.get())
            assertEquals(0,h.coordinator.state(h.lease)!!.acknowledged)
            assertNull(h.db.pushDao().batch(frozen.id)!!.responseJson)
            assertArrayEquals(frozen.batch.body(),h.db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
            h.answer={_,_,_->SyncStepResult.LoginRequired}
            assertEquals(SyncCoordinator.Outcome.Stopped("login"),h.runtime.manual(h.lease));assertEquals(2,h.calls.get())
        }finally{deliverLegacy.complete(Unit);connection.disconnect();pending?.cancelAndJoin();sockets.coroutineContext.job.cancelAndJoin();h.close()}
    }
    private class BlockingTrialAdmission:SyncRuntimeAdmission {
        override val changes=MutableStateFlow(0L)
        private val jobs=java.util.concurrent.CopyOnWriteArrayList<Job>()
        @Volatile private var paused=false
        override fun attach(contractVersion:Int){require(contractVersion==1)}
        override suspend fun <T> run(block:suspend ()->T):SyncRuntimeEntry<T> = coroutineScope {
            if(paused)SyncRuntimeEntry.Paused else {
                val job=currentCoroutineContext().job;jobs+=job
                try{SyncRuntimeEntry.Admitted(block())}finally{jobs-=job}
            }
        }
        suspend fun pause(){paused=true;val old=jobs.toList();old.forEach {it.cancel()};old.joinAll()}
        fun open(){paused=false;changes.value++}
    }
    private suspend fun blockingLifecycle(mode:String)=coroutineScope {
        val source=ReusedRevisionGate();val trial=BlockingTrialAdmission();val h=Harness(source,admission=trial)
        val entered=CompletableDeferred<Unit>();val connection=BlockingConnection(entered)
        val sockets=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        var pending:Deferred<SyncCoordinator.Outcome>?=null;var pause:Deferred<Unit>?=null
        try {
            h.start();val frozen=h.frozen();h.checkpoint();val unchangedAllowed=source.changes.value
            val factory=PolicyConnectionFactory(sockets,source){connection}
            h.answer={_,_,_->withContext(Dispatchers.IO){factory.open(java.net.URL("https://fixture.example/synthetic")).inputStream.read()};SyncStepResult.Completed(acknowledged=1)}
            pending=async {h.runtime.manual(h.lease)};withTimeout(10000){entered.await()}
            when(mode) {
                "owner"->{
                    val owners=LocalOwnerStore(h.db);val id=h.db.ownerDao().byScope(h.lease.storageScope)!!.id
                    owners.select(owners.ensureGuest().id);h.lease=owners.select(id)
                }
                "context"->{h.binding=h.binding.copy(accountGeneration=h.binding.accountGeneration+1);h.db.bootstrapDao().update(h.binding)}
                "pause"->{
                    pause=async {trial.pause()}
                    // Admission joins its inner scope; cancellation can still be unwinding
                    // through runtime.manual to this caller. Join both within the same bound.
                    withTimeout(3000){pause.await();pending.join()}
                }
                else->error("Unknown lifecycle fixture")
            }
            if(mode=="pause")assertTrue(pending.isCancelled)
            else assertEquals(SyncCoordinator.Outcome.Stale,withTimeout(3000){pending.await()})
            assertEquals("Cancellation is local to the request, not a device policy change",unchangedAllowed,source.changes.value)
            assertEquals(1,connection.disconnects.get())
            assertEquals(0,h.db.syncWorkDao().state(h.lease.storageScope)!!.acknowledged)
            assertNull(h.db.pushDao().batch(frozen.id)!!.responseJson)
            assertArrayEquals(frozen.batch.body(),h.db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
            trial.open();h.answer={_,_,_->SyncStepResult.LoginRequired}
            assertEquals(SyncCoordinator.Outcome.Stopped("login"),h.runtime.manual(h.lease));assertEquals(2,h.calls.get())
        }finally{connection.disconnect();pending?.cancelAndJoin();pause?.cancelAndJoin();sockets.coroutineContext.job.cancelAndJoin();h.close()}
    }
    @Test fun ownerChangeDisconnectsBlockingIoUnderUnchangedAllowed()=runBlocking<Unit>{blockingLifecycle("owner")}
    @Test fun contextChangeDisconnectsBlockingIoUnderUnchangedAllowed()=runBlocking<Unit>{blockingLifecycle("context")}
    @Test fun admissionPauseDisconnectsBlockingIoUnderUnchangedAllowed()=runBlocking<Unit>{blockingLifecycle("pause")}
    @Test fun requestCancellationRegistrationInitDisposeAndNormalCompletionStayConnectionLocal()=runBlocking<Unit> {
        val gate=ReusedRevisionGate();val sockets=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val created=java.util.concurrent.CopyOnWriteArrayList<BlockingConnection>()
        val factory=PolicyConnectionFactory(sockets,gate){BlockingConnection(CompletableDeferred()).also {created+=it}}
        val url=java.net.URL("https://fixture.example/synthetic")
        try {
            val cancelled=Job();cancelled.cancel()
            val initClosed=withContext(NonCancellable+NetworkOperationCancellation(cancelled)){factory.open(url)}
            assertEquals(1,created.last().disconnects.get())
            denied {initClosed.connect()};assertFalse(created.last().entered.isCompleted)

            val completed=Job()
            val normal=withContext(NetworkOperationCancellation(completed)){factory.open(url)}
            val normalDelegate=created.last();completed.complete()
            assertEquals(0,normalDelegate.disconnects.get());normal.connect()
            normal.disconnect();assertEquals(1,normalDelegate.disconnects.get())

            val old=Job();val oldConnection=withContext(NetworkOperationCancellation(old)){factory.open(url)}
            val oldDelegate=created.last();oldConnection.disconnect()
            val fresh=Job();val freshConnection=withContext(NetworkOperationCancellation(fresh)){factory.open(url)}
            val freshDelegate=created.last();old.cancel()
            assertEquals(1,oldDelegate.disconnects.get());assertEquals(0,freshDelegate.disconnects.get())
            freshConnection.connect();fresh.cancel();assertEquals(1,freshDelegate.disconnects.get())
            assertEquals(NetworkAccessState.Allowed(7),gate.state.value)
        }finally{created.forEach {it.disconnect()};sockets.coroutineContext.job.cancelAndJoin()}
    }
}
