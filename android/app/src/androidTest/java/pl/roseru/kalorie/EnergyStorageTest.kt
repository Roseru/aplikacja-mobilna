package pl.roseru.kalorie

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.energy.*
import java.time.LocalDate
import java.util.UUID

class EnergyStorageTest {
    @Test fun durableConsentMarkerCannotBeClearedByAnOverlappingReadAndOwnUnknownConsentStaysUncertain()=runBlocking<Unit> {
        val name="energy-consent-${UUID.randomUUID()}";var db=EnergyFixture.database(name)
        try {
            val scope=EnergyFixture.account(db);val server=EnergyFixture.Server();val repository=EnergyFixture.repository(db,scope,server)
            repository.refresh(scope.lease)
            val change=repository.beginConsentChange(scope.lease)
            assertTrue(repository.local(scope.lease).consentUncertain)
            repository.refresh(scope.lease)
            assertTrue(repository.local(scope.lease).consentUncertain);assertNull(repository.local(scope.lease).reviewToken)
            repository.finishConsentChange(change)
            db.close();db=EnergyFixture.database(name)
            val restored=checkNotNull(EnergyStore(db).scope(LocalOwnerStore(db).currentLease()))
            val next=EnergyFixture.repository(db,restored,server)
            assertTrue(next.local(restored.lease).consentUncertain)
            next.refresh(restored.lease)
            assertFalse(next.local(restored.lease).consentUncertain);assertNotNull(next.local(restored.lease).reviewToken)
            val store=EnergyStore(db)
            val row=store.prepare(restored,"consents","consent","PUT","/me/consents",
                "{\"ranking\":false,\"automatic_energy_adjustment\":false}","\"2\"",EnergyFixture.instant.toEpochMilli())
            store.attempted(restored,row)
            next.refresh(restored.lease)
            assertTrue(next.local(restored.lease).consentUncertain);assertNull(next.local(restored.lease).reviewToken)
            assertTrue(server.requests.none {it.second!=null})
        }finally {db.close();EnergyFixture.context.deleteDatabase(name)}
    }
    @Test fun uncertainAdmissionSurvivesReopenAndLateForeignOwnerCannotCommitIt()=runBlocking<Unit> {
        val name="energy-replay-${UUID.randomUUID()}";var db=EnergyFixture.database(name)
        try {
            val scope=EnergyFixture.account(db);val ownerId=checkNotNull(db.ownerDao().byScope(scope.lease.storageScope)).id
            val goalId=UUID.randomUUID().toString();DiaryRepository(db,EnergyFixture.context,scope.lease).setGoal(2500.0,null,null,null,goalId)
            val goal=db.dao().goalById(scope.lease.storageScope,goalId)
            fun outbox(database:CalorieDatabase)=database.openHelper.readableDatabase.query("SELECT rowid,* FROM outbox ORDER BY rowid").use(::rows)
            val original=outbox(db);val server=EnergyFixture.Server(loseFirstCreate=true)
            val first=EnergyFixture.repository(db,scope,server)
            first.local(scope.lease);assertTrue(server.requests.isEmpty())
            first.refresh(scope.lease)
            val token=checkNotNull(first.local(scope.lease).reviewToken)
            assertTrue(runCatching {first.create(scope.lease,token,true,true)}.isFailure)
            val uncertain=EnergyStore(db).attempts(scope).single()
            assertEquals("unknown",uncertain.state);assertTrue(uncertain.attempted);assertEquals(1,server.admissions)
            assertTrue(runCatching {db.openHelper.writableDatabase.execSQL("UPDATE energy_attempts SET body='{}' WHERE id=?",arrayOf(uncertain.id))}.isFailure)
            assertTrue(runCatching {db.openHelper.writableDatabase.execSQL("DELETE FROM energy_attempts WHERE id=?",arrayOf(uncertain.id))}.isFailure)
            db.close();db=EnergyFixture.database(name)
            val restored=checkNotNull(EnergyStore(db).scope(LocalOwnerStore(db).currentLease()))
            assertEquals(uncertain,EnergyStore(db).attempts(restored).single())
            val second=EnergyFixture.repository(db,restored,server)
            server.afterReply={server.afterReply=null;EnergyFixture.account(db,"B")}
            assertTrue(runCatching {second.retry(restored.lease,uncertain.id)}.exceptionOrNull() is StaleOwnerException)
            val other=checkNotNull(EnergyStore(db).scope(LocalOwnerStore(db).currentLease()))
            assertTrue(EnergyStore(db).cached(other).isEmpty());assertTrue(EnergyStore(db).attempts(other).isEmpty())
            val newLease=LocalOwnerStore(db).select(ownerId);val resumed=checkNotNull(EnergyStore(db).scope(newLease))
            val final=EnergyFixture.repository(db,resumed,server).retry(newLease,uncertain.id)
            assertEquals("succeeded",final.state);assertEquals(uncertain.body,final.body)
            assertEquals(uncertain.fingerprint,final.fingerprint);assertEquals(uncertain.leaseGeneration,final.leaseGeneration)
            assertNotEquals(newLease.generation,final.leaseGeneration)
            assertEquals(1,server.admissions)
            val sends=server.requests.filter {it.second!=null}
            assertEquals(3,sends.size);assertEquals(1,sends.map {it.second}.distinct().size);assertEquals(1,sends.map {it.third}.distinct().size)
            assertEquals(goal,db.dao().goalById(newLease.storageScope,goalId));assertEquals(original,outbox(db))
        }finally {db.close();EnergyFixture.context.deleteDatabase(name)}
    }
    @Test fun room24MigrationKeepsEveryOldColumnAndRequestAndAddsOnlyEmptyEnergyTables()=runBlocking<Unit> {
        val context=EnergyFixture.context;val sourceName="energy-source-${UUID.randomUUID()}";val name="energy-room24-${UUID.randomUUID()}"
        val source=EnergyFixture.database(sourceName);var migrated:CalorieDatabase?=null
        try {
            val lease=LocalOwnerStore(source).currentLease();val diary=DiaryRepository(source,context,lease)
            diary.setProfile("Syntetyczny profil",180.125,ActivityClass.LINE,DietAim.MAINTAIN)
            val input=MaintenanceInput(30,"180".toBigDecimal(),"80".toBigDecimal(),EquationVariant.PLUS_5,ActivityClass.LINE)
            diary.setCalculatedGoal(MaintenanceEstimate.calculate(input),2500.125,null,0.0,200.0,DietAim.REDUCE,true)
            diary.addWeight(81.123456789,LocalDate.of(2026,10,24))
            val fixture=androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context.assets
                .open("pl.roseru.kalorie.data.CalorieDatabase/24.json").use {StrictJson.read(it.readBytes()).getJSONObject("database")}
            val entities=fixture.getJSONArray("entities")
            fun columns(entity:org.json.JSONObject)="rowid,"+entity.getJSONArray("fields").let {fields->(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}}
            fun dump(query:(String)->Cursor)=buildMap<String,List<List<String?>>>{for(i in 0 until entities.length()) {
                val entity=entities.getJSONObject(i);put(entity.getString("tableName"),query("SELECT ${columns(entity)} FROM `${entity.getString("tableName")}` ORDER BY rowid").use(::rows))
            }}
            val before=dump {source.openHelper.readableDatabase.query(it)}
            context.getDatabasePath(name).parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use {old->
                old.execSQL("PRAGMA foreign_keys=OFF");old.execSQL("ATTACH DATABASE ? AS origin",arrayOf(context.getDatabasePath(sourceName).absolutePath))
                for(i in 0 until entities.length()) {
                    val entity=entities.getJSONObject(i);val table=entity.getString("tableName")
                    fun resolved(sql:String)=sql.replace("\${TABLE_NAME}",table)
                    old.execSQL(resolved(entity.getString("createSql")))
                    val indices=entity.optJSONArray("indices")?:JSONArray()
                    for(j in 0 until indices.length())old.execSQL(resolved(indices.getJSONObject(j).getString("createSql")))
                    old.execSQL("INSERT INTO `$table` (${columns(entity)}) SELECT ${columns(entity)} FROM origin.`$table`")
                }
                old.execSQL("DETACH DATABASE origin");old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(fixture.getString("identityHash")));old.version=24
            }
            migrated=androidx.room.Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_24_25).addCallback(DATABASE_GUARDS).build()
            val sql=migrated.openHelper.readableDatabase;assertEquals(25,sql.version);assertEquals(before,dump {sql.query(it)})
            for(table in listOf("energy_cache","energy_attempts","energy_backoff"))assertEquals(0,sql.query("SELECT count(*) FROM $table").use {it.moveToFirst();it.getInt(0)})
            assertFalse(sql.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
            assertTrue(sql.query("SELECT count(*) FROM goals WHERE estimateJson IS NOT NULL").use {it.moveToFirst();it.getInt(0)>0})
        }finally {migrated?.close();source.close();context.deleteDatabase(name);context.deleteDatabase(sourceName)}
    }
    private fun rows(cursor:Cursor):List<List<String?>> = buildList {
        while(cursor.moveToNext())add((0 until cursor.columnCount).map {if(cursor.isNull(it))null else "${cursor.getType(it)}:${cursor.getString(it)}"})
    }
}
