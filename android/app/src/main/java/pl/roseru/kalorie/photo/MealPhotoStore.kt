package pl.roseru.kalorie.photo

import android.content.Context
import android.graphics.BitmapFactory
import android.util.AtomicFile
import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import pl.roseru.kalorie.data.*
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import java.security.MessageDigest

@Entity(tableName = "meal_photo_drafts", primaryKeys = ["ownerScope", "id"], foreignKeys = [ForeignKey(
    entity = LocalOwnerEntity::class, parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT)])
data class MealPhotoDraft(val ownerScope: String, val id: String, val localDate: String, val createdAt: String,
    val source: String, val sha256: String, val byteCount: Int, val width: Int, val height: Int)

@Dao interface MealPhotoDao {
    @Query("SELECT * FROM meal_photo_drafts WHERE ownerScope = :scope ORDER BY createdAt DESC, id")
    fun observe(scope: String): kotlinx.coroutines.flow.Flow<List<MealPhotoDraft>>
    @Query("SELECT * FROM meal_photo_drafts WHERE ownerScope = :scope AND id = :id") suspend fun get(scope: String, id: String): MealPhotoDraft?
    @Insert suspend fun insert(value: MealPhotoDraft)
    @Query("DELETE FROM meal_photo_drafts WHERE ownerScope = :scope AND id = :id") suspend fun delete(scope: String, id: String)
}

val MIGRATION_8_9 = object : Migration(8,9) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS meal_photo_drafts (ownerScope TEXT NOT NULL, id TEXT NOT NULL, localDate TEXT NOT NULL, createdAt TEXT NOT NULL, source TEXT NOT NULL, sha256 TEXT NOT NULL, byteCount INTEGER NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, PRIMARY KEY(ownerScope,id), FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
    }
}

/** Files and metadata are private and scoped. Saving a photo never adds a meal or sync operation. */
class MealPhotoStore(private val context: Context, private val db: CalorieDatabase, val lease: OwnerLease) {
    private val owners = LocalOwnerStore(db)
    val drafts = db.photoDao().observe(lease.storageScope)
    private fun imageFile(id: String): File {
        require(UUID.fromString(id).toString() == id)
        require(lease.storageScope == DiaryRepository.GUEST || UUID.fromString(lease.storageScope).toString() == lease.storageScope)
        return File(File(File(context.filesDir, "meal-photo-drafts"), lease.storageScope), "$id.jpg")
    }
    suspend fun import(input: java.io.InputStream, date: LocalDate, source: String, id: String = UUID.randomUUID().toString()): MealPhotoDraft = withContext(Dispatchers.IO) {
        require(source in setOf("camera", "gallery"))
        val prepared = input.use { owners.requireCurrent(lease); MealPhotoPreparation.prepare(it) }
        val entity = MealPhotoDraft(lease.storageScope, id, date.toString(), Instant.now().toString(), source,
            prepared.sha256, prepared.size, prepared.width, prepared.height)
        val file = imageFile(id)
        withContext(NonCancellable) {
            try {
                db.withTransaction {
                    owners.requireCurrent(lease)
                    require(db.photoDao().get(lease.storageScope, id) == null)
                    check(file.parentFile!!.isDirectory || file.parentFile!!.mkdirs())
                    val atomic = AtomicFile(file)
                    val output = atomic.startWrite()
                    try { output.write(prepared.bytes()); atomic.finishWrite(output) }
                    catch (error: Exception) { atomic.failWrite(output); throw error }
                    db.photoDao().insert(entity)
                }
                entity
            } catch (error: Exception) {
                // Never remove a committed image on a late cancellation or failed result delivery.
                if (db.photoDao().get(lease.storageScope, id) == null) AtomicFile(file).delete()
                throw error
            }
        }
    }
    suspend fun preview(id: String) = withContext(Dispatchers.IO) {
        db.withTransaction {
            owners.requireCurrent(lease)
            val row = requireNotNull(db.photoDao().get(lease.storageScope,id))
            val bytes = AtomicFile(imageFile(id)).openRead().use { MealPhotoPreparation.bounded(it, MealPhotoPreparation.OUTPUT_BYTES) }
            require(bytes.size == row.byteCount && sha(bytes) == row.sha256)
            requireNotNull(BitmapFactory.decodeByteArray(bytes,0,bytes.size)).also {
                require(it.width == row.width && it.height == row.height)
            }
        }
    }
    suspend fun delete(id: String) = withContext(Dispatchers.IO + NonCancellable) {
        db.withTransaction {
            owners.requireCurrent(lease)
            requireNotNull(db.photoDao().get(lease.storageScope,id))
            val file = imageFile(id)
            check(!file.exists() || file.delete())
            AtomicFile(file).delete()
            db.photoDao().delete(lease.storageScope,id)
        }
    }
    private fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}
