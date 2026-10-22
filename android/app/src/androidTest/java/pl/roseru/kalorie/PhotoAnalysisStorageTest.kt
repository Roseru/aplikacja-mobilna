package pl.roseru.kalorie

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.graphics.Bitmap
import android.graphics.Color
import androidx.room.Room
import androidx.room.withTransaction
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
    @Test fun migrationNineToLatestPreservesEveryOldColumnPhotoDiaryAndForeignKeys()=runBlocking<Unit> {migrationOldSchema(9)}
    @Test fun migrationTenToLatestPreservesPendingDecisionAndAllTwentyFourTables()=runBlocking<Unit> {migrationOldSchema(10)}
    @Test fun migrationElevenToTwelvePreservesMaterializationPendingDecisionAndAllTwentyFiveTables()=runBlocking<Unit> {migrationOldSchema(11)}
    private suspend fun migrationOldSchema(from:Int) {
        val schema=JSONObject(InstrumentationRegistry.getInstrumentation().context.assets.open("pl.roseru.kalorie.data.CalorieDatabase/$from.json").bufferedReader().use {it.readText()}).getJSONObject("database")
        val entities=schema.getJSONArray("entities")
        fun snapshot(db:SupportSQLiteDatabase)=buildMap<String,List<List<String?>>>{
            for(index in 0 until entities.length()) {
                val table=entities.getJSONObject(index).getString("tableName")
                val fields=entities.getJSONObject(index).getJSONArray("fields")
                val columns=(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                put(table,db.query("SELECT $columns FROM \"$table\" ORDER BY rowid").use {cursor->buildList {
                    while(cursor.moveToNext()) add((0 until cursor.columnCount).map {if(cursor.isNull(it))null else cursor.getString(it)})
                }})
            }
        }
        val source=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val name="queue-migration-${UUID.randomUUID()}";var scope:String?=null
        var itemRowids=emptyMap<String,Long>()
        try {
            val lease=account(source,"migration");scope=lease.storageScope
            val repository=DiaryRepository(source,context,lease);repository.initialize()
            repository.add(source.dao().products(lease.storageScope).first().first().id,120.0,MealType.LUNCH,LocalDate.now())
            repository.addWeight(80.0,LocalDate.now());val storedPhoto=photo(source,lease)
            if(from==11) {
                val(store,prepared)=materializationReceipt(source,lease)
                store.materializeConfirmationPrepared(prepared)
            }
            if(from>=10) {
                val (store,row)=cancellationQueue(source,lease);confirmationDraft(store,row.operationId)
                store.acceptConfirmationPrepared(store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,1))
                if(from==12) {
                    store.acceptConfirmationPrepared(store.prepareConfirmationAttempted(row.operationId,0))
                    val sent=store.stored(row.operationId).confirmation!!.request(row.syncEpoch)
                    store.acceptConfirmationPrepared(store.prepareConfirmationRejection(row.operationId,"photo_catalog_choice_changed",sent))
                }
            }
            val before=snapshot(source.openHelper.readableDatabase);assertEquals(from+14,before.size)
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
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(schema.getString("identityHash")));old.version=from
                itemRowids=old.rawQuery("SELECT id,rowid FROM meal_items",null).use {cursor->buildMap {while(cursor.moveToNext())put(cursor.getString(0),cursor.getLong(1))}}
            }
            val migrated=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_9_10, pl.roseru.kalorie.data.MIGRATION_10_11, pl.roseru.kalorie.data.MIGRATION_11_12, pl.roseru.kalorie.photo.MIGRATION_12_13, pl.roseru.kalorie.data.MIGRATION_13_14, pl.roseru.kalorie.data.MIGRATION_14_15).addCallback(DATABASE_GUARDS).build()
            try {
                assertEquals(15,migrated.openHelper.readableDatabase.version)
                assertEquals(before,snapshot(migrated.openHelper.readableDatabase))
                assertEquals(itemRowids,migrated.openHelper.readableDatabase.query("SELECT id,rowid FROM meal_items").use {cursor->buildMap<String,Long> {while(cursor.moveToNext())put(cursor.getString(0),cursor.getLong(1))}})
                if(from==12) {
                    val store=PhotoAnalysisStore(context,migrated,LocalOwnerStore(migrated).currentLease())
                    val row=store.pending()!!;val saved=store.stored(row.operationId)
                    assertTrue(migrated.photoConfirmationHistoryDao().decisions(lease.storageScope,row.operationId).isEmpty())
                    assertFalse(store.canReopenConfirmation(row.operationId,saved))
                    store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().toString().toByteArray()))
                    assertTrue(store.canReopenConfirmation(row.operationId,store.stored(row.operationId)))
                    assertEquals(1,migrated.photoConfirmationHistoryDao().decisions(lease.storageScope,row.operationId).size)
                }
                if(from==9)assertNull(migrated.photoAnalysisDao().get(lease.storageScope)) else
                    assertNotNull(PhotoAnalysisStore(context,migrated,LocalOwnerStore(migrated).currentLease()).stored(migrated.photoAnalysisDao().get(lease.storageScope)!!.operationId).confirmation)
                assertFalse(migrated.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
                assertTrue(migrated.pushDao().pending(lease.storageScope).isEmpty())
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

    private fun readResult()=JSONObject(InstrumentationRegistry.getInstrumentation().context.assets
        .open("analysis-read-succeeded.json").bufferedReader().use {it.readText()})
    private fun workingRead(revision:Int)=readResult().put("state","running").put("proposal",JSONObject.NULL)
        .put("revision",revision).toString().toByteArray(Charsets.UTF_8)

    @Test fun savedReadSurvivesRoomRestartWithoutImageAndAckReplayCannotEraseIt()=runBlocking<Unit> {
        val name="read-${UUID.randomUUID()}";var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
        var scope:String?=null
        try {
            val lease=account(db,"read-restart");scope=lease.storageScope;var store=PhotoAnalysisStore(context,db,lease)
            val row=store.prepare(photo(db,lease).id,caps,true);val sent=store.request(row.operationId)
            store.markAttempted(row.operationId,0);store.acceptPrepared(store.prepareReceipt(row.operationId,ack(),sent))
            val lateAck=store.prepareReceipt(row.operationId,ack(),sent)
            val prepared=store.prepareRead(row.operationId,readResult().toString().toByteArray(Charsets.UTF_8))
            val meals=db.dao().achievementMeals(lease.storageScope);val ops=db.dao().operationCount(lease.storageScope)
            assertEquals("PreparedPhotoRead(redacted)",prepared.toString())
            assertTrue(File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg").delete())
            store.acceptReadPrepared(prepared);val saved=store.pending()!!.receiptJson
            rejected {store.acceptPrepared(lateAck)}
            store.acceptPrepared(store.prepareReceipt(row.operationId,ack(),sent))
            assertEquals(saved,store.pending()!!.receiptJson)
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
            store=PhotoAnalysisStore(context,db,LocalOwnerStore(db).currentLease())
            val restored=store.stored(row.operationId)
            assertEquals(1L,restored.receipt.revision);assertEquals(2L,restored.latest!!.revision)
            assertEquals("Banan",restored.latest.proposal!!.items.single().name)
            assertEquals(meals,db.dao().achievementMeals(lease.storageScope));assertEquals(ops,db.dao().operationCount(lease.storageScope))
        } finally {db.close();context.deleteDatabase(name);scope?.let(::clean)}
    }
    @Test fun preparedReadCasPreservesTheNewerRevisionAndConcurrentRetryState()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"read-cas");scope=lease.storageScope;val store=PhotoAnalysisStore(context,db,lease)
            val row=store.prepare(photo(db,lease).id,caps,true);store.markAttempted(row.operationId,0);store.accept(row.operationId,ack())
            val older=store.prepareRead(row.operationId,workingRead(2));val newer=store.prepareRead(row.operationId,workingRead(3))
            store.acceptReadPrepared(newer);rejected {store.acceptReadPrepared(older)}
            assertEquals(3L,store.stored(row.operationId).latest!!.revision)
            val stale=store.prepareRead(row.operationId,workingRead(2));val before=store.pending()
            store.acceptReadPrepared(stale);assertEquals(before,store.pending())
            val next=store.prepareRead(row.operationId,workingRead(4))
            db.photoAnalysisDao().defer(lease.storageScope,row.operationId,90_000)
            rejected {store.acceptReadPrepared(next)}
            assertEquals(90_000L,store.pending()!!.retryAtMillis);assertEquals(3L,store.stored(row.operationId).latest!!.revision)
        } finally {db.close();scope?.let(::clean)}
    }
    private suspend fun cancellationQueue(db:CalorieDatabase,lease:OwnerLease):Pair<PhotoAnalysisStore,PhotoAnalysisRequestEntity> {
        val store=PhotoAnalysisStore(context,db,lease)
        val row=store.prepare(photo(db,lease).id,caps,true)
        store.markAttempted(row.operationId,0);store.accept(row.operationId,ack())
        store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().toString().toByteArray()))
        return store to row
    }
    private fun cancelAck(id:String,revision:Int=3)=JSONObject().put("analysis_id",id).put("revision",revision)
        .put("state","failed").put("decision_state","cancelled").put("error_code","analysis_cancelled").toString().toByteArray()

    @Test fun cancellationIntentAndAttemptSurviveRoomRestartWithoutImageOrJournalWrites()=runBlocking<Unit> {
        val name="cancel-${UUID.randomUUID()}";var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build();var scope:String?=null
        try {
            val lease=account(db,"cancel-restart");scope=lease.storageScope
            var (store,row)=cancellationQueue(db,lease);val key=UUID.randomUUID().toString()
            val meals=db.dao().achievementMeals(lease.storageScope);val ops=db.dao().operationCount(lease.storageScope)
            rejected {store.prepareCancellation(row.operationId,row.operationId,2)}
            store.acceptCancellationPrepared(store.prepareCancellation(row.operationId,key,2))
            store.acceptCancellationPrepared(store.prepareCancellationAttempted(row.operationId,0))
            val first=store.stored(row.operationId).cancellation!!.request(row.syncEpoch,store.stored(row.operationId).receipt.analysisId)
            assertTrue(File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg").delete())
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
            store=PhotoAnalysisStore(context,db,LocalOwnerStore(db).currentLease())
            val restored=store.stored(row.operationId);val replay=restored.cancellation!!.request(row.syncEpoch,restored.receipt.analysisId)
            assertTrue(restored.cancellation.attempted);assertEquals(first.key,replay.key);assertArrayEquals(first.body(),replay.body())
            assertEquals(meals,db.dao().achievementMeals(lease.storageScope));assertEquals(ops,db.dao().operationCount(lease.storageScope))
        } finally {db.close();context.deleteDatabase(name);scope?.let(::clean)}
    }
    @Test fun cancellationCasRejectsParallelDecisionGetAndBackoffWithoutResettingPause()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"cancel-cas");scope=lease.storageScope;val (store,row)=cancellationQueue(db,lease)
            val key=UUID.randomUUID().toString();val first=store.prepareCancellation(row.operationId,key,2)
            val second=store.prepareCancellation(row.operationId,UUID.randomUUID().toString(),2)
            db.withTransaction {store.acceptCancellationPrepared(first)};rejected {store.acceptCancellationPrepared(second)}
            val attempted=store.prepareCancellationAttempted(row.operationId,0)
            store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().put("revision",3).toString().toByteArray()))
            rejected {store.acceptCancellationPrepared(attempted)}
            assertEquals(key,store.stored(row.operationId).cancellation!!.key)
            val next=store.prepareCancellationAttempted(row.operationId,0)
            db.photoAnalysisDao().defer(lease.storageScope,row.operationId,5_000)
            rejected {store.acceptCancellationPrepared(next)};rejected {store.prepareCancellationAttempted(row.operationId,0)}
            store.acceptCancellationPrepared(store.prepareCancellationAttempted(row.operationId,5_000))
            assertEquals(5_000L,store.pending()!!.retryAtMillis)
            assertEquals(2L,store.stored(row.operationId).cancellation!!.expectedRevision)
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun cancellationReceiptIsBoundToExactRequestAndRejectedAcrossAbaOrContextChange()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();val scopes=mutableListOf<String>()
        try {
            val lease=account(db,"cancel-A");scopes+=lease.storageScope;val (store,row)=cancellationQueue(db,lease)
            store.acceptCancellationPrepared(store.prepareCancellation(row.operationId,UUID.randomUUID().toString(),2))
            store.acceptCancellationPrepared(store.prepareCancellationAttempted(row.operationId,0))
            val saved=store.stored(row.operationId);val request=saved.cancellation!!.request(row.syncEpoch,saved.receipt.analysisId)
            val other=UUID.randomUUID().toString();val body=cancelAck(saved.receipt.analysisId);val key=checkNotNull(request.key)
            for(wrong in listOf(PhotoHttpRequest.Cancel(other,row.syncEpoch,saved.receipt.analysisId,2),
                PhotoHttpRequest.Cancel(key,other,saved.receipt.analysisId,2),
                PhotoHttpRequest.Cancel(key,row.syncEpoch,other,2),PhotoHttpRequest.Cancel(key,row.syncEpoch,saved.receipt.analysisId,3)))
                rejected {store.prepareCancellationReceipt(row.operationId,body,wrong)}
            val prepared=store.prepareCancellationReceipt(row.operationId,body,request);val before=store.pending()
            val original=db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(original.copy(contextRevision=original.contextRevision+1))
            rejected {store.acceptCancellationPrepared(prepared)};db.bootstrapDao().update(original)
            val b=account(db,"cancel-B");scopes+=b.storageScope;rejected {store.acceptCancellationPrepared(prepared)}
            val resumed=LocalOwnerStore(db).select(lease.storageScope);rejected {store.acceptCancellationPrepared(prepared)}
            assertEquals(before,PhotoAnalysisStore(context,db,resumed).pending())
        } finally {db.close();scopes.forEach(::clean)}
    }
    @Test fun onlyVerifiedCancellationReleasesQueueAndDeletesItsInputWithoutTouchingSourcePhoto()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"cancel-release");scope=lease.storageScope;val (store,row)=cancellationQueue(db,lease)
            val meals=db.dao().achievementMeals(lease.storageScope);val ops=db.dao().operationCount(lease.storageScope)
            rejected {store.prepareCancelledRelease(row.operationId)}
            store.acceptCancellationPrepared(store.prepareCancellation(row.operationId,UUID.randomUUID().toString(),2))
            store.acceptCancellationPrepared(store.prepareCancellationAttempted(row.operationId,0))
            val saved=store.stored(row.operationId);val sent=saved.cancellation!!.request(row.syncEpoch,saved.receipt.analysisId)
            val prepared=store.prepareCancellationReceipt(row.operationId,cancelAck(saved.receipt.analysisId),sent)
            assertEquals("PreparedPhotoCancellation(redacted)",prepared.toString())
            db.withTransaction {store.acceptCancellationPrepared(prepared)}
            val input=File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg");assertTrue(input.exists())
            val released=store.prepareCancelledRelease(row.operationId);db.withTransaction {store.releaseCancelledPrepared(released)}
            assertNull(store.pending());assertTrue(input.exists()) // IO is a separate step outside the guard.
            store.cleanupReleasedInput(row.operationId);assertFalse(input.exists())
            MealPhotoStore(context,db,lease).preview(row.sourcePhotoId).let {assertEquals(48,it.width);it.recycle()}
            val next=store.prepare(row.sourcePhotoId,caps,true);rejected {store.releaseCancelledPrepared(released)}
            assertEquals(next.operationId,store.pending()!!.operationId)
            assertEquals(meals,db.dao().achievementMeals(lease.storageScope));assertEquals(ops,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scope?.let(::clean)}
    }

    @Test fun preparedReadCannotCommitAcrossContextChangeOrOwnerAba()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();val scopes=mutableListOf<String>()
        try {
            val a=account(db,"read-A");scopes+=a.storageScope;val store=PhotoAnalysisStore(context,db,a)
            val row=store.prepare(photo(db,a).id,caps,true);store.markAttempted(row.operationId,0);store.accept(row.operationId,ack())
            val prepared=store.prepareRead(row.operationId,workingRead(2));val before=store.pending()
            val original=db.bootstrapDao().binding(a.storageScope)!!
            db.bootstrapDao().update(original.copy(contextRevision=original.contextRevision+1))
            rejected {store.acceptReadPrepared(prepared)};db.bootstrapDao().update(original)
            val b=account(db,"read-B");scopes+=b.storageScope
            rejected {store.acceptReadPrepared(prepared)};assertNull(PhotoAnalysisStore(context,db,b).pending())
            val resumed=LocalOwnerStore(db).select(a.storageScope)
            rejected {store.acceptReadPrepared(prepared)}
            assertEquals(before,PhotoAnalysisStore(context,db,resumed).pending())
        } finally {db.close();scopes.forEach(::clean)}
    }

    private fun correctionInput(name:String="Rosół",amount:String="250")=PhotoDraftInput(name,amount,"ml","40","2","1","")
    @Test fun mealCorrectionsSurviveRoomRestartWithoutEitherImageAndPreservePauseAndDiary()=runBlocking<Unit> {
        val name="meal-draft-${UUID.randomUUID()}";var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build();var scope:String?=null
        try {
            val lease=account(db,"draft-restart");scope=lease.storageScope;var(store,row)=cancellationQueue(db,lease)
            db.photoAnalysisDao().defer(lease.storageScope,row.operationId,900_000)
            val prepared=store.prepareMealDraft(row.operationId,2,java.time.Instant.parse("2026-10-17T12:00:00Z"),java.time.ZoneId.of("Europe/Warsaw"))
            db.withTransaction{store.acceptMealDraftPrepared(prepared)}
            val first=store.stored(row.operationId).mealDraft!!
            store.acceptMealDraftPrepared(store.prepareMealDraftEdit(row.operationId,1){it.replace(first.items.single().id,correctionInput())})
            val before=store.pending()!!;assertEquals(900_000L,before.retryAtMillis)
            MealPhotoStore(context,db,lease).delete(row.sourcePhotoId)
            assertTrue(File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg").delete())
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
            store=PhotoAnalysisStore(context,db,LocalOwnerStore(db).currentLease())
            val restored=store.stored(row.operationId).mealDraft!!
            assertEquals(first.mealId,restored.mealId);assertEquals(first.items.single().id,restored.items.single().id)
            assertEquals("Rosół",restored.items.single().name);assertEquals("100",restored.totals.energy.canonical)
            assertEquals(before,store.pending());assertEquals(0,db.dao().operationCount(lease.storageScope))
            assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty())
        } finally {db.close();context.deleteDatabase(name);scope?.let(::clean)}
    }
    @Test fun correctionCasRejectsCompetingEditsAndStaleDiscardWithoutLosingTheAcceptedChanges()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"draft-cas");scope=lease.storageScope;val(store,row)=cancellationQueue(db,lease)
            store.acceptMealDraftPrepared(store.prepareMealDraft(row.operationId,2,java.time.Instant.now(),java.time.ZoneId.of("UTC")))
            val id=store.stored(row.operationId).mealDraft!!.items.single().id
            val first=store.prepareMealDraftEdit(row.operationId,1){it.replace(id,correctionInput("Pierwszy"))}
            val second=store.prepareMealDraftEdit(row.operationId,1){it.replace(id,correctionInput("Drugi"))}
            val discard=store.prepareMealDraftDiscard(row.operationId,1)
            store.acceptMealDraftPrepared(first);rejected{store.acceptMealDraftPrepared(second)};rejected{store.acceptMealDraftPrepared(discard)}
            assertEquals("Pierwszy",store.stored(row.operationId).mealDraft!!.items.single().name)
            rejected{store.prepareMealDraftEdit(row.operationId,1){it.rename("Stale")}}
            assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun newerGetAndCancelDecisionInvalidatePreparedCorrectionCommits()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"draft-newer");scope=lease.storageScope;val(store,row)=cancellationQueue(db,lease)
            store.acceptMealDraftPrepared(store.prepareMealDraft(row.operationId,2,java.time.Instant.now(),java.time.ZoneId.of("UTC")))
            val edit=store.prepareMealDraftEdit(row.operationId,1){it.rename("Old")}
            store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().put("revision",3).toString().toByteArray()))
            rejected{store.acceptMealDraftPrepared(edit)}
            val next=store.prepareMealDraftEdit(row.operationId,1){it.rename("Not after cancel")}
            store.acceptCancellationPrepared(store.prepareCancellation(row.operationId,UUID.randomUUID().toString(),3))
            rejected{store.acceptMealDraftPrepared(next)};rejected{store.prepareMealDraftEdit(row.operationId,1){it.rename("Frozen")}}
            assertEquals("Posiłek ze zdjęcia",store.stored(row.operationId).mealDraft!!.title)
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun preparedCorrectionsAreFencedByContextAndAbaButTheOriginalAccountRetainsItsDraft()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();val scopes=mutableListOf<String>()
        try {
            val lease=account(db,"draft-A");scopes+=lease.storageScope;val(store,row)=cancellationQueue(db,lease)
            store.acceptMealDraftPrepared(store.prepareMealDraft(row.operationId,2,java.time.Instant.now(),java.time.ZoneId.of("UTC")))
            val prepared=store.prepareMealDraftEdit(row.operationId,1){it.rename("Late")};val before=store.pending()
            val mapping=db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(mapping.copy(contextRevision=mapping.contextRevision+1));rejected{store.acceptMealDraftPrepared(prepared)}
            db.bootstrapDao().update(mapping);scopes+=account(db,"draft-B").storageScope;rejected{store.acceptMealDraftPrepared(prepared)}
            val resumed=LocalOwnerStore(db).select(lease.storageScope);rejected{store.acceptMealDraftPrepared(prepared)}
            assertEquals(before,PhotoAnalysisStore(context,db,resumed).pending())
        } finally {db.close();scopes.forEach(::clean)}
    }

    private suspend fun confirmationDraft(store:PhotoAnalysisStore,id:String) {
        store.acceptMealDraftPrepared(store.prepareMealDraft(id,2,java.time.Instant.parse("2026-10-17T12:00:00Z"),java.time.ZoneId.of("Europe/Warsaw")))
    }
    @Test fun confirmationIntentSurvivesRoomRestartNoImagesAndBackoffWithoutDiaryWrites()=runBlocking<Unit> {
        val name="confirm-${UUID.randomUUID()}";var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build();var scope:String?=null
        try {
            val lease=account(db,"confirm-restart");scope=lease.storageScope;var(store,row)=cancellationQueue(db,lease)
            confirmationDraft(store,row.operationId);store.deferRead(row.operationId,8000)
            val key=UUID.randomUUID().toString();store.acceptConfirmationPrepared(store.prepareConfirmation(row.operationId,key,2,1))
            assertEquals(8000L,store.pending()!!.retryAtMillis);rejected{store.prepareConfirmationAttempted(row.operationId,7999)}
            store.acceptConfirmationPrepared(store.prepareConfirmationAttempted(row.operationId,8000))
            val first=store.stored(row.operationId).confirmation!!.request(row.syncEpoch)
            File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg").delete()
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
            store=PhotoAnalysisStore(context,db,LocalOwnerStore(db).currentLease())
            val restored=store.stored(row.operationId);val retry=restored.confirmation!!.request(row.syncEpoch)
            assertTrue(restored.confirmation.attempted);assertEquals(key,retry.key);assertArrayEquals(first.body(),retry.body())
            assertEquals(8000L,store.pending()!!.retryAtMillis);assertFalse(restored.canEditProposal)
            assertEquals(0,db.dao().operationCount(lease.storageScope));assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty())
        } finally {db.close();context.deleteDatabase(name);scope?.let(::clean)}
    }
    @Test fun confirmationCasFencesCompetingDecisionOldEditNewGetAndLateAttempt()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"confirm-cas");scope=lease.storageScope;val(store,row)=cancellationQueue(db,lease);confirmationDraft(store,row.operationId)
            val edit=store.prepareMealDraftEdit(row.operationId,1){it.rename("Late")}
            val first=store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,1)
            val competing=store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,1)
            store.acceptConfirmationPrepared(first);rejected{store.acceptConfirmationPrepared(competing)};rejected{store.acceptMealDraftPrepared(edit)}
            val attempt=store.prepareConfirmationAttempted(row.operationId,0)
            store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().put("revision",3).toString().toByteArray()))
            rejected{store.acceptConfirmationPrepared(attempt)}
            val saved=store.stored(row.operationId);assertFalse(saved.confirmation!!.attempted);assertEquals(2L,saved.confirmation.expectedRevision)
            assertEquals("Posiłek ze zdjęcia",saved.mealDraft!!.title);assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun confirmationPreparationCannotBypassContextOrAbaOrChangeTheOriginalAccount()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();val scopes=mutableListOf<String>()
        try {
            val lease=account(db,"confirm-A");scopes+=lease.storageScope;val(store,row)=cancellationQueue(db,lease);confirmationDraft(store,row.operationId)
            val prepared=store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,1);val before=store.pending()
            val mapping=db.bootstrapDao().binding(lease.storageScope)!!;db.bootstrapDao().update(mapping.copy(contextRevision=mapping.contextRevision+1))
            rejected{store.acceptConfirmationPrepared(prepared)};db.bootstrapDao().update(mapping)
            scopes+=account(db,"confirm-B").storageScope;rejected{store.acceptConfirmationPrepared(prepared)}
            val resumed=LocalOwnerStore(db).select(lease.storageScope);rejected{store.acceptConfirmationPrepared(prepared)}
            rejected{PhotoAnalysisStore(context,db,resumed).acceptConfirmationPrepared(prepared)};assertEquals(before,PhotoAnalysisStore(context,db,resumed).pending());assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scopes.forEach(::clean)}
    }
    @Test fun confirmationReceiptOnlyPreparesValidatedBytesAndNeverCommitsAnIncompleteDiary()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"confirm-ack");scope=lease.storageScope;val(store,row)=cancellationQueue(db,lease);confirmationDraft(store,row.operationId)
            store.acceptConfirmationPrepared(store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,1))
            store.acceptConfirmationPrepared(store.prepareConfirmationAttempted(row.operationId,0))
            val snapshot=store.stored(row.operationId);val sent=snapshot.confirmation!!.request(row.syncEpoch)
            val body=JSONObject(sent.body().toString(Charsets.UTF_8));val source=readResult()
            val provenance=source.getJSONObject("profile").put("analysis_id",source.getString("analysis_id"))
                .put("model_version",source.getJSONObject("proposal").get("model_version"))
                .put("uncertainty",org.json.JSONArray().put(JSONObject().put("component_id","d7777777-7777-4777-8777-777777777777").put("uncertainty","medium")))
            val ack=JSONObject().put("analysis_id",source.getString("analysis_id")).put("meal",body.getJSONObject("meal"))
                .put("drafts",body.getJSONArray("drafts")).put("provenance",provenance).toString().toByteArray()
            val before=store.pending();val prepared=store.prepareConfirmationReceipt(row.operationId,ack,sent)
            assertTrue(prepared.snapshot.confirmation!!.confirmed);assertEquals(before,store.pending())
            assertNull(store.stored(row.operationId).confirmation!!.receiptJson)
            val wrong=PhotoHttpRequest.Confirm(UUID.randomUUID().toString(),row.syncEpoch,snapshot.receipt.analysisId,2,sent.body())
            rejected{store.prepareConfirmationReceipt(row.operationId,ack,wrong)}
            assertEquals(0,db.dao().operationCount(lease.storageScope));assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty())
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun serverCancellationRetainsPendingConfirmationReadOnlyAndRefusesLateAck()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"confirm-cancelled");scope=lease.storageScope;val(store,row)=cancellationQueue(db,lease);confirmationDraft(store,row.operationId)
            store.acceptConfirmationPrepared(store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,1))
            store.acceptConfirmationPrepared(store.prepareConfirmationAttempted(row.operationId,0))
            val cancelled=readResult().put("revision",3).put("state","failed").put("decision_state","cancelled")
                .put("proposal",JSONObject.NULL).put("error_code","analysis_cancelled")
            store.acceptReadPrepared(store.prepareRead(row.operationId,cancelled.toString().toByteArray()))
            val saved=store.stored(row.operationId);assertTrue(saved.cancelled);assertNotNull(saved.confirmation);assertFalse(saved.canEditProposal)
            rejected{store.prepareConfirmationAttempted(row.operationId,0)};assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scope?.let(::clean)}
    }

    private suspend fun materializationReceipt(db:CalorieDatabase,lease:OwnerLease,unknownMl:Boolean=false):Pair<PhotoAnalysisStore,PreparedPhotoConfirmationReceipt> {
        val (store,row)=cancellationQueue(db,lease);confirmationDraft(store,row.operationId)
        if(unknownMl) {
            val item=store.stored(row.operationId).mealDraft!!.items.single().id
            store.acceptMealDraftPrepared(store.prepareMealDraftEdit(row.operationId,1){it.replace(item,PhotoDraftInput("Napój","150.5","ml","","0","","22.8"))})
        }
        val draft=store.stored(row.operationId).mealDraft!!
        store.acceptConfirmationPrepared(store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,draft.editRevision))
        store.acceptConfirmationPrepared(store.prepareConfirmationAttempted(row.operationId,0))
        val snapshot=store.stored(row.operationId);val sent=snapshot.confirmation!!.request(row.syncEpoch)
        val value=JSONObject(sent.body().toString(Charsets.UTF_8));val source=readResult()
        val provenance=source.getJSONObject("profile").put("analysis_id",source.getString("analysis_id"))
            .put("model_version",source.getJSONObject("proposal").get("model_version"))
            .put("uncertainty",org.json.JSONArray().put(JSONObject().put("component_id","d7777777-7777-4777-8777-777777777777").put("uncertainty","medium")))
        val ack=JSONObject().put("analysis_id",source.getString("analysis_id")).put("meal",value.getJSONObject("meal"))
            .put("drafts",value.getJSONArray("drafts")).put("provenance",provenance).toString().toByteArray()
        return store to store.prepareConfirmationReceipt(row.operationId,ack,sent)
    }
    @Test fun confirmedMealProvenanceAndCanonicalOutboxCommitTogetherWithHonestMissingValues()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"materialize-values");scope=lease.storageScope;val(store,prepared)=materializationReceipt(db,lease,true)
            val record=store.materializeConfirmationPrepared(prepared);val saved=db.dao().meal(record.mealId,lease.storageScope)!!
            assertNull(store.pending());assertNotNull(db.photoDao().get(lease.storageScope,record.sourcePhotoId))
            val item=saved.items.single();assertNull(item.productId);assertNull(item.kcalPer100);assertEquals("ml",item.unit);assertEquals("150.5",item.amountText)
            assertFalse(item.consumed().asExact().energy.complete);assertEquals(0,item.consumed().asExact().protein.knownSum.signum())
            assertEquals("UNSPECIFIED",saved.meal.mealType);assertTrue(db.dao().recent(lease.storageScope).first().isEmpty())
            val outbox=db.dao().operation(record.firstOutboxId)!!;assertEquals("sync-v1",outbox.wireFormat);assertNull(outbox.baseRevision)
            val wire=JSONObject(outbox.wireJson!!);assertEquals("upsert",wire.getString("action"));assertTrue(wire.isNull("base_revision"))
            assertFalse(wire.getJSONObject("payload").has("provenance"));assertEquals(record.mealId,wire.getString("entity_id"))
            assertEquals(record,db.materializationDao().get(lease.storageScope,record.analysisId));assertEquals(1,db.dao().operationCount(lease.storageScope))
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun materializationFailureRollsBackMealItemsOutboxLedgerAndQueueRelease()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"materialize-failure");scope=lease.storageScope;val(store,prepared)=materializationReceipt(db,lease)
            val before=store.pending();db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_materialization BEFORE INSERT ON photo_materializations BEGIN SELECT RAISE(ABORT,'Synthetic commit failure'); END")
            rejected{store.materializeConfirmationPrepared(prepared)}
            assertEquals(before,store.pending());assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty());assertEquals(0,db.dao().operationCount(lease.storageScope))
            assertNull(db.materializationDao().get(lease.storageScope,prepared.snapshot.receipt.analysisId))
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_materialization")
            assertNotNull(store.materializeConfirmationPrepared(prepared));assertEquals(1,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun replayAfterRestartAndLocalEditOrDeleteNeverResurrectsOriginalMealOrAddsAnOperation()=runBlocking<Unit> {
        val name="materialize-replay-${UUID.randomUUID()}";var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build();var scope:String?=null
        try {
            val lease=account(db,"materialize-replay");scope=lease.storageScope;var(store,prepared)=materializationReceipt(db,lease)
            val record=store.materializeConfirmationPrepared(prepared);val repository=DiaryRepository(db,context,lease)
            val item=db.dao().meal(record.mealId,lease.storageScope)!!.items.single().id
            repository.editItem(record.mealId,item,175.5,"175.5");val operations=db.dao().operationCount(lease.storageScope)
            assertEquals(record,store.materializeConfirmationPrepared(prepared));assertEquals("175.5",db.dao().meal(record.mealId,lease.storageScope)!!.items.single().amountText)
            assertEquals(operations,db.dao().operationCount(lease.storageScope))
            repository.delete(record.mealId);val afterDelete=db.dao().operationCount(lease.storageScope)
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build();store=PhotoAnalysisStore(context,db,LocalOwnerStore(db).currentLease())
            assertEquals(record,store.materializeConfirmationPrepared(prepared));assertTrue(db.dao().meal(record.mealId,lease.storageScope)!!.meal.deleted)
            assertEquals(afterDelete,db.dao().operationCount(lease.storageScope));assertTrue(db.dao().canonicalMealOperations(lease.storageScope,record.mealId).isEmpty())
        } finally {db.close();context.deleteDatabase(name);scope?.let(::clean)}
    }
    @Test fun oldReceiptReplayCannotReleaseTheNextPhotoQueue()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"materialize-next");scope=lease.storageScope;val(store,prepared)=materializationReceipt(db,lease)
            val record=store.materializeConfirmationPrepared(prepared);val next=store.prepare(photo(db,lease).id,caps,true)
            assertEquals(record,store.materializeConfirmationPrepared(prepared));assertEquals(next,store.pending());assertEquals(1,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun materializationContextRecoveryAndAbaFencesPreserveAllPendingState()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();val scopes=mutableListOf<String>()
        try {
            val lease=account(db,"materialize-A");scopes+=lease.storageScope;val(store,prepared)=materializationReceipt(db,lease);val before=store.pending()
            val binding=db.bootstrapDao().binding(lease.storageScope)!!;db.bootstrapDao().update(binding.copy(requiresRecovery=true))
            rejected{store.materializeConfirmationPrepared(prepared)};db.bootstrapDao().update(binding.copy(contextRevision=2))
            rejected{store.materializeConfirmationPrepared(prepared)};db.bootstrapDao().update(binding)
            scopes+=account(db,"materialize-B").storageScope;rejected{store.materializeConfirmationPrepared(prepared)}
            val resumed=LocalOwnerStore(db).select(lease.storageScope);rejected{PhotoAnalysisStore(context,db,resumed).materializeConfirmationPrepared(prepared)}
            assertEquals(before,db.photoAnalysisDao().get(lease.storageScope));assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {db.close();scopes.forEach(::clean)}
    }
    @Test fun foreignMealOrItemCollisionCannotOverwriteHistoryOrPartiallyCommit()=runBlocking<Unit> {
        for(itemCollision in listOf(false,true)) {
            val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
            try {
                val lease=account(db,"materialize-collision");scope=lease.storageScope;val(store,prepared)=materializationReceipt(db,lease)
                val target=prepared.plan.meal.id;val other=if(itemCollision)UUID.randomUUID().toString() else target
                db.dao().insertMeal(MealEntity(other,"guest","2026-10-17","2026-10-17T12:00:00Z","Europe/Warsaw","LUNCH"))
                if(itemCollision)db.dao().insertItem(MealItemEntity(prepared.plan.items.single().id,other,"legacy-product","Zachowany",100.0,80.0,null,null,null))
                val before=db.dao().meal(other,"guest");rejected{store.materializeConfirmationPrepared(prepared)}
                assertEquals(before,db.dao().meal(other,"guest"));assertNull(db.dao().meal(target,lease.storageScope))
                assertNotNull(store.pending());assertEquals(0,db.dao().operationCount(lease.storageScope))
            } finally {db.close();scope?.let(::clean)}
        }
    }
    @Test fun unattemptedEditsCoalesceButInFlightPayloadRemainsImmutableAndNewEditsWaitForRevision()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"materialize-chain");scope=lease.storageScope;val(store,prepared)=materializationReceipt(db,lease)
            val record=store.materializeConfirmationPrepared(prepared);val repository=DiaryRepository(db,context,lease);val item=db.dao().meal(record.mealId,lease.storageScope)!!.items.single().id
            repository.editItem(record.mealId,item,150.5,"150.5");assertEquals("superseded",db.dao().operation(record.firstOutboxId)!!.status)
            val first=db.dao().canonicalMealOperations(lease.storageScope,record.mealId).single();assertNotNull(first.wireJson)
            db.dao().updateOperation(first.copy(attempted=true));repository.editItem(record.mealId,item,160.5,"160.5")
            val active=db.dao().canonicalMealOperations(lease.storageScope,record.mealId)
            assertEquals(first.wireJson,db.dao().operation(first.operationId)!!.wireJson)
            assertEquals("waiting_revision",active.last().status);assertNull(active.last().wireJson)
            assertEquals("160.5",db.dao().meal(record.mealId,lease.storageScope)!!.items.single().amountText)
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun recoveryKeepsLocalEditsWithoutExportingOldContextAndKnownServerRevisionPermitsDelete()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"materialize-recovery");scope=lease.storageScope;val(store,prepared)=materializationReceipt(db,lease)
            val record=store.materializeConfirmationPrepared(prepared);val repository=DiaryRepository(db,context,lease)
            val binding=db.bootstrapDao().binding(lease.storageScope)!!;db.bootstrapDao().update(binding.copy(requiresRecovery=true))
            val saved=db.dao().meal(record.mealId,lease.storageScope)!!;repository.editItem(record.mealId,saved.items.single().id,100.5,"100.5")
            val queued=db.dao().canonicalMealOperations(lease.storageScope,record.mealId).single()
            assertEquals("waiting_recovery",queued.status);assertNull(queued.wireJson);assertEquals("100.5",db.dao().meal(record.mealId,lease.storageScope)!!.items.single().amountText)
            db.bootstrapDao().update(binding);db.dao().updateMeal(db.dao().meal(record.mealId,lease.storageScope)!!.meal.copy(serverRevision=3))
            db.dao().updateOperation(queued.copy(status="acked",attempted=true));repository.delete(record.mealId)
            val deletion=db.dao().canonicalMealOperations(lease.storageScope,record.mealId).single();val wire=JSONObject(deletion.wireJson!!)
            assertEquals("delete",wire.getString("action"));assertEquals(3,wire.getInt("base_revision"));assertTrue(wire.isNull("payload"))
        } finally {db.close();scope?.let(::clean)}
    }
    private suspend fun rejectedConfirmation(db:CalorieDatabase,lease:OwnerLease,code:String="photo_catalog_choice_changed"):
        Triple<PhotoAnalysisStore,PhotoAnalysisRequestEntity,PhotoHttpRequest.Confirm> {
        val(store,row)=cancellationQueue(db,lease);confirmationDraft(store,row.operationId)
        store.acceptConfirmationPrepared(store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,1))
        store.acceptConfirmationPrepared(store.prepareConfirmationAttempted(row.operationId,0))
        val request=store.stored(row.operationId).confirmation!!.request(row.syncEpoch)
        store.acceptConfirmationPrepared(store.prepareConfirmationRejection(row.operationId,code,request))
        return Triple(store,row,request)
    }
    @Test fun migration12To13PreservesAll26TablesAndBackfillsHistoryOnlyAfterExplicitGet()=runBlocking<Unit> {migrationOldSchema(12)}

    @Test fun rejectionReadProofAndReopeningSurviveRoomRestartWithoutImageOrDiaryWrites()=runBlocking<Unit> {
        val name="reopen-${UUID.randomUUID()}";var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build();var scope:String?=null
        try {
            val lease=account(db,"reopen-restart");scope=lease.storageScope
            var(store,row,request)=rejectedConfirmation(db,lease)
            val frozen=db.photoConfirmationHistoryDao().get(scope,request.key!!)!!
            assertNull(frozen.lastReadSnapshotHash);rejected {store.prepareConfirmationReopen(row.operationId,2,1)}
            store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().toString().toByteArray()))
            assertTrue(store.canReopenConfirmation(row.operationId,store.stored(row.operationId)))
            assertTrue(File(context.filesDir,"photo-analysis-inputs/$scope/${row.operationId}.jpg").delete())
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
            store=PhotoAnalysisStore(context,db,LocalOwnerStore(db).currentLease())
            assertTrue(store.canReopenConfirmation(row.operationId,store.stored(row.operationId)))
            val prepared=store.prepareConfirmationReopen(row.operationId,2,1)
            val resumed=store.acceptConfirmationReopenPrepared(prepared)
            assertTrue(resumed.canEditProposal);assertEquals(2L,resumed.mealDraft!!.editRevision);assertNull(resumed.confirmation)
            val history=db.photoConfirmationHistoryDao().get(scope,request.key!!)!!
            assertEquals(frozen.decisionJson,history.decisionJson);assertEquals(frozen.archivedAt,history.archivedAt)
            assertEquals(2L,history.reopenedEditRevision);assertNotNull(history.lastReadSnapshotHash)
            rejected {store.acceptConfirmationReopenPrepared(prepared)}
            assertTrue(db.dao().achievementMeals(scope).isEmpty());assertEquals(0,db.dao().operationCount(scope))
            assertTrue(MealPhotoStore(context,db,LocalOwnerStore(db).currentLease()).uploadBytes(row.sourcePhotoId).isNotEmpty())
        } finally {db.close();context.deleteDatabase(name);scope?.let(::clean)}
    }
    @Test fun historyAndQueueRollbackTogetherOnRejectionReadAndReopenFailures()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"reopen-atomic");scope=lease.storageScope;val(store,row)=cancellationQueue(db,lease);confirmationDraft(store,row.operationId)
            store.acceptConfirmationPrepared(store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,1))
            store.acceptConfirmationPrepared(store.prepareConfirmationAttempted(row.operationId,0))
            val sent=store.stored(row.operationId).confirmation!!.request(row.syncEpoch);val pending=store.pending()
            val rejection=store.prepareConfirmationRejection(row.operationId,"proposal_revision_conflict",sent)
            val sql=db.openHelper.writableDatabase
            sql.execSQL("CREATE TRIGGER fail_history_insert BEFORE INSERT ON photo_confirmation_history BEGIN SELECT RAISE(ABORT,'synthetic history insert'); END")
            rejected {store.acceptConfirmationPrepared(rejection)};assertEquals(pending,store.pending())
            assertTrue(db.photoConfirmationHistoryDao().decisions(scope,row.operationId).isEmpty())
            sql.execSQL("DROP TRIGGER fail_history_insert");store.acceptConfirmationPrepared(rejection)
            val denied=store.pending();val history=db.photoConfirmationHistoryDao().get(scope,sent.key!!)!!
            val read=store.prepareRead(row.operationId,readResult().put("revision",3).toString().toByteArray())
            sql.execSQL("CREATE TRIGGER fail_history_read BEFORE UPDATE ON photo_confirmation_history BEGIN SELECT RAISE(ABORT,'synthetic history proof'); END")
            rejected {store.acceptReadPrepared(read)};assertEquals(denied,store.pending());assertEquals(history,db.photoConfirmationHistoryDao().get(scope,sent.key!!))
            sql.execSQL("DROP TRIGGER fail_history_read");store.acceptReadPrepared(read)
            val current=store.pending();val proved=db.photoConfirmationHistoryDao().get(scope,sent.key!!)!!
            val reopen=store.prepareConfirmationReopen(row.operationId,3,1)
            sql.execSQL("CREATE TRIGGER fail_reopen_queue BEFORE UPDATE ON photo_analysis_requests BEGIN SELECT RAISE(ABORT,'synthetic reopen queue'); END")
            rejected {store.acceptConfirmationReopenPrepared(reopen)}
            assertEquals(current,store.pending());assertEquals(proved,db.photoConfirmationHistoryDao().get(scope,sent.key!!))
            sql.execSQL("DROP TRIGGER fail_reopen_queue");store.acceptConfirmationReopenPrepared(reopen)
            assertEquals(0,db.dao().operationCount(scope));assertTrue(db.dao().achievementMeals(scope).isEmpty())
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun reopenedDecisionForbidsArchivedKeyReuseAndLateAckButKeepsStableMealIds()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"reopen-keys");scope=lease.storageScope;val(store,row,sent)=rejectedConfirmation(db,lease)
            val old=store.stored(row.operationId);val history=db.photoConfirmationHistoryDao().get(scope,sent.key!!)!!
            store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().toString().toByteArray()))
            val next=store.acceptConfirmationReopenPrepared(store.prepareConfirmationReopen(row.operationId,2,1))
            assertEquals(old.mealDraft!!.mealId,next.mealDraft!!.mealId);assertEquals(old.mealDraft.items.map {it.id},next.mealDraft.items.map {it.id})
            rejected {store.prepareConfirmation(row.operationId,sent.key!!,2,2)}
            rejected {store.prepareCancellation(row.operationId,sent.key!!,2)}
            store.acceptConfirmationPrepared(store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),2,2))
            store.acceptConfirmationPrepared(store.prepareConfirmationAttempted(row.operationId,0))
            val current=store.stored(row.operationId);val wire=current.confirmation!!.request(row.syncEpoch)
            val payload=JSONObject(String(wire.body()));val provenance=current.confirmation.journal().getJSONObject("expected_provenance")
            val ack=JSONObject().put("analysis_id",current.receipt.analysisId).put("meal",payload.getJSONObject("meal"))
                .put("drafts",payload.getJSONArray("drafts")).put("provenance",provenance).toString().toByteArray()
            rejected {store.prepareConfirmationReceipt(row.operationId,ack,sent)}
            val materialization=store.materializeConfirmationPrepared(store.prepareConfirmationReceipt(row.operationId,ack,wire))
            assertEquals(old.mealDraft.mealId,materialization.mealId);assertNull(store.pending())
            assertEquals(1,db.dao().operationCount(scope));assertEquals(1,db.dao().achievementMeals(scope).size)
            assertEquals(history.decisionJson,db.photoConfirmationHistoryDao().get(scope,sent.key!!)!!.decisionJson)
            assertEquals(1,db.photoConfirmationHistoryDao().decisions(scope,row.operationId).size)
        } finally {db.close();scope?.let(::clean)}
    }
    @Test fun reopenedPlansRejectNewerReadsContextChangesAbaAndStaleReviewRevisions()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();val scopes=mutableListOf<String>()
        try {
            val lease=account(db,"reopen-A");scopes+=lease.storageScope;val(store,row,_)=rejectedConfirmation(db,lease)
            val source=store.pending()!!
            store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().toString().toByteArray()))
            // A GET captured before rejection/proof cannot be relabelled as a fresh current request.
            rejected {store.prepareRead(row.operationId,readResult().toString().toByteArray(),source.copy(receiptJson="stale"))}
            rejected {store.prepareConfirmationReopen(row.operationId,2,2)}
            val prepared=store.prepareConfirmationReopen(row.operationId,2,1)
            store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().put("revision",3).toString().toByteArray()))
            rejected {store.acceptConfirmationReopenPrepared(prepared)}
            val fresh=store.prepareConfirmationReopen(row.operationId,3,1);val before=store.pending()
            val binding=db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(binding.copy(contextRevision=binding.contextRevision+1));rejected {store.acceptConfirmationReopenPrepared(fresh)}
            db.bootstrapDao().update(binding);scopes+=account(db,"reopen-B").storageScope;rejected {store.acceptConfirmationReopenPrepared(fresh)}
            val resumed=LocalOwnerStore(db).select(lease.storageScope);rejected {store.acceptConfirmationReopenPrepared(fresh)}
            assertEquals(before,PhotoAnalysisStore(context,db,resumed).pending())
            assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty())
        } finally {db.close();scopes.forEach(::clean)}
    }


    @Test fun olderValidGetCannotAuthorizeReopeningAgainstANewerStoredProposal()=runBlocking<Unit> {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build();var scope:String?=null
        try {
            val lease=account(db,"reopen-stale-get");scope=lease.storageScope;val(store,row)=cancellationQueue(db,lease)
            confirmationDraft(store,row.operationId)
            store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().put("revision",3).toString().toByteArray()))
            store.acceptConfirmationPrepared(store.prepareConfirmation(row.operationId,UUID.randomUUID().toString(),3,1))
            store.acceptConfirmationPrepared(store.prepareConfirmationAttempted(row.operationId,0))
            val sent=store.stored(row.operationId).confirmation!!.request(row.syncEpoch)
            store.acceptConfirmationPrepared(store.prepareConfirmationRejection(row.operationId,"photo_catalog_choice_changed",sent))
            val stale=store.prepareRead(row.operationId,readResult().toString().toByteArray())
            assertFalse(stale.canReopenConfirmation);store.acceptReadPrepared(stale)
            assertFalse(store.canReopenConfirmation(row.operationId,store.stored(row.operationId)))
            assertNull(db.photoConfirmationHistoryDao().get(scope,sent.key!!)!!.lastReadSnapshotHash)
            store.acceptReadPrepared(store.prepareRead(row.operationId,readResult().put("revision",3).toString().toByteArray()))
            assertTrue(store.canReopenConfirmation(row.operationId,store.stored(row.operationId)))
        } finally {db.close();scope?.let(::clean)}
    }
}
