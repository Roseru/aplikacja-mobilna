package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.CancellationException
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

/** Real Room storage/projection with explicitly synthetic wire; not live APK/API acceptance. */
class GoalEnergySnapshotStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val energy get()=EnergySchema(context.assets.open("energy/energy.schema.json").use {it.readBytes()})
    private val protocol get()=SnapshotProtocol(schema,energy)
    private val epoch="11111111-1111-4111-8111-111111111111"
    private val shared="22222222-2222-4222-8222-222222222222"
    private fun open(name:String)=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);val lease=owners.select(owners.registerIdentity("https://identity.fixture/realm","A").id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse("44444444-4444-4444-8444-444444444444",epoch,1,"2026-10-24T09:00:00Z"))
        SyncProtocolStore(db).readScope(lease,checkNotNull(db.bootstrapDao().binding(lease.storageScope)),true)
        return lease
    }
    private fun version()=EnergyFixture.sample("version").put("revision",1).also {
        it.getJSONObject("payload").getJSONObject("audit").put("goal_timeline_revision",1)
    }
    private fun goal()=JSONObject().put("entity_type","goal").put("entity_id",shared).put("revision",1).put("deleted",false)
        .put("payload",JSONObject().put("effective_from","2026-10-01").put("decided_at","2026-10-01T09:00:00Z")
            .put("time_zone","UTC").put("goal_type","maintain").put("energy_kcal","2500")
            .put("protein_g",JSONObject.NULL).put("fat_g",JSONObject.NULL).put("carbs_g",JSONObject.NULL)
            .put("activity_class","line").put("estimate",version().getJSONObject("payload").getJSONObject("audit").getJSONObject("estimate"))
            .put("timeline_base_revision",0).put("reason","user_decision").put("correction_of",JSONObject.NULL))
    private fun page(rows:List<JSONObject>,next:String?=null,mode:String="snapshot",timeline:Int=1)=StrictJson.canonical(JSONObject()
        .put("sync_epoch",epoch).put("mode",mode).put("snapshot_token",if(mode=="snapshot")"synthetic-snapshot" else JSONObject.NULL)
        .put("page_token",next?:JSONObject.NULL).put("checkpoint",if(next==null)"synthetic-checkpoint" else JSONObject.NULL)
        .put("server_time","2026-10-24T10:00:00Z").put("goal_timeline_revision",timeline).put("entities",JSONArray(rows))
        .put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())).toByteArray(Charsets.UTF_8)
    private suspend fun rejected(block:suspend ()->Unit) {
        var refused=false
        try {block()}catch(error:CancellationException){throw error}catch(_:Exception){refused=true}
        assertTrue("Same-domain duplicate must remain rejected",refused)
    }
    private fun identities(db:CalorieDatabase,run:String):List<String> = db.openHelper.readableDatabase.query(
        "SELECT field,identity FROM server_snapshot_identities WHERE runId=? ORDER BY field,identity",arrayOf<Any>(run)).use {cursor->
        buildList {while(cursor.moveToNext())add(cursor.getString(0)+"="+cursor.getString(1))}
    }
    private suspend fun assertProjected(db:CalorieDatabase,lease:OwnerLease,runId:String) {
        val binding=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        assertEquals(runId,db.serverDiaryDao().latest(lease.storageScope)?.runId)
        assertEquals(runId,ServerSnapshotStore(db,protocol).active(lease)?.id)
        val goal=checkNotNull(db.dao().goalById(lease.storageScope,shared))
        assertEquals(2500.0,goal.kcal,0.0)
        assertEquals("3204",pl.roseru.kalorie.core.MaintenanceEstimate.read(checkNotNull(goal.estimateJson)).maintenance.stripTrailingZeros().toPlainString())
        val versions=db.canonicalEnergyDao().all(lease.storageScope,CanonicalMealRows.context(binding))
        assertEquals(shared,versions.single().entityId)
        assertEquals(1,versions.single().revision)
        assertTrue(db.serverDiaryDao().unsettled(lease.storageScope).isEmpty())
        assertFalse(binding.requiresRecovery)
    }
    @Test fun oldRoom27BareIndexResumesEitherOrderWithoutRewritingSavedPagesOrPermittingDuplicates()=runBlocking<Unit> {
        for(energyFirst in listOf(false,true)) {
            val name="goal-energy-old-index-${UUID.randomUUID()}";var db=open(name)
            try {
                val lease=account(db);var store=ServerSnapshotStore(db,protocol)
                val first=store.beginRead(lease,SyncProtocolScope.ENERGY_V1)
                val initial=if(energyFirst)version() else goal()
                val other=if(energyFirst)goal() else version()
                val next=checkNotNull(store.apply(first,page(listOf(initial),"synthetic-next")))
                val saved=db.snapshotDao().pages(first.runId).single()
                // Reproduce the released Room27 derived index, not a different schema.
                db.openHelper.writableDatabase.execSQL("UPDATE server_snapshot_identities SET identity=? WHERE runId=? AND field='entities'",
                    arrayOf<Any>(shared,first.runId))
                db.close();db=open(name);store=ServerSnapshotStore(db,protocol)
                val resumed=store.beginRead(lease,SyncProtocolScope.ENERGY_V1)
                assertEquals(next.runId,resumed.runId);assertEquals(next.query.encoded(),resumed.query.encoded())
                val beforeRun=db.snapshotDao().run(first.runId);val beforeIdentities=identities(db,first.runId)
                rejected {store.apply(resumed,page(listOf(initial)))}
                assertEquals(listOf(saved),db.snapshotDao().pages(first.runId))
                assertEquals(beforeRun,db.snapshotDao().run(first.runId))
                assertEquals(beforeIdentities,identities(db,first.runId))
                assertNull(db.serverDiaryDao().latest(lease.storageScope))
                assertNull(store.apply(resumed,page(listOf(other))))
                val all=db.snapshotDao().pages(first.runId)
                assertEquals(saved,all.first());assertEquals(2,all.size)
                ServerDiaryStore(db,schema,energy).apply(lease,first.runId)
                assertProjected(db,lease,first.runId)
                assertEquals(listOf(shared),db.snapshotDao().bareEntityIdentities(first.runId,listOf(shared)))
            }finally {db.close();context.deleteDatabase(name)}
        }
    }
    @Test fun newPlaneIndexStillRejectsRepeatedIdentityAndRollsBackTheWholePage()=runBlocking<Unit> {
        for(energyFirst in listOf(false,true)) {
            val name="goal-energy-new-index-${UUID.randomUUID()}";val db=open(name)
            try {
                val lease=account(db);val store=ServerSnapshotStore(db,protocol)
                val first=store.beginRead(lease,SyncProtocolScope.ENERGY_V1)
                val initial=if(energyFirst)version() else goal()
                val other=if(energyFirst)goal() else version()
                val next=checkNotNull(store.apply(first,page(listOf(initial),"synthetic-next")))
                val saved=db.snapshotDao().pages(first.runId);val run=db.snapshotDao().run(first.runId)
                val index=identities(db,first.runId)
                assertTrue(db.snapshotDao().bareEntityIdentities(first.runId,listOf(shared)).isEmpty())
                rejected {store.apply(next,page(listOf(initial)))}
                assertEquals(saved,db.snapshotDao().pages(first.runId));assertEquals(run,db.snapshotDao().run(first.runId))
                assertEquals(index,identities(db,first.runId));assertNull(db.serverDiaryDao().latest(lease.storageScope))
                assertNull(store.apply(next,page(listOf(other))))
                ServerDiaryStore(db,schema,energy).apply(lease,first.runId)
                assertProjected(db,lease,first.runId)
            }finally {db.close();context.deleteDatabase(name)}
        }
    }
    @Test fun samePageFullAndIncrementalProjectBothDomainsInEitherOrder()=runBlocking<Unit> {
        for(incremental in listOf(false,true))for(energyFirst in listOf(false,true)) {
            val name="goal-energy-typed-${UUID.randomUUID()}";val db=open(name)
            try {
                val lease=account(db);val store=ServerSnapshotStore(db,protocol)
                if(incremental) {
                    val empty=store.beginRead(lease,SyncProtocolScope.ENERGY_V1)
                    assertNull(store.apply(empty,page(emptyList(),timeline=0)))
                    ServerDiaryStore(db,schema,energy).apply(lease,empty.runId)
                }
                val request=store.beginRead(lease,SyncProtocolScope.ENERGY_V1)
                assertEquals(if(incremental)"incremental" else "snapshot",db.snapshotDao().run(request.runId)?.readMode)
                val rows=if(energyFirst)listOf(version(),goal()) else listOf(goal(),version())
                assertNull(store.apply(request,page(rows,mode=if(incremental)"incremental" else "snapshot")))
                ServerDiaryStore(db,schema,energy).apply(lease,request.runId)
                assertProjected(db,lease,request.runId)
                assertTrue(db.snapshotDao().bareEntityIdentities(request.runId,listOf(shared)).isEmpty())
            }finally {db.close();context.deleteDatabase(name)}
        }
    }
}
