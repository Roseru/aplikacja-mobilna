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
}
