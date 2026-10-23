package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import java.util.UUID

/** Real SQLite and synthetic immutable snapshots; no transport or credentials. */
class SnapshotArchiveStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/archive",UUID.randomUUID().toString()).id)
        val boot=AccountBootstrapStore(db)
        boot.apply(boot.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),epoch,1,"2026-10-23T12:00:00Z"))
        return lease
    }
    private fun page(index:Int,weightId:String?=null,next:String?=null):ByteArray {
        val entities=JSONArray()
        if(weightId!=null)entities.put(JSONObject().put("entity_type","weight").put("entity_id",weightId).put("revision",1).put("deleted",false)
            .put("payload",JSONObject().put("weight_kg","80").put("occurred_at","2026-10-21T08:00:00Z")
                .put("time_zone","Europe/Warsaw").put("local_date","2026-10-21")))
        return JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-snapshot-$index")
            .put("page_token",next?:JSONObject.NULL).put("checkpoint",if(next==null)"synthetic-checkpoint-$index" else JSONObject.NULL)
            .put("server_time","2026-10-23T12:00:00Z").put("goal_timeline_revision",0).put("entities",entities)
            .put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray()).toString().toByteArray()
    }
    private suspend fun complete(store:ServerSnapshotStore,lease:OwnerLease,index:Int,id:String?=null):SnapshotRequest {
        val request=store.begin(lease);assertNull(store.apply(request,page(index,id)));return request
    }
    private fun foreignKeys(db:CalorieDatabase)=assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})

    @Test fun repeatedSuccessfulFullCopiesDoNotStopAtNinth()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
            val first=complete(snapshots,lease,0);val original=db.snapshotDao().run(first.runId)!!
            val originalPage=db.snapshotDao().pages(first.runId).single()
            repeat(11) {complete(snapshots,lease,it+1)}
            val active=snapshots.active(lease)!!.id
            assertEquals(12,db.snapshotDao().runs(lease.storageScope).size)
            assertEquals(8,db.snapshotArchiveDao().rawRuns(lease.storageScope).size)
            assertEquals(original,db.snapshotDao().run(first.runId))
            assertTrue(db.snapshotDao().pages(first.runId).isEmpty())
            val receipt=db.snapshotArchiveDao().receipt(first.runId)!!
            assertEquals(LegacyImportStore.digest(receipt.manifestJson),receipt.manifestHash)
            val saved=JSONObject(receipt.manifestJson).getJSONArray("pages").getJSONObject(0)
            assertEquals(LegacyImportStore.digest(originalPage.queryJson),saved.getString("query_sha256"))
            assertEquals(LegacyImportStore.digest(originalPage.responseJson),saved.getString("response_sha256"))
            assertEquals(original.pageCount,receipt.originalPages)
            assertEquals(original.byteCount,receipt.originalByteCount)
            assertNull(snapshots.apply(first,page(0)))
            assertEquals(active,snapshots.active(lease)!!.id)
            assertEquals(1,db.snapshotDao().pages(active).size)
            foreignKeys(db)
        }finally{db.close()}
    }
    @Test fun pendingFrozenRequestProtectsItsOriginalSnapshotAndExactBody()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
            val id=UUID.randomUUID().toString();val first=complete(snapshots,lease,0,id)
            ServerDiaryStore(db,schema).apply(lease,first.runId)
            DiaryRepository(db,context,lease).editWeight(id,82.0)
            val push=MealPushStore(db,schema);val request=push.prepare(lease)!!;push.markAttempted(request)
            val batch=db.pushDao().batch(request.id)!!;val original=db.snapshotDao().pages(first.runId)
            repeat(12){complete(snapshots,lease,it+1,id)}
            assertNull(db.snapshotArchiveDao().receipt(first.runId))
            assertEquals(original,db.snapshotDao().pages(first.runId))
            assertEquals(batch,db.pushDao().batch(request.id))
            assertEquals(82.0,db.dao().weight(id,lease.storageScope)!!.kg,0.0)
            assertEquals(8,db.snapshotArchiveDao().rawRuns(lease.storageScope).size)
            foreignKeys(db)
        }finally{db.close()}
    }
    @Test fun allProtectedArchivesRefuseCapacityWithoutLosingPendingPagesOrActiveCopy()=runBlocking<Unit> {
        val db=memory()
        try {
            var lease=account(db);val owners=LocalOwnerStore(db);val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
            val active=complete(snapshots,lease,0).runId
            val pending=mutableListOf<String>()
            repeat(7) {index->
                owners.select(owners.ensureGuest().id);lease=owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
                val start=snapshots.begin(lease);snapshots.apply(start,page(index+1,next="pending-next"));pending+=start.runId
            }
            owners.select(owners.ensureGuest().id);lease=owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
            val runs=db.snapshotDao().runs(lease.storageScope);val pages=pending.associateWith {db.snapshotDao().pages(it)}
            try{snapshots.begin(lease);fail("All raw runs are protected")}catch(_:SnapshotCapacityException){}
            assertEquals(runs,db.snapshotDao().runs(lease.storageScope))
            for((id,saved)in pages)assertEquals(saved,db.snapshotDao().pages(id))
            assertEquals(active,db.snapshotDao().access(lease.storageScope)!!.activeRunId)
            assertEquals(8,db.snapshotArchiveDao().rawRuns(lease.storageScope).size)
            foreignKeys(db)
        }finally{db.close()}
    }
    @Test fun historicalApplicationReturnsSavedResultAfterCompactionAndPreservesLaterLocalEdit()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));val diary=ServerDiaryStore(db,schema)
            val id=UUID.randomUUID().toString();val first=complete(snapshots,lease,0,id);val saved=diary.apply(lease,first.runId)
            DiaryRepository(db,context,lease).editWeight(id,82.0)
            repeat(12){val copy=complete(snapshots,lease,it+1,id);diary.apply(lease,copy.runId)}
            assertNotNull(db.snapshotArchiveDao().receipt(first.runId))
            assertTrue(db.snapshotDao().pages(first.runId).isEmpty())
            val queue=db.serverDiaryDao().unsettled(lease.storageScope);val active=snapshots.active(lease)!!.id
            assertEquals(saved,diary.apply(lease,first.runId))
            assertEquals(82.0,db.dao().weight(id,lease.storageScope)!!.kg,0.0)
            assertEquals(queue,db.serverDiaryDao().unsettled(lease.storageScope))
            assertEquals(active,snapshots.active(lease)!!.id)
            foreignKeys(db)
        }finally{db.close()}
    }
    @Test fun invalidFinalSemanticsCannotPublishActivePointerAndValidRetryUsesOriginalQuery()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
            val active=complete(snapshots,lease,0).runId;val request=snapshots.begin(lease)
            val invalid=JSONObject(String(page(1))).put("entities",JSONArray().put(JSONObject()
                .put("entity_type","profile").put("entity_id",UUID.randomUUID().toString()).put("revision",1).put("deleted",false)
                .put("payload",JSONObject().put("pseudonym","Synthetic").put("height_cm","301").put("activity_class","line").put("time_zone","UTC"))))
            var failed=false;try{snapshots.apply(request,invalid.toString().toByteArray())}catch(_:Exception){failed=true}
            assertTrue(failed);assertEquals(active,snapshots.active(lease)!!.id)
            assertTrue(db.snapshotDao().pages(request.runId).isEmpty())
            assertEquals("pending",db.snapshotDao().run(request.runId)!!.state)
            assertEquals(request.query.encoded(),snapshots.begin(lease).query.encoded())
            invalid.getJSONArray("entities").getJSONObject(0).getJSONObject("payload").put("height_cm","180")
            assertNull(snapshots.apply(request,invalid.toString().toByteArray()))
            assertEquals(request.runId,snapshots.active(lease)!!.id)
            foreignKeys(db)
        }finally{db.close()}
    }
}
