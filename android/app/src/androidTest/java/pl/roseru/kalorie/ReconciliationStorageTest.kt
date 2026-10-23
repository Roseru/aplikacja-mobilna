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
    private fun page(currentEpoch:String,entities:List<JSONObject> = emptyList(),checkpoint:String="synthetic-checkpoint",receipts:List<JSONObject> = emptyList(),mappings:List<JSONObject> = emptyList()):ByteArray=
        JSONObject().put("sync_epoch",currentEpoch).put("mode","snapshot").put("snapshot_token","synthetic-snapshot")
            .put("page_token",JSONObject.NULL).put("checkpoint",checkpoint).put("server_time","2026-10-23T14:00:00Z")
            .put("goal_timeline_revision",0).put("entities",JSONArray(entities)).put("recovery_mappings",JSONArray(mappings))
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
        entities:List<JSONObject> = emptyList(),checkpoint:String="synthetic-new-checkpoint",mappings:List<JSONObject> = emptyList(),receipts:List<JSONObject> = emptyList()):SnapshotRequest {
        val request=store.nextSnapshot(lease,binding,plan.planId)!!
        assertNull(ServerSnapshotStore(db,SnapshotProtocol(schema)).apply(request,page(binding.syncEpoch,entities,checkpoint,receipts,mappings)))
        store.acceptCompletedSnapshot(lease,binding,plan.planId,request.runId);return request
    }
    private suspend fun rejects(action:suspend ()->Unit) {var rejected=false;try{action()}catch(_:Exception){rejected=true};assertTrue(rejected)}
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
    private object StrictJsonForTest {
        fun operation(batch:PushBatch)=pl.roseru.kalorie.core.catalog.StrictJson.canonical(batch.json().getJSONArray("operations").getJSONObject(0))
    }
}
