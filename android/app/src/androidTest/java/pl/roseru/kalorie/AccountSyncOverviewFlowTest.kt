package pl.roseru.kalorie

import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.viewModelScope
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.network.NetworkAccessState
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.sync.AccountSyncOverviewViewModel
import pl.roseru.kalorie.sync.SnapshotMaintenanceViewModel
import pl.roseru.kalorie.ui.AccountSyncOverviewScreen
import pl.roseru.kalorie.ui.CalorieTheme
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Local SQLite and UI only. Retains the separate three maintenance proofs from 0.8.37. */
class AccountSyncOverviewFlowTest {
    @get:Rule val compose=createComposeRule()
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private val time="2026-10-25T12:00:00Z"
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/sync-overview",UUID.randomUUID().toString()).id)
        val boot=AccountBootstrapStore(db);boot.apply(boot.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),epoch,1,time))
        return lease
    }
    private suspend fun reselect(db:CalorieDatabase,lease:OwnerLease):OwnerLease {
        val owners=LocalOwnerStore(db);owners.select(owners.ensureGuest().id)
        return owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
    }
    private suspend fun work(db:CalorieDatabase,lease:OwnerLease,status:String="idle",retry:Long=0):SyncWorkState {
        val binding=db.bootstrapDao().binding(lease.storageScope)!!
        return SyncWorkState(lease.storageScope,lease.generation,CanonicalMealRows.context(binding),UUID.randomUUID().toString(),
            "pull_after",status,retry,0,1,1,1,2,0,System.currentTimeMillis())
    }
    private fun page(weightId:String?=null):ByteArray {
        val entities=JSONArray()
        if(weightId!=null)entities.put(JSONObject().put("entity_type","weight").put("entity_id",weightId).put("revision",1).put("deleted",false)
            .put("payload",JSONObject().put("weight_kg","80").put("occurred_at","2026-10-21T08:00:00Z")
                .put("time_zone","Europe/Warsaw").put("local_date","2026-10-21")))
        return JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-overview")
            .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-checkpoint").put("server_time",time)
            .put("goal_timeline_revision",0).put("entities",entities).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray()).toString().toByteArray()
    }
    private suspend fun enqueue(db:CalorieDatabase,owner:String,type:String,status:String="pending"):OutboxEntity {
        val row=OutboxEntity(UUID.randomUUID().toString(),owner,type,UUID.randomUUID().toString(),"upsert",null,"{}",time,status)
        db.dao().enqueue(row);return row
    }

    @Test fun countsAreOwnerScopedExcludeSettledHistoryAndDoNotPrepareOrAcknowledgeWrites()=runBlocking<Unit> {
        val db=memory()
        try {
            val a=account(db)
            val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));val first=snapshots.begin(a)
            val weight=UUID.randomUUID().toString();snapshots.apply(first,page(weight));ServerDiaryStore(db,schema).apply(a,first.runId)
            DiaryRepository(db,context,a).editWeight(weight,82.0)
            val pushes=MealPushStore(db,schema);val attempt=pushes.prepare(a)!!;pushes.markAttempted(attempt)
            val deadline=System.currentTimeMillis()+120_000
            val frozen=db.pushDao().batch(attempt.id)!!.copy(retryAtMillis=deadline);db.pushDao().update(frozen)
            enqueue(db,a.storageScope,"weight");enqueue(db,a.storageScope,"goal","waiting_recovery")
            enqueue(db,a.storageScope,"meal","conflict");enqueue(db,a.storageScope,"meal","acked")
            enqueue(db,a.storageScope,"meal","local_only");enqueue(db,a.storageScope,"meal","superseded")
            val b=account(db);enqueue(db,b.storageScope,"meal");enqueue(db,DiaryRepository.GUEST,"weight")
            val lease=reselect(db,a);val savedWork=work(db,lease);db.syncWorkDao().save(savedWork)
            val queue=db.serverDiaryDao().unsettled(lease.storageScope);val other=db.serverDiaryDao().unsettled(b.storageScope)
            val overview=AccountSyncOverviewStore(db).read(lease)
            assertEquals(4,overview.queued);assertEquals(1,overview.waiting);assertEquals(1,overview.attention)
            assertEquals(mapOf("weight" to 2,"goal" to 1,"meal" to 1),overview.domains)
            assertEquals(3,overview.legacy);assertEquals(savedWork,overview.work);assertNotNull(overview.lastAppliedAt)
            assertTrue(overview.unconfirmedWrite);assertEquals(deadline,overview.retryAtMillis)
            assertEquals(queue,db.serverDiaryDao().unsettled(lease.storageScope))
            assertEquals(other,db.serverDiaryDao().unsettled(b.storageScope))
            assertEquals(savedWork,db.syncWorkDao().state(lease.storageScope))
            assertEquals(listOf(frozen),db.pushDao().pending(lease.storageScope))
        }finally{db.close()}
    }

    @Test fun previousContextOrLeaseCannotAppearAsCurrentCompletedSynchronization()=runBlocking<Unit> {
        val db=memory()
        try {
            var lease=account(db);val snapshot=ServerSnapshotStore(db,SnapshotProtocol(schema));val request=snapshot.begin(lease)
            snapshot.apply(request,page());val application=ServerDiaryStore(db,schema).apply(lease,request.runId)
            val saved=work(db,lease);db.syncWorkDao().save(saved)
            val store=AccountSyncOverviewStore(db);val first=store.read(lease)
            assertEquals(saved,first.work);assertEquals(application.appliedAt,first.lastAppliedAt)
            val oldLease=lease;lease=reselect(db,lease)
            assertNull(store.read(lease).work);assertEquals(application.appliedAt,store.read(lease).lastAppliedAt)
            try {store.read(oldLease);fail("An obsolete local owner lease cannot read this overview")}
            catch(_:StaleOwnerException){}
            db.syncWorkDao().save(work(db,lease))
            val binding=db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(binding.copy(contextRevision=binding.contextRevision+1,requiresRecovery=true))
            val changed=store.read(lease);assertNull(changed.work);assertNull(changed.lastAppliedAt);assertTrue(changed.requiresRecovery)
            assertEquals(application,db.serverDiaryDao().application(request.runId))
        }finally{db.close()}
    }

    @Test fun storageHelpOpensLocalMaintenanceAndRetryWaitsForDeadlineAndNetworkPermission()=runBlocking<Unit> {
        val db=memory();var model:AccountSyncOverviewViewModel?=null
        try {
            val lease=account(db);val owner=db.ownerDao().byScope(lease.storageScope)!!
            var saved=work(db,lease,"storage");db.syncWorkDao().save(saved)
            val overview=AccountSyncOverviewViewModel(lease,AccountSyncOverviewStore(db));model=overview
            val maintenance=SnapshotMaintenanceViewModel(SnapshotMaintenanceStore(db),lease)
            var network:NetworkAccessState by mutableStateOf(NetworkAccessState.Blocked)
            var view by mutableStateOf(SessionView(binding=SessionBinding(owner,lease),configured=true,apiConfigured=true,
                mealPushConfigured=true,hasSession=true,serverLinked=true))
            var center by mutableStateOf(false)
            val calls=AtomicInteger()
            val actions=SessionActions({},{},{},{},{},{},synchronizeMeals={selected->assertEquals(lease,selected);calls.incrementAndGet()})
            compose.setContent {CalorieTheme(false) {
                if(center)AccountSyncOverviewScreen(overview,view,actions,network,maintenance,{center=false},{},{})
                else SessionScreen(view,actions,back={},onSyncOverview={center=true})
            }}
            compose.onNodeWithTag("session-sync-overview").performScrollTo().performClick()
            compose.waitUntil(5_000) {overview.state.value.overview?.work?.status=="storage"}
            compose.onNodeWithTag("sync-overview-action").performScrollTo().performClick()
            compose.onNodeWithTag("snapshot-maintenance-check").assertIsDisplayed()
            assertEquals(0,calls.get())
            compose.onNodeWithTag("sync-maintenance-back").performClick()
            saved=saved.copy(status="deferred",retryAtMillis=System.currentTimeMillis()+60_000);db.syncWorkDao().save(saved)
            compose.runOnIdle {network=NetworkAccessState.Allowed(1)}
            compose.waitUntil(5_000) {overview.state.value.overview?.work?.status=="deferred"}
            compose.onNodeWithTag("sync-overview-action").performScrollTo().assertIsNotEnabled()
            db.syncWorkDao().save(saved.copy(status="ready",retryAtMillis=0))
            compose.waitUntil(5_000) {overview.state.value.overview?.work?.status=="ready"}
            compose.onNodeWithTag("sync-overview-action").performScrollTo().assertIsEnabled().performClick()
            assertEquals(1,calls.get())
            compose.onNodeWithText("Wróć do konta").performScrollTo().performClick()
            compose.waitUntil(8_000) {overview.state.value.loading && overview.state.value.overview==null}
            val binding=db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(binding.copy(contextRevision=binding.contextRevision+1,requiresRecovery=true))
            compose.onNodeWithTag("session-sync-overview").performScrollTo().performClick()
            compose.waitUntil(5_000) {overview.state.value.overview?.requiresRecovery==true}
            compose.onNodeWithTag("sync-overview-title").assertTextEquals("Dane wymagają uzgodnienia")
            assertEquals(1,calls.get())
            val guest=LocalOwnerStore(db).ensureGuest();val guestLease=LocalOwnerStore(db).select(guest.id)
            compose.runOnIdle {view=view.copy(binding=SessionBinding(guest,guestLease))}
            compose.onNodeWithTag("sync-overview-stale").assertIsDisplayed()
            compose.onNodeWithTag("sync-overview-action").assertDoesNotExist()
            assertEquals(1,calls.get())
        }finally{compose.runOnIdle {model?.viewModelScope?.cancel()};db.close()}
    }
}
