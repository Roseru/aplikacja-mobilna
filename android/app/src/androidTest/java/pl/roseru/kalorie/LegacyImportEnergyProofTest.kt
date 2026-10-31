package pl.roseru.kalorie

import androidx.room.Room
import androidx.room.withTransaction
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.energy.*
import java.util.UUID

/** Real guarded Room and production stores, synthetic wire only; no network or actual-account claim. */
class LegacyImportEnergyProofTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val energy get()=EnergySchema(context.assets.open("energy/energy.schema.json").use {it.readBytes()})
    private val protocol get()=SnapshotProtocol(schema,energy)
    private val epoch="11111111-1111-4111-8111-111111111111"
    private val shared="22222222-2222-4222-8222-222222222222"
    private fun uuid()=UUID.randomUUID().toString()
    private fun open(name:String)=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://identity.fixture/realm",uuid()).id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-24T09:00:00Z"))
        SyncProtocolStore(db).readScope(lease,checkNotNull(db.bootstrapDao().binding(lease.storageScope)),true)
        return lease
    }
    private fun version()=EnergyFixture.sample("version").put("entity_id",shared).put("revision",1).also {
        it.getJSONObject("payload").getJSONObject("audit").put("goal_timeline_revision",1)
    }
    private fun goal()=JSONObject().put("entity_type","goal").put("entity_id",shared).put("revision",1).put("deleted",false)
        .put("payload",JSONObject().put("effective_from","2026-10-01").put("decided_at","2026-10-01T09:00:00Z")
            .put("time_zone","UTC").put("goal_type","maintain").put("energy_kcal","2500")
            .put("protein_g",JSONObject.NULL).put("fat_g",JSONObject.NULL).put("carbs_g",JSONObject.NULL)
            .put("activity_class","line").put("estimate",version().getJSONObject("payload").getJSONObject("audit").getJSONObject("estimate"))
            .put("timeline_base_revision",0).put("reason","user_decision").put("correction_of",JSONObject.NULL))
    private fun page(rows:List<JSONObject>,checkpoint:String,mode:String="snapshot")=StrictJson.canonical(JSONObject()
        .put("sync_epoch",epoch).put("mode",mode).put("snapshot_token",if(mode=="snapshot")"snapshot-$checkpoint" else JSONObject.NULL)
        .put("page_token",JSONObject.NULL).put("checkpoint",checkpoint).put("server_time","2026-10-24T10:00:00Z")
        .put("goal_timeline_revision",1).put("entities",JSONArray(rows)).put("recovery_mappings",JSONArray())
        .put("operation_receipts",JSONArray())).toByteArray(Charsets.UTF_8)
    private suspend fun full(db:CalorieDatabase,lease:OwnerLease):String {
        val store=ServerSnapshotStore(db,protocol);val request=store.beginRead(lease,SyncProtocolScope.ENERGY_V1)
        assertEquals("snapshot",db.snapshotDao().run(request.runId)?.readMode)
        assertNull(store.apply(request,page(listOf(goal(),version()),"checkpoint-${uuid()}")))
        ServerDiaryStore(db,schema,energy).apply(lease,request.runId)
        return request.runId
    }
    private suspend fun delta(db:CalorieDatabase,lease:OwnerLease):String {
        val store=ServerSnapshotStore(db,protocol);val request=store.beginRead(lease,SyncProtocolScope.ENERGY_V1)
        assertEquals("incremental",db.snapshotDao().run(request.runId)?.readMode)
        assertNull(store.apply(request,page(emptyList(),"checkpoint-${uuid()}","incremental")))
        ServerDiaryStore(db,schema,energy).apply(lease,request.runId)
        return request.runId
    }
    private suspend fun rejected(block:suspend ()->Unit) {
        var refused=false
        try {block()}catch(error:CancellationException){throw error}catch(_:Exception){refused=true}
        assertTrue("Invalid, incomplete or foreign proof must refuse import",refused)
    }
    private fun source()=WeightEntity(uuid(),"guest","2026-10-23","2026-10-23T09:00:00Z","UTC",80.125)
    private fun reply(request:MealPushRequest)=JSONObject().put("sync_epoch",epoch).put("server_time","2026-10-24T11:00:00Z")
        .put("results",JSONArray(request.operations.map {op->JSONObject().put("operation_id",op.operationId)
            .put("entity_id",op.entityId).put("status","accepted").put("revision",1).put("recovery_mapping",JSONObject.NULL)}))
        .toString().toByteArray()
    private suspend fun importAndAck(db:CalorieDatabase,lease:OwnerLease,weight:WeightEntity,runId:String) {
        val binding=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        val savedRun=db.snapshotDao().run(runId);val savedPages=db.snapshotDao().pages(runId)
        val savedRecords=db.serverDiaryDao().records(lease.storageScope)
        val savedEnergy=db.canonicalEnergyDao().all(lease.storageScope,CanonicalMealRows.context(binding))
        val savedGoal=db.dao().goalById(lease.storageScope,shared)
        assertEquals(1,savedRecords.size);assertEquals("goal",savedRecords.single().entityType)
        assertEquals(shared,savedEnergy.single().entityId)
        val store=LegacyImportStore(db,schema,energy)
        val preview=store.preview(lease,"guest")
        assertEquals(1,preview.total);assertEquals(1,preview.pending);assertTrue(preview.decisions.isEmpty())
        assertEquals(0,db.dao().operationCount(lease.storageScope))
        assertEquals(preview.planId,store.preview(lease,"guest").planId)
        store.approve(lease,preview.planId,preview.account,preview.issuer,preview.subject)
        assertEquals(1,store.resume(lease,preview.planId).queued)
        val imported=store.source(lease,preview.planId,"weight",weight.id)
        assertEquals(weight.id,imported.wireId);assertNotEquals(weight.id,imported.localId)
        assertEquals(imported.sourceHash,LegacyImportStore.digest(imported.sourceJson))
        assertEquals(weight,db.dao().weight(weight.id,"guest"))
        val push=MealPushStore(db,schema);val request=checkNotNull(push.prepare(lease))
        assertEquals(SyncProtocolScope.ENERGY_V1,request.batch.protocolScope)
        assertEquals("weight",request.operations.single().entityType)
        assertEquals(weight.id,request.operations.single().entityId)
        val bytes=request.batch.body();val hash=request.batch.sha256
        push.markAttempted(request);push.applyAck(push.prepareAck(request,200,reply(request)))
        val ack=checkNotNull(db.dao().operation(checkNotNull(imported.operationId)))
        assertEquals("acked",ack.status);assertTrue(ack.attempted)
        assertEquals(1,db.weightSyncDao().state(lease.storageScope,imported.localId)?.serverRevision)
        assertEquals(1,store.status(lease,preview.planId).acknowledged)
        store.resume(lease,preview.planId)
        assertEquals(ack,db.dao().operation(ack.operationId));assertEquals(1,db.dao().operationCount(lease.storageScope))
        assertArrayEquals(bytes,push.open(lease,request.id).batch.body());assertEquals(hash,push.open(lease,request.id).batch.sha256)
        assertEquals(weight,db.dao().weight(weight.id,"guest"));assertEquals(0,db.dao().operationCount("guest"))
        assertEquals(savedRun,db.snapshotDao().run(runId));assertEquals(savedPages,db.snapshotDao().pages(runId))
        assertEquals(savedRecords,db.serverDiaryDao().records(lease.storageScope))
        assertEquals(savedEnergy,db.canonicalEnergyDao().all(lease.storageScope,CanonicalMealRows.context(binding)))
        assertEquals(savedGoal,db.dao().goalById(lease.storageScope,shared));assertEquals(binding,db.bootstrapDao().binding(lease.storageScope))
    }
    // These two baseline RED cases reference no new production reader/type. Only the constructor
    // energy argument needs omitting in an explicitly modified pre-fix test copy.
    @Test fun fullEnergyActiveProofImportsGuestAndPreservesOriginalWireAndRealAck()=runBlocking<Unit> {
        val name="legacy-energy-full-${uuid()}";val db=open(name)
        try {val lease=account(db);val weight=source();db.dao().saveWeight(weight)
            importAndAck(db,lease,weight,full(db,lease))
        }finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun incrementalEnergyActiveProofImportsGuestAndPreservesOriginalWireAndRealAck()=runBlocking<Unit> {
        val name="legacy-energy-incremental-${uuid()}";val db=open(name)
        try {val lease=account(db);val weight=source();db.dao().saveWeight(weight);val base=full(db,lease)
            val run=delta(db,lease);assertEquals(base,db.snapshotDao().run(run)?.baseRunId)
            assertEquals(0,db.snapshotDao().run(run)?.itemCount)
            importAndAck(db,lease,weight,run)
        }finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun reopenedIncrementalProofAfterRealArchiveCompactionNeedsNoHistoricalRawPages()=runBlocking<Unit> {
        val name="legacy-energy-compacted-${uuid()}";var db=open(name)
        try {
            var lease=account(db);val weight=source();db.dao().saveWeight(weight);full(db,lease)
            var current="";repeat(10){current=delta(db,lease)}
            val archived=db.snapshotDao().runs(lease.storageScope).filter {db.snapshotArchiveDao().receipt(it.id)!=null}
            assertTrue("Fixture must really compact an older raw run",archived.isNotEmpty())
            archived.forEach {assertTrue(db.snapshotDao().pages(it.id).isEmpty());assertNotNull(db.serverDiaryDao().application(it.id))}
            db.close();db=open(name);lease=LocalOwnerStore(db).currentLease()
            assertEquals(current,db.snapshotDao().access(lease.storageScope)?.activeRunId)
            importAndAck(db,lease,weight,current)
        }finally {db.close();context.deleteDatabase(name)}
    }
    private class RollbackProbe:RuntimeException()
    private suspend fun corruptAndRefuse(db:CalorieDatabase,lease:OwnerLease,change:suspend ()->Unit) {
        val access=db.snapshotDao().access(lease.storageScope);val records=db.serverDiaryDao().records(lease.storageScope)
        val weight=db.dao().weights("guest").first();val plans=db.importDao().plans(lease.storageScope)
        try {db.withTransaction {change();rejected {LegacyImportStore(db,schema,energy).preview(lease,"guest")};throw RollbackProbe()}}
        catch(_:RollbackProbe) { /* Restore deliberately inconsistent test metadata atomically. */ }
        assertEquals(access,db.snapshotDao().access(lease.storageScope));assertEquals(records,db.serverDiaryDao().records(lease.storageScope))
        assertEquals(weight,db.dao().weights("guest").first());assertEquals(plans,db.importDao().plans(lease.storageScope))
        assertEquals(0,db.dao().operationCount(lease.storageScope))
    }
    @Test fun incompleteUnappliedBlockedAndWrongLimitProofCannotCreatePlanOrQueue()=runBlocking<Unit> {
        val name="legacy-energy-invalid-${uuid()}";val db=open(name)
        try {
            val lease=account(db);db.dao().saveWeight(source());val current=full(db,lease)
            val savedAccess=checkNotNull(db.snapshotDao().access(lease.storageScope))
            val store=ServerSnapshotStore(db,protocol);val pending=store.begin(lease,scope=SyncProtocolScope.ENERGY_V1)
            corruptAndRefuse(db,lease){db.snapshotDao().save(savedAccess.copy(activeRunId=pending.runId))}
            // Malformed wire is refused by the production store; no page or proof is fabricated.
            val malformed=JSONObject(String(page(emptyList(),"bad"))).put("sync_epoch",uuid()).toString().toByteArray()
            rejected {store.apply(pending,malformed)};assertTrue(db.snapshotDao().pages(pending.runId).isEmpty())
            assertNull(store.apply(pending,page(listOf(goal(),version()),"unapplied")))
            assertNull(db.serverDiaryDao().application(pending.runId))
            corruptAndRefuse(db,lease){db.snapshotDao().save(savedAccess.copy(activeRunId=pending.runId))}
            corruptAndRefuse(db,lease){db.snapshotDao().save(savedAccess.copy(blocked=true))}
            corruptAndRefuse(db,lease){val run=checkNotNull(db.snapshotDao().run(current));db.snapshotDao().update(run.copy(limit=run.limit+1))}
            assertTrue(db.importDao().plans(lease.storageScope).isEmpty())
        }finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun staleCurrentShadowWitnessAndMissingEnergySchemaRefuseWithoutChangingSourceOrQueue()=runBlocking<Unit> {
        val name="legacy-energy-stale-${uuid()}";val db=open(name)
        try {
            val lease=account(db);val weight=source();db.dao().saveWeight(weight);val base=full(db,lease);delta(db,lease)
            rejected {LegacyImportStore(db,schema,null).preview(lease,"guest")}
            corruptAndRefuse(db,lease){val row=db.serverDiaryDao().records(lease.storageScope).single()
                db.serverDiaryDao().save(row.copy(runId=base))}
            assertEquals(weight,db.dao().weight(weight.id,"guest"));assertTrue(db.importDao().plans(lease.storageScope).isEmpty())
        }finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun foreignOwnerActiveRunAndOldLeaseCannotImportGuest()=runBlocking<Unit> {
        val name="legacy-energy-owner-${uuid()}";val db=open(name)
        try {
            val first=account(db);val weight=source();db.dao().saveWeight(weight);val foreign=full(db,first)
            val second=account(db)
            rejected {LegacyImportStore(db,schema,energy).preview(first,"guest")}
            corruptAndRefuse(db,second){db.snapshotDao().save(ServerSnapshotAccess(second.storageScope,foreign,false))}
            assertEquals(weight,db.dao().weight(weight.id,"guest"));assertTrue(db.importDao().plans(first.storageScope).isEmpty())
            assertTrue(db.importDao().plans(second.storageScope).isEmpty());assertEquals(0,db.dao().operationCount(first.storageScope))
        }finally {db.close();context.deleteDatabase(name)}
    }
}
