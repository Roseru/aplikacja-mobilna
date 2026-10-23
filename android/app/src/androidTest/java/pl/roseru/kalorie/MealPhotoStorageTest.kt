package pl.roseru.kalorie

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import androidx.core.content.FileProvider
import androidx.exifinterface.media.ExifInterface
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.photo.*
import pl.roseru.kalorie.core.MealType
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.time.LocalDate
import java.util.UUID

class MealPhotoStorageTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private fun image(width:Int=32,height:Int=64,alpha:Boolean=false):ByteArray {
        val bitmap=Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(if(alpha) Color.TRANSPARENT else Color.BLUE)
        if(!alpha) for(y in 0 until height/2) for(x in 0 until width) bitmap.setPixel(x,y,Color.RED)
        return ByteArrayOutputStream().also { bitmap.compress(if(alpha) Bitmap.CompressFormat.PNG else Bitmap.CompressFormat.JPEG,100,it);bitmap.recycle() }.toByteArray()
    }
    private fun reject(action:()->Unit) { try { action();fail("Invalid input accepted") } catch(_:IllegalArgumentException) { } }

    @Test fun preparationAppliesExifRotationRemovesGpsFlattensAlphaAndBoundsInput() {
        val source=File(context.cacheDir,"orientation-${UUID.randomUUID()}.jpg")
        try {
            source.writeBytes(image())
            ExifInterface(source).apply { setAttribute(ExifInterface.TAG_ORIENTATION,"6");setGpsInfo(android.location.Location("synthetic").apply { latitude=52.22;longitude=21.01 });saveAttributes() }
            val prepared=source.inputStream().use(MealPhotoPreparation::prepare)
            assertEquals(64,prepared.width);assertEquals(32,prepared.height)
            val output=prepared.bytes()
            val exif=ExifInterface(ByteArrayInputStream(output))
            assertNull(exif.getAttribute(ExifInterface.TAG_GPS_LATITUDE))
            assertEquals(ExifInterface.ORIENTATION_UNDEFINED,exif.getAttributeInt(ExifInterface.TAG_ORIENTATION,ExifInterface.ORIENTATION_UNDEFINED))
            assertFalse(output.toString(Charsets.ISO_8859_1).contains("Exif\u0000\u0000"))
            val pixels=BitmapFactory.decodeByteArray(output,0,output.size)
            try {
                val right=pixels.getPixel(48,16);val left=pixels.getPixel(16,16)
                assertTrue(Color.red(right)>200 && Color.blue(right)<60)
                assertTrue(Color.blue(left)>200 && Color.red(left)<60)
            } finally { pixels.recycle() }
            output[0]=0;assertEquals(255,prepared.bytes()[0].toInt() and 255)
            val transparent=MealPhotoPreparation.prepare(ByteArrayInputStream(image(alpha=true))).bytes()
            val white=BitmapFactory.decodeByteArray(transparent,0,transparent.size)
            try { assertTrue(Color.red(white.getPixel(10,10))>240 && Color.green(white.getPixel(10,10))>240) } finally { white.recycle() }
            val resized=MealPhotoPreparation.prepare(ByteArrayInputStream(image(4000,1000)))
            assertEquals(1600,resized.width);assertEquals(400,resized.height)
            assertArrayEquals(ByteArray(4096),MealPhotoPreparation.bounded(ByteArrayInputStream(ByteArray(4096)),4096))
            reject { MealPhotoPreparation.bounded(ByteArrayInputStream(ByteArray(4097)),4096) }
            reject { MealPhotoPreparation.prepare(ByteArrayInputStream("not an image".toByteArray())) }
            val animated="RIFF".toByteArray()+ByteArray(4)+"WEBPANIM".toByteArray()+ByteArray(4)
            reject { MealPhotoPreparation.prepare(ByteArrayInputStream(animated)) }
        } finally { source.delete() }
    }

    @Test fun persistedCopySurvivesOriginalDeletionAndReopenWithoutMealOrOutboxAndDeletesOnlyItself() = runBlocking {
        val name="photo-${UUID.randomUUID()}.db"
        var db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
        var draft:MealPhotoDraft?=null
        try {
            val owners=LocalOwnerStore(db);owners.ensureGuest();val lease=owners.currentLease()
            val store=MealPhotoStore(context,db,lease)
            val id=UUID.randomUUID().toString()
            draft=store.import(ByteArrayInputStream(image()),LocalDate.of(2026,10,13),"gallery",id)
            assertEquals(0,db.dao().operationCount(lease.storageScope))
            assertEquals(0,db.openHelper.readableDatabase.query("SELECT COUNT(*) FROM meals").use { it.moveToFirst();it.getInt(0) })
            val saved=draft
            db.close();db=Room.databaseBuilder(context,CalorieDatabase::class.java,name).build()
            val reopened=MealPhotoStore(context,db,LocalOwnerStore(db).currentLease())
            assertEquals(saved,db.photoDao().get(lease.storageScope,id))
            reopened.preview(id).let { assertEquals(32,it.width);it.recycle() }
            try { reopened.import(ByteArrayInputStream("broken".toByteArray()),LocalDate.now(),"gallery");fail() } catch(_:IllegalArgumentException) { }
            assertEquals(saved,db.photoDao().get(lease.storageScope,id))
            val file=File(context.filesDir,"meal-photo-drafts/${lease.storageScope}/$id.jpg")
            try { FileProvider.getUriForFile(context,"${context.packageName}.photo-capture",file);fail("Stored photo exposed by camera provider") } catch(_:IllegalArgumentException) { }
            reopened.delete(id);assertFalse(file.exists());assertNull(db.photoDao().get(lease.storageScope,id))
        } finally {
            draft?.let { File(context.filesDir,"meal-photo-drafts/${it.ownerScope}/${it.id}.jpg").delete() }
            db.close();context.deleteDatabase(name)
        }
    }

    @Test fun oldLeaseCannotImportReadOrDeleteOtherScopesIncludingAba() = runBlocking {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build()
        val rows=mutableListOf<MealPhotoDraft>()
        try {
            val owners=LocalOwnerStore(db);owners.ensureGuest()
            val a=owners.registerIdentity("https://example.test/realms/photo","a")
            val b=owners.registerIdentity("https://example.test/realms/photo","b")
            val first=owners.select(a.id);val old=MealPhotoStore(context,db,first)
            val row=old.import(ByteArrayInputStream(image()),LocalDate.now(),"gallery");rows+=row
            val second=owners.select(b.id);val other=MealPhotoStore(context,db,second)
            assertTrue(other.drafts.first().isEmpty())
            try { old.preview(row.id);fail() } catch(_:StaleOwnerException) { }
            try { other.delete(row.id);fail() } catch(_:IllegalArgumentException) { }
            val third=owners.select(a.id)
            try { old.import(ByteArrayInputStream(image()),LocalDate.now(),"gallery");fail() } catch(_:StaleOwnerException) { }
            try { old.delete(row.id);fail() } catch(_:StaleOwnerException) { }
            val current=MealPhotoStore(context,db,third);assertEquals(listOf(row),current.drafts.first())
            current.preview(row.id).recycle();current.delete(row.id)
        } finally { rows.forEach { File(context.filesDir,"meal-photo-drafts/${it.ownerScope}/${it.id}.jpg").delete() };db.close() }
    }

    @Test fun cameraAndGalleryCancellationOrLateCallbackNeverCreatePhotoOrNetworkConsent() = runBlocking {
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build()
        try {
            val owners=LocalOwnerStore(db);owners.ensureGuest();val lease=owners.currentLease()
            val handle=androidx.lifecycle.SavedStateHandle()
            val app=context.applicationContext as android.app.Application
            val model=MealPhotoViewModel(app,MealPhotoStore(context,db,lease),handle)
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                model.beginGallery(LocalDate.now()) { }
                assertTrue(model.selectionPending.value)
                model.cancelSelection();model.galleryResult(android.net.Uri.parse("content://example.test/late"))
                model.beginGallery(LocalDate.now()) { };model.galleryResult(null)
                assertFalse(model.busy.value)
            }
            val latch=java.util.concurrent.CountDownLatch(1)
            var uri:android.net.Uri?=null
            InstrumentationRegistry.getInstrumentation().runOnMainSync { model.beginCamera(LocalDate.now()) { uri=it;latch.countDown() } }
            assertTrue(latch.await(10,java.util.concurrent.TimeUnit.SECONDS))
            val cameraId=checkNotNull(handle.get<String>("photo-id"))
            context.contentResolver.openOutputStream(checkNotNull(uri))!!.use { it.write(image()) }
            InstrumentationRegistry.getInstrumentation().runOnMainSync { model.cameraResult(false) }
            val deadline=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(5)
            while(File(context.cacheDir,"photo-captures/$cameraId.jpg").exists() && System.nanoTime()<deadline) Thread.sleep(20)
            assertFalse(File(context.cacheDir,"photo-captures/$cameraId.jpg").exists())
            assertTrue(db.photoDao().observe(lease.storageScope).first().isEmpty())
            assertEquals(0,db.dao().operationCount(lease.storageScope))
            val newer=owners.select(checkNotNull(db.ownerDao().byScope(lease.storageScope)).id)
            val saved=androidx.lifecycle.SavedStateHandle(mapOf("photo-source" to "gallery","photo-owner" to lease.storageScope,"photo-generation" to lease.generation))
            val restored=MealPhotoViewModel(app,MealPhotoStore(context,db,newer),saved)
            assertFalse(restored.selectionPending.value);assertFalse(restored.busy.value)
        } finally { db.close() }
    }

    @Test fun migrationFromImmutableSchema8PreservesEveryOldColumnAndAddsOnlyPhotoTable() = runBlocking {
        val name="photo-migration-${UUID.randomUUID()}.db"
        val sourceName="photo-source-${UUID.randomUUID()}.db"
        val schema=JSONObject(InstrumentationRegistry.getInstrumentation().context.assets.open("pl.roseru.kalorie.data.CalorieDatabase/8.json").bufferedReader().use { it.readText() }).getJSONObject("database")
        val entities=schema.getJSONArray("entities")
        val source=Room.databaseBuilder(context,CalorieDatabase::class.java,sourceName).addCallback(DATABASE_GUARDS).build()
        fun snapshot(db:androidx.sqlite.db.SupportSQLiteDatabase):Map<String,List<List<String?>>> = (0 until entities.length()).associate { index ->
            val entity=entities.getJSONObject(index);val fields=entity.getJSONArray("fields")
            val names=(0 until fields.length()).map { fields.getJSONObject(it).getString("columnName") }
            val rows=db.query("SELECT ${names.joinToString(",") { "\"$it\"" }} FROM \"${entity.getString("tableName")}\"").use { cursor ->
                buildList { while(cursor.moveToNext()) add(names.indices.map { if(cursor.isNull(it)) null else cursor.getString(it) }) }
            }.sortedBy { it.toString() }
            entity.getString("tableName") to rows
        }
        try {
            val owners=LocalOwnerStore(source);owners.ensureGuest();val lease=owners.currentLease()
            val repository=DiaryRepository(source,context,lease);repository.initialize()
            repository.add(source.dao().products(lease.storageScope).first().first().id,100.0,MealType.LUNCH,LocalDate.now())
            repository.addWeight(82.0,LocalDate.now());repository.setGoal(3100.0,160.0,90.0,330.0)
            val before=snapshot(source.openHelper.readableDatabase);assertEquals(22,before.size)
            source.close()
            SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use { old ->
                old.execSQL("PRAGMA foreign_keys=OFF")
                for(index in 0 until entities.length()) {
                    val entity=entities.getJSONObject(index);val table=entity.getString("tableName")
                    old.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}",table))
                    val indices=entity.optJSONArray("indices") ?: org.json.JSONArray()
                    for(i in 0 until indices.length()) old.execSQL(indices.getJSONObject(i).getString("createSql").replace("\${TABLE_NAME}",table))
                    val fields=entity.getJSONArray("fields")
                    before.getValue(table).forEach { row ->
                        val values=ContentValues()
                        row.forEachIndexed { i,value -> val column=fields.getJSONObject(i).getString("columnName");if(value==null) values.putNull(column) else values.put(column,value) }
                        old.insertOrThrow(table,null,values)
                    }
                }
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(schema.getString("identityHash")))
                old.version=8
            }
            val migrated=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_8_9,MIGRATION_9_10, pl.roseru.kalorie.data.MIGRATION_10_11, pl.roseru.kalorie.data.MIGRATION_11_12, pl.roseru.kalorie.photo.MIGRATION_12_13, pl.roseru.kalorie.data.MIGRATION_13_14, pl.roseru.kalorie.data.MIGRATION_14_15, pl.roseru.kalorie.data.MIGRATION_15_16, pl.roseru.kalorie.data.MIGRATION_16_17, pl.roseru.kalorie.data.MIGRATION_17_18, pl.roseru.kalorie.data.MIGRATION_18_19, pl.roseru.kalorie.data.MIGRATION_19_20, pl.roseru.kalorie.data.MIGRATION_20_21).addCallback(DATABASE_GUARDS).build()
            try {
                assertEquals(21, migrated.openHelper.readableDatabase.version)
                assertEquals(before,snapshot(migrated.openHelper.readableDatabase))
                assertTrue(migrated.photoDao().observe(lease.storageScope).first().isEmpty())
                assertFalse(migrated.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
            } finally { migrated.close() }
        } finally { source.close();context.deleteDatabase(sourceName);context.deleteDatabase(name) }
    }

    @Test fun cameraSuccessRestoresPendingDecisionKeepsOriginalDateAndIgnoresDuplicateCallback() = runBlocking {
        val app=context.applicationContext as android.app.Application
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).build()
        var row:MealPhotoDraft?=null
        try {
            val owners=LocalOwnerStore(db);owners.ensureGuest();val lease=owners.currentLease()
            val store=MealPhotoStore(app,db,lease)
            val handle=androidx.lifecycle.SavedStateHandle()
            val model=MealPhotoViewModel(app,store,handle)
            val latch=java.util.concurrent.CountDownLatch(1)
            var uri:android.net.Uri?=null
            val date=LocalDate.of(2026,10,12)
            InstrumentationRegistry.getInstrumentation().runOnMainSync { model.beginCamera(date) { uri=it;latch.countDown() } }
            assertTrue(latch.await(10,java.util.concurrent.TimeUnit.SECONDS))
            val id=checkNotNull(handle.get<String>("photo-id"))
            context.contentResolver.openOutputStream(checkNotNull(uri))!!.use { it.write(image()) }
            val restored=MealPhotoViewModel(app,store,androidx.lifecycle.SavedStateHandle(handle.keys().associateWith { handle.get<Any>(it) }))
            assertTrue(restored.selectionPending.value)
            InstrumentationRegistry.getInstrumentation().runOnMainSync { restored.cameraResult(true) }
            row=kotlinx.coroutines.withTimeout(15_000) { store.drafts.first { it.size==1 }.single() }
            assertEquals(id,row.id);assertEquals(date.toString(),row.localDate);assertEquals("camera",row.source)
            val deadline=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(5)
            while((File(context.cacheDir,"photo-captures/$id.jpg").exists() || restored.busy.value) && System.nanoTime()<deadline) Thread.sleep(20)
            assertFalse(File(context.cacheDir,"photo-captures/$id.jpg").exists());assertFalse(restored.busy.value)
            InstrumentationRegistry.getInstrumentation().runOnMainSync { restored.cameraResult(true) }
            assertEquals(1,store.drafts.first().size);assertEquals(0,db.dao().operationCount(lease.storageScope))
            store.preview(id).recycle();store.delete(id)
        } finally { row?.let { File(context.filesDir,"meal-photo-drafts/${it.ownerScope}/${it.id}.jpg").delete() };db.close() }
    }
}
