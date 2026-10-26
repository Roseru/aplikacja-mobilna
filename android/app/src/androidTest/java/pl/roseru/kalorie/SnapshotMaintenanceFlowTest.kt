package pl.roseru.kalorie

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.sync.SnapshotMaintenanceViewModel
import pl.roseru.kalorie.ui.CalorieTheme
import pl.roseru.kalorie.ui.SnapshotMaintenancePanel
import java.util.UUID

/** Explicit local decision against real SQLite; no account credentials or server transport. */
class SnapshotMaintenanceFlowTest {
    @get:Rule val compose=createComposeRule()
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/maintenance",UUID.randomUUID().toString()).id)
        val boot=AccountBootstrapStore(db)
        boot.apply(boot.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),epoch,1,"2026-10-25T12:00:00Z"))
        return lease
    }
    private suspend fun reselect(db:CalorieDatabase,lease:OwnerLease):OwnerLease {
        val owners=LocalOwnerStore(db);owners.select(owners.ensureGuest().id)
        return owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
    }
    private fun page(index:Int,next:String?=null,weightId:String?=null):ByteArray {
        val entities=JSONArray()
        if(weightId!=null)entities.put(JSONObject().put("entity_type","weight").put("entity_id",weightId).put("revision",1).put("deleted",false)
            .put("payload",JSONObject().put("weight_kg","80").put("occurred_at","2026-10-21T08:00:00Z")
                .put("time_zone","Europe/Warsaw").put("local_date","2026-10-21")))
        return JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-snapshot-$index")
            .put("page_token",next?:JSONObject.NULL).put("checkpoint",if(next==null)"synthetic-checkpoint-$index" else JSONObject.NULL)
            .put("server_time","2026-10-25T12:00:00Z").put("goal_timeline_revision",0).put("entities",entities)
            .put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray()).toString().toByteArray()
    }
    private fun foreignKeys(db:CalorieDatabase)=assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})

    @Test fun explicitDecisionUnblocksNinthCopyWhileKeepingDiaryFrozenWriteAndOriginalProofs()=runBlocking<Unit> {
        val db=memory()
        try {
            var lease=account(db);val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
            val weight=UUID.randomUUID().toString();val active=snapshots.begin(lease)
            snapshots.apply(active,page(0,weightId=weight));ServerDiaryStore(db,schema).apply(lease,active.runId)
            DiaryRepository(db,context,lease).editWeight(weight,82.0)
            val push=MealPushStore(db,schema);val request=push.prepare(lease)!!;push.markAttempted(request)
            val batch=db.pushDao().batch(request.id)!!;val outbox=db.serverDiaryDao().unsettled(lease.storageScope)
            val pending=mutableListOf<SnapshotRequest>()
            repeat(7) {index->
                lease=reselect(db,lease)
                val start=snapshots.begin(lease);snapshots.apply(start,page(index+1,"pending-next"));pending+=start
            }
            lease=reselect(db,lease)
            val before=db.snapshotDao().runs(lease.storageScope);val pages=pending.associate {it.runId to db.snapshotDao().pages(it.runId)}
            try {snapshots.begin(lease);fail("Conservative reservation must still refuse eight protected raw copies")}
            catch(_:SnapshotCapacityException){}
            val maintenance=SnapshotMaintenanceStore(db);val review=maintenance.review(lease)!!
            assertEquals(7,review.count);assertEquals(before,db.snapshotDao().runs(lease.storageScope))
            assertEquals(7,maintenance.confirm(review))
            for(run in before)assertEquals(if(run.state=="pending")run.copy(state="expired") else run,db.snapshotDao().run(run.id))
            for((id,saved)in pages)assertEquals(saved,db.snapshotDao().pages(id))
            val next=snapshots.begin(lease)
            assertEquals(8,db.snapshotArchiveDao().rawRuns(lease.storageScope).size)
            val archived=pending.first();val receipt=db.snapshotArchiveDao().receipt(archived.runId)!!
            val manifest=JSONObject(receipt.manifestJson).getJSONArray("pages").getJSONObject(0)
            assertEquals(LegacyImportStore.digest(receipt.manifestJson),receipt.manifestHash)
            assertEquals(LegacyImportStore.digest(pages.getValue(archived.runId).single().queryJson),manifest.getString("query_sha256"))
            assertEquals(LegacyImportStore.digest(pages.getValue(archived.runId).single().responseJson),manifest.getString("response_sha256"))
            val settled=db.snapshotDao().runs(lease.storageScope)
            try {snapshots.apply(archived,page(1,"pending-next"))}catch(_:StaleOwnerException){}
            assertEquals(settled,db.snapshotDao().runs(lease.storageScope))
            assertEquals("pending",db.snapshotDao().run(next.runId)!!.state)
            assertEquals(active.runId,db.snapshotDao().access(lease.storageScope)!!.activeRunId)
            assertEquals(batch,db.pushDao().batch(request.id));assertEquals(outbox,db.serverDiaryDao().unsettled(lease.storageScope))
            assertEquals(82.0,db.dao().weight(weight,lease.storageScope)!!.kg,0.0)
            foreignKeys(db)
        }finally{db.close()}
    }

    @Test fun currentRecoveryAndNewEvidenceStayProtectedAndAbaRejectsCapturedDecision()=runBlocking<Unit> {
        val db=memory()
        try {
            var lease=account(db);val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));val maintenance=SnapshotMaintenanceStore(db)
            val first=snapshots.begin(lease);snapshots.apply(first,page(1,"pending-next"))
            lease=reselect(db,lease);val review=maintenance.review(lease)!!;assertEquals(1,review.count)
            val binding=db.bootstrapDao().binding(lease.storageScope)!!;val owner=db.ownerDao().byScope(lease.storageScope)!!
            val plan=ImportPlan(UUID.randomUUID().toString(),lease.storageScope,lease.storageScope,binding.accountId,
                owner.issuer!!,owner.subject!!,"recovery","synthetic-maintenance",CanonicalMealRows.context(binding),"2026-10-25T12:00:00Z")
            db.importDao().insert(plan)
            db.importDao().insert(ReconciliationEvidence(plan.id,"synthetic","evidence","{}",LegacyImportStore.digest("{}"),first.runId))
            val before=db.snapshotDao().runs(lease.storageScope)
            try {maintenance.confirm(review);fail("A new proof must invalidate the whole captured decision")}
            catch(_:SnapshotMaintenanceChangedException){}
            assertEquals(before,db.snapshotDao().runs(lease.storageScope))
            val recovery=snapshots.begin(lease);snapshots.apply(recovery,page(2,"pending-next"))
            db.importDao().insert(ReconciliationPull(recovery.runId,plan.id,0,"[]"))
            val current=snapshots.begin(lease);snapshots.apply(current,page(3,"pending-next"))
            assertEquals(0,maintenance.review(lease)!!.count)
            lease=reselect(db,lease);val captured=maintenance.review(lease)!!;assertEquals(1,captured.count)
            lease=reselect(db,lease);val all=db.snapshotDao().runs(lease.storageScope)
            try {maintenance.confirm(captured);fail("A -> guest -> A cannot reuse an earlier confirmation")}
            catch(_:StaleOwnerException){}
            assertEquals(all,db.snapshotDao().runs(lease.storageScope))
            assertEquals(1,maintenance.review(lease)!!.count)
            assertTrue(all.all {it.state=="pending"});foreignKeys(db)
        }finally{db.close()}
    }

    @Test fun userCanCancelThenExplicitlyConfirmTheLocalDecision()=runBlocking<Unit> {
        val db=memory()
        try {
            var lease=account(db);val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
            val first=snapshots.begin(lease);snapshots.apply(first,page(1,"pending-next"));lease=reselect(db,lease)
            val model=SnapshotMaintenanceViewModel(SnapshotMaintenanceStore(db),lease)
            compose.setContent {CalorieTheme(false) {SnapshotMaintenancePanel(model)}}
            compose.onNodeWithTag("snapshot-maintenance-check").performClick()
            compose.waitUntil(5_000) {model.state.value.review!=null}
            compose.onNodeWithTag("snapshot-maintenance-cancel").performClick()
            compose.onNodeWithTag("snapshot-maintenance-dialog").assertDoesNotExist()
            assertEquals("pending",db.snapshotDao().run(first.runId)!!.state)
            compose.onNodeWithTag("snapshot-maintenance-check").performClick()
            compose.waitUntil(5_000) {model.state.value.review!=null}
            compose.onNodeWithTag("snapshot-maintenance-confirm").performClick()
            compose.waitUntil(5_000) {!model.state.value.busy && model.state.value.review==null}
            compose.onNodeWithTag("snapshot-maintenance-message").assertTextContains("Poprzednie pobierania zostały przerwane",substring=true)
            assertEquals("expired",db.snapshotDao().run(first.runId)!!.state)
            assertEquals(1,db.snapshotDao().pages(first.runId).size);foreignKeys(db)
        }finally{db.close()}
    }
}
