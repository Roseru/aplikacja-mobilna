package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.util.UUID

/** Real Room, retained source rows and existing ordinary six-domain push, without network. */
class LegacyImportStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun uuid()=UUID.randomUUID().toString()
    private suspend fun account(db:CalorieDatabase,subject:String=uuid()):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/import",subject).id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-23T12:00:00Z"))
        val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));val request=snapshots.begin(lease)
        val page=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-import")
            .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-checkpoint").put("server_time","2026-10-23T12:00:00Z")
            .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
        assertNull(snapshots.apply(request,page.toString().toByteArray()));return lease
    }
    private suspend fun approve(store:LegacyImportStore,lease:OwnerLease,plan:ImportProgress)=
        store.approve(lease,plan.planId,plan.account,plan.issuer,plan.subject)
    private suspend fun rejects(action:suspend ()->Unit) {var rejected=false;try {action()} catch(_:Exception){rejected=true};assertTrue(rejected)}
    private fun reply(request:MealPushRequest):ByteArray {
        val results=JSONArray();request.operations.forEach {op->results.put(JSONObject().put("operation_id",op.operationId)
            .put("entity_id",op.entityId).put("status","accepted").put("revision",(op.baseRevision ?: 0)+1).put("recovery_mapping",JSONObject.NULL))}
        return JSONObject().put("sync_epoch",epoch).put("server_time","2026-10-23T13:00:00Z").put("results",results).toString().toByteArray()
    }
    @Test fun recordsWithoutOutboxKeepSourceUuidAndHistoryWhileChunkResumeAndLaterEditUseAliases()=runBlocking<Unit> {
        val name="import-resume-${uuid()}"
        fun open()=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        var db=open()
        try {
            LocalOwnerStore(db).ensureGuest()
            val mealId=uuid()
            val meal=MealEntity(mealId,"guest","2001-01-02","2001-01-02T12:00:00Z","UTC","LUNCH")
            val item=MealItemEntity("old-item",mealId,"basic-rice","Historical meal",50.0,100.125,null,0.0,12.5)
            val point=WeightEntity("old-weight","guest","2001-01-02","2001-01-02T12:00:00Z","UTC",80.125)
            db.dao().insertMeal(meal);db.dao().insertItem(item);db.dao().saveWeight(point)
            assertEquals(0,db.dao().operationCount("guest"))
            var lease=account(db);var store=LegacyImportStore(db,schema)
            val preview=store.preview(lease,"guest");assertEquals(2,preview.total)
            assertEquals(preview.planId,store.preview(lease,"guest").planId)
            assertEquals("draft",preview.state);assertEquals(0,db.dao().operationCount(lease.storageScope))
            rejects {store.approve(lease,preview.planId,preview.account,preview.issuer,"another subject")}
            approve(store,lease,preview);approve(store,lease,preview)
            store.resume(lease,preview.planId,1)
            assertEquals(1,db.dao().operationCount(lease.storageScope))
            val first=db.importDao().sources(preview.planId).first {it.state=="queued"}
            val firstOperation=first.operationId
            db.close();db=open();lease=LocalOwnerStore(db).currentLease();store=LegacyImportStore(db,schema)
            store.resume(lease,preview.planId,1);store.resume(lease,preview.planId,1)
            assertEquals(2,db.dao().operationCount(lease.storageScope))
            assertEquals(firstOperation,db.importDao().source(preview.planId,first.entityType,first.sourceId)!!.operationId)
            assertEquals(meal,db.dao().meal(mealId,"guest")!!.meal);assertEquals(item,db.dao().meal(mealId,"guest")!!.items.single())
            assertEquals(point,db.dao().weight("old-weight","guest"))
            val imported=db.importDao().sources(preview.planId).single {it.entityType=="meal"}
            assertEquals(mealId,imported.wireId);assertNotEquals(mealId,imported.localId)
            assertEquals(imported.sourceHash,LegacyImportStore.digest(imported.sourceJson))
            val projection=db.dao().meal(imported.localId,lease.storageScope)!!
            assertEquals("2001-01-02",projection.meal.localDate)
            val payload=JSONObject(projection.meal.wirePayload!!);val wireItem=payload.getJSONArray("items").getJSONObject(0)
            assertTrue(wireItem.isNull("product"));assertNull(projection.items.single().proteinPer100)
            assertEquals(0.0,projection.items.single().fatPer100!!,0.0)
            val push=MealPushStore(db,schema);val request=push.prepare(lease)!!;push.markAttempted(request)
            val bytes=request.batch.body();val hash=request.batch.sha256
            assertEquals(setOf("meal","weight"),request.operations.map {it.entityType}.toSet())
            assertEquals(mealId,request.operations.single {it.entityType=="meal"}.entityId)
            assertTrue(CanonicalMealEditor(db,context,lease).change(imported.localId,projection.items.single().id,"25"))
            assertArrayEquals(bytes,push.open(lease,request.id).batch.body());assertEquals(hash,push.open(lease,request.id).batch.sha256)
            push.applyAck(push.prepareAck(request,200,reply(request)))
            val next=push.prepare(lease)!!;assertEquals(1,next.operations.single().baseRevision)
            assertEquals(mealId,next.operations.single().entityId)
            assertEquals("25",JSONObject(next.operations.single().payload).getJSONArray("items").getJSONObject(0).getJSONObject("quantity").getString("amount"))
            assertEquals(item,db.dao().meal(mealId,"guest")!!.items.single())
        } finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun consentIsPermanentForGuestAndStaleLeaseCannotResumeAfterAnotherAccount()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            LocalOwnerStore(db).ensureGuest()
            db.dao().saveWeight(WeightEntity("legacy","guest","2000-01-02","2000-01-02T12:00:00Z","UTC",80.125))
            val a=account(db);val store=LegacyImportStore(db,schema);val plan=store.preview(a,"guest");approve(store,a,plan)
            val b=account(db)
            rejects {store.preview(b,"guest")};rejects {store.resume(a,plan.planId)}
            val again=LocalOwnerStore(db).select(db.ownerDao().byScope(a.storageScope)!!.id)
            assertNotEquals(a.generation,again.generation)
            rejects {store.resume(a,plan.planId)}
            store.resume(again,plan.planId)
            assertEquals(1,db.dao().operationCount(a.storageScope));assertEquals(0,db.dao().operationCount(b.storageScope))
            assertEquals(1,db.importDao().sources(plan.planId).size)
        } finally {db.close()}
    }
    @Test fun legacyRealBeyondWirePrecisionNeedsCorrectionAndOriginalOperationBodyRemainsUntouched()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            LocalOwnerStore(db).ensureGuest()
            val row=WeightEntity("weight","guest","2000-01-02","2000-01-02T12:00:00Z","UTC",80.123456789)
            db.dao().saveWeight(row)
            val legacy=OutboxEntity("old-operation","guest","weight",row.id,"create",null,"{\"kg\":80.123456789}","2000-01-02T12:00:00Z")
            db.dao().enqueue(legacy)
            val lease=account(db);val store=LegacyImportStore(db,schema);val plan=store.preview(lease,"guest");approve(store,lease,plan)
            val progress=store.resume(lease,plan.planId)
            assertEquals("precision_review",progress.decisions.single().code)
            val source=store.source(lease,plan.planId,"weight",row.id)
            assertEquals(source.sourceHash,LegacyImportStore.digest(source.sourceJson))
            assertEquals(row,db.dao().weight(row.id,"guest"));assertEquals(legacy,db.dao().operation(legacy.operationId))
            assertEquals(0,db.dao().operationCount(lease.storageScope))
            store.decide(lease,plan.planId,"weight",row.id,source.sourceHash,"{\"choice\":\"keep_local\"}")
            assertEquals(1,db.importDao().decisions(plan.planId).size)
            assertEquals(legacy,db.dao().operation(legacy.operationId))
        } finally {db.close()}
    }
}
