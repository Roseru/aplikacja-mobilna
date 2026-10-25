package pl.roseru.kalorie

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

class MaintenanceStorageTest {
    private val instrumentation get()=InstrumentationRegistry.getInstrumentation()
    private val context get()=instrumentation.targetContext
    private fun uuid()=UUID.randomUUID().toString()
    private fun estimate()=MaintenanceEstimate.calculate(MaintenanceInput(30,BigDecimal("180"),BigDecimal("80"),
        EquationVariant.PLUS_5,ActivityClass.LINE),Instant.parse("2026-10-24T12:00:00Z"))
    private fun schema()=CanonicalMealRows.schema(context)
    private fun memory()=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db:CalorieDatabase):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val lease=owners.select(owners.registerIdentity("https://fixture.example/realms/maintenance",uuid()).id)
        val bootstrap=AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(uuid(),uuid(),1,"2026-10-24T12:00:00Z"))
        val binding=checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        val page=JSONObject().put("sync_epoch",binding.syncEpoch).put("mode","snapshot")
            .put("snapshot_token","synthetic-maintenance-snapshot").put("page_token",JSONObject.NULL)
            .put("checkpoint","synthetic-maintenance-checkpoint").put("server_time","2026-10-24T12:00:00Z")
            .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
        val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema()))
        assertNull(snapshots.apply(snapshots.begin(lease),page.toString().toByteArray()))
        db.domainSyncDao().save(CanonicalGoalTimeline(lease.storageScope,CanonicalMealRows.context(binding),0))
        return lease
    }
    private suspend fun refused(block:suspend ()->Unit) {
        val failure=runCatching {block()}.exceptionOrNull()
        assertNotNull("Expected refusal without a partial write",failure)
    }

    @Test fun guestAuditSurvivesReopenAndManualGoalCorrectionPreservesOriginalRequestAndHistory()=runBlocking<Unit> {
        val name="maintenance-history-${uuid()}"
        var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
        try {
            val lease=LocalOwnerStore(db).currentLease();val repo=DiaryRepository(db,context,lease)
            val old=GoalEntity(uuid(),lease.storageScope,LocalDate.now().minusDays(1).toString(),2800.0,null,0.0,null)
            db.dao().saveGoal(old)
            val id=uuid();val audit=estimate()
            refused {repo.setCalculatedGoal(audit,2500.0,null,60.0,0.0,DietAim.REDUCE,false,id)}
            assertNull(db.dao().goalById(lease.storageScope,id))
            repo.setCalculatedGoal(audit,2500.0,null,60.0,0.0,DietAim.REDUCE,true,id)
            val selected=checkNotNull(db.dao().goalById(lease.storageScope,id))
            assertEquals(audit.stored(),selected.estimateJson);assertEquals(2500.0,selected.kcal,0.0)
            assertEquals(old,db.dao().goalById(lease.storageScope,old.id))
            fun frozen():List<String> = db.openHelper.readableDatabase.query("SELECT operationId,payload,wireJson,attempted FROM outbox WHERE entityId=? ORDER BY rowid",arrayOf(id)).use {cursor->
                buildList {while(cursor.moveToNext())add((0 until cursor.columnCount).joinToString("|"){if(cursor.isNull(it))"<NULL>" else cursor.getString(it)})}}
            val wireBefore=frozen()
            val payload=db.openHelper.readableDatabase.query("SELECT payload FROM outbox WHERE entityId=?",arrayOf(id)).use {it.moveToFirst();JSONObject(it.getString(0))}
            assertEquals("reduce",payload.getString("goal_type"));assertEquals("LINE",payload.getString("activity_class"))
            assertEquals(audit.stored(),StrictJson.canonical(payload.getJSONObject("estimate")))
            repo.setGoal(2400.0,null,60.0,0.0)
            assertEquals(selected,db.dao().goalById(lease.storageScope,id));assertEquals(wireBefore,frozen())
            assertNull(db.dao().goalOn(lease.storageScope,LocalDate.now().toString())!!.estimateJson)
            val captured=LegacyImportStore(db,schema()).capture(lease.storageScope,true).single {entry->
                entry.first=="goal" && StrictJson.read(entry.second.toByteArray()).getJSONObject("row").getString("id")==id}
            val source=StrictJson.read(captured.second.toByteArray())
            val originals=source.getJSONArray("outboxes")
            val converted=LegacyImportWire.convert(LegacyImportSource("goal",id,source.getJSONObject("row").toString(),
                originalOutboxes=(0 until originals.length()).map {originals.getJSONObject(it).toString()}),
                LegacyImportIds(mapOf("goal:$id" to uuid())),LegacyImportMetadata(confirmed=true,timelineBaseRevision=0),schema())
            assertTrue(converted.toString(),converted is LegacyImportConversion.Ready)
            val ready=converted as LegacyImportConversion.Ready
            assertEquals(audit.stored(),StrictJson.canonical(StrictJson.read(checkNotNull(ready.payload).toByteArray()).getJSONObject("estimate")))
            val stateBefore=db.dao().goalById(lease.storageScope,id)
            val broken=audit.json().put("maintenance_kcal","9999").toString()
            refused {db.openHelper.writableDatabase.execSQL("INSERT OR REPLACE INTO goals SELECT id,ownerScope,validFrom,kcal,protein,fat,carbs,localSequence,decidedAt,zoneId,reason,correctionOf,? FROM goals WHERE id=?",arrayOf(broken,id))}
            assertEquals(stateBefore,db.dao().goalById(lease.storageScope,id))
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addCallback(DATABASE_GUARDS).build()
            assertEquals(selected,db.dao().goalById(lease.storageScope,id));assertEquals(old,db.dao().goalById(lease.storageScope,old.id))
            assertEquals(wireBefore,frozen())
        }finally{db.close();context.deleteDatabase(name)}
    }

    @Test fun accountUsesValidatedGoalEstimateWithoutChangingProfileOrAnotherOwnersData()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val repo=DiaryRepository(db,context,lease)
            repo.setProfile("Syntetyczny profil",175.0,ActivityClass.GARRISON,DietAim.MAINTAIN)
            val profile=db.dao().currentProfile(lease.storageScope)
            val id=uuid();repo.setCalculatedGoal(estimate(),2500.0,null,0.0,200.0,DietAim.REDUCE,true,id)
            val row=checkNotNull(db.domainSyncDao().state(lease.storageScope,"goal",id))
            val wire=PrivateDomainsWire.read("goal",checkNotNull(row.wirePayload),schema())
            val payload=StrictJson.read(wire.toByteArray())
            assertEquals("2500",payload.getString("energy_kcal"));assertEquals("3204",payload.getJSONObject("estimate").getString("maintenance_kcal"))
            assertEquals("line",payload.getString("activity_class"));assertEquals("reduce",payload.getString("goal_type"))
            assertEquals(profile,db.dao().currentProfile(lease.storageScope))
            val before=db.dao().goalById(lease.storageScope,id)
            val other=account(db)
            assertNull(db.dao().goalById(other.storageScope,id))
            refused {repo.setCalculatedGoal(estimate(),2400.0,null,null,null,DietAim.MAINTAIN,true)}
            assertEquals(before,db.dao().goalById(lease.storageScope,id))
            assertNull(db.dao().goalOn(other.storageScope,LocalDate.now().toString()))
        }finally{db.close()}
    }

    @Test fun room23MigrationPreservesEveryOldColumnRowidAndRequestAndAddsOnlyNullAudit()=runBlocking<Unit> {
        val sourceName="maintenance-source-${uuid()}";val oldName="maintenance-room23-${uuid()}"
        val source=Room.databaseBuilder(context,CalorieDatabase::class.java,sourceName).addCallback(DATABASE_GUARDS).build()
        var migrated:CalorieDatabase?=null
        try {
            val lease=account(source);val repo=DiaryRepository(source,context,lease)
            val id=uuid();repo.setCalculatedGoal(estimate(),2500.0,null,0.0,200.0,DietAim.REDUCE,true,id)
            val audit=source.dao().goalById(lease.storageScope,id)!!.estimateJson
            val exported=instrumentation.context.assets.open("pl.roseru.kalorie.data.CalorieDatabase/23.json").use {StrictJson.read(it.readBytes()).getJSONObject("database")}
            val entities=exported.getJSONArray("entities")
            fun columns(entity:JSONObject)="rowid,"+entity.getJSONArray("fields").let {fields->(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}}
            fun dump(query:(String)->Cursor)=buildMap<String,List<List<String?>>>{for(i in 0 until entities.length()) {
                val entity=entities.getJSONObject(i);val name=entity.getString("tableName")
                put(name,query("SELECT ${columns(entity)} FROM `$name` ORDER BY rowid").use {cursor->buildList {
                    while(cursor.moveToNext())add((0 until cursor.columnCount).map {if(cursor.isNull(it))null else cursor.getString(it)})}})
            }}
            val before=dump {source.openHelper.readableDatabase.query(it)}
            context.getDatabasePath(oldName).parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(oldName),null).use {old->
                old.execSQL("PRAGMA foreign_keys=OFF");old.execSQL("ATTACH DATABASE ? AS origin",arrayOf(context.getDatabasePath(sourceName).absolutePath))
                for(i in 0 until entities.length()) {
                    val entity=entities.getJSONObject(i);val table=entity.getString("tableName")
                    fun resolve(sql:String)=sql.replace("\${TABLE_NAME}",table)
                    old.execSQL(resolve(entity.getString("createSql")))
                    val indices=entity.optJSONArray("indices") ?: JSONArray()
                    for(j in 0 until indices.length())old.execSQL(resolve(indices.getJSONObject(j).getString("createSql")))
                    old.execSQL("INSERT INTO `$table` (${columns(entity)}) SELECT ${columns(entity)} FROM origin.`$table`")
                }
                old.execSQL("DETACH DATABASE origin");old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(exported.getString("identityHash")));old.version=23
            }
            migrated=Room.databaseBuilder(context,CalorieDatabase::class.java,oldName).addMigrations(MIGRATION_23_24, pl.roseru.kalorie.energy.MIGRATION_24_25).addCallback(DATABASE_GUARDS).build()
            val sql=migrated.openHelper.readableDatabase
            assertEquals(25,sql.version);assertEquals(before,dump {sql.query(it)})
            assertEquals(0,sql.query("SELECT count(*) FROM goals WHERE estimateJson IS NOT NULL").use {it.moveToFirst();it.getInt(0)})
            assertFalse(sql.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
            // The exact previously archived canonical audit remains readable without updating the immutable old row.
            val oldGoal=migrated.dao().goalById(lease.storageScope,id)!!
            assertNull(oldGoal.estimateJson)
            val owners=LocalOwnerStore(migrated);val current=owners.currentLease()
            val projected=DiaryRepository(migrated,context,current).observeGoalEstimate(oldGoal).first()
            assertEquals(audit,projected?.estimateJson);assertNull(migrated.dao().goalById(lease.storageScope,id)!!.estimateJson)
        }finally{migrated?.close();source.close();context.deleteDatabase(sourceName);context.deleteDatabase(oldName)}
    }
}
