package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
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

/** Real Room, immutable envelopes and ACKs, injected synthetic executor; not O1/HTTP integration. */
class SyncCoordinatorStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun uuid()=UUID.randomUUID().toString()
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/coordinator",uuid()).id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-23T12:00:00Z"))
        return lease
    }
    private inner class Server(val db:CalorieDatabase):SyncStepExecutor {
        val calls=mutableListOf<SyncStep>();val sent=mutableListOf<Pair<String,String>>()
        val records=linkedMapOf<String,JSONObject>();var loseNextAck=false
        override suspend fun executeSyncStep(expectedLease:OwnerLease,expectedContext:AccountBindingEntity,step:SyncStep):SyncStepResult {
            calls+=step
            if(step==SyncStep.PULL) {
                val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));var request:SnapshotRequest?=snapshots.begin(expectedLease)
                val chunks=records.values.toList().chunked(100).ifEmpty {listOf(emptyList())};val token=uuid();val run=request!!.runId
                for((index,rows)in chunks.withIndex()) {
                    val next=if(index==chunks.lastIndex)null else "page-${index+1}"
                    val value=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token",token)
                        .put("page_token",next?:JSONObject.NULL).put("checkpoint",if(next==null)"checkpoint-$token" else JSONObject.NULL)
                        .put("server_time","2026-10-23T12:00:00Z").put("goal_timeline_revision",0).put("entities",JSONArray(rows))
                        .put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
                    request=snapshots.apply(checkNotNull(request),value.toString().toByteArray())
                }
                return SyncStepResult.Completed(runId=run)
            }
            val push=MealPushStore(db,schema);val request=push.prepare(expectedLease)?:return SyncStepResult.Completed()
            push.markAttempted(request);sent+=request.id to request.batch.sha256
            val operations=request.batch.json().getJSONArray("operations");val results=JSONArray()
            for(index in 0 until operations.length()) {
                val op=operations.getJSONObject(index);val id=op.getString("entity_id")
                val revision=if(op.isNull("base_revision"))1 else op.getInt("base_revision")+1
                val already=records.containsKey(id)
                records[id]=JSONObject().put("entity_type",op.getString("entity_type")).put("entity_id",id).put("revision",revision)
                    .put("deleted",op.getString("action")=="delete").put("payload",op.get("payload"))
                results.put(JSONObject().put("operation_id",op.getString("operation_id")).put("entity_id",id)
                    .put("status",if(already)"already_applied" else "accepted").put("revision",revision).put("recovery_mapping",JSONObject.NULL))
            }
            if(loseNextAck){loseNextAck=false;throw CancellationException("Synthetic lost response")}
            val response=InstrumentationRegistry.getInstrumentation().context.assets.open("materialized-meal-push-response.json")
                .use {JSONObject(String(it.readBytes()))}.put("results",results)
            val ack=push.applyAck(push.prepareAck(request,200,response.toString().toByteArray()))
            return SyncStepResult.Completed(batchId=request.id,acknowledged=ack.acknowledged,refused=ack.refused)
        }
    }
    @Test fun completedPushIsNotAssumedEmptyAndEachBatchGetsFreshPullBeforeNextPush()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!
            repeat(125){DiaryRepository(db,context,lease).addWeight(80.0,LocalDate.of(2026,10,21))}
            val server=Server(db);val coordinator=SyncCoordinator(db,schema,server)
            coordinator.request(lease,binding);assertEquals(SyncCoordinator.Outcome.Complete,coordinator.run(lease,binding))
            assertTrue(server.sent.size>=2)
            assertEquals(0,db.serverDiaryDao().unsettled(lease.storageScope).size)
            assertEquals(125,server.records.size)
            assertEquals("idle",coordinator.state(lease)!!.status)
            assertEquals(SyncStep.PULL,server.calls.first());assertEquals(SyncStep.PULL,server.calls.last())
            for(index in server.calls.indices.filter {server.calls[it]==SyncStep.PUSH}) {
                assertEquals(SyncStep.PULL,server.calls[index-1]);assertEquals(SyncStep.PULL,server.calls[index+1])
            }
        }finally{db.close()}
    }
    @Test fun cancellationAfterPossibleCommitRetainsPhaseFrozenBodyAndOperationForReplay()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!
            DiaryRepository(db,context,lease).addWeight(82.0,LocalDate.of(2026,10,21))
            val server=Server(db).apply {loseNextAck=true};val coordinator=SyncCoordinator(db,schema,server)
            coordinator.request(lease,binding)
            try{coordinator.run(lease,binding);fail("Cancellation must propagate")}catch(_:CancellationException){}
            assertEquals("push",coordinator.state(lease)!!.phase)
            val batch=db.pushDao().pending(lease.storageScope).single();val queue=db.serverDiaryDao().unsettled(lease.storageScope)
            assertTrue(batch.attempted);assertNull(batch.responseJson)
            assertEquals(SyncCoordinator.Outcome.Complete,SyncCoordinator(db,schema,server).run(lease,binding))
            assertEquals(server.sent[0],server.sent[1]);assertEquals(1,server.records.size)
            assertTrue(queue.all {db.dao().operation(it.operationId)!!.status=="acked"})
        }finally{db.close()}
    }
    @Test fun retryAfterSurvivesReopenLogoutNewLeaseAndManualRequestWithoutEarlierExecution()=runBlocking<Unit> {
        val name="coordinator-${uuid()}";fun open()=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        var db=open();var clock=1_000L;var calls=0
        try {
            var lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!
            val first=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls++;SyncStepResult.RetryAt(90_000)},{clock})
            first.request(lease,binding);assertEquals(SyncCoordinator.Outcome.Deferred(90_000),first.run(lease,binding))
            db.close();db=open()
            val owners=LocalOwnerStore(db);owners.select(owners.ensureGuest().id);lease=owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
            val second=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls++;SyncStepResult.LoginRequired},{clock})
            second.request(lease,binding,true);assertEquals(SyncCoordinator.Outcome.Deferred(90_000),second.run(lease,binding));assertEquals(1,calls)
            clock=90_000;assertEquals(SyncCoordinator.Outcome.Stopped("login"),second.run(lease,binding));assertEquals(2,calls)
            assertEquals(90_000,second.state(lease)!!.retryAtMillis)
        }finally{db.close();context.deleteDatabase(name)}
    }
    @Test fun accountAbaWhileExecutorIsInFlightCannotAdvanceDurablePhaseOrApplyLateResult()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!
            val owners=LocalOwnerStore(db);var returned:OwnerLease?=null
            val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->
                owners.select(owners.ensureGuest().id);returned=owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
                SyncStepResult.Completed(runId=uuid())
            })
            coordinator.request(lease,binding);assertEquals(SyncCoordinator.Outcome.Stale,coordinator.run(lease,binding))
            assertEquals("pull_before",coordinator.state(returned!!)!!.phase)
            assertNull(db.serverDiaryDao().latest(lease.storageScope))
        }finally{db.close()}
    }
    @Test fun sharedManualWorkerMutexPreventsConcurrentExecutorLoopsWithoutSleeps()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!
            val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>();var calls=0
            val executor=SyncStepExecutor {_,_,_->calls++;entered.complete(Unit);release.await();SyncStepResult.LoginRequired}
            val manual=SyncCoordinator(db,schema,executor);val worker=SyncCoordinator(db,schema,executor)
            manual.request(lease,binding)
            coroutineScope {
                val running=async {manual.run(lease,binding)};entered.await()
                assertEquals(SyncCoordinator.Outcome.Busy,worker.run(lease,binding));assertEquals(1,calls)
                release.complete(Unit);assertEquals(SyncCoordinator.Outcome.Stopped("login"),running.await())
            }
        }finally{db.close()}
    }
    @Test fun loginOrReconciliationDoesNotRetryOnWriteUntilExplicitResume()=runBlocking<Unit> {
        for(result in listOf(SyncStepResult.LoginRequired,SyncStepResult.ReconciliationRequired("synthetic"),SyncStepResult.NotConfigured)) {
            val db=memory()
            try {
                val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!;var calls=0
                val coordinator=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls++;result})
                coordinator.request(lease,binding);assertTrue(coordinator.run(lease,binding) is SyncCoordinator.Outcome.Stopped)
                repeat(3){coordinator.request(lease,binding);assertTrue(coordinator.run(lease,binding) is SyncCoordinator.Outcome.Stopped)}
                assertEquals(1,calls)
                coordinator.request(lease,binding,true);coordinator.run(lease,binding);assertEquals(2,calls)
            }finally{db.close()}
        }
    }
    @Test fun zeroProgressResumesPushForNewIndependentWriteOrReleasedDependency()=runBlocking<Unit> {
        for(releaseDependency in listOf(false,true)) {
            val db=memory();var clock=1_000L
            try {
                val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!
                val repository=DiaryRepository(db,context,lease);val blockedId=uuid()
                repository.addWeight(80.0,LocalDate.of(2026,10,21),blockedId)
                val original=db.serverDiaryDao().unsettled(lease.storageScope).single()
                val waiting=original.copy(status="waiting_revision")
                db.dao().updateOperation(waiting)
                val server=Server(db);val coordinator=SyncCoordinator(db,schema,server){clock}
                coordinator.request(lease,binding)
                assertEquals(SyncCoordinator.Outcome.Deferred(11_000),coordinator.run(lease,binding))
                assertEquals(listOf(SyncStep.PULL,SyncStep.PUSH,SyncStep.PULL),server.calls)
                assertEquals("push",coordinator.state(lease)!!.phase)
                assertEquals(waiting,db.dao().operation(original.operationId));assertTrue(server.sent.isEmpty())
                val snapshot=db.snapshotDao().access(lease.storageScope)!!.activeRunId!!
                val checkpoint=db.snapshotDao().run(snapshot)!!.checkpoint
                val readyId=if(releaseDependency) {
                    db.dao().updateOperation(original);blockedId
                } else uuid().also {repository.addWeight(82.0,LocalDate.of(2026,10,22),it)}
                val readyOperationId=if(releaseDependency)original.operationId else db.weightSyncDao().operations(lease.storageScope,readyId).single().operationId
                coordinator.request(lease,binding)
                assertEquals(snapshot,db.snapshotDao().access(lease.storageScope)!!.activeRunId)
                assertEquals(checkpoint,db.snapshotDao().run(snapshot)!!.checkpoint)
                server.calls.clear();clock=11_000
                val resumed=SyncCoordinator(db,schema,server){clock}.run(lease,binding)
                assertEquals(SyncStep.PUSH,server.calls.first())
                assertEquals(1,server.sent.size);assertEquals(setOf(readyId),server.records.keys)
                val sentOperation=checkNotNull(db.dao().operation(readyOperationId))
                assertEquals("acked",sentOperation.status)
                if(releaseDependency)assertEquals(SyncCoordinator.Outcome.Complete,resumed)
                else {
                    assertTrue(resumed is SyncCoordinator.Outcome.Deferred)
                    assertEquals(waiting,db.dao().operation(original.operationId))
                    assertEquals(80.0,db.dao().weight(blockedId,lease.storageScope)!!.kg,0.0)
                }
            }finally{db.close()}
        }
    }
    @Test fun expiredRetryAtUsesDurableGrowingBackoffAcrossReopenAndPreservesFutureServerFloor()=runBlocking<Unit> {
        for(past in listOf(false,true)) {
            val name="expired-retry-${uuid()}"
            fun open()=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
            var db=open();var clock=1_000L;var calls=0
            val executor=SyncStepExecutor {_,_,_->calls++;SyncStepResult.RetryAt(if(past)0 else clock)}
            try {
                val lease=account(db);val binding=db.bootstrapDao().binding(lease.storageScope)!!
                val first=SyncCoordinator(db,schema,executor){clock}
                first.request(lease,binding)
                assertEquals(SyncCoordinator.Outcome.Deferred(11_000),first.run(lease,binding));assertEquals(1,calls)
                db.close();db=open()
                val resumed=SyncCoordinator(db,schema,executor){clock}
                resumed.request(lease,binding)
                assertEquals(SyncCoordinator.Outcome.Deferred(11_000),resumed.run(lease,binding));assertEquals(1,calls)
                clock=11_000
                assertEquals(SyncCoordinator.Outcome.Deferred(31_000),resumed.run(lease,binding));assertEquals(2,calls)
                assertEquals(2,resumed.state(lease)!!.consecutiveFailures)
                clock=31_000
                val future=SyncCoordinator(db,schema,SyncStepExecutor {_,_,_->calls++;SyncStepResult.RetryAt(121_000)}){clock}
                assertEquals(SyncCoordinator.Outcome.Deferred(121_000),future.run(lease,binding));assertEquals(3,calls)
                future.request(lease,binding)
                assertEquals(SyncCoordinator.Outcome.Deferred(121_000),future.run(lease,binding));assertEquals(3,calls)
            }finally{db.close();context.deleteDatabase(name)}
        }
    }
}
