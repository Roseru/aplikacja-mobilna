package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

/** Synthetic server pages/ACK, real Room context changes and original ordinary push. */
class ReconciliationStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun uuid()=UUID.randomUUID().toString()
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/reconcile",uuid()).id)
        val boot=AccountBootstrapStore(db);boot.apply(boot.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-23T12:00:00Z"))
        val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
        assertNull(snapshots.apply(snapshots.begin(lease),page(epoch)))
        return lease
    }
    private fun page(currentEpoch:String,entities:List<JSONObject> = emptyList(),checkpoint:String="synthetic-checkpoint",receipts:List<JSONObject> = emptyList(),mappings:List<JSONObject> = emptyList(),timelineRevision:Int=0):ByteArray=
        JSONObject().put("sync_epoch",currentEpoch).put("mode","snapshot").put("snapshot_token","synthetic-snapshot")
            .put("page_token",JSONObject.NULL).put("checkpoint",checkpoint).put("server_time","2026-10-23T14:00:00Z")
            .put("goal_timeline_revision",timelineRevision).put("entities",JSONArray(entities)).put("recovery_mappings",JSONArray(mappings))
            .put("operation_receipts",JSONArray(receipts)).toString().toByteArray()
    private fun entity(operation:OutboxEntity,revision:Int=1):JSONObject=JSONObject().put("entity_id",operation.entityId).put("entity_type",operation.entityType)
        .put("revision",revision).put("deleted",operation.action=="delete").put("payload",if(operation.action=="delete")JSONObject.NULL else JSONObject(operation.payload))
    private fun reply(batch:PushBatch):ByteArray {
        val ops=batch.json().getJSONArray("operations");val results=JSONArray()
        for(i in 0 until ops.length()) {
            val op=ops.getJSONObject(i);val revision=if(op.isNull("base_revision"))1 else op.getInt("base_revision")+1
            val mapping=op.optJSONObject("recovery")?.let {source->JSONObject().put("source_epoch",source.getString("source_epoch"))
                .put("source_entity_id",source.getString("source_entity_id")).put("target_entity_id",op.getString("entity_id")).put("target_revision",revision)}
            results.put(JSONObject().put("operation_id",op.getString("operation_id")).put("entity_id",op.getString("entity_id"))
                .put("status","accepted").put("revision",revision).put("recovery_mapping",mapping ?: JSONObject.NULL))
        }
        return JSONObject().put("sync_epoch",batch.json().getString("sync_epoch")).put("server_time","2026-10-23T14:00:00Z").put("results",results).toString().toByteArray()
    }
    private suspend fun expire(db:CalorieDatabase,lease:OwnerLease,request:MealPushRequest):AccountBindingEntity {
        MealPushStore(db,schema).requireReconciliation(request)
        val old=db.bootstrapDao().binding(lease.storageScope)!!;val boot=AccountBootstrapStore(db)
        val binding=boot.apply(boot.begin(lease),BootstrapResponse(old.accountId,old.syncEpoch,old.accountGeneration,"2026-10-23T13:00:00Z"))
        assertTrue(binding.requiresRecovery);return binding
    }
    private suspend fun plan(store:ReconciliationStore,lease:OwnerLease,binding:AccountBindingEntity):ImportProgress {
        val plan=store.begin(lease,binding);store.approve(lease,binding,plan.planId,plan.account,plan.issuer,plan.subject);return plan
    }
    private suspend fun pull(db:CalorieDatabase,store:ReconciliationStore,lease:OwnerLease,binding:AccountBindingEntity,plan:ImportProgress,
        entities:List<JSONObject> = emptyList(),checkpoint:String="synthetic-new-checkpoint",mappings:List<JSONObject> = emptyList(),receipts:List<JSONObject> = emptyList(),timelineRevision:Int=0):SnapshotRequest {
        val request=store.nextSnapshot(lease,binding,plan.planId)!!
        assertNull(ServerSnapshotStore(db,SnapshotProtocol(schema)).apply(request,page(binding.syncEpoch,entities,checkpoint,receipts,mappings,timelineRevision)))
        store.acceptCompletedSnapshot(lease,binding,plan.planId,request.runId);return request
    }
    private suspend fun rejects(action:suspend ()->Unit) {var rejected=false;try{action()}catch(_:Exception){rejected=true};assertTrue(rejected)}
    @Test fun ordinaryCopyAfterRecoveryAckCannotPreventRequestingFreshTypedPlanSnapshot()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);DiaryRepository(db,context,lease).addWeight(80.125,LocalDate.of(2001,1,2))
            val ordinary=MealPushStore(db,schema);val frozen=ordinary.prepare(lease)!!;ordinary.markAttempted(frozen)
            val original=db.dao().operation(frozen.operations.single().operationId)!!
            val binding=expire(db,lease,frozen);val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
            pull(db,store,lease,binding,plan);val source=db.importDao().sources(plan.planId).single()
            store.decide(lease,binding,plan.planId,source.entityType,source.sourceId,source.sourceHash,"{\"choice\":\"replay_original\"}")
            val request=store.preparePush(lease,binding,plan.planId)!!;store.markAttempted(request)
            store.applyAck(store.prepareAck(request,200,reply(request.batch)))
            val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
            assertNull(snapshots.apply(snapshots.begin(lease),page(binding.syncEpoch,checkpoint="ordinary-after-ack")))
            rejects {store.finish(lease,binding,plan.planId)}
            val fresh=store.nextSnapshot(lease,binding,plan.planId)
            assertNotNull("Ordinary copy must not make the plan impossible to resume",fresh)
            assertEquals(plan.planId,db.importDao().pull(fresh!!.runId)!!.planId)
            assertNull(snapshots.apply(fresh,page(binding.syncEpoch,listOf(entity(original)),checkpoint="typed-after-ack")))
            store.acceptCompletedSnapshot(lease,binding,plan.planId,fresh.runId)
            assertEquals(1,store.finish(lease,binding,plan.planId).included)
            assertFalse(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
        }finally{db.close()}
    }
    @Test fun checkpointExpiryReenvelopesIdenticalOperationAndFinishesOnlyAfterAckAndFreshFullCopy()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease)
            repo.addWeight(80.125,LocalDate.of(2001,1,2))
            val ordinary=MealPushStore(db,schema);val old=ordinary.prepare(lease)!!;ordinary.markAttempted(old)
            val original=db.dao().operation(old.operations.single().operationId)!!
            val bytes=old.batch.body();val hash=old.batch.sha256
            val binding=expire(db,lease,old);val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
            val first=pull(db,store,lease,binding,plan)
            assertTrue(first.query.encoded().contains("recovery_operation_ids="+original.operationId))
            val source=db.importDao().sources(plan.planId).single()
            assertEquals("same_epoch_review",source.decisionCode)
            store.decide(lease,binding,plan.planId,source.entityType,source.sourceId,source.sourceHash,"{\"choice\":\"replay_original\"}")
            val request=store.preparePush(lease,binding,plan.planId)!!
            assertNotEquals(hash,request.batch.sha256)
            assertEquals(original.wireJson,StrictJsonForTest.operation(request.batch))
            assertEquals(original.operationId,request.operations.single().operationId)
            assertEquals(original.wireContext,request.operations.single().wireContext)
            assertArrayEquals(bytes,db.pushDao().batch(old.id)!!.requestJson.toByteArray())
            assertEquals(hash,db.pushDao().batch(old.id)!!.requestHash)
            rejects {store.finish(lease,binding,plan.planId)}
            store.markAttempted(request)
            val reopened=ReconciliationStore(db,schema).preparePush(lease,binding,plan.planId)!!
            assertArrayEquals(request.batch.body(),reopened.batch.body())
            store.applyAck(store.prepareAck(request,200,reply(request.batch)))
            assertTrue(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            rejects {store.finish(lease,binding,plan.planId)}
            pull(db,store,lease,binding,plan,listOf(entity(original)))
            val application=store.finish(lease,binding,plan.planId)
            assertEquals(1,application.included)
            val ready=db.bootstrapDao().binding(lease.storageScope)!!;assertFalse(ready.requiresRecovery)
            assertEquals(1,db.weightSyncDao().state(lease.storageScope,original.entityId)!!.serverRevision)
            assertEquals("acked",db.dao().operation(original.operationId)!!.status)
            assertEquals("archived_reconciled",db.pushDao().batch(old.id)!!.state)
            assertArrayEquals(bytes,db.pushDao().batch(old.id)!!.requestJson.toByteArray())
            assertNull(ordinary.prepare(lease));assertEquals(application,store.finish(lease,ready,plan.planId))
        } finally {db.close()}
    }
    @Test fun knownSameEpochAbsenceCannotReplayOrRecreateAndExplicitServerChoiceKeepsOriginalBytes()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease);repo.addWeight(80.0,LocalDate.of(2001,1,2))
            val push=MealPushStore(db,schema);val created=push.prepare(lease)!!;push.markAttempted(created)
            push.applyAck(push.prepareAck(created,200,reply(created.batch)))
            val id=created.operations.single().entityId;repo.editWeight(id,81.0)
            val pending=push.prepare(lease)!!;push.markAttempted(pending)
            val body=pending.batch.body();val binding=expire(db,lease,pending);val store=ReconciliationStore(db,schema)
            val plan=plan(store,lease,binding);pull(db,store,lease,binding,plan)
            val source=db.importDao().sources(plan.planId).single();assertEquals("absent_same_epoch",source.decisionCode)
            rejects {store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"replay_original\"}")}
            rejects {store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"recreate_missing\"}")}
            store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"accept_server\"}")
            assertNull(store.preparePush(lease,binding,plan.planId))
            store.finish(lease,binding,plan.planId)
            assertTrue(db.dao().weight(id,lease.storageScope)!!.deleted)
            assertEquals("local_only",db.dao().operation(pending.operations.single().operationId)!!.status)
            assertArrayEquals(body,db.pushDao().batch(pending.id)!!.requestJson.toByteArray())
            assertTrue(db.serverDiaryDao().records(lease.storageScope).single().absent)
            assertFalse(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
        } finally {db.close()}
    }
    private suspend fun changedEpoch(db:CalorieDatabase,lease:OwnerLease):AccountBindingEntity {
        val old=db.bootstrapDao().binding(lease.storageScope)!!;val boot=AccountBootstrapStore(db)
        return boot.apply(boot.begin(lease),BootstrapResponse(old.accountId,"66666666-6666-4666-8666-666666666666",old.accountGeneration,"2026-10-23T13:00:00Z"))
    }
    private fun mapping(source:ImportSource,target:String,revision:Int)=JSONObject().put("source_epoch",source.sourceEpoch)
        .put("source_entity_id",JSONObject(source.sourceJson).getString("wire_id")).put("target_entity_id",target).put("target_revision",revision)
    private suspend fun oldAcceptedWeight(db:CalorieDatabase,lease:OwnerLease):MealPushRequest {
        DiaryRepository(db,context,lease).addWeight(80.125,LocalDate.of(2001,1,2))
        val store=MealPushStore(db,schema);val request=store.prepare(lease)!!;store.markAttempted(request)
        store.applyAck(store.prepareAck(request,200,reply(request.batch)));return request
    }
    @Test fun newEpochUsesNewOperationAndExplicitSourceWithoutReceiptThenPreservesLocalIdentityAfterFinalCopy()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val old=oldAcceptedWeight(db,lease);val oldOp=db.dao().operation(old.operations.single().operationId)!!
            val body=old.batch.body();val binding=changedEpoch(db,lease);assertTrue(binding.requiresRecovery)
            val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding);pull(db,store,lease,binding,plan)
            val source=db.importDao().sources(plan.planId).single();assertEquals("epoch_recovery_review",source.decisionCode)
            store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"recreate_missing\"}")
            val request=store.preparePush(lease,binding,plan.planId)!!;val op=request.batch.json().getJSONArray("operations").getJSONObject(0)
            assertNotEquals(oldOp.operationId,op.getString("operation_id"));assertNotEquals(oldOp.entityId,op.getString("entity_id"))
            assertEquals(binding.syncEpoch,op.getString("sync_epoch"));assertEquals(epoch,op.getJSONObject("recovery").getString("source_epoch"))
            assertEquals(oldOp.operationId,op.getJSONObject("recovery").getString("source_operation_id"));assertEquals(1,op.getJSONObject("recovery").getInt("source_revision"))
            assertEquals(oldOp,db.dao().operation(oldOp.operationId));assertArrayEquals(body,db.pushDao().batch(old.id)!!.requestJson.toByteArray())
            store.markAttempted(request);store.applyAck(store.prepareAck(request,200,reply(request.batch)))
            val target=op.getString("entity_id");val row=entity(request.operations.single())
            pull(db,store,lease,binding,plan,listOf(row),mappings=listOf(mapping(source,target,1)))
            store.finish(lease,binding,plan.planId)
            assertFalse(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            assertEquals(oldOp.entityId,db.importDao().wire(lease.storageScope,"weight",target)!!.localId)
            assertEquals("2001-01-02",db.dao().weight(oldOp.entityId,lease.storageScope)!!.localDate)
            assertEquals(oldOp,db.dao().operation(oldOp.operationId));assertArrayEquals(body,db.pushDao().batch(old.id)!!.requestJson.toByteArray())
            DiaryRepository(db,context,lease).editWeight(oldOp.entityId,82.0)
            val ordinary=MealPushStore(db,schema).prepare(lease)!!
            assertEquals(target,ordinary.operations.single().entityId);assertEquals(1,ordinary.operations.single().baseRevision)
            assertFalse(ordinary.batch.json().getJSONArray("operations").getJSONObject(0).has("recovery"))
        } finally {db.close()}
    }
    @Test fun anotherDeviceMappingWithCompactReceiptRequiresTypedSnapshotBeforeAnyAck()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);oldAcceptedWeight(db,lease);val binding=changedEpoch(db,lease)
            val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding);pull(db,store,lease,binding,plan)
            val source=db.importDao().sources(plan.planId).single()
            store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"recreate_missing\"}")
            val request=store.preparePush(lease,binding,plan.planId)!!;store.markAttempted(request)
            val target=uuid();val mapped=mapping(source,target,7)
            val receipt=JSONObject().put("sync_epoch",binding.syncEpoch).put("server_time","2026-10-23T14:00:00Z")
                .put("results",JSONArray().put(JSONObject().put("operation_id",request.operations.single().operationId)
                    .put("entity_id",request.operations.single().entityId).put("status","already_applied").put("revision",5).put("recovery_mapping",mapped))).toString().toByteArray()
            val pending=store.prepareAck(request,200,receipt);assertTrue(pending.result.awaitingSnapshot)
            store.applyAck(pending)
            assertEquals("recovery_pending",db.dao().operation(request.operations.single().operationId)!!.status)
            assertEquals("queued",db.importDao().sources(plan.planId).single().state)
            rejects {store.requireCurrent(request)} // No second HTTP while its valid reply awaits proof.
            val server=entity(request.operations.single(),7).put("entity_id",target)
            pull(db,store,lease,binding,plan,listOf(server),mappings=listOf(mapped))
            val reopened=store.preparePush(lease,binding,plan.planId)!!;assertTrue(reopened.needsAckRevalidation)
            store.applyAck(store.prepareAck(reopened,200,reopened.savedResponse()!!))
            assertEquals(target,db.importDao().sources(plan.planId).single().wireId)
            store.finish(lease,binding,plan.planId)
            val state=db.weightSyncDao().state(lease.storageScope,source.localId)!!
            assertEquals(7,state.serverRevision);assertEquals(source.localId,db.importDao().wire(lease.storageScope,"weight",target)!!.localId)
            assertEquals("acked",db.dao().operation(request.operations.single().operationId)!!.status)
        } finally {db.close()}
    }
    @Test fun receiptPlanOverOneHundredIdsPersistsBothGroupsAndNeverCompletesAfterFirstGroup()=runBlocking<Unit> {
        val name="receipt-groups-${uuid()}"
        fun open()=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        var db=open()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease)
            repeat(101) {repo.addWeight(80.125,LocalDate.of(2001,1,2))}
            val push=MealPushStore(db,schema);val first=push.prepare(lease)!!;assertEquals(100,first.operations.size)
            push.markAttempted(first);push.applyAck(push.prepareAck(first,200,reply(first.batch)))
            val last=push.prepare(lease)!!;push.markAttempted(last)
            val binding=changedEpoch(db,lease);var store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
            val group0=pull(db,store,lease,binding,plan)
            assertEquals(100,group0.query.json().getJSONArray("recovery_operation_ids").length())
            val source=db.importDao().sources(plan.planId).first()
            rejects {store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"recreate_missing\"}")}
            val second=store.nextSnapshot(lease,binding,plan.planId)!!
            assertEquals(1,second.query.json().getJSONArray("recovery_operation_ids").length())
            val query=second.query.encoded();db.close();db=open();store=ReconciliationStore(db,schema)
            val resumed=store.nextSnapshot(lease,binding,plan.planId)!!;assertEquals(second.runId,resumed.runId);assertEquals(query,resumed.query.encoded())
            assertNull(ServerSnapshotStore(db,SnapshotProtocol(schema)).apply(resumed,page(binding.syncEpoch)))
            store.acceptCompletedSnapshot(lease,binding,plan.planId,resumed.runId)
            assertEquals(2,db.importDao().evidence(plan.planId).count {it.kind=="receipt_group"})
            store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"recreate_missing\"}")
            assertTrue(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            rejects {store.finish(lease,binding,plan.planId)}
        } finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun unrelatedHistoricalMappingsToDeletedAndRetainedTargetsDoNotBlockFullSnapshotOrFinish()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val binding=changedEpoch(db,lease);val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
            val deleted=uuid();val retained=uuid()
            fun historical(target:String)=JSONObject().put("source_epoch",epoch).put("source_entity_id",uuid())
                .put("target_entity_id",target).put("target_revision",4)
            val dead=JSONObject().put("entity_type","weight").put("entity_id",deleted).put("revision",4).put("deleted",true).put("payload",JSONObject.NULL)
            val snapshot=pull(db,store,lease,binding,plan,listOf(dead),mappings=listOf(historical(deleted),historical(retained)))
            assertEquals(2,db.importDao().evidence(plan.planId).count {it.kind=="mapping"})
            assertEquals(1,db.importDao().evidence(plan.planId).count {it.kind=="receipt_group"})
            val application=store.finish(lease,binding,plan.planId)
            assertEquals(snapshot.runId,application.runId);assertFalse(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            assertNull(db.dao().weight(deleted,lease.storageScope));assertNull(db.dao().weight(retained,lease.storageScope))
        } finally {db.close()}
    }
    @Test fun historicalMappingReservationCannotAuthorizeRecreateOfDeletedOrRetainedTarget()=runBlocking<Unit> {
        for(deleted in listOf(false,true)) {
            val db=memory()
            try {
                val lease=account(db);val old=oldAcceptedWeight(db,lease);val binding=changedEpoch(db,lease)
                val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
                val source=db.importDao().sources(plan.planId).single();val target=uuid()
                val entities=if(deleted)listOf(JSONObject().put("entity_type","weight").put("entity_id",target).put("revision",4)
                    .put("deleted",true).put("payload",JSONObject.NULL)) else emptyList()
                pull(db,store,lease,binding,plan,entities,mappings=listOf(mapping(source,target,4)))
                store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"recreate_missing\"}")
                val count=db.dao().operationCount(lease.storageScope)
                rejects {store.preparePush(lease,binding,plan.planId)}
                assertEquals(count,db.dao().operationCount(lease.storageScope));assertTrue(db.importDao().batches(plan.planId).isEmpty())
                assertEquals("acked",db.dao().operation(old.operations.single().operationId)!!.status)
                assertTrue(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
                store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"preserve_local\"}")
                store.finish(lease,binding,plan.planId)
                assertFalse(db.dao().weight(source.localId,lease.storageScope)!!.deleted)
                assertEquals(80.125,db.dao().weight(source.localId,lease.storageScope)!!.kg,0.0)
                assertFalse(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            } finally {db.close()}
        }
    }
    @Test fun replayBeforeBeginNewerLocalIntentNeverAcceptsServerOverWaitingCreateOrUpdate()=runBlocking<Unit> {
        for(update in listOf(false,true)) {
            val db=memory()
            try {
                val lease=account(db);val repo=DiaryRepository(db,context,lease);val push=MealPushStore(db,schema)
                val id:String;var prior:OutboxEntity?=null
                if(update) {
                    val created=oldAcceptedWeight(db,lease);id=created.operations.single().entityId;prior=created.operations.single()
                    repo.editWeight(id,82.0)
                } else {repo.addWeight(80.0,LocalDate.of(2001,1,2));id=push.prepare(lease)!!.operations.single().entityId}
                val frozen=push.prepare(lease)!!;push.markAttempted(frozen)
                val intended=if(update)84.0 else 82.0
                repo.editWeight(id,intended)
                val local=db.dao().weight(id,lease.storageScope)!!
                val waiting=db.weightSyncDao().operations(lease.storageScope,id).single {it.operationId!=frozen.operations.single().operationId}
                assertEquals("waiting_revision",waiting.status);assertFalse(waiting.attempted);assertNull(waiting.wireJson)
                val bytes=frozen.batch.body();val hash=frozen.batch.sha256
                val binding=expire(db,lease,frozen);val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
                pull(db,store,lease,binding,plan,prior?.let {listOf(entity(it))} ?: emptyList())
                val source=db.importDao().sources(plan.planId).single()
                store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"replay_original\"}")
                val retry=store.preparePush(lease,binding,plan.planId)!!;store.markAttempted(retry)
                store.applyAck(store.prepareAck(retry,200,reply(retry.batch)))
                val acceptedRevision=if(update)2 else 1
                pull(db,store,lease,binding,plan,listOf(entity(frozen.operations.single(),acceptedRevision)))
                assertEquals("later_local_intent",db.importDao().sources(plan.planId).single().decisionCode)
                rejects {store.finish(lease,binding,plan.planId)}
                assertEquals(local,db.dao().weight(id,lease.storageScope));assertEquals(intended,db.dao().weight(id,lease.storageScope)!!.kg,0.0)
                assertEquals(waiting,db.dao().operation(waiting.operationId))
                assertEquals("acked",db.dao().operation(frozen.operations.single().operationId)!!.status)
                assertArrayEquals(bytes,db.pushDao().batch(frozen.id)!!.requestJson.toByteArray());assertEquals(hash,db.pushDao().batch(frozen.id)!!.requestHash)
                assertTrue(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
                assertEquals(source.sourceHash,db.importDao().sources(plan.planId).single().sourceHash)
            } finally {db.close()}
        }
    }
    @Test fun uncertainUpdateSourceRevisionComesFromThatOperationsReceiptAndNeverEarlierProjectionAck()=runBlocking<Unit> {
        for(receiptKind in listOf("missing","accepted","rejected")) {
            val db=memory()
            try {
                val lease=account(db);val created=oldAcceptedWeight(db,lease);val id=created.operations.single().entityId
                DiaryRepository(db,context,lease).editWeight(id,82.0)
                val push=MealPushStore(db,schema);val lost=push.prepare(lease)!!;push.markAttempted(lost)
                val original=db.dao().operation(lost.operations.single().operationId)!!
                assertEquals(1,original.baseRevision);assertEquals(1,db.weightSyncDao().state(lease.storageScope,id)!!.serverRevision)
                val bytes=lost.batch.body();val hash=lost.batch.sha256
                val binding=changedEpoch(db,lease);val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
                val source=db.importDao().sources(plan.planId).single()
                assertEquals(original.operationId,source.sourceOperationId);assertNull(source.sourceRevision)
                assertEquals(1,JSONObject(source.sourceJson).getInt("server_revision")) // Earlier create ACK remains historical projection evidence.
                val receipts=if(receiptKind=="missing")emptyList() else listOf(JSONObject().put("source_epoch",epoch)
                    .put("operation_id",original.operationId).put("entity_id",id).put("status",receiptKind)
                    .put("revision",if(receiptKind=="accepted")2 else JSONObject.NULL).put("code",if(receiptKind=="accepted")JSONObject.NULL else "invalid_payload"))
                pull(db,store,lease,binding,plan,receipts=receipts)
                store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"recreate_missing\"}")
                if(receiptKind=="rejected") {
                    val count=db.dao().operationCount(lease.storageScope)
                    rejects {store.preparePush(lease,binding,plan.planId)}
                    assertEquals(count,db.dao().operationCount(lease.storageScope));assertTrue(db.importDao().batches(plan.planId).isEmpty())
                } else {
                    val recovery=store.preparePush(lease,binding,plan.planId)!!
                    val reference=recovery.batch.json().getJSONArray("operations").getJSONObject(0).getJSONObject("recovery")
                    assertEquals(original.operationId,reference.getString("source_operation_id"))
                    if(receiptKind=="accepted")assertEquals(2,reference.getInt("source_revision")) else assertTrue(reference.isNull("source_revision"))
                    assertNotEquals(original.operationId,recovery.operations.single().operationId)
                    assertEquals(binding.syncEpoch,recovery.batch.json().getString("sync_epoch"))
                }
                assertEquals(original,db.dao().operation(original.operationId));assertArrayEquals(bytes,db.pushDao().batch(lost.id)!!.requestJson.toByteArray())
                assertEquals(hash,db.pushDao().batch(lost.id)!!.requestHash);assertTrue(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
                assertNull(db.importDao().sources(plan.planId).single().sourceRevision)
            } finally {db.close()}
        }
    }
    @Test fun mappedGoalKeepsHistoricalAxisWhileNewDecisionRequiresCurrentAxisAndSeparateProjection()=runBlocking<Unit> {
        for(mapped in listOf(true,false)) {
            val db=memory()
            try {
                val lease=account(db);val repo=DiaryRepository(db,context,lease)
                repo.setGoal(2500.0,null,0.0,null)
                val ordinary=MealPushStore(db,schema);val old=ordinary.prepare(lease)!!;ordinary.markAttempted(old)
                ordinary.applyAck(ordinary.prepareAck(old,200,reply(old.batch)))
                val op=db.dao().operation(old.operations.single().operationId)!!
                val original=db.dao().goalById(lease.storageScope,op.entityId)!!;val bytes=old.batch.body();val hash=old.batch.sha256
                val binding=changedEpoch(db,lease);val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
                val source=db.importDao().sources(plan.planId).single();val target=uuid()
                val mappedEntity=entity(op,5).put("entity_id",target)
                val mappedProof=mapping(source,target,5)
                pull(db,store,lease,binding,plan,if(mapped)listOf(mappedEntity) else emptyList(),
                    mappings=if(mapped)listOf(mappedProof) else emptyList(),timelineRevision=8)
                val choice=if(mapped)JSONObject().put("choice","resolve_existing").put("target_id",target)
                    else JSONObject().put("choice","new_goal_decision").put("payload",JSONObject(op.payload).put("energy_kcal","2600").put("timeline_base_revision",0))
                store.decide(lease,binding,plan.planId,"goal",source.sourceId,source.sourceHash,choice.toString())
                if(!mapped) {
                    rejects {store.preparePush(lease,binding,plan.planId)}
                    assertEquals(1,db.dao().operationCount(lease.storageScope))
                    choice.getJSONObject("payload").put("timeline_base_revision",8)
                    store.decide(lease,binding,plan.planId,"goal",source.sourceId,source.sourceHash,choice.toString())
                }
                val request=store.preparePush(lease,binding,plan.planId)!!
                val sent=request.operations.single();val payload=JSONObject(sent.payload)
                assertEquals(if(mapped)0 else 8,payload.getInt("timeline_base_revision"))
                assertEquals(if(mapped)"2500" else "2600",payload.getString("energy_kcal"));assertTrue(payload.isNull("protein_g"))
                store.markAttempted(request);store.applyAck(store.prepareAck(request,200,reply(request.batch)))
                val refreshed=db.importDao().sources(plan.planId).single();val revision=if(mapped)6 else 1
                val accepted=entity(sent,revision)
                pull(db,store,lease,binding,plan,listOf(accepted),mappings=listOf(mapping(source,refreshed.wireId,revision)),timelineRevision=if(mapped)8 else 9)
                val application=store.finish(lease,binding,plan.planId)
                assertEquals(0,application.held);assertFalse(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
                assertEquals(original,db.dao().goalById(lease.storageScope,original.id));assertEquals(op,db.dao().operation(op.operationId))
                assertArrayEquals(bytes,db.pushDao().batch(old.id)!!.requestJson.toByteArray());assertEquals(hash,db.pushDao().batch(old.id)!!.requestHash)
                val finalSource=db.importDao().sources(plan.planId).single()
                if(mapped)assertEquals(original.id,finalSource.localId) else {
                    assertNotEquals(original.id,finalSource.localId)
                    assertEquals(2600.0,db.dao().goalById(lease.storageScope,finalSource.localId)!!.kcal,0.0)
                    assertTrue(db.resolvedOriginalGoals(lease.storageScope).contains(original.id))
                    assertEquals("Resolved immutable history must not become a second legacy import",0,LegacyImportStore(db,schema).preview(lease,lease.storageScope).total)
                }
                repo.setGoal(2700.0,null,0.0,null)
                val following=ordinary.prepare(lease)!!
                assertEquals(finalSource.wireId,JSONObject(following.operations.single().payload).getString("correction_of"))
                assertEquals("history_correction",JSONObject(following.operations.single().payload).getString("reason"))
                assertEquals(original,db.dao().goalById(lease.storageScope,original.id))
            } finally {db.close()}
        }
    }
    @Test fun acceptingKnownAbsentProfileReleasesUniqueSlotWithoutChangingFrozenRequest()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease)
            repo.setProfile("Before",180.0,ActivityClass.LINE,DietAim.MAINTAIN)
            val push=MealPushStore(db,schema);val created=push.prepare(lease)!!;push.markAttempted(created)
            push.applyAck(push.prepareAck(created,200,reply(created.batch)));val id=created.operations.single().entityId
            repo.setProfile("Pending",181.0,ActivityClass.LINE,DietAim.MAINTAIN)
            val pending=push.prepare(lease)!!;push.markAttempted(pending);val bytes=pending.batch.body();val hash=pending.batch.sha256
            val binding=expire(db,lease,pending);val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
            pull(db,store,lease,binding,plan);val source=db.importDao().sources(plan.planId).single()
            assertEquals("absent_same_epoch",source.decisionCode)
            store.decide(lease,binding,plan.planId,"profile",source.sourceId,source.sourceHash,"{\"choice\":\"accept_server\"}")
            store.finish(lease,binding,plan.planId)
            assertNull(db.dao().currentProfile(lease.storageScope));assertTrue(db.domainSyncDao().state(lease.storageScope,"profile",id)!!.deleted)
            assertTrue(db.serverDiaryDao().records(lease.storageScope).single().absent)
            assertEquals("local_only",db.dao().operation(pending.operations.single().operationId)!!.status)
            assertArrayEquals(bytes,db.pushDao().batch(pending.id)!!.requestJson.toByteArray());assertEquals(hash,db.pushDao().batch(pending.id)!!.requestHash)
            repo.setProfile("Replacement",182.0,ActivityClass.LINE,DietAim.MAINTAIN)
            val replacement=push.prepare(lease)!!;assertNotEquals(id,replacement.operations.single().entityId)
            assertNull(replacement.operations.single().baseRevision);assertEquals("Replacement",db.dao().currentProfile(lease.storageScope)!!.nickname)
            assertTrue(db.domainSyncDao().state(lease.storageScope,"profile",id)!!.deleted)
        } finally {db.close()}
    }
    @Test fun ordinaryGoalAfterRetainingOldEpochHistoryDoesNotReferenceAbsentServerGoal()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease);repo.setGoal(2500.0,null,0.0,null)
            val push=MealPushStore(db,schema);val old=push.prepare(lease)!!;push.markAttempted(old)
            push.applyAck(push.prepareAck(old,200,reply(old.batch)))
            val op=db.dao().operation(old.operations.single().operationId)!!
            val historical=db.dao().goalById(lease.storageScope,op.entityId)!!;val bytes=old.batch.body();val hash=old.batch.sha256
            val binding=changedEpoch(db,lease);val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
            pull(db,store,lease,binding,plan)
            val source=db.importDao().sources(plan.planId).single()
            store.decide(lease,binding,plan.planId,"goal",source.sourceId,source.sourceHash,"{\"choice\":\"preserve_local\"}")
            store.finish(lease,binding,plan.planId)
            assertFalse(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            repo.setGoal(2600.0,null,0.0,null)
            val next=push.prepare(lease)!!;val payload=JSONObject(next.operations.single().payload)
            assertTrue("Historical E0 UUID must not become an E1 correction_of",payload.isNull("correction_of"))
            assertEquals("user_decision",payload.getString("reason"));assertEquals(0,payload.getInt("timeline_base_revision"))
            assertEquals(binding.syncEpoch,next.batch.json().getJSONArray("operations").getJSONObject(0).getString("sync_epoch"))
            assertNotEquals(op.entityId,next.operations.single().entityId)
            val fresh=db.dao().goalById(lease.storageScope,next.operations.single().entityId)!!
            assertNull(fresh.correctionOf);assertEquals("user_decision",fresh.reason)
            assertEquals(historical,db.dao().goalById(lease.storageScope,historical.id));assertEquals(op,db.dao().operation(op.operationId))
            assertArrayEquals(bytes,db.pushDao().batch(old.id)!!.requestJson.toByteArray());assertEquals(hash,db.pushDao().batch(old.id)!!.requestHash)
        } finally {db.close()}
    }
    @Test fun decisionProofIsCheckedAtomicallyAndChangedServerVersionRequiresNewConsentBeforeFinish()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val accepted=oldAcceptedWeight(db,lease)
            val original=db.dao().operation(accepted.operations.single().operationId)!!
            DiaryRepository(db,context,lease).editWeight(original.entityId,82.0)
            val push=MealPushStore(db,schema);val frozen=push.prepare(lease)!!;push.markAttempted(frozen)
            val bytes=frozen.batch.body();val hash=frozen.batch.sha256
            val binding=expire(db,lease,frozen);val store=ReconciliationStore(db,schema);val plan=plan(store,lease,binding)
            val r1=pull(db,store,lease,binding,plan,listOf(entity(original)))
            val source=db.importDao().sources(plan.planId).single()
            // R1 is the version shown by the VM. Publish R2 before the store write; no timing sleeps.
            suspend fun publish(value:String,revision:Int,checkpoint:String):SnapshotRequest {
                val request=ServerSnapshotStore(db,SnapshotProtocol(schema)).begin(lease,emptyList(),plan.planId,1)
                val payload=JSONObject(original.payload).put("weight_kg",value)
                val server=entity(original,revision).put("payload",payload)
                assertNull(ServerSnapshotStore(db,SnapshotProtocol(schema)).apply(request,page(binding.syncEpoch,listOf(server),checkpoint)))
                store.acceptCompletedSnapshot(lease,binding,plan.planId,request.runId);return request
            }
            val r2=publish("81",2,"synthetic-proof-r2")
            val before=db.importDao().sources(plan.planId);val point=db.dao().weight(source.sourceId,lease.storageScope)
            val operation=db.dao().operation(frozen.operations.single().operationId)!!;val count=db.dao().operationCount(lease.storageScope)
            rejects {store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"accept_server\"}",expectedProofRunId=r1.runId)}
            assertTrue(db.importDao().decisions(plan.planId).isEmpty());assertEquals(before,db.importDao().sources(plan.planId))
            assertEquals(point,db.dao().weight(source.sourceId,lease.storageScope));assertEquals(operation,db.dao().operation(operation.operationId))
            assertEquals(count,db.dao().operationCount(lease.storageScope));assertArrayEquals(bytes,db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
            assertEquals(hash,db.pushDao().batch(frozen.id)!!.requestHash)
            store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"accept_server\"}",expectedProofRunId=r2.runId)
            val decided=db.importDao().source(plan.planId,"weight",source.sourceId)!!
            val proof=JSONObject(decided.metadataJson).getJSONObject("decision_proof")
            assertEquals(r2.runId,proof.getString("run_id"));assertEquals(source.sourceHash,proof.getString("source_hash"))
            assertEquals("81",proof.getJSONObject("observation").getJSONObject("payload").getString("weight_kg"))
            assertEquals(1,db.importDao().decisions(plan.planId).size);assertEquals(point,db.dao().weight(source.sourceId,lease.storageScope))
            val r3=publish("83",3,"synthetic-proof-r3")
            rejects {store.finish(lease,binding,plan.planId)}
            val review=store.status(lease,binding,plan.planId)
            assertEquals("server_proof_changed",review.decisions.single().code)
            assertEquals(point,db.dao().weight(source.sourceId,lease.storageScope));assertEquals(operation,db.dao().operation(operation.operationId))
            assertEquals(1,db.importDao().decisions(plan.planId).size);assertEquals(count,db.dao().operationCount(lease.storageScope))
            assertEquals(decided.metadataJson,db.importDao().source(plan.planId,"weight",source.sourceId)!!.metadataJson)
            store.decide(lease,binding,plan.planId,"weight",source.sourceId,source.sourceHash,"{\"choice\":\"accept_server\"}",expectedProofRunId=r3.runId)
            store.finish(lease,binding,plan.planId)
            assertEquals(83.0,db.dao().weight(source.sourceId,lease.storageScope)!!.kg,0.0)
            assertEquals(2,db.importDao().decisions(plan.planId).size)
            assertArrayEquals(bytes,db.pushDao().batch(frozen.id)!!.requestJson.toByteArray());assertEquals(hash,db.pushDao().batch(frozen.id)!!.requestHash)
        } finally {db.close()}
    }
    private object StrictJsonForTest {
        fun operation(batch:PushBatch)=pl.roseru.kalorie.core.catalog.StrictJson.canonical(batch.json().getJSONArray("operations").getJSONObject(0))
    }
}
