package pl.roseru.kalorie

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.importing.ImportViewModel
import pl.roseru.kalorie.sync.*
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** UI callbacks against real Room; fake network counts verify that stale work never reaches the port. */
class ImportViewModelTest {
    private val instrumentation get()=InstrumentationRegistry.getInstrumentation()
    private val context get()=instrumentation.targetContext
    private val epoch="55555555-5555-4555-8555-555555555555"
    private val nextEpoch="66666666-6666-4666-8666-666666666666"
    private fun uuid()=UUID.randomUUID().toString()
    private fun db()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/import-ui",uuid()).id)
        val boot=AccountBootstrapStore(db);boot.apply(boot.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-23T12:00:00Z"))
        val snapshots=ServerSnapshotStore(db,SnapshotProtocol(CanonicalMealRows.schema(context)));val request=snapshots.begin(lease)
        val page=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-ui")
            .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-checkpoint").put("server_time","2026-10-23T12:00:00Z")
            .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
        assertNull(snapshots.apply(request,page.toString().toByteArray()));return lease
    }
    private suspend fun changeEpoch(db:CalorieDatabase,lease:OwnerLease,value:String=nextEpoch) {
        val old=db.bootstrapDao().binding(lease.storageScope)!!;val boot=AccountBootstrapStore(db)
        boot.apply(boot.begin(lease),BootstrapResponse(old.accountId,value,old.accountGeneration,"2026-10-23T13:00:00Z"))
    }
    private fun model(db:CalorieDatabase,lease:OwnerLease,store:ViewModelStore,calls:AtomicInteger):ImportViewModel {
        lateinit var model:ImportViewModel
        instrumentation.runOnMainSync {
            val factory=object:ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST") override fun <T:ViewModel> create(modelClass:Class<T>):T=
                    ImportViewModel(db,CanonicalMealRows.schema(context),lease,ReconciliationStepExecutor {_,_,_,_->
                        calls.incrementAndGet();SyncStepResult.NotConfigured},SavedStateHandle()) as T
            }
            model=ViewModelProvider(store,factory)[ImportViewModel::class.java]
        }
        return model
    }
    private suspend fun await(model:ImportViewModel){withTimeout(5000){model.state.first {!it.busy}}}
    private suspend fun act(model:ImportViewModel,action:()->Unit){instrumentation.runOnMainSync(action);await(model)}
    @Test fun oldCorrectionCallbackAfterAccountRoundTripWritesNoDecisionOrOutbox()=runBlocking<Unit> {
        val db=db();val store=ViewModelStore()
        try {
            LocalOwnerStore(db).ensureGuest()
            db.dao().saveWeight(WeightEntity("precise","guest","2001-01-02","2001-01-02T12:00:00Z","UTC",1.234567890123))
            val lease=account(db);val calls=AtomicInteger();val model=model(db,lease,store,calls);await(model)
            act(model){model.previewGuest()};val plan=model.state.value.plan!!
            assertFalse(model.state.value.approved);assertEquals(0,db.dao().operationCount(lease.storageScope))
            act(model){model.approve(true)};val row=model.state.value.rows.single()
            val owners=LocalOwnerStore(db);val a=db.ownerDao().byScope(lease.storageScope)!!
            owners.select(owners.registerIdentity("https://fixture.example/realms/import-ui",uuid()).id)
            owners.select(a.id)
            val before=db.importDao().decisions(plan.planId).size
            act(model){model.correct(row,mapOf("row:kg" to "1.234567"),false)}
            assertEquals(before,db.importDao().decisions(plan.planId).size)
            assertEquals(0,db.dao().operationCount(lease.storageScope));assertEquals(0,calls.get())
            assertEquals("decision",db.importDao().source(plan.planId,"weight","precise")!!.state)
        } finally {instrumentation.runOnMainSync{store.clear()};db.close()}
    }
    @Test fun oldReconciliationCallbackAfterEpochChangeNeverCallsTransport()=runBlocking<Unit> {
        val db=db();val store=ViewModelStore()
        try {
            val lease=account(db);changeEpoch(db,lease)
            val calls=AtomicInteger();val model=model(db,lease,store,calls);await(model)
            act(model){model.previewOwn()};act(model){model.approve(true)}
            val id=model.state.value.plan!!.planId;val before=db.importDao().plan(id)!!
            changeEpoch(db,lease,"77777777-7777-4777-8777-777777777777")
            act(model){model.downloadProof()}
            assertEquals(0,calls.get());assertEquals(before,db.importDao().plan(id));assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {instrumentation.runOnMainSync{store.clear()};db.close()}
    }
}
