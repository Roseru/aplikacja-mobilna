package pl.roseru.kalorie

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
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

class ImportOriginsMigrationTest {
    @Test fun migration21To22PreservesBlockedStateAndAllOldCellsWithoutInventingCompletionProof()=migrate(21)
    @Test fun migration20To21PreservesAllOldTablesFrozenRequestsAndOrigins()=migrate(20)
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private fun uuid()=UUID.randomUUID().toString()
    @Test fun actualRoom19RetainsAllOldCellsAndFrozenBodiesWhileBackfillingCrossPlanOrigin()=migrate(19)
    @Test fun releasedRoom18PreservesLegacyAndAttemptedCanonicalDataThroughBothMigrations()=migrate(18)
    private fun migrate(version:Int)=runBlocking<Unit> {
        val source=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val name="origin-room$version-${uuid()}";var target:CalorieDatabase?=null
        try {
            val owners=LocalOwnerStore(source);owners.ensureGuest();val id=uuid()
            source.dao().insertMeal(MealEntity(id,"guest","2001-01-02","2001-01-02T12:00:00Z","UTC","LUNCH"))
            source.dao().insertItem(MealItemEntity("item-"+id,id,null,"Historical",50.0,100.125,null,0.0,12.5))
            val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/origins",uuid()).id)
            val epoch="55555555-5555-4555-8555-555555555555";val boot=AccountBootstrapStore(source)
            boot.apply(boot.begin(lease),BootstrapResponse(uuid(),epoch,1,"2026-10-23T12:00:00Z"))
            val wire=CanonicalMealRows.schema(context);val snapshots=ServerSnapshotStore(source,SnapshotProtocol(wire))
            val page=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-origin")
                .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-checkpoint").put("server_time","2026-10-23T12:00:00Z")
                .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
            assertNull(snapshots.apply(snapshots.begin(lease),page.toString().toByteArray()))
            val plan=if(version>=19) {
                val importer=LegacyImportStore(source,wire);val preview=importer.preview(lease,"guest")
                importer.approve(lease,preview.planId,preview.account,preview.issuer,preview.subject);importer.resume(lease,preview.planId)
                preview
            } else {
                // Authentic schema18 data: no import ledger, aliases or converted local projections.
                source.dao().saveGoal(GoalEntity("legacy-goal","guest","2001-01-02",2100.123456789,null,0.0,null))
                source.dao().saveProfile(ProfileEntity("legacy-profile","guest","Historical",180.125,"LINE","REDUCE","UTC",1))
                source.dao().saveDiaryDay(DiaryDayEntity("legacy-day","guest","2001-01-02",true,1))
                source.dao().insertProduct(ProductEntity("legacy-product","Label","label",150.5,null,0.0,null,100.0,"Private","Historical label",0,"guest"))
                source.dao().saveWeight(WeightEntity("legacy-weight","guest","2001-01-02","2001-01-02T12:00:00Z","UTC",80.123456789))
                source.dao().enqueue(OutboxEntity("legacy-operation","guest","weight","legacy-weight","update",null,"{\"kg\":80.123456789}","2001-01-02T12:00:00Z"))
                DiaryRepository(source,context,lease).addWeight(81.125,java.time.LocalDate.of(2001,1,2))
                null
            }
            val origin=plan?.let {source.importDao().sources(it.planId).single()};val push=MealPushStore(source,wire)
            val frozen=push.prepare(lease)!!;push.markAttempted(frozen)
            if(version==21)source.syncWorkDao().save(SyncWorkState(lease.storageScope,lease.generation,
                CanonicalMealRows.context(source.bootstrapDao().binding(lease.storageScope)!!),"old-cycle","push","reconciliation",90000,3,7,5,2,0,1,123))
            val original=source.dao().operation(frozen.operations.single().operationId)!!
            val body=frozen.batch.body();val hash=frozen.batch.sha256
            val schema=InstrumentationRegistry.getInstrumentation().context.assets.open("pl.roseru.kalorie.data.CalorieDatabase/$version.json")
                .use {JSONObject(String(it.readBytes())).getJSONObject("database")}
            val entities=schema.getJSONArray("entities")
            fun dump(query:(String)->Cursor):Map<String,List<List<Any?>>> = buildMap {
                for(i in 0 until entities.length()) {
                    val entity=entities.getJSONObject(i);val table=entity.getString("tableName");val fields=entity.getJSONArray("fields")
                    val columns="rowid,"+(0 until fields.length()).joinToString(",") {"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    put(table,query("SELECT $columns FROM `$table` ORDER BY rowid").use {cursor->buildList {
                        while(cursor.moveToNext())add((0 until cursor.columnCount).map {column->when(cursor.getType(column)) {
                            Cursor.FIELD_TYPE_NULL->null;Cursor.FIELD_TYPE_INTEGER->cursor.getLong(column)
                            Cursor.FIELD_TYPE_FLOAT->cursor.getDouble(column);else->cursor.getString(column)
                        }})
                    }})
                }
            }
            val cells=dump {source.openHelper.readableDatabase.query(it)}
            context.getDatabasePath(name).parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use {old->
                old.execSQL("PRAGMA foreign_keys=OFF")
                for(i in 0 until entities.length()) {
                    val entity=entities.getJSONObject(i);val table=entity.getString("tableName");val fields=entity.getJSONArray("fields")
                    old.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}",table))
                    val indices=entity.optJSONArray("indices") ?: JSONArray()
                    for(j in 0 until indices.length())old.execSQL(indices.getJSONObject(j).getString("createSql").replace("\${TABLE_NAME}",table))
                    val columns="rowid,"+(0 until fields.length()).joinToString(",") {"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    val marks=(0..fields.length()).joinToString(","){"?"}
                    cells.getValue(table).forEach {old.execSQL("INSERT INTO `$table` ($columns) VALUES ($marks)",it.toTypedArray())}
                }
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(schema.getString("identityHash")))
                old.version=version
                assertEquals(cells,dump {old.rawQuery(it,null)})
                assertFalse(old.rawQuery("PRAGMA foreign_key_check",null).use {it.moveToFirst()})
            }
            target=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_18_19,MIGRATION_19_20, pl.roseru.kalorie.data.MIGRATION_20_21, pl.roseru.kalorie.data.MIGRATION_21_22, pl.roseru.kalorie.data.MIGRATION_22_23, pl.roseru.kalorie.data.MIGRATION_23_24, pl.roseru.kalorie.energy.MIGRATION_24_25).addCallback(DATABASE_GUARDS).build()
            val db=target!!;assertEquals(25,db.openHelper.readableDatabase.version)
            if(version==21) {
                val migratedState=db.syncWorkDao().state(lease.storageScope)!!
                assertNull(migratedState.reconciliationBaseline)
                assertEquals("reconciliation",migratedState.status)
                assertEquals(0L,db.syncWorkDao().completionSequence(lease.storageScope,migratedState.wireContext))
            }
            assertEquals(cells,dump {db.openHelper.readableDatabase.query(it)})
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
            if(version>=19) {
                val migrated=db.importDao().origin("guest","meal",id)!!
                assertEquals(plan!!.planId,migrated.firstPlanId);assertEquals(original.operationId,migrated.firstOperationId)
                assertEquals(origin!!.originFingerprint,migrated.firstFingerprint)
            } else {
                assertTrue(db.importDao().plans(lease.storageScope).isEmpty())
                assertEquals(80.123456789,db.dao().weight("legacy-weight","guest")!!.kg,0.0)
                assertEquals("{\"kg\":80.123456789}",db.dao().operation("legacy-operation")!!.payload)
            }
            assertEquals(original,db.dao().operation(original.operationId))
            assertArrayEquals(body,db.pushDao().batch(frozen.id)!!.requestJson.toByteArray());assertEquals(hash,db.pushDao().batch(frozen.id)!!.requestHash)
            db.dao().saveWeight(WeightEntity("new-after-migration","guest","2001-01-03","2001-01-03T12:00:00Z","UTC",81.0))
            val importer2=LegacyImportStore(db,wire);val second=importer2.preview(lease,"guest")
            if(version>=19)assertEquals("already_imported",db.importDao().source(second.planId,"meal",id)!!.state)
            else assertEquals(7,second.total)
            if(version>=19){importer2.approve(lease,second.planId,second.account,second.issuer,second.subject);importer2.resume(lease,second.planId)}
            assertEquals(original,db.dao().operation(original.operationId))
            assertArrayEquals(body,db.pushDao().batch(frozen.id)!!.requestJson.toByteArray())
        } finally {target?.close();source.close();context.deleteDatabase(name)}
    }
}
