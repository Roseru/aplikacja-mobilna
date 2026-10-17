package pl.roseru.kalorie.photo

import android.content.Context
import android.util.AtomicFile
import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.data.*
import java.io.File
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID

/** One unresolved operation per local account. No image/token is stored in Room. */
@Entity(tableName="photo_analysis_requests", foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,
    parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)],
    indices=[Index(value=["operationId"],unique=true)])
data class PhotoAnalysisRequestEntity(@PrimaryKey val ownerScope:String,val operationId:String,
    val accountId:String,val accountGeneration:Int,val syncEpoch:String,val contextRevision:Long,
    val sourcePhotoId:String,val provider:String,val model:String,val noticeVersion:String,
    val imageLimit:Int,val imageSha256:String,val imageBytes:Int,val acceptedAt:String,
    val attempted:Boolean,val receiptJson:String?,val retryAtMillis:Long,val blockedCode:String?) {
    override fun toString()="PhotoAnalysisRequestEntity(redacted)"
}

@Dao interface PhotoAnalysisDao {
    @Query("SELECT * FROM photo_analysis_requests WHERE ownerScope=:scope") suspend fun get(scope:String):PhotoAnalysisRequestEntity?
    @Insert suspend fun insert(row:PhotoAnalysisRequestEntity)
    @Query("UPDATE photo_analysis_requests SET attempted=1 WHERE ownerScope=:scope AND operationId=:id")
    suspend fun markAttempted(scope:String,id:String):Int
    @Query("UPDATE photo_analysis_requests SET receiptJson=:receipt, retryAtMillis=0, blockedCode=NULL WHERE ownerScope=:scope AND operationId=:id")
    suspend fun accept(scope:String,id:String,receipt:String):Int
    @Query("UPDATE photo_analysis_requests SET retryAtMillis=:until WHERE ownerScope=:scope AND operationId=:id")
    suspend fun defer(scope:String,id:String,until:Long):Int
    @Query("UPDATE photo_analysis_requests SET blockedCode=:code WHERE ownerScope=:scope AND operationId=:id")
    suspend fun block(scope:String,id:String,code:String):Int
    @Query("UPDATE photo_analysis_requests SET receiptJson=:receipt WHERE ownerScope=:scope AND operationId=:id")
    suspend fun replaceSnapshot(scope:String,id:String,receipt:String):Int
    @Query("DELETE FROM photo_analysis_requests WHERE ownerScope=:scope AND operationId=:id")
    suspend fun dropCancelled(scope:String,id:String):Int
    @Query("DELETE FROM photo_analysis_requests WHERE ownerScope=:scope AND operationId=:id AND attempted=0")
    suspend fun dropUnsent(scope:String,id:String):Int
}

val MIGRATION_9_10=object:Migration(9,10) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS photo_analysis_requests (ownerScope TEXT NOT NULL, operationId TEXT NOT NULL, accountId TEXT NOT NULL, accountGeneration INTEGER NOT NULL, syncEpoch TEXT NOT NULL, contextRevision INTEGER NOT NULL, sourcePhotoId TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, noticeVersion TEXT NOT NULL, imageLimit INTEGER NOT NULL, imageSha256 TEXT NOT NULL, imageBytes INTEGER NOT NULL, acceptedAt TEXT NOT NULL, attempted INTEGER NOT NULL, receiptJson TEXT, retryAtMillis INTEGER NOT NULL, blockedCode TEXT, PRIMARY KEY(ownerScope), FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS index_photo_analysis_requests_operationId ON photo_analysis_requests(operationId)")
    }
}

/** Network-free durable preparation. The session controller must guard token use separately. */
internal class PhotoAnalysisStore(private val context:Context,private val db:CalorieDatabase,val lease:OwnerLease) {
    private val owners=LocalOwnerStore(db)
    private val dao=db.photoAnalysisDao()
    private fun file(id:String):File {
        PhotoHttpRequest.uuid(lease.storageScope);PhotoHttpRequest.uuid(id)
        return File(File(File(context.filesDir,"photo-analysis-inputs"),lease.storageScope),"$id.jpg")
    }
    private fun sha(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)}
    private suspend fun account():AccountBindingEntity {
        owners.requireCurrent(lease)
        require(db.ownerDao().byScope(lease.storageScope)?.kind=="account")
        return checkNotNull(db.bootstrapDao().binding(lease.storageScope)).also { require(!it.requiresRecovery) }
    }
    private fun sameContext(row:PhotoAnalysisRequestEntity,current:AccountBindingEntity) {
        check(row.ownerScope==current.ownerScope && row.accountId==current.accountId &&
            row.accountGeneration==current.accountGeneration && row.syncEpoch==current.syncEpoch && row.contextRevision==current.contextRevision)
    }
    private suspend fun checked(id:String):PhotoAnalysisRequestEntity {
        PhotoHttpRequest.uuid(id)
        val current=account()
        return checkNotNull(dao.get(lease.storageScope)).also { check(it.operationId==id);sameContext(it,current) }
    }
    suspend fun pending():PhotoAnalysisRequestEntity?=db.withTransaction {
        owners.requireCurrent(lease);dao.get(lease.storageScope)
    }

    /** Consent is explicit; file IO finishes before Room commit, with orphan-only cleanup on failure. */
    suspend fun prepare(sourcePhotoId:String,capabilities:PhotoCapabilitiesRead,accepted:Boolean):PhotoAnalysisRequestEntity=withContext(Dispatchers.IO) {
        require(accepted && capabilities.available)
        val binding=db.withTransaction { account().also { check(dao.get(lease.storageScope)==null) } }
        val image=MealPhotoStore(context,db,lease).uploadBytes(sourcePhotoId)
        val id=UUID.randomUUID().toString()
        PhotoHttpRequest.Create.prepare(id,binding.syncEpoch,capabilities,accepted,image,"image/jpeg")
        val row=PhotoAnalysisRequestEntity(lease.storageScope,id,binding.accountId,binding.accountGeneration,
            binding.syncEpoch,binding.contextRevision,sourcePhotoId,capabilities.provider,capabilities.model,
            capabilities.noticeVersion,capabilities.imageBytes,sha(image),image.size,Instant.now().toString(),false,null,0,null)
        val target=file(id)
        try {
            check(target.parentFile!!.isDirectory || target.parentFile!!.mkdirs())
            val atomic=AtomicFile(target);val output=atomic.startWrite()
            try { output.write(image);atomic.finishWrite(output) }
            catch(error:Exception){atomic.failWrite(output);throw error}
            db.withTransaction {
                sameContext(row,account());check(dao.get(lease.storageScope)==null);dao.insert(row)
            }
            row
        } catch(error:Exception) {
            withContext(NonCancellable) {
                // A late cancellation after commit must never remove the referenced input.
                if(dao.get(lease.storageScope)?.operationId!=id) AtomicFile(target).delete()
            }
            throw error
        }
    }
    /** Reads the preserved input, never a mutable gallery URI or a newly encoded preview. */
    suspend fun request(id:String):PhotoHttpRequest.Create=withContext(Dispatchers.IO) {
        val row=db.withTransaction { checked(id).also { check(it.blockedCode==null) } }
        val bytes=AtomicFile(file(id)).openRead().use { MealPhotoPreparation.bounded(it,PhotoHttpRequest.IMAGE_BYTES) }
        require(bytes.size==row.imageBytes && sha(bytes)==row.imageSha256)
        db.withTransaction { sameContext(row,account());check(checked(id)==row) }
        PhotoHttpRequest.Create.prepare(row.operationId,row.syncEpoch,
            PhotoCapabilitiesRead(row.provider,row.model,row.noticeVersion,true,null,row.imageLimit,10),true,bytes,"image/jpeg")
    }
    suspend fun markAttempted(id:String,nowMillis:Long):PhotoAnalysisRequestEntity=db.withTransaction {
        val row=checked(id)
        check(row.receiptJson==null && row.blockedCode==null && row.retryAtMillis<=nowMillis)
        check(dao.markAttempted(lease.storageScope,id)==1)
        row.copy(attempted=true)
    }
    /** Validate outside the session/Room guard, using the exact request that was sent. */
    suspend fun prepareReceipt(id:String,body:ByteArray,sent:PhotoHttpRequest.Create):PreparedPhotoReceipt {
        require(body.size in 1..65_536)
        val row=db.withTransaction { checked(id).also { check(it.attempted && it.blockedCode==null) } }
        require(sent.key==row.operationId && sent.epoch==row.syncEpoch && sent.provider==row.provider &&
            sent.noticeVersion==row.noticeVersion && sent.imageSha256==row.imageSha256)
        val exact=body.copyOf()
        row.receiptJson?.let { PhotoAnalysisSnapshot.read(it,row.provider).requireSameReceipt(exact) }
        return PreparedPhotoReceipt(row,StrictJson.canonical(StrictJson.read(exact)),PhotoAnalysisProtocol.create(exact,sent))
    }
    /** DB-only commit: safe inside SessionController.withApiSession, no image read/hash/codec. */
    suspend fun acceptPrepared(prepared:PreparedPhotoReceipt):PhotoCreateReceipt=db.withTransaction {
        val row=checked(prepared.source.operationId)
        val original=prepared.source
        check(row.copy(attempted=original.attempted,receiptJson=original.receiptJson,
            retryAtMillis=original.retryAtMillis,blockedCode=original.blockedCode)==original)
        check(row.attempted && row.blockedCode==null)
        if(row.receiptJson==null) {
            check(original.receiptJson==null)
            check(dao.accept(lease.storageScope,row.operationId,prepared.canonical)==1)
        } else {
            // An identical ACK is a no-op. A wrapper was validated before entering this guard;
            // if it changed since preparation, reject rather than erasing a newer GET.
            check(row.receiptJson==prepared.canonical ||
                (original.receiptJson!=null && row.receiptJson==original.receiptJson))
        }
        prepared.receipt
    }
    suspend fun accept(id:String,body:ByteArray):PhotoCreateReceipt =
        acceptPrepared(prepareReceipt(id,body,request(id)))

    /** Decode outside the session guard. No input image is required after an accepted POST. */
    suspend fun stored(id:String):PhotoAnalysisSnapshot {
        val source=db.withTransaction { checked(id).also { check(it.attempted && it.blockedCode==null) } }
        val snapshot=PhotoAnalysisSnapshot.read(checkNotNull(source.receiptJson),source.provider)
        db.withTransaction { check(checked(id)==source) }
        return snapshot
    }

    /** Parse and reconcile a GET outside the Room/session guard, against its captured source row. */
    suspend fun prepareRead(id:String,body:ByteArray):PreparedPhotoRead {
        val source=db.withTransaction { checked(id).also { check(it.attempted && it.blockedCode==null) } }
        val snapshot=PhotoAnalysisSnapshot.read(checkNotNull(source.receiptJson),source.provider).withRead(body)
        return PreparedPhotoRead(source,snapshot)
    }

    /** DB-only CAS. A concurrent read, retry state or owner/context change must be prepared anew. */
    suspend fun acceptReadPrepared(prepared:PreparedPhotoRead):PhotoAnalysisSnapshot=db.withTransaction {
        val row=checked(prepared.source.operationId)
        check(row==prepared.source && row.attempted && row.blockedCode==null && row.receiptJson!=null)
        if(row.receiptJson!=prepared.snapshot.serialized) {
            check(dao.accept(lease.storageScope,row.operationId,prepared.snapshot.serialized)==1)
        }
        prepared.snapshot
    }
    suspend fun defer(id:String,retryAtMillis:Long)=db.withTransaction {
        require(retryAtMillis>=0);check(checked(id).receiptJson==null);check(dao.defer(lease.storageScope,id,retryAtMillis)==1)
    }

    /** Snapshot preparation stays outside the session/Room guard, also for tiny cancel receipts. */
    private suspend fun cancellationSource(id:String):Pair<PhotoAnalysisRequestEntity,PhotoAnalysisSnapshot> {
        val source=db.withTransaction {checked(id).also {check(it.attempted && it.blockedCode==null && it.receiptJson!=null)}}
        return source to PhotoAnalysisSnapshot.read(checkNotNull(source.receiptJson),source.provider)
    }
    suspend fun prepareCancellation(id:String,key:String,revision:Long):PreparedPhotoCancellation {
        val (source,snapshot)=cancellationSource(id)
        require(key!=source.operationId)
        return PreparedPhotoCancellation(source,snapshot.prepareCancellation(key,revision))
    }
    suspend fun prepareCancellationAttempted(id:String,nowMillis:Long):PreparedPhotoCancellation {
        val (source,snapshot)=cancellationSource(id)
        check(source.retryAtMillis<=nowMillis)
        return PreparedPhotoCancellation(source,snapshot.markCancellationAttempted())
    }
    private fun cancellationRequestMatches(source:PhotoAnalysisRequestEntity,snapshot:PhotoAnalysisSnapshot,sent:PhotoHttpRequest.Cancel) {
        val intent=checkNotNull(snapshot.cancellation)
        require(sent.key==intent.key && sent.epoch==source.syncEpoch && sent.expectedRevision==intent.expectedRevision &&
            sent.path=="/ai/food-analyses/${snapshot.receipt.analysisId}/cancel")
    }
    suspend fun prepareCancellationReceipt(id:String,body:ByteArray,sent:PhotoHttpRequest.Cancel):PreparedPhotoCancellation {
        val (source,snapshot)=cancellationSource(id)
        cancellationRequestMatches(source,snapshot,sent)
        return PreparedPhotoCancellation(source,snapshot.withCancellationReceipt(body))
    }
    suspend fun prepareCancellationRejection(id:String,code:String,sent:PhotoHttpRequest.Cancel):PreparedPhotoCancellation {
        val (source,snapshot)=cancellationSource(id)
        cancellationRequestMatches(source,snapshot,sent)
        return PreparedPhotoCancellation(source,snapshot.rejectCancellation(code))
    }
    /** DB-only whole-row CAS; unlike a successful GET, preparation never resets shared backoff. */
    suspend fun acceptCancellationPrepared(prepared:PreparedPhotoCancellation):PhotoAnalysisSnapshot=db.withTransaction {
        val row=checked(prepared.source.operationId)
        check(row==prepared.source && row.attempted && row.receiptJson!=null && row.blockedCode==null)
        if(row.receiptJson!=prepared.snapshot.serialized)
            check(dao.replaceSnapshot(lease.storageScope,row.operationId,prepared.snapshot.serialized)==1)
        prepared.snapshot
    }
    suspend fun prepareCancelledRelease(id:String):PreparedPhotoCancellation {
        val (source,snapshot)=cancellationSource(id)
        check(snapshot.cancelled)
        return PreparedPhotoCancellation(source,snapshot)
    }
    /** Only a verified cancel ACK/GET permits an explicit local release. Source photo stays. */
    suspend fun releaseCancelledPrepared(prepared:PreparedPhotoCancellation)=db.withTransaction {
        check(prepared.snapshot.cancelled)
        check(checked(prepared.source.operationId)==prepared.source)
        check(dao.dropCancelled(lease.storageScope,prepared.source.operationId)==1)
    }
    /** Call after release commit and outside the session guard; an orphan is safe if interrupted. */
    suspend fun cleanupReleasedInput(id:String)=withContext(Dispatchers.IO+NonCancellable) {
        db.withTransaction {owners.requireCurrent(lease);check(dao.get(lease.storageScope)?.operationId!=id)}
        AtomicFile(file(id)).delete()
    }
    suspend fun deferRead(id:String,retryAtMillis:Long)=db.withTransaction {
        require(retryAtMillis>=0)
        val row=checked(id);check(row.receiptJson!=null && row.attempted && row.blockedCode==null)
        check(dao.defer(lease.storageScope,id,maxOf(row.retryAtMillis,retryAtMillis))==1)
    }
    suspend fun blockRead(id:String)=db.withTransaction {
        val row=checked(id);check(row.receiptJson!=null && row.attempted)
        check(dao.block(lease.storageScope,id,"photo_read_rejected")==1)
    }
    suspend fun block(id:String,code:String)=db.withTransaction {
        require(Regex("[a-z][a-z0-9_]{0,99}").matches(code));check(checked(id).receiptJson==null);check(dao.block(lease.storageScope,id,code)==1)
    }
    suspend fun dropNeverAttempted(id:String)=withContext(Dispatchers.IO+NonCancellable) {
        db.withTransaction {
            owners.requireCurrent(lease)
            check(dao.get(lease.storageScope)?.operationId==id)
            check(dao.dropUnsent(lease.storageScope,id)==1)
        }
        AtomicFile(file(id)).delete()
    }
}

/** Internal validated receipt, never an alternative parser or a permission to bypass the session guard. */
internal class PreparedPhotoReceipt internal constructor(internal val source:PhotoAnalysisRequestEntity,
    internal val canonical:String,internal val receipt:PhotoCreateReceipt) {
    override fun toString()="PreparedPhotoReceipt(redacted)"
}

/** Captured state plus a fully validated replacement; never a permission to bypass withApiSession. */
internal class PreparedPhotoRead internal constructor(internal val source:PhotoAnalysisRequestEntity,
    internal val snapshot:PhotoAnalysisSnapshot) {
    override fun toString()="PreparedPhotoRead(redacted)"
}

internal class PreparedPhotoCancellation internal constructor(internal val source:PhotoAnalysisRequestEntity,
    internal val snapshot:PhotoAnalysisSnapshot) {
    override fun toString()="PreparedPhotoCancellation(redacted)"
}
