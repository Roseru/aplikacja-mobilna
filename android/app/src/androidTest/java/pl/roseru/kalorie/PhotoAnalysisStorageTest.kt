package pl.roseru.kalorie

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.graphics.Bitmap
import android.graphics.Color
import androidx.room.Room
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.photo.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.time.LocalDate
import java.util.UUID

/** Real Room/filesystem and deterministic receipt fixtures; no HTTP or authenticated-user claim. */
class PhotoAnalysisStorageTest {
    private val context get()=InstrumentationRegistry.getInstrumentation().targetContext
    private val caps=PhotoCapabilitiesRead("mock","mock-food-v1","food-photo-notice-v1",true,null,5_242_880,10)
    private fun image():ByteArray {
        val bitmap=Bitmap.createBitmap(48,32,Bitmap.Config.ARGB_8888);bitmap.eraseColor(Color.GREEN)
        return ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.JPEG,95,it);bitmap.recycle() }.toByteArray()
    }
    private fun ack()=InstrumentationRegistry.getInstrumentation().context.assets.open("create-accepted.json").use { it.readBytes() }
    private suspend fun rejected(action:suspend()->Unit) {
        var rejected=false
        try { action() } catch(error:CancellationException){throw error} catch(_:Exception){rejected=true}
        assertTrue("Invalid or stale operation was accepted; values suppressed",rejected)
    }
    private suspend fun account(db:CalorieDatabase,subject:String):OwnerLease {
        val owners=LocalOwnerStore(db);owners.ensureGuest()
        val owner=owners.registerIdentity("https://fixture.example/realms/queue",subject)
        val lease=owners.select(owner.id)
        if(db.bootstrapDao().binding(lease.storageScope)==null) db.bootstrapDao().insert(AccountBindingEntity(lease.storageScope,
            UUID.randomUUID().toString(),1,UUID.randomUUID().toString(),"2026-10-15T12:00:00Z",1,false))
        return lease
    }
    private suspend fun photo(db:CalorieDatabase,lease:OwnerLease)=MealPhotoStore(context,db,lease)
        .import(ByteArrayInputStream(image()),LocalDate.of(2026,10,15),"gallery")
    private fun clean(scope:String) {
        // These fixture account scopes are fresh UUIDs; no recursive delete of shared directories.
        require(UUID.fromString(scope).toString()==scope)
        for(root in listOf("photo-analysis-inputs","meal-photo-drafts")) {
            val folder=File(context.filesDir,"$root/$scope")
            folder.listFiles()?.forEach { check(it.parentFile==folder && it.isFile);it.delete() }
            folder.delete()
        }
    }
    @Test fun pendingInputAndKeySurviveRestartSourceDeletionAndLostAckWithoutJournalWrites()=runBlocking<Unit> {
        val name="queue-${UUID.randomUUID()}";var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
        var scope:String?=null
        try {
            val lease=account(db,"restart");scope=lease.storageScope
            val source=photo(db,lease);var store=PhotoAnalysisStore(context,db,lease)
            val beforeMeals=db.dao().achievementMeals(lease.storageScope);val beforeOps=db.dao().operationCount(lease.storageScope)
            val row=store.prepare(source.id,caps,true);val first=store.request(row.operationId).body()
            assertFalse(row.attempted);assertNull(row.receiptJson);assertEquals("PhotoAnalysisRequestEntity(redacted)",row.toString())
            MealPhotoStore(context,db,lease).delete(source.id)
            assertNull(db.photoDao().get(lease.storageScope,source.id))
            store.markAttempted(row.operationId,0)
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
            store=PhotoAnalysisStore(context,db,LocalOwnerStore(db).currentLease())
            assertEquals(row.operationId,store.pending()!!.operationId);assertTrue(store.pending()!!.attempted)
            assertArrayEquals(first,store.request(row.operationId).body())
            store.markAttempted(row.operationId,0) // explicit lost-ACK retry, same operation
            assertArrayEquals(first,store.request(row.operationId).body())
            val accepted=store.accept(row.operationId,ack())
            assertEquals("queued",accepted.state);assertNotNull(store.pending()!!.receiptJson)
            assertEquals(beforeMeals,db.dao().achievementMeals(lease.storageScope));assertEquals(beforeOps,db.dao().operationCount(lease.storageScope))
            val privateImage=File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg")
            try { androidx.core.content.FileProvider.getUriForFile(context,"${context.packageName}.photo-capture",privateImage);fail("Analysis input exposed by camera provider") } catch(_:IllegalArgumentException){}
        } finally {db.close();context.deleteDatabase(name);scope?.let(::clean)}
    }
    @Test fun guestRefusedConsentAndUnavailableProviderNeverCreateAnOperation()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val owners=LocalOwnerStore(db);owners.ensureGuest();val guest=owners.currentLease()
            rejected {PhotoAnalysisStore(context,db,guest).prepare(UUID.randomUUID().toString(),caps,true)}
            assertNull(db.photoAnalysisDao().get("guest"))
            val lease=account(db,"consent");scope=lease.storageScope;val source=photo(db,lease)
            val store=PhotoAnalysisStore(context,db,lease)
            rejected {store.prepare(source.id,caps,false)}
            rejected {store.prepare(source.id,caps.copy(available=false,unavailableReason="not_ready"),true)}
            assertNull(store.pending());assertNotNull(db.photoDao().get(lease.storageScope,source.id))
            assertFalse(File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}").exists())
            assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun abaAndServerContextChangesFenceDeliveryButPreservePendingInput()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();val scopes=mutableListOf<String>()
        try {
            val a=account(db,"A");scopes+=a.storageScope;val store=PhotoAnalysisStore(context,db,a)
            val row=store.prepare(photo(db,a).id,caps,true);val bytes=store.request(row.operationId).body()
            val b=account(db,"B");scopes+=b.storageScope;assertNull(PhotoAnalysisStore(context,db,b).pending())
            rejected {store.request(row.operationId)};rejected {store.markAttempted(row.operationId,0)}
            rejected {store.accept(row.operationId,ack())}
            val newer=LocalOwnerStore(db).select(a.storageScope);rejected {store.pending()}
            val resumed=PhotoAnalysisStore(context,db,newer);assertArrayEquals(bytes,resumed.request(row.operationId).body())
            val original=checkNotNull(db.bootstrapDao().binding(newer.storageScope))
            for(changed in listOf(original.copy(accountGeneration=2),original.copy(syncEpoch=UUID.randomUUID().toString()),
                original.copy(contextRevision=2),original.copy(requiresRecovery=true),original.copy(accountId=UUID.randomUUID().toString()))) {
                db.bootstrapDao().update(changed);rejected {resumed.request(row.operationId)}
                assertEquals(row,resumed.pending());db.bootstrapDao().update(original)
            }
            db.bootstrapDao().update(original.copy(requiresRecovery=true,contextRevision=2))
            resumed.dropNeverAttempted(row.operationId) // explicit local discard, never sent
            assertNull(resumed.pending())
        } finally {db.close();scopes.forEach(::clean)}
    }
    @Test fun twoConcurrentPreparationsCannotReplaceConsentKeyOrLeaveASecondInput()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"race");scope=lease.storageScope;val source=photo(db,lease)
            val store=PhotoAnalysisStore(context,db,lease)
            val results=coroutineScope {(1..2).map {async(Dispatchers.IO){runCatching {store.prepare(source.id,caps,true)}}}.awaitAll()}
            assertEquals(1,results.count {it.isSuccess});assertEquals(1,results.count {it.isFailure})
            val row=store.pending()!!;assertNotNull(store.request(row.operationId))
            val files=File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}").listFiles()!!.filter {it.name.endsWith(".jpg")}
            assertEquals(listOf("${row.operationId}.jpg"),files.map {it.name})
            assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun damagedInputRetryAfterAndInvalidAckCannotAdvanceOrReplaceAcceptedReceipt()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"integrity");scope=lease.storageScope;val store=PhotoAnalysisStore(context,db,lease)
            val row=store.prepare(photo(db,lease).id,caps,true)
            val file=File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg")
            val original=file.readBytes();file.writeBytes(byteArrayOf(0));rejected {store.request(row.operationId)}
            assertNull(store.pending()!!.receiptJson);file.writeBytes(original)
            store.defer(row.operationId,60_000);rejected {store.markAttempted(row.operationId,59_999)}
            assertFalse(store.pending()!!.attempted);store.markAttempted(row.operationId,60_000)
            rejected {store.accept(row.operationId,"{}".toByteArray())};assertNull(store.pending()!!.receiptJson)
            rejected {store.dropNeverAttempted(row.operationId)}
            store.accept(row.operationId,ack());val accepted=store.pending()!!
            store.accept(row.operationId,ack());assertEquals(accepted,store.pending())
            val changed=JSONObject(ack().toString(Charsets.UTF_8)).put("analysis_id",UUID.randomUUID().toString()).toString().toByteArray()
            rejected {store.accept(row.operationId,changed)};rejected {store.block(row.operationId,"unauthorized")}
            rejected {store.defer(row.operationId,70_000)};rejected {store.markAttempted(row.operationId,70_000)}
            assertEquals(accepted,store.pending());assertTrue(file.exists())
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun migrationNineToTenPreservesAllTwentyThreeTablesPhotoDiaryAndForeignKeys()=runBlocking<Unit> {
        val schema=JSONObject(InstrumentationRegistry.getInstrumentation().context.assets.open("pl.roseru.kalorie.data.CalorieDatabase/9.json").bufferedReader().use {it.readText()}).getJSONObject("database")
        val entities=schema.getJSONArray("entities")
        fun snapshot(db:SupportSQLiteDatabase)=buildMap<String,List<List<String?>>>{
            for(index in 0 until entities.length()) {
                val table=entities.getJSONObject(index).getString("tableName")
                put(table,db.query("SELECT * FROM \"$table\" ORDER BY rowid").use {cursor->buildList {
                    while(cursor.moveToNext()) add((0 until cursor.columnCount).map {if(cursor.isNull(it))null else cursor.getString(it)})
                }})
            }
        }
        val source=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val name="queue-migration-${UUID.randomUUID()}";var scope:String?=null
        try {
            val lease=account(source,"migration");scope=lease.storageScope
            val repository=DiaryRepository(source,context,lease);repository.initialize()
            repository.add(source.dao().products(lease.storageScope).first().first().id,120.0,MealType.LUNCH,LocalDate.now())
            repository.addWeight(80.0,LocalDate.now());val storedPhoto=photo(source,lease)
            val before=snapshot(source.openHelper.readableDatabase);assertEquals(23,before.size)
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use {old->
                old.execSQL("PRAGMA foreign_keys=OFF")
                for(index in 0 until entities.length()) {
                    val entity=entities.getJSONObject(index);val table=entity.getString("tableName")
                    old.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}",table))
                    val indices=entity.optJSONArray("indices")?:org.json.JSONArray()
                    for(i in 0 until indices.length()) old.execSQL(indices.getJSONObject(i).getString("createSql").replace("\${TABLE_NAME}",table))
                    val fields=entity.getJSONArray("fields")
                    before.getValue(table).forEach {row->
                        val values=ContentValues();row.forEachIndexed {i,value->val column=fields.getJSONObject(i).getString("columnName");if(value==null)values.putNull(column) else values.put(column,value)}
                        old.insertOrThrow(table,null,values)
                    }
                }
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(schema.getString("identityHash")));old.version=9
            }
            val migrated=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_9_10).addCallback(DATABASE_GUARDS).build()
            try {
                assertEquals(10,migrated.openHelper.readableDatabase.version)
                assertEquals(before,snapshot(migrated.openHelper.readableDatabase));assertNull(migrated.photoAnalysisDao().get(lease.storageScope))
                assertFalse(migrated.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
                MealPhotoStore(context,migrated,LocalOwnerStore(migrated).currentLease()).preview(storedPhoto.id).let {assertEquals(48,it.width);it.recycle()}
            } finally {migrated.close()}
        } finally {source.close();context.deleteDatabase(name);scope?.let(::clean)}
    }
    @Test fun preparedReceiptCommitsWithoutImageIoAndStillRejectsChangedContext()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"prepared-ack");scope=lease.storageScope;val store=PhotoAnalysisStore(context,db,lease)
            val row=store.prepare(photo(db,lease).id,caps,true);val sent=store.request(row.operationId);store.markAttempted(row.operationId,0)
            val different=PhotoHttpRequest.Create.prepare(row.operationId,checkNotNull(sent.epoch),caps,true,image().also {it[it.lastIndex]=(it.last()+1).toByte()},"image/jpeg")
            rejected {store.prepareReceipt(row.operationId,ack(),different)}
            assertNull(store.pending()!!.receiptJson)
            val prepared=store.prepareReceipt(row.operationId,ack(),sent)
            assertEquals("PreparedPhotoReceipt(redacted)",prepared.toString())
            assertTrue(File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg").delete())
            val original=db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(original.copy(contextRevision=original.contextRevision+1))
            rejected {store.acceptPrepared(prepared)};assertNull(store.pending()!!.receiptJson)
            db.bootstrapDao().update(original)
            store.acceptPrepared(prepared);assertNotNull(store.pending()!!.receiptJson)
        } finally {db.close();scope?.let(::clean)}
    }

}
