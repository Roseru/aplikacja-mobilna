package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
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

/** Public repository plus actual Room/ACK transactions. All server responses are synthetic. */
class WeightSyncStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get()=CanonicalMealRows.schema(context)
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun uuid()=UUID.randomUUID().toString()
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase,linked:Boolean=true):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/weight",uuid()).id)
        if(linked) {
            val boot=AccountBootstrapStore(db);boot.apply(boot.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-21T12:00:00Z"))
            val page=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","fixture-snapshot")
                .put("page_token",JSONObject.NULL).put("checkpoint","fixture-checkpoint").put("server_time","2026-10-21T12:00:00Z")
                .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
            val store=ServerSnapshotStore(db,SnapshotProtocol(schema));assertNull(store.apply(store.begin(lease),page.toString().toByteArray()))
        }
        return lease
    }
    private fun reply(request:MealPushRequest,status:String="accepted"):ByteArray {
        val testContext=InstrumentationRegistry.getInstrumentation().context
        val value=testContext.assets.open("materialized-meal-push-response.json").use {JSONObject(String(it.readBytes()))}
        val operations=request.batch.json().getJSONArray("operations");val results=JSONArray()
        for(i in 0 until operations.length()) {
            val op=operations.getJSONObject(i)
            results.put(JSONObject().put("operation_id",op.getString("operation_id")).put("entity_id",op.getString("entity_id"))
                .put("status",status).put("revision",if(op.isNull("base_revision"))1 else op.getInt("base_revision")+1).put("recovery_mapping",JSONObject.NULL))
        }
        return value.put("results",results).toString().toByteArray()
    }
    private suspend fun rejected(action:suspend()->Unit) {
        var failed=false;try{action()}catch(e:CancellationException){throw e}catch(_:Exception){failed=true}
        assertTrue("Expected atomic refusal; private values suppressed",failed)
    }

    @Test fun createEditAndDeleteBeforeFirstAttemptCoalesceWithoutUploadingDeletedWeight()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease);val id=uuid()
            repo.addWeight(80.125,LocalDate.now(),id);repo.addWeight(99.0,LocalDate.now(),id)
            assertEquals(1,db.dao().operationCount(lease.storageScope))
            val initial=db.weightSyncDao().operations(lease.storageScope,id).single()
            assertEquals("sync-v1",initial.wireFormat);assertEquals("80.125",JSONObject(initial.payload).getString("weight_kg"))
            repo.editWeight(id,81.5)
            assertEquals("superseded",db.dao().operation(initial.operationId)!!.status)
            assertEquals("81.5",JSONObject(db.weightSyncDao().operations(lease.storageScope,id).single().payload).getString("weight_kg"))
            repo.deleteWeight(id);assertTrue(db.dao().weight(id,lease.storageScope)!!.deleted)
            assertTrue(db.weightSyncDao().operations(lease.storageScope,id).isEmpty())
            assertNull(MealPushStore(db,schema).prepare(lease))
        }finally{db.close()}
    }

    @Test fun frozenWeightSurvivesRestartAndLostAckWithoutLosingNewEditOrLaterDelete()=runBlocking<Unit> {
        val name="weight-sync-${uuid()}";var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease);val id=uuid()
            repo.addWeight(80.125,LocalDate.now(),id)
            val first=MealPushStore(db,schema);val request=first.prepare(lease)!!;first.markAttempted(request)
            val body=request.batch.body();val hash=request.batch.sha256;repo.editWeight(id,82.5)
            assertEquals("waiting_revision",db.weightSyncDao().operations(lease.storageScope,id).last().status)
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
            val current=LocalOwnerStore(db).currentLease();val store=MealPushStore(db,schema);val reopened=store.open(current,request.id)
            assertArrayEquals(body,reopened.batch.body());assertEquals(hash,reopened.batch.sha256)
            val ack=store.prepareAck(reopened,200,reply(reopened,"already_applied"));assertFalse(store.applyAck(ack).replay)
            assertTrue(store.applyAck(ack).replay);assertEquals(82.5,db.dao().weight(id,current.storageScope)!!.kg,0.0)
            assertEquals(1,db.weightSyncDao().state(current.storageScope,id)!!.serverRevision)
            val next=db.weightSyncDao().operations(current.storageScope,id).single();assertEquals(1,next.baseRevision)
            assertEquals("82.5",JSONObject(next.payload).getString("weight_kg"))
            val updated=store.prepare(current)!!;store.markAttempted(updated);store.applyAck(store.prepareAck(updated,200,reply(updated)))
            DiaryRepository(db,context,current).deleteWeight(id)
            val delete=store.prepare(current)!!;store.markAttempted(delete)
            assertTrue(delete.batch.json().getJSONArray("operations").getJSONObject(0).isNull("payload"))
            store.applyAck(store.prepareAck(delete,200,reply(delete)))
            assertEquals(3,db.weightSyncDao().state(current.storageScope,id)!!.serverRevision)
            assertTrue(db.dao().weight(id,current.storageScope)!!.deleted);assertNull(store.prepare(current))
        }finally{db.close();context.deleteDatabase(name)}
    }

    @Test fun mixedMealAndWeightAckCommitsAtomicallyAndRejectsInvalidLaterResult()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease);val meal=uuid();val weight=uuid()
            repo.addCustomProduct(CustomProductDraft("Synthetic meal",100.0,null,0.0,12.0,"fixture"),100.0,MealType.LUNCH,LocalDate.now(),meal)
            repo.addWeight(80.5,LocalDate.now(),weight)
            val store=MealPushStore(db,schema);val request=store.prepare(lease)!!;store.markAttempted(request)
            assertEquals(2,request.batch.json().getJSONArray("operations").length())
            val bad=JSONObject(String(reply(request)));bad.getJSONArray("results").getJSONObject(1).put("entity_id",uuid())
            rejected{store.prepareAck(request,200,bad.toString().toByteArray())}
            val prepared=store.prepareAck(request,200,reply(request))
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_weight_ack BEFORE UPDATE ON canonical_weights BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
            rejected{store.applyAck(prepared)}
            assertEquals(0,db.dao().meal(meal,lease.storageScope)!!.meal.serverRevision)
            assertEquals(0,db.weightSyncDao().state(lease.storageScope,weight)!!.serverRevision)
            assertNull(db.pushDao().batch(request.id)!!.responseJson)
            assertTrue(request.operations.all {db.dao().operation(it.operationId)!!.status=="pending"})
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_weight_ack")
            assertEquals(2,store.applyAck(prepared).acknowledged)
            assertEquals(1,db.dao().meal(meal,lease.storageScope)!!.meal.serverRevision)
            assertEquals(1,db.weightSyncDao().state(lease.storageScope,weight)!!.serverRevision)
        }finally{db.close()}
    }

    @Test fun guestUnlinkedAndExcessPrecisionRemainLocalAndRecoveryPreservesCanonicalEdit()=runBlocking<Unit> {
        for(mode in 0..3) {
            val db=memory()
            try {
                val lease=if(mode==0)LocalOwnerStore(db).let {it.ensureGuest();it.currentLease()} else account(db,mode!=1)
                val repo=DiaryRepository(db,context,lease);val id=uuid();val kg=if(mode==2)80.1234567 else 80.5
                repo.addWeight(kg,LocalDate.now(),id)
                if(mode<3) {
                    assertNull(db.weightSyncDao().state(lease.storageScope,id));assertEquals(kg,db.dao().weight(id,lease.storageScope)!!.kg,0.0)
                    assertEquals(1,db.dao().operationCount(lease.storageScope))
                } else {
                    val binding=db.bootstrapDao().binding(lease.storageScope)!!;db.bootstrapDao().update(binding.copy(requiresRecovery=true))
                    repo.editWeight(id,81.25);assertEquals(81.25,db.dao().weight(id,lease.storageScope)!!.kg,0.0)
                    assertEquals("waiting_recovery",db.weightSyncDao().operations(lease.storageScope,id).single().status)
                    val other=account(db);rejected{repo.addWeight(90.0,LocalDate.now(),uuid())}
                    assertNotEquals(lease.storageScope,other.storageScope)
                }
            }finally{db.close()}
        }
    }

    @Test fun migration14To15PreservesEveryOldTableLegacyPrecisionQueueAndWeightRowids()=runBlocking<Unit> {
        val source=memory();val name="weight-migration-${uuid()}";var target:CalorieDatabase?=null
        try {
            val owners=LocalOwnerStore(source);owners.ensureGuest();val lease=owners.currentLease()
            val weight=uuid();DiaryRepository(source,context,lease).addWeight(80.123456789,LocalDate.now(),weight)
            val testContext=InstrumentationRegistry.getInstrumentation().context
            val schema=testContext.assets.open("pl.roseru.kalorie.data.CalorieDatabase/14.json").use {JSONObject(String(it.readBytes())).getJSONObject("database")}
            val entities=schema.getJSONArray("entities")
            fun dump(query:(String)->android.database.Cursor)=buildMap<String,List<List<String?>>>{
                for(i in 0 until entities.length()) {
                    val e=entities.getJSONObject(i);val fields=e.getJSONArray("fields")
                    val columns=(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    put(e.getString("tableName"),query("SELECT $columns FROM `${e.getString("tableName")}` ORDER BY rowid").use {c->buildList {
                        while(c.moveToNext())add((0 until c.columnCount).map {
                            when {
                                c.isNull(it)->null
                                c.getType(it)==android.database.Cursor.FIELD_TYPE_FLOAT->c.getDouble(it).toString()
                                else->c.getString(it)
                            }
                        })
                    }})
                }
            }
            val rows=dump {source.openHelper.readableDatabase.query(it)}
            context.getDatabasePath(name).parentFile!!.mkdirs();var before=emptyMap<String,List<List<String?>>>()
            android.database.sqlite.SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use {old->
                old.execSQL("PRAGMA foreign_keys=OFF")
                for(i in 0 until entities.length()) {
                    val e=entities.getJSONObject(i);val table=e.getString("tableName");old.execSQL(e.getString("createSql").replace("\${TABLE_NAME}",table))
                    val indices=e.optJSONArray("indices")?:JSONArray();for(j in 0 until indices.length())old.execSQL(indices.getJSONObject(j).getString("createSql").replace("\${TABLE_NAME}",table))
                    val fields=e.getJSONArray("fields");val columns=(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    val marks=(0 until fields.length()).joinToString(","){"?"}
                    rows.getValue(table).forEach {old.execSQL("INSERT INTO `$table` ($columns) VALUES ($marks)",it.toTypedArray())}
                }
                old.execSQL("UPDATE weights SET rowid=100 WHERE id=?",arrayOf(weight))
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(schema.getString("identityHash")));old.version=14
                before=dump {old.rawQuery(it,null)}
                assertEquals(80.123456789,old.rawQuery("SELECT kg FROM weights WHERE id=?",arrayOf(weight)).use {
                    assertTrue(it.moveToFirst());it.getDouble(0)
                },0.0)
            }
            target=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_14_15, pl.roseru.kalorie.data.MIGRATION_15_16).addCallback(DATABASE_GUARDS).build()
            val sql=target!!.openHelper.readableDatabase;assertEquals(16,sql.version);assertEquals(before,dump {sql.query(it)})
            assertEquals(80.123456789,target!!.dao().weight(weight,lease.storageScope)!!.kg,0.0)
            assertNull(target!!.weightSyncDao().state(lease.storageScope,weight))
            assertEquals(100L,sql.query("SELECT rowid FROM weights WHERE id=?",arrayOf(weight)).use {assertTrue(it.moveToFirst());it.getLong(0)})
            assertFalse(sql.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
        }finally{target?.close();source.close();context.deleteDatabase(name)}
    }
}
