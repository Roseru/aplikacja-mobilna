package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

/** Synthetic completed archives and actual Room; no HTTP, login or external provider. */
class ServerDiaryStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun uuid()=UUID.randomUUID().toString()
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/diary","A").id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-22T08:00:00Z"))
        return lease
    }
    private fun row(type:String,payload:JSONObject,id:String=uuid(),revision:Int=1)=JSONObject()
        .put("entity_type",type).put("entity_id",id).put("revision",revision).put("deleted",false).put("payload",payload)
    private fun all():List<JSONObject> {
        val profile=JSONObject().put("pseudonym","Synthetic soldier").put("height_cm",JSONObject.NULL)
            .put("activity_class","line").put("time_zone","Europe/Warsaw")
        val goal=JSONObject().put("effective_from","2026-10-01").put("decided_at","2026-10-01T08:00:00Z")
            .put("time_zone","Europe/Warsaw").put("goal_type","maintain").put("energy_kcal","2500")
            .put("protein_g",JSONObject.NULL).put("fat_g",JSONObject.NULL).put("carbs_g",JSONObject.NULL)
            .put("activity_class","line").put("estimate",JSONObject.NULL).put("timeline_base_revision",0)
            .put("reason","user_decision").put("correction_of",JSONObject.NULL)
        val meal=ManualMealWire.create("Synthetic soup",uuid(),"100","g",ExactNutrition(java.math.BigDecimal("50"),null,null,null),
            "2026-10-21T08:00:00Z","Europe/Warsaw","lunch",schema).json()
        val weight=WeightWire.create(82.125,"2026-10-21T08:00:00Z","Europe/Warsaw","2026-10-21",schema).json()
        val day=JSONObject().put("local_date","2026-10-21").put("time_zone","Europe/Warsaw").put("declared_complete",true)
        val draft=JSONObject().put("name","Synthetic drink").put("brand",JSONObject.NULL).put("variant",JSONObject.NULL)
            .put("basis_unit","ml").put("nutrition_per_100",JSONObject().put("energy_kcal",JSONObject.NULL)
                .put("protein_g",JSONObject.NULL).put("fat_g",JSONObject.NULL).put("carbs_g",JSONObject.NULL))
            .put("package_quantity",JSONObject().put("amount","250").put("unit","ml"))
            .put("density_g_per_ml","1.25").put("density_source","Synthetic label").put("source_description","Synthetic estimate")
        return listOf(row("profile",profile),row("goal",goal),row("meal",meal),row("weight",weight),row("diary_day",day),row("product_draft",draft))
    }
    private suspend fun snapshot(db:CalorieDatabase,lease:OwnerLease,rows:List<JSONObject>,time:String="2026-10-22T10:00:00Z"):String {
        val store=ServerSnapshotStore(db,SnapshotProtocol(schema));val request=store.begin(lease)
        val value=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-${uuid()}")
            .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-${uuid()}").put("server_time",time)
            .put("goal_timeline_revision",1).put("entities",JSONArray(rows)).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
        assertNull(store.apply(request,value.toString().toByteArray()))
        return request.runId
    }
    private suspend fun refused(action:suspend()->Unit) {
        var failed=false
        try{action()}catch(error:CancellationException){throw error}catch(_:Exception){failed=true}
        assertTrue("Expected atomic refusal; values suppressed",failed)
    }
    private fun List<JSONObject>.id(type:String)=single{it.getString("entity_type")==type}.getString("entity_id")

    @Test fun fullCopyPopulatesAllSixDomainsAndReplayCannotUndoLaterLocalEdit()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val rows=all();snapshot(db,lease,rows)
            val store=ServerDiaryStore(db,schema);val result=store.apply(lease)
            assertEquals(6,result.included);assertEquals(0,result.held)
            assertEquals(0,db.dao().operationCount(lease.storageScope))
            assertEquals(2500.0,db.dao().goal(lease.storageScope,"2026-10-21").first()!!.kcal,0.0)
            assertNull(db.dao().currentProfile(lease.storageScope)!!.heightCm)
            assertEquals(ActivityClass.LINE.name,db.dao().currentProfile(lease.storageScope)!!.activityClass)
            assertEquals(82.125,db.dao().weight(rows.id("weight"),lease.storageScope)!!.kg,0.0)
            assertTrue(db.dao().currentDiaryDay(lease.storageScope,"2026-10-21")!!.declaredComplete)
            val product=db.dao().product(rows.id("product_draft"),lease.storageScope)!!
            assertEquals("ml",product.unit);assertEquals(250.0,product.defaultGrams,0.0)
            assertFalse(product.nutrients().asExact().energy.complete)
            assertEquals(1,product.portion("125","g").asExact().energy.missingCount)
            val meal=db.dao().meal(rows.id("meal"),lease.storageScope)!!
            DiaryRepository(db,context,lease).editItem(meal.meal.id,meal.items.single().id,75.0,"75")
            val edited=db.dao().meal(meal.meal.id,lease.storageScope)
            assertEquals(result,store.apply(lease));assertEquals(edited,db.dao().meal(meal.meal.id,lease.storageScope))
            DiaryRepository(db,context,lease).add(product.id,125.0,MealType.SNACK,LocalDate.of(2026,10,21),amountText="125")
            val created=db.dao().day(lease.storageScope,"2026-10-21").first().single {it.meal.id!=meal.meal.id}
            assertFalse(created.items.single().consumed().asExact().energy.complete)
            assertEquals("ml",created.items.single().unit)
            assertTrue(db.serverDiaryDao().unsettled(lease.storageScope).all{it.wireFormat=="sync-v1"})
        }finally{db.close()}
    }
    @Test fun newCopyPreservesFrozenRequestAndBothWeightVersionsWithoutAnAcknowledgement()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val rows=all();snapshot(db,lease,rows);ServerDiaryStore(db,schema).apply(lease)
            val id=rows.id("weight");DiaryRepository(db,context,lease).editWeight(id,84.5)
            val push=MealPushStore(db,schema);val request=push.prepare(lease)!!;push.markAttempted(request)
            val batch=db.pushDao().batch(request.id)!!;val queued=db.serverDiaryDao().unsettled(lease.storageScope)
            rows.single{it.getString("entity_type")=="weight"}.put("revision",2).getJSONObject("payload").put("weight_kg","92")
            snapshot(db,lease,rows,"2026-10-22T11:00:00Z")
            val result=ServerDiaryStore(db,schema).apply(lease)
            assertEquals(1,result.held);assertEquals(84.5,db.dao().weight(id,lease.storageScope)!!.kg,0.0)
            assertEquals(queued,db.serverDiaryDao().unsettled(lease.storageScope));assertEquals(batch,db.pushDao().batch(request.id))
            val observed=db.serverDiaryDao().records(lease.storageScope).single{it.entityId==id}
            assertEquals("pending_local",observed.disposition);assertEquals("92",JSONObject(observed.payload!!).getString("weight_kg"))
            assertEquals(1,db.weightSyncDao().state(lease.storageScope,id)!!.serverRevision)
        }finally{db.close()}
    }
    @Test fun absenceDeletesOnlyPreviouslyObservedRowsWithoutInventingARevisionOrAck()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val rows=all();snapshot(db,lease,rows);ServerDiaryStore(db,schema).apply(lease)
            snapshot(db,lease,emptyList(),"2026-10-22T11:00:00Z");val result=ServerDiaryStore(db,schema).apply(lease)
            assertEquals(6,result.included);assertEquals(0,result.held)
            assertTrue(db.dao().meal(rows.id("meal"),lease.storageScope)!!.meal.deleted)
            assertTrue(db.dao().weight(rows.id("weight"),lease.storageScope)!!.deleted)
            assertNull(db.dao().goal(lease.storageScope,"2026-10-21").first())
            assertNotNull(db.dao().goalById(lease.storageScope,rows.id("goal"))) // Immutable history remains.
            assertNull(db.dao().currentProfile(lease.storageScope));assertNull(db.dao().product(rows.id("product_draft"),lease.storageScope))
            assertFalse(db.dao().currentDiaryDay(lease.storageScope,"2026-10-21")!!.declaredComplete)
            assertTrue(db.serverDiaryDao().records(lease.storageScope).all{it.absent && it.deleted && it.knownRevision==1})
            assertEquals(1,db.weightSyncDao().state(lease.storageScope,rows.id("weight"))!!.serverRevision)
            assertEquals(0,db.dao().operationCount(lease.storageScope))
        }finally{db.close()}
    }
    @Test fun invalidLaterPayloadOrForeignIdentityRollsBackEveryDomainAndKeepsTheArchive()=runBlocking<Unit> {
        for(invalid in listOf("height","foreign")) {
            val db=memory()
            try {
                val lease=account(db);val rows=all()
                if(invalid=="height")rows.single{it.getString("entity_type")=="profile"}.getJSONObject("payload").put("height_cm","301")
                else {
                    val foreign=LocalOwnerStore(db).registerIdentity("https://fixture.example/realms/diary","B")
                    db.dao().saveWeight(WeightEntity(rows.id("weight"),foreign.storageScope,"2026-10-21","2026-10-21T08:00:00Z","Europe/Warsaw",90.0))
                }
                val run=snapshot(db,lease,rows)
                refused{ServerDiaryStore(db,schema).apply(lease)}
                assertNull(db.serverDiaryDao().application(run));assertTrue(db.serverDiaryDao().records(lease.storageScope).isEmpty())
                assertNull(db.dao().currentProfile(lease.storageScope));assertTrue(db.serverDiaryDao().allGoals(lease.storageScope).isEmpty())
                assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty());assertEquals(0,db.dao().operationCount(lease.storageScope))
                assertEquals("complete",db.snapshotDao().run(run)!!.state)
            }finally{db.close()}
        }
    }
    @Test fun legacyProfileGoalDayAndDraftRemainVisibleAndTheirQueuesAreUnchanged()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val rows=all();val owner=lease.storageScope
            val profile=ProfileEntity(uuid(),owner,"Local",177.5,ActivityClass.GARRISON.name,DietAim.REDUCE.name,"Europe/Warsaw",4)
            val goal=GoalEntity(uuid(),owner,"2026-10-01",1900.0,null,null,null,1)
            val day=DiaryDayEntity(uuid(),owner,"2026-10-21",false,3)
            val product=ProductEntity(rows.id("product_draft"),"Local bar","local bar",444.0,null,null,null,50.0,"Własny produkt","Synthetic local",0,owner)
            db.dao().saveProfile(profile);db.dao().saveGoal(goal);db.dao().saveDiaryDay(day);db.dao().insertProduct(product)
            for((type,id)in listOf("profile" to profile.id,"goal" to goal.id,"diary_day" to day.id,"product_draft" to product.id))
                db.dao().enqueue(OutboxEntity(uuid(),owner,type,id,"update",null,"{\"synthetic\":true}","2026-10-22T09:00:00Z"))
            val queue=db.serverDiaryDao().unsettled(owner);snapshot(db,lease,rows)
            val result=ServerDiaryStore(db,schema).apply(lease)
            assertEquals(4,result.held);assertEquals(profile,db.dao().currentProfile(owner));assertEquals(goal,db.dao().goalById(owner,goal.id))
            assertEquals(day,db.dao().currentDiaryDay(owner,day.localDate));assertEquals(product,db.dao().product(product.id,owner))
            assertEquals(queue,db.serverDiaryDao().unsettled(owner))
        }finally{db.close()}
    }
    @Test fun failedFinalCommitIsAtomicAndCanRetryAfterRestartWithoutDuplicatingRows()=runBlocking<Unit> {
        val name="diary-${uuid()}";fun open()=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        var db=open()
        try {
            val lease=account(db);val rows=all();val run=snapshot(db,lease,rows)
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_diary BEFORE INSERT ON server_diary_applications BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
            refused{ServerDiaryStore(db,schema).apply(lease)}
            assertNull(db.dao().currentProfile(lease.storageScope));assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty())
            assertTrue(db.serverDiaryDao().records(lease.storageScope).isEmpty());assertNull(db.serverDiaryDao().application(run))
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_diary");db.close();db=open()
            val restored=LocalOwnerStore(db).currentLease();val result=ServerDiaryStore(db,schema).apply(restored)
            db.close();db=open();assertEquals(result,ServerDiaryStore(db,schema).apply(LocalOwnerStore(db).currentLease()))
            assertEquals(1,db.dao().achievementMeals(restored.storageScope).size)
        }finally{db.close();context.deleteDatabase(name)}
    }
    @Test fun anOlderCopyCannotRollBackANewerAppliedCopyOrAConfirmedWeightRevision()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val rows=all();snapshot(db,lease,rows);ServerDiaryStore(db,schema).apply(lease)
            val before=db.dao().weight(rows.id("weight"),lease.storageScope)
            snapshot(db,lease,rows,"2026-10-22T09:00:00Z");refused{ServerDiaryStore(db,schema).apply(lease)}
            assertEquals(before,db.dao().weight(rows.id("weight"),lease.storageScope))
            val state=db.weightSyncDao().state(lease.storageScope,rows.id("weight"))!!
            db.weightSyncDao().update(state.copy(serverRevision=3))
            snapshot(db,lease,rows,"2026-10-22T12:00:00Z");refused{ServerDiaryStore(db,schema).apply(lease)}
            assertEquals(3,db.weightSyncDao().state(lease.storageScope,state.id)!!.serverRevision)
        }finally{db.close()}
    }
}
