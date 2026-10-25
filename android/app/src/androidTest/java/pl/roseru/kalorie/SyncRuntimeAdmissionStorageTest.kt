package pl.roseru.kalorie

import android.database.Cursor
import androidx.room.Room
import androidx.room.withTransaction
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.*
import androidx.work.testing.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.sync.*
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import kotlin.coroutines.AbstractCoroutineContextElement
import kotlin.coroutines.CoroutineContext

/** Actual Room/WorkManager and runtime entries. The trial admission is only an in-memory test gate. */
class SyncRuntimeAdmissionStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun uuid()=UUID.randomUUID().toString()

    private class InsideAdmission:AbstractCoroutineContextElement(Key) {
        companion object Key:CoroutineContext.Key<InsideAdmission>
    }
    private class TrialAdmission(initiallyPaused:Boolean):SyncRuntimeAdmission {
        private val mutex=Mutex()
        private var paused=initiallyPaused
        private val running=mutableSetOf<Job>()
        private val mutableChanges=MutableStateFlow(0L)
        override val changes:StateFlow<Long> = mutableChanges
        val attempts=MutableStateFlow(0)
        val active=MutableStateFlow(0)
        val completed=MutableStateFlow(0)
        val attached=CopyOnWriteArrayList<Int>()
        override fun attach(contractVersion:Int) {require(contractVersion==1);attached+=contractVersion}
        override suspend fun <T> run(block:suspend ()->T):SyncRuntimeEntry<T> {
            check(currentCoroutineContext()[InsideAdmission]==null){"Nested admission.run is outside the contract"}
            return coroutineScope {
                val entry=currentCoroutineContext().job
                val accepted=mutex.withLock {
                    attempts.value=attempts.value+1
                    if(paused)false else {running+=entry;active.value=running.size;true}
                }
                if(!accepted){mutex.withLock {completed.value=completed.value+1};return@coroutineScope SyncRuntimeEntry.Paused}
                try {withContext(InsideAdmission()){SyncRuntimeEntry.Admitted(block())}}
                finally {withContext(NonCancellable){mutex.withLock {running-=entry;active.value=running.size;completed.value=completed.value+1}}}
            }
        }
        suspend fun pause() {
            val old=mutex.withLock {paused=true;running.toList()}
            old.forEach {it.cancel(CancellationException("Synthetic validation trial"))}
            old.joinAll()
            assertEquals("pause must wait for all active finally blocks",0,active.value)
        }
        suspend fun open()=mutex.withLock {paused=false;mutableChanges.value=mutableChanges.value+1}
        suspend fun attempted(atLeast:Int)=withTimeout(15_000){attempts.first {it>=atLeast}}
    }
    private class Gate:ObservableNetworkAccessGate() {
        init {publish(NetworkAccessState.Allowed(7))}
        fun block() {publish(NetworkAccessState.Blocked)}
        fun allow() {publish(NetworkAccessState.Allowed(7))}
    }
    private data class WorkRow(val id:UUID,val state:WorkInfo.State,val tags:List<String>,val attempts:Int)
    private inner class Harness(val admission:SyncRuntimeAdmission=OpenSyncRuntimeAdmission) {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val gate=Gate()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val calls=AtomicInteger();val drains=AtomicInteger();val executedOwners=CopyOnWriteArrayList<OwnerLease>()
        var clock=1000L
        var answer:suspend ()->SyncStepResult={SyncStepResult.LoginRequired}
        var localAnswer:suspend ()->SavedSyncEvidenceResult={SavedSyncEvidenceResult.NO_LOCAL_WORK}
        lateinit var lease:OwnerLease;lateinit var binding:AccountBindingEntity
        lateinit var sessions:MutableStateFlow<SyncSessionSignal>
        val factory=object:WorkerFactory() {
            override fun createWorker(appContext:android.content.Context,workerClassName:String,parameters:WorkerParameters):ListenableWorker?=when(workerClassName) {
                DiarySyncWorker::class.java.name->DiarySyncWorker(appContext,parameters,runtime)
                DiarySyncWatchWorker::class.java.name->DiarySyncWatchWorker(appContext,parameters,runtime)
                else->null
            }
        }
        val work:WorkManager
        val coordinator:SyncCoordinator
        val scheduler:SyncWorkScheduler
        val runtime:SyncWorkRuntime
        init {
            WorkManagerTestInitHelper.initializeTestWorkManager(context,Configuration.Builder().setExecutor(SynchronousExecutor())
                .setTaskExecutor(SynchronousExecutor()).setWorkerFactory(factory).build())
            work=WorkManager.getInstance(context)
            coordinator=SyncCoordinator(db,schema,SyncStepExecutor {l,_,_->calls.incrementAndGet();executedOwners+=l;answer()},
                networkGate=gate,savedEvidence=SavedSyncEvidenceDrainer {_,_->drains.incrementAndGet();localAnswer()}) {clock}
            scheduler=SyncWorkScheduler(work){clock}
            runtime=SyncWorkRuntime(db,coordinator,scheduler,admission)
        }
        suspend fun account():Pair<OwnerLease,AccountBindingEntity> {
            val owners=LocalOwnerStore(db);owners.ensureGuest()
            val l=owners.select(owners.registerIdentity("https://fixture.example/realms/admission",uuid()).id)
            val bootstrap=AccountBootstrapStore(db)
            val b=bootstrap.apply(bootstrap.begin(l),BootstrapResponse(uuid(),epoch,1,"2026-10-25T12:00:00Z"))
            val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
            val page=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-${uuid()}")
                .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-${uuid()}").put("server_time","2026-10-25T12:00:00Z")
                .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
            assertNull(snapshots.apply(snapshots.begin(l),page.toString().toByteArray()))
            return l to b
        }
        suspend fun seed() {val identity=account();lease=identity.first;binding=identity.second;sessions=MutableStateFlow(SyncSessionSignal(lease,true,true))}
        fun ticket(l:OwnerLease=lease,b:AccountBindingEntity=binding):SyncWorkTicket {
            val permit=gate.captureAllowed()
            return SyncWorkTicket(l.storageScope,l.generation,CanonicalMealRows.context(b),permit.revision,permit.issuance)
        }
        suspend fun frozen(deadline:Long=90000):MealPushRequest {
            DiaryRepository(db,context,lease).addWeight(82.125,LocalDate.of(2001,1,2))
            val push=MealPushStore(db,schema);val request=push.prepare(lease)!!;push.markAttempted(request,clock)
            if(deadline>0)push.defer(request,deadline)
            val old=coordinator.request(lease,binding)
            db.syncWorkDao().save(old.copy(phase="push",status="ready",activeVersion=old.requestedVersion,retryAtMillis=deadline,consecutiveFailures=2))
            return request
        }
        suspend fun state(l:OwnerLease=lease,predicate:(SyncWorkState)->Boolean)=withTimeout(15_000) {
            db.syncWorkDao().observe(l.storageScope).filterNotNull().first(predicate)
        }
        suspend fun jobs(ticket:SyncWorkTicket,predicate:(List<WorkInfo>)->Boolean)=withTimeout(15_000) {
            work.getWorkInfosForUniqueWorkFlow(ticket.uniqueName()).first(predicate)
        }
        suspend fun worker(ticket:SyncWorkTicket)=TestListenableWorkerBuilder<DiarySyncWorker>(context).setWorkerFactory(factory)
            .setInputData(ticket.data()).build().doWork()
        suspend fun watch()=TestListenableWorkerBuilder<DiarySyncWatchWorker>(context).setWorkerFactory(factory).build().doWork()
        suspend fun workImage():List<WorkRow> = withContext(Dispatchers.IO) {
            (work.getWorkInfosByTag(SyncWorkScheduler.NETWORK_TAG).get()+work.getWorkInfosForUniqueWork(SyncWorkScheduler.WATCH).get())
                .distinctBy {it.id}.map {WorkRow(it.id,it.state,it.tags.sorted(),it.runAttemptCount)}.sortedBy {it.id.toString()}
        }
        suspend fun databaseImage():List<String> = withContext(Dispatchers.IO) {db.withTransaction {
            val sql=db.openHelper.readableDatabase
            val tables=sql.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").use {cursor->
                buildList {while(cursor.moveToNext())add(cursor.getString(0))}
            }
            tables.flatMap {table->
                val quoted="\""+table.replace("\"","\"\"")+"\""
                val rows=sql.query("SELECT * FROM $quoted").use {cursor->buildList {
                    while(cursor.moveToNext())add((0 until cursor.columnCount).joinToString("|") {index->when(cursor.getType(index)) {
                        Cursor.FIELD_TYPE_NULL->"null"
                        Cursor.FIELD_TYPE_INTEGER->"i:"+cursor.getLong(index)
                        Cursor.FIELD_TYPE_FLOAT->"f:"+cursor.getDouble(index)
                        Cursor.FIELD_TYPE_BLOB->"b:"+cursor.getBlob(index).joinToString(""){"%02x".format(it)}
                        else->"s:"+cursor.getString(index)
                    }})
                }}
                listOf("table:$table")+rows.sorted()
            }
        }}
        suspend fun close() {scope.coroutineContext.job.cancelAndJoin();work.cancelAllWork().result.get();db.close()}
    }

    @Test fun pausedEmptyDatabaseNeverInitializesOwnerFromAnyRuntimeEntry()=runBlocking<Unit> {
        val trial=TrialAdmission(true);val h=Harness(trial)
        try {
            assertEquals(listOf(1),trial.attached.toList())
            val before=h.databaseImage();val jobs=h.workImage()
            val absent=OwnerLease("synthetic-absent-owner",1)
            val permit=h.gate.captureAllowed();val ticket=SyncWorkTicket(absent.storageScope,absent.generation,"synthetic-context",permit.revision,permit.issuance)
            assertNull(h.runtime.current());h.runtime.signal()
            assertEquals(SyncCoordinator.Outcome.Stopped("validation_trial"),h.runtime.manual(absent))
            assertEquals(SyncCoordinator.Outcome.Stopped("validation_trial"),h.runtime.execute(ticket))
            h.runtime.reschedule(ticket,SyncCoordinator.Outcome.Deferred(90000));h.worker(ticket);h.watch()
            val beforeObserver=trial.attempts.value
            h.runtime.observe(h.scope,flowOf(SyncSessionSignal(absent,true,true)))
            trial.attempted(beforeObserver+1)
            assertEquals(before,h.databaseImage());assertEquals(jobs,h.workImage())
            assertNull(h.db.ownerDao().active());assertNull(h.db.ownerDao().byScope(DiaryRepository.GUEST))
            assertEquals(0,h.calls.get());assertEquals(0,h.drains.get());assertEquals(0,trial.active.value)
        }finally{h.close()}
    }

    @Test fun pausedSeededEntriesAndObserversPreserveAllRowsAndJobsThenChangesResumesDeadline()=runBlocking<Unit> {
        val trial=TrialAdmission(true);val h=Harness(trial)
        try {
            h.seed();val frozen=h.frozen();val ticket=h.ticket()
            val oldJob=h.scheduler.enqueue(ticket,90000);h.scheduler.installWatch()
            val before=h.databaseImage();val jobs=h.workImage();val oldState=h.db.syncWorkDao().state(h.lease.storageScope)!!
            assertNull(h.runtime.current());h.runtime.signal(resumeBlocked=true,expected=ticket)
            assertEquals(SyncCoordinator.Outcome.Stopped("validation_trial"),h.runtime.manual(h.lease))
            assertEquals(SyncCoordinator.Outcome.Stopped("validation_trial"),h.runtime.execute(ticket))
            h.runtime.reschedule(ticket,SyncCoordinator.Outcome.Deferred(90000));h.worker(ticket);h.watch()
            val beforeObserver=trial.attempts.value;h.runtime.observe(h.scope,h.sessions)
            // Account/context and existing outbox each reach the closed boundary.
            trial.attempted(beforeObserver+2)
            val beforePolicy=trial.attempts.value;h.gate.block();h.sessions.value=SyncSessionSignal(h.lease,false,true)
            trial.attempted(beforePolicy+1)
            val beforeAllowed=trial.attempts.value;h.gate.allow();h.sessions.value=SyncSessionSignal(h.lease,true,true)
            trial.attempted(beforeAllowed+1)
            assertEquals(before,h.databaseImage());assertEquals(jobs,h.workImage())
            assertEquals(0,h.calls.get());assertEquals(0,h.drains.get())
            val current=h.ticket();assertNotEquals(ticket.uniqueName(),current.uniqueName())
            trial.open()
            val resumed=h.state {it.requestedVersion>oldState.requestedVersion}
            assertEquals("push",resumed.phase);assertEquals(90000L,resumed.retryAtMillis);assertEquals(2,resumed.consecutiveFailures)
            val fresh=h.jobs(current){rows->rows.any {it.id!=oldJob.id && it.state==WorkInfo.State.ENQUEUED}}
                .first {it.id!=oldJob.id && it.state==WorkInfo.State.ENQUEUED}
            assertEquals(0,h.calls.get());assertArrayEquals(frozen.batch.body(),h.db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
            h.clock=90000
            val driver=WorkManagerTestInitHelper.getTestDriver(context)!!;driver.setAllConstraintsMet(fresh.id);driver.setInitialDelayMet(fresh.id)
            h.state {it.status=="login"};assertEquals(1,h.calls.get());assertEquals(listOf(h.lease),h.executedOwners.toList())
            assertTrue(h.drains.get()>0);assertEquals(frozen.batch.sha256,h.db.pushDao().batch(frozen.id)!!.requestHash)
        }finally{h.close()}
    }

    @Test fun pausedLoginConfigurationAndOutboxEventsAreNotConsumedBeforeChangesReevaluatesThem()=runBlocking<Unit> {
        for(reason in listOf("login","not_configured")) {
            val trial=TrialAdmission(false);val h=Harness(trial)
            try {
                h.seed();val frozen=h.frozen();h.sessions.value=SyncSessionSignal(h.lease,false,false)
                val initial=h.db.syncWorkDao().state(h.lease.storageScope)!!
                h.db.syncWorkDao().save(initial.copy(status=reason))
                val initialEntries=trial.completed.value
                h.runtime.observe(h.scope,h.sessions)
                withTimeout(15_000){trial.completed.first {it>=initialEntries+2}}
                trial.pause()
                assertEquals(reason,h.db.syncWorkDao().state(h.lease.storageScope)!!.status)
                val pausedEntries=trial.attempts.value
                h.sessions.value=SyncSessionSignal(h.lease,true,true)
                // A normal local edit is outside the runtime; preserve it while refusing its wakeup.
                DiaryRepository(h.db,context,h.lease).addWeight(80.125,LocalDate.of(2001,1,3))
                trial.attempted(pausedEntries+2)
                val before=h.databaseImage();val jobs=h.workImage()
                val blocked=h.db.syncWorkDao().state(h.lease.storageScope)!!
                assertEquals(reason,blocked.status);assertEquals(0,h.calls.get());assertEquals(0,h.drains.get())
                assertEquals(before,h.databaseImage());assertEquals(jobs,h.workImage())
                trial.open()
                // Both the held session event and the held outbox row must be reevaluated. No new edit/session signal is sent.
                val resumed=h.state {it.status=="ready" && it.requestedVersion>=blocked.requestedVersion+2}
                assertEquals("push",resumed.phase);assertEquals(90000L,resumed.retryAtMillis)
                val fresh=h.jobs(h.ticket()){rows->rows.any {it.state==WorkInfo.State.ENQUEUED}}.first {it.state==WorkInfo.State.ENQUEUED}
                assertEquals(0,h.calls.get());h.clock=90000
                val driver=WorkManagerTestInitHelper.getTestDriver(context)!!;driver.setAllConstraintsMet(fresh.id);driver.setInitialDelayMet(fresh.id)
                h.state {it.status=="login"};assertEquals(1,h.calls.get())
                assertEquals(frozen.batch.sha256,h.db.pushDao().batch(frozen.id)!!.requestHash)
            }finally{h.close()}
        }
    }

    @Test fun pausingActiveManualCancelsExecutorWaitsForFinallyAndCannotAckOrRescheduleOutsideBoundary()=runBlocking<Unit> {
        val trial=TrialAdmission(false);val h=Harness(trial)
        val entered=CompletableDeferred<Unit>();val finished=CompletableDeferred<Unit>();var pending:Deferred<SyncCoordinator.Outcome>?=null
        try {
            h.seed();val frozen=h.frozen(deadline=0);val row=h.db.pushDao().batch(frozen.id)!!
            val operation=h.db.dao().operation(frozen.operations.single().operationId)!!;val ticket=h.ticket()
            h.answer={entered.complete(Unit);try{awaitCancellation()}finally{finished.complete(Unit)}}
            pending=async {h.runtime.manual(h.lease)};withTimeout(15_000){entered.await()}
            assertTrue(trial.active.value>0);trial.pause();withTimeout(15_000){finished.await()}
            assertTrue(pending.isCancelled);assertEquals(0,trial.active.value)
            assertEquals(row,h.db.pushDao().batch(frozen.id));assertEquals(operation,h.db.dao().operation(operation.operationId))
            val stopped=h.db.syncWorkDao().state(h.lease.storageScope)!!;assertEquals("push",stopped.phase);assertEquals(0,stopped.acknowledged)
            val before=h.databaseImage();val jobs=h.workImage()
            h.runtime.signal();h.runtime.reschedule(ticket,SyncCoordinator.Outcome.Deferred(90000))
            assertEquals(before,h.databaseImage());assertEquals(jobs,h.workImage());assertEquals(1,h.calls.get())
            assertNull(h.db.pushDao().batch(frozen.id)!!.responseJson)
        }finally{pending?.cancelAndJoin();h.close()}
    }

    @Test fun staleOwnerInputsDuringPauseCannotBecomeFreshOwnerWorkAfterAdmissionOpens()=runBlocking<Unit> {
        val trial=TrialAdmission(true);val h=Harness(trial)
        try {
            h.seed();val a=h.lease;val frozen=h.frozen();val old=h.ticket();val aState=h.db.syncWorkDao().state(a.storageScope)
            val b=h.account();h.lease=b.first;h.binding=b.second
            val before=h.databaseImage();val jobs=h.workImage()
            assertEquals(SyncCoordinator.Outcome.Stopped("validation_trial"),h.runtime.manual(a))
            assertEquals(SyncCoordinator.Outcome.Stopped("validation_trial"),h.runtime.execute(old))
            h.runtime.reschedule(old,SyncCoordinator.Outcome.Deferred(90000))
            val beforeObserver=trial.attempts.value;h.runtime.observe(h.scope,h.sessions);trial.attempted(beforeObserver+1)
            assertEquals(before,h.databaseImage());assertEquals(jobs,h.workImage())
            val beforeOpen=trial.attempts.value;trial.open();trial.attempted(beforeOpen+1)
            assertEquals(aState,h.db.syncWorkDao().state(a.storageScope));assertNull(h.db.syncWorkDao().state(h.lease.storageScope))
            assertEquals(SyncCoordinator.Outcome.Stale,h.runtime.manual(a));assertEquals(SyncCoordinator.Outcome.Stale,h.runtime.execute(old))
            assertEquals(0,h.calls.get());h.sessions.value=SyncSessionSignal(h.lease,true,true)
            h.state {it.requestedVersion>0}
            val fresh=h.jobs(h.ticket()){rows->rows.any {it.state==WorkInfo.State.ENQUEUED}}.first {it.state==WorkInfo.State.ENQUEUED}
            WorkManagerTestInitHelper.getTestDriver(context)!!.setAllConstraintsMet(fresh.id)
            h.state {it.status=="login"};assertEquals(listOf(h.lease),h.executedOwners.toList())
            assertEquals(aState,h.db.syncWorkDao().state(a.storageScope));assertEquals(frozen.batch.sha256,h.db.pushDao().batch(frozen.id)!!.requestHash)
        }finally{h.close()}
    }

    @Test fun cancellationAtAdmissionPauseDoesNotConsumeObserverEventAndChangesReplaysIt()=runBlocking<Unit> {
        val trial=TrialAdmission(false);val h=Harness(trial)
        val entered=CompletableDeferred<Unit>();val exited=CompletableDeferred<Unit>();val replayed=CompletableDeferred<Unit>()
        val first=java.util.concurrent.atomic.AtomicBoolean(true)
        try {
            h.seed();val frozen=h.frozen();h.gate.block()
            h.localAnswer={
                if(first.getAndSet(false)) {
                    entered.complete(Unit);try{awaitCancellation()}finally{exited.complete(Unit)}
                } else {replayed.complete(Unit);SavedSyncEvidenceResult.NO_LOCAL_WORK}
            }
            val observer=h.runtime.observe(h.scope,h.sessions)
            withTimeout(15_000){entered.await()}
            trial.pause();withTimeout(15_000){exited.await()}
            assertTrue("observer must survive cancellation of just its admitted entry",observer.isActive)
            val before=h.databaseImage();val jobs=h.workImage();val version=h.db.syncWorkDao().state(h.lease.storageScope)!!.requestedVersion
            h.runtime.signal();assertEquals(SyncCoordinator.Outcome.Stopped("validation_trial"),h.runtime.manual(h.lease))
            assertEquals(before,h.databaseImage());assertEquals(jobs,h.workImage())
            trial.open() // No new Room, session, or network event: replay only through admission.changes.
            withTimeout(15_000){replayed.await()}
            val resumed=h.state {it.requestedVersion>version && it.status=="network_blocked"}
            assertEquals("push",resumed.phase);assertEquals(90000L,resumed.retryAtMillis)
            assertTrue(observer.isActive);assertEquals(0,h.calls.get());assertTrue(h.drains.get()>=2)
            assertEquals(frozen.batch.sha256,h.db.pushDao().batch(frozen.id)!!.requestHash)
        }finally{h.close()}
    }

    @Test fun defaultOpenAdmissionPreservesNormalManualExecution()=runBlocking<Unit> {
        val h=Harness()
        try {
            h.seed();assertEquals(h.lease,h.runtime.current()!!.first)
            assertEquals(SyncCoordinator.Outcome.Stopped("login"),h.runtime.manual(h.lease))
            assertEquals(1,h.calls.get());assertTrue(h.drains.get()>0)
        }finally{h.close()}
    }
}
