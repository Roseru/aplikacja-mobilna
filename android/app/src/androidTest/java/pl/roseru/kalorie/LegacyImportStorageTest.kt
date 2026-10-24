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
    @Test fun explicitPrecisionCorrectionCreatesDerivativeAndPreservesArchivedOriginal()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            LocalOwnerStore(db).ensureGuest()
            val old=WeightEntity("precise","guest","2000-01-02","2000-01-02T12:00:00Z","UTC",80.123456789)
            db.dao().saveWeight(old)
            val lease=account(db);val store=LegacyImportStore(db,schema);val plan=store.preview(lease,"guest")
            assertEquals("precision_review",plan.decisions.single().code);assertEquals(0,plan.pending)
            approve(store,lease,plan)
            val source=store.source(lease,plan.planId,"weight",old.id)
            val choice=JSONObject().put("choice","metadata").put("row_overrides",JSONObject().put("kg","80.123457"))
            store.decide(lease,plan.planId,"weight",old.id,source.sourceHash,choice.toString());store.resume(lease,plan.planId)
            val updated=store.source(lease,plan.planId,"weight",old.id)
            assertEquals("queued",updated.state);assertEquals(source.sourceJson,updated.sourceJson);assertEquals(source.sourceHash,updated.sourceHash)
            assertEquals(old,db.dao().weight(old.id,"guest"))
            val request=MealPushStore(db,schema).prepare(lease)!!
            assertEquals("80.123457",JSONObject(request.operations.single().payload).getString("weight_kg"))
            assertEquals(80.123457,db.dao().weight(updated.localId,lease.storageScope)!!.kg,0.0)
        } finally {db.close()}
    }
    @Test fun correctedAccountGoalKeepsImmutableOriginalButOnlyDerivativeIsVisible()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val lease=account(db)
            val old=GoalEntity("old-goal",lease.storageScope,"2001-01-02",2000.123456789,null,0.0,100.0)
            db.dao().saveGoal(old)
            val store=LegacyImportStore(db,schema);val plan=store.preview(lease,lease.storageScope)
            assertEquals(1,plan.decisions.size);approve(store,lease,plan)
            val source=store.source(lease,plan.planId,"goal",old.id)
            val choice=JSONObject().put("choice","metadata").put("goal_decided_at","2001-01-02T12:00:00Z")
                .put("zone","UTC").put("goal_reason","user_decision").put("goal_aim","maintain").put("goal_activity","line")
                .put("row_overrides",JSONObject().put("kcal","2000.123457"))
            store.decide(lease,plan.planId,"goal",old.id,source.sourceHash,choice.toString())
            val progress=store.resume(lease,plan.planId)
            assertTrue(progress.decisions.toString(),progress.decisions.isEmpty())
            val imported=store.source(lease,plan.planId,"goal",old.id)
            assertNotEquals(old.id,imported.localId);assertEquals(old,db.dao().goalById(lease.storageScope,old.id))
            val visible=db.dao().achievementGoals(lease.storageScope)
            assertEquals(1,visible.size);assertEquals(imported.localId,visible.single().id)
            assertEquals(2000.123457,visible.single().kcal,0.0);assertNull(visible.single().protein);assertEquals(0.0,visible.single().fat!!,0.0)
            val push=MealPushStore(db,schema);val request=push.prepare(lease)!!
            assertEquals("2000.123457",JSONObject(request.operations.single().payload).getString("energy_kcal"))
            push.markAttempted(request);push.applyAck(push.prepareAck(request,200,reply(request)))
            assertEquals(setOf(old.id),db.resolvedOriginalGoals(lease.storageScope))
            assertEquals(old,db.dao().goalById(lease.storageScope,old.id))
        } finally {db.close()}
    }
    @Test fun sixHistoricalDomainsImportThroughOrdinaryMixedBatchWithoutGuessingCatalogueOrLosingNulls()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            LocalOwnerStore(db).ensureGuest()
            val goal=GoalEntity("legacy-goal","guest","2001-01-02",2100.125,null,0.0,null)
            val profile=ProfileEntity("legacy-profile","guest","Old profile",180.125,"LINE","REDUCE","UTC",1)
            val product=ProductEntity("legacy-private","Historical private","historical private",150.5,null,0.0,null,100.0,"Private","Historical label",0,"guest")
            val day=DiaryDayEntity("legacy-day","guest","2001-01-02",true,1)
            val meal=MealEntity("legacy-meal","guest","2001-01-02","2001-01-02T12:00:00Z","UTC","UNSPECIFIED",rationName="Historical ration")
            val item=MealItemEntity("legacy-item",meal.id,"basic-rice","Historical component",12.125,100.5,null,0.0,null)
            val weight=WeightEntity("legacy-weight","guest","2001-01-02","2001-01-02T12:00:00Z","UTC",80.125)
            db.dao().saveGoal(goal);db.dao().saveProfile(profile);db.dao().insertProduct(product);db.dao().saveDiaryDay(day)
            db.dao().insertMeal(meal);db.dao().insertItem(item);db.dao().saveWeight(weight)
            val lease=account(db);val store=LegacyImportStore(db,schema);val plan=store.preview(lease,"guest")
            assertEquals(6,plan.total);assertEquals(setOf("goal","diary_day"),plan.decisions.map {it.type}.toSet())
            assertEquals(0,db.dao().operationCount(lease.storageScope));approve(store,lease,plan)
            val archived=db.importDao().sources(plan.planId).associateBy {it.entityType}
            for(source in archived.values.filter {it.entityType in setOf("goal","diary_day")}) {
                val choice=JSONObject().put("choice","metadata").put("zone","UTC")
                if(source.entityType=="goal")choice.put("goal_decided_at","2001-01-02T10:00:00Z").put("goal_reason","user_decision")
                    .put("goal_aim","reduce").put("goal_activity","line")
                store.decide(lease,plan.planId,source.entityType,source.sourceId,source.sourceHash,choice.toString())
            }
            val queued=store.resume(lease,plan.planId);assertTrue(queued.decisions.toString(),queued.decisions.isEmpty())
            assertEquals(6,queued.queued);assertEquals(0,queued.acknowledged)
            val push=MealPushStore(db,schema);val request=push.prepare(lease)!!
            assertEquals(setOf("profile","goal","diary_day","product_draft","meal","weight"),request.operations.map {it.entityType}.toSet())
            if(InstrumentationRegistry.getArguments().getString("o2ExportLegacy")=="true") {
                // Opt-in synthetic fixture only: the test runner may uninstall its target after completion.
                val body=request.batch.body();val hash=LegacyImportStore.digest(String(body))
                val chunks=android.util.Base64.encodeToString(body,android.util.Base64.NO_WRAP).chunked(1800)
                android.util.Log.i("O2LegacyOracle","SYNTHETIC_BEGIN:$hash:${chunks.size}")
                chunks.forEachIndexed {index,chunk->android.util.Log.i("O2LegacyOracle","SYNTHETIC_PART:$hash:$index:$chunk")}
                android.util.Log.i("O2LegacyOracle","SYNTHETIC_END:$hash")
            }
            val wires=request.operations.associate {it.entityType to JSONObject(it.payload)}
            val mealWire=wires.getValue("meal");assertEquals("2001-01-02",mealWire.getString("local_date"));assertTrue(mealWire.isNull("meal_type"))
            assertTrue(mealWire.isNull("ration"));val wireItem=mealWire.getJSONArray("items").getJSONObject(0)
            assertTrue(wireItem.isNull("product"));assertEquals("manual",wireItem.getString("nutrition_origin"))
            assertEquals("12.125",wireItem.getJSONObject("quantity").getString("amount"))
            assertTrue(wireItem.getJSONObject("nutrition_per_100").isNull("protein_g"))
            assertEquals("0",wireItem.getJSONObject("nutrition_per_100").getString("fat_g"))
            assertEquals("Historical label",wires.getValue("product_draft").getString("source_description"))
            assertTrue(wires.getValue("goal").isNull("protein_g"));assertEquals("reduce",wires.getValue("goal").getString("goal_type"))
            push.markAttempted(request);assertArrayEquals(request.batch.body(),push.open(lease,request.id).batch.body())
            assertEquals(0,store.status(lease,plan.planId).acknowledged)
            push.applyAck(push.prepareAck(request,200,reply(request)))
            val complete=store.status(lease,plan.planId);assertEquals("complete",complete.state);assertEquals(6,complete.acknowledged)
            for(source in db.importDao().sources(plan.planId)) {
                assertEquals(archived.getValue(source.entityType).sourceJson,source.sourceJson)
                assertEquals(source.sourceHash,LegacyImportStore.digest(source.sourceJson))
            }
            assertEquals(goal,db.dao().goalById("guest",goal.id));assertEquals(profile,db.dao().currentProfile("guest"))
            assertEquals(product,db.dao().product(product.id,"guest"));assertEquals(day,db.dao().currentDiaryDay("guest",day.localDate))
            assertEquals(meal,db.dao().meal(meal.id,"guest")!!.meal);assertEquals(item,db.dao().meal(meal.id,"guest")!!.items.single())
            assertEquals(weight,db.dao().weight(weight.id,"guest"));assertEquals(6,db.dao().operationCount(lease.storageScope))
        } finally {db.close()}
    }
    private suspend fun guestMeal(db:CalorieDatabase):String {
        LocalOwnerStore(db).ensureGuest();val id=uuid()
        db.dao().insertMeal(MealEntity(id,"guest","2001-01-02","2001-01-02T12:00:00Z","UTC","LUNCH"))
        db.dao().insertItem(MealItemEntity(uuid(),id,"basic-rice","Historical rice",50.0,100.125,null,0.0,12.5))
        return id
    }
    private suspend fun imported(db:CalorieDatabase,lease:OwnerLease):Pair<ImportProgress,ImportSource> {
        val store=LegacyImportStore(db,schema);val plan=store.preview(lease,"guest");approve(store,lease,plan);store.resume(lease,plan.planId)
        return plan to db.importDao().sources(plan.planId).single {it.entityType=="meal"}
    }
    @Test fun newPlansNeverReinstallUnchangedOriginAfterTargetEditLostAckRestartAndFullPull()=runBlocking<Unit> {
        val name="origin-resume-${uuid()}"
        fun open()=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        var db=open()
        try {
            val guestId=guestMeal(db);val lease=account(db);val (first,source)=imported(db,lease)
            val push=MealPushStore(db,schema);val sent=push.prepare(lease)!!;push.markAttempted(sent);push.applyAck(push.prepareAck(sent,200,reply(sent)))
            val local=db.dao().meal(source.localId,lease.storageScope)!!
            assertTrue(CanonicalMealEditor(db,context,lease).change(source.localId,local.items.single().id,"25"))
            val frozen=push.prepare(lease)!!;push.markAttempted(frozen)
            val target=db.dao().meal(source.localId,lease.storageScope)!!;val operation=db.dao().operation(frozen.operations.single().operationId)!!
            val bytes=frozen.batch.body();val hash=frozen.batch.sha256
            db.dao().saveWeight(WeightEntity("guest-new-1","guest","2001-01-03","2001-01-03T12:00:00Z","UTC",81.125))
            db.close();db=open();var store=LegacyImportStore(db,schema)
            val second=store.preview(lease,"guest");assertNotEquals(first.planId,second.planId)
            val same=db.importDao().source(second.planId,"meal",guestId)!!
            assertEquals("already_imported",same.state);assertNull(same.decisionCode)
            approve(store,lease,second);store.resume(lease,second.planId)
            assertEquals(target,db.dao().meal(source.localId,lease.storageScope));assertEquals(operation,db.dao().operation(operation.operationId))
            assertArrayEquals(bytes,db.pushDao().batch(frozen.id)!!.requestJson.toByteArray());assertEquals(hash,db.pushDao().batch(frozen.id)!!.requestHash)
            val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));val request=snapshots.begin(lease)
            val original=JSONObject().put("entity_id",source.wireId).put("entity_type","meal").put("revision",1)
                .put("deleted",false).put("payload",JSONObject(sent.operations.single().payload))
            val page=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-origin-pull")
                .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-origin-checkpoint").put("server_time","2026-10-23T14:00:00Z")
                .put("goal_timeline_revision",0).put("entities",JSONArray().put(original)).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
            assertNull(snapshots.apply(request,page.toString().toByteArray()));ServerDiaryStore(db,schema).apply(lease,request.runId)
            assertEquals(target,db.dao().meal(source.localId,lease.storageScope))
            db.dao().saveWeight(WeightEntity("guest-new-2","guest","2001-01-04","2001-01-04T12:00:00Z","UTC",82.125))
            store=LegacyImportStore(db,schema);val third=store.preview(lease,"guest");assertNotEquals(second.planId,third.planId)
            assertEquals("already_imported",db.importDao().source(third.planId,"meal",guestId)!!.state)
            assertEquals("already_imported",db.importDao().source(third.planId,"weight","guest-new-1")!!.state)
            approve(store,lease,third);store.resume(lease,third.planId)
            assertEquals(target,db.dao().meal(source.localId,lease.storageScope));assertEquals(operation,db.dao().operation(operation.operationId))
            assertArrayEquals(bytes,db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
            assertEquals(2,db.openHelper.readableDatabase.query("SELECT COUNT(*) FROM outbox WHERE ownerScope=? AND entityType='meal'",arrayOf(lease.storageScope)).use {it.moveToFirst();it.getInt(0)})
            assertEquals(first.planId,db.importDao().origin("guest","meal",guestId)!!.firstPlanId)
            assertEquals(50.0,db.dao().meal(guestId,"guest")!!.items.single().grams,0.0)
        } finally {db.close();context.deleteDatabase(name)}
    }
    @Test fun changedImportedSourceRequiresExplicitSeparateCopyAndNeverOverwritesFrozenTarget()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        try {
            val guestId=guestMeal(db);val lease=account(db);val (first,source)=imported(db,lease)
            val originalSource=db.importDao().source(first.planId,"meal",guestId)!!
            val push=MealPushStore(db,schema);val sent=push.prepare(lease)!!;push.markAttempted(sent);push.applyAck(push.prepareAck(sent,200,reply(sent)))
            val local=db.dao().meal(source.localId,lease.storageScope)!!
            CanonicalMealEditor(db,context,lease).change(source.localId,local.items.single().id,"25")
            val frozen=push.prepare(lease)!!;push.markAttempted(frozen)
            val target=db.dao().meal(source.localId,lease.storageScope)!!;val operation=db.dao().operation(frozen.operations.single().operationId)!!
            val guest=db.dao().meal(guestId,"guest")!!
            db.dao().updateMeal(guest.meal.copy(localRevision=2));db.dao().updateItem(guest.items.single().copy(grams=75.0))
            val sourceEdit=OutboxEntity(uuid(),"guest","meal",guestId,"update",null,"{\"grams\":75}","2026-10-23T12:00:00Z")
            db.dao().enqueue(sourceEdit)
            val store=LegacyImportStore(db,schema);val second=store.preview(lease,"guest");approve(store,lease,second)
            val changed=db.importDao().source(second.planId,"meal",guestId)!!
            assertEquals("previously_imported_source_changed",changed.decisionCode)
            assertNotEquals(originalSource.originFingerprint,changed.originFingerprint)
            store.resume(lease,second.planId)
            assertEquals(target,db.dao().meal(source.localId,lease.storageScope));assertEquals(operation,db.dao().operation(operation.operationId))
            rejects {store.decide(lease,second.planId,"meal",guestId,changed.sourceHash,"{\"choice\":\"metadata\"}")}
            store.decide(lease,second.planId,"meal",guestId,changed.sourceHash,"{\"choice\":\"new_identity\"}")
            store.resume(lease,second.planId)
            val separate=db.importDao().source(second.planId,"meal",guestId)!!
            assertEquals("queued",separate.state);assertNotEquals(source.localId,separate.localId);assertNotEquals(source.wireId,separate.wireId)
            assertEquals(75.0,db.dao().meal(separate.localId,lease.storageScope)!!.items.single().grams,0.0)
            val originalItem=db.dao().meal(guestId,"guest")!!.items.single().id
            val firstAlias=db.importDao().items(lease.storageScope,source.localId).single()
            val copyAlias=db.importDao().items(lease.storageScope,separate.localId).single()
            assertEquals(originalItem,firstAlias.wireId) // Preserve the ordinary UUID on its first import.
            assertNotEquals(firstAlias.wireId,copyAlias.wireId) // An explicit new Meal has its own durable item identity.
            assertEquals(originalItem,copyAlias.sourceId)
            assertEquals(copyAlias.wireId,JSONObject(separate.appliedPayload!!).getJSONArray("items").getJSONObject(0).getString("item_id"))
            assertEquals(target,db.dao().meal(source.localId,lease.storageScope));assertEquals(operation,db.dao().operation(operation.operationId))
            assertArrayEquals(frozen.batch.body(),db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
            assertEquals(originalSource,db.importDao().source(first.planId,"meal",guestId))
            assertEquals(sourceEdit,db.dao().operation(sourceEdit.operationId))
            db.dao().saveWeight(WeightEntity("new-after-copy","guest","2001-01-04","2001-01-04T12:00:00Z","UTC",82.125))
            val third=store.preview(lease,"guest")
            assertEquals("already_imported",db.importDao().source(third.planId,"meal",guestId)!!.state)
            approve(store,lease,third);store.resume(lease,third.planId)
            assertEquals(target,db.dao().meal(source.localId,lease.storageScope));assertEquals(operation,db.dao().operation(operation.operationId))
            assertEquals(first.planId,db.importDao().origin("guest","meal",guestId)!!.firstPlanId)
        } finally {db.close()}
    }

}
