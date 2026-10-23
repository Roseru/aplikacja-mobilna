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
import java.time.LocalDate
import java.util.UUID

class ReconciliationSnapshotAcceptanceTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun page()=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-acceptance")
        .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-checkpoint").put("server_time","2026-10-23T14:00:00Z")
        .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray()).toString().toByteArray()
    private data class Fixture(val lease:OwnerLease,val binding:AccountBindingEntity,val plan:String,val run:String,val original:SyncPushBatch)
    private suspend fun fixture(db:CalorieDatabase):Fixture {
        val owners=LocalOwnerStore(db);owners.ensureGuest();val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/acceptance",UUID.randomUUID().toString()).id)
        val boot=AccountBootstrapStore(db);boot.apply(boot.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),epoch,1,"2026-10-23T12:00:00Z"))
        val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));snapshots.apply(snapshots.begin(lease),page())
        DiaryRepository(db,context,lease).addWeight(80.125,LocalDate.of(2001,1,2))
        val push=MealPushStore(db,schema);val request=push.prepare(lease)!!;push.markAttempted(request)
        val frozen=db.pushDao().batch(request.id)!!;push.requireReconciliation(request)
        val old=db.bootstrapDao().binding(lease.storageScope)!!
        val binding=boot.apply(boot.begin(lease),BootstrapResponse(old.accountId,epoch,1,"2026-10-23T13:00:00Z"))
        val store=ReconciliationStore(db,schema);val plan=store.begin(lease,binding)
        store.approve(lease,binding,plan.planId,plan.account,plan.issuer,plan.subject)
        val raw=store.nextSnapshot(lease,binding,plan.planId)!!
        snapshots.apply(raw,page()) // Crash window: no acceptCompletedSnapshot/receipt_group yet.
        return Fixture(lease,binding,plan.planId,raw.runId,frozen)
    }
    private suspend fun rejected(action:suspend()->Unit) {
        var rejected=false;try{action()}catch(error:kotlinx.coroutines.CancellationException){throw error}catch(_:Exception){rejected=true};assertTrue(rejected)
    }
    @Test fun completedRawSurvivesRestartAndAcceptsLocallyWithoutNewRunOrAck()=runBlocking<Unit> {
        val name="acceptance-${UUID.randomUUID()}";fun open()=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        var db=open()
        try {
            val f=fixture(db);val runs=db.snapshotDao().runs(f.lease.storageScope);val raw=db.snapshotDao().pages(f.run)
            val outbox=db.serverDiaryDao().unsettled(f.lease.storageScope);val prior=db.snapshotDao().access(f.lease.storageScope)
            db.close();db=open();val store=ReconciliationStore(db,schema)
            assertEquals(f.run,store.pendingSnapshotAcceptance(f.lease,f.binding,f.plan))
            assertEquals(runs,db.snapshotDao().runs(f.lease.storageScope));assertEquals(prior,db.snapshotDao().access(f.lease.storageScope))
            val prepared=store.prepareCompletedSnapshot(f.lease,f.binding,f.plan,f.run)
            assertFalse(prepared.toString().contains(f.plan));assertTrue(db.importDao().evidence(f.plan).isEmpty())
            store.applyCompletedSnapshot(prepared)
            assertEquals(f.run,db.snapshotDao().access(f.lease.storageScope)!!.activeRunId)
            assertNull(store.pendingSnapshotAcceptance(f.lease,f.binding,f.plan))
            val evidence=db.importDao().evidence(f.plan);assertEquals(1,evidence.count {it.kind=="receipt_group"})
            assertEquals(1,evidence.count {it.kind=="snapshot_acceptance"})
            store.applyCompletedSnapshot(prepared);store.acceptCompletedSnapshot(f.lease,f.binding,f.plan,f.run)
            assertEquals(evidence,db.importDao().evidence(f.plan));assertEquals(raw,db.snapshotDao().pages(f.run))
            assertEquals(outbox,db.serverDiaryDao().unsettled(f.lease.storageScope));assertEquals(f.original,db.pushDao().batch(f.original.id))
            assertTrue(db.bootstrapDao().binding(f.lease.storageScope)!!.requiresRecovery)
        }finally{db.close();context.deleteDatabase(name)}
    }
    @Test fun preparedCaptureRejectsSourceAccessPagesContextAndOwnerAbaChangesAtomically()=runBlocking<Unit> {
        for(change in listOf("source","access","pages","context","owner")) {
            val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
            try {
                val f=fixture(db);val store=ReconciliationStore(db,schema);val prepared=store.prepareCompletedSnapshot(f.lease,f.binding,f.plan,f.run)
                when(change) {
                    "source"->{val row=db.importDao().sources(f.plan).single();db.importDao().update(row.copy(decisionCode="different-observation"))}
                    "access"->db.snapshotDao().save(ServerSnapshotAccess(f.lease.storageScope,null,false))
                    "pages"->db.openHelper.writableDatabase.execSQL("UPDATE server_snapshot_pages SET responseJson=responseJson || ' ' WHERE runId=?",arrayOf(f.run))
                    "context"->db.bootstrapDao().update(f.binding.copy(contextRevision=f.binding.contextRevision+1))
                    "owner"->{val owners=LocalOwnerStore(db);owners.select(owners.ensureGuest().id);owners.select(db.ownerDao().byScope(f.lease.storageScope)!!.id)}
                }
                val access=db.snapshotDao().access(f.lease.storageScope);val sources=db.importDao().sources(f.plan)
                rejected {store.applyCompletedSnapshot(prepared)}
                assertTrue(db.importDao().evidence(f.plan).isEmpty());assertEquals(access,db.snapshotDao().access(f.lease.storageScope))
                assertEquals(sources,db.importDao().sources(f.plan));assertEquals(f.original,db.pushDao().batch(f.original.id))
            }finally{db.close()}
        }
    }
    @Test fun malformedCompletedRawHasNoTypedEvidenceAndRemainsAvailableForExplicitDiagnosis()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val f=fixture(db);val store=ReconciliationStore(db,schema)
            db.openHelper.writableDatabase.execSQL("UPDATE server_snapshot_pages SET responseJson='{}' WHERE runId=?",arrayOf(f.run))
            val before=db.snapshotDao().access(f.lease.storageScope)
            assertEquals(f.run,store.pendingSnapshotAcceptance(f.lease,f.binding,f.plan))
            rejected {store.prepareCompletedSnapshot(f.lease,f.binding,f.plan,f.run)}
            assertTrue(db.importDao().evidence(f.plan).isEmpty());assertEquals(before,db.snapshotDao().access(f.lease.storageScope))
            assertEquals(f.original,db.pushDao().batch(f.original.id));assertEquals("complete",db.snapshotDao().run(f.run)!!.state)
        }finally{db.close()}
    }
}
