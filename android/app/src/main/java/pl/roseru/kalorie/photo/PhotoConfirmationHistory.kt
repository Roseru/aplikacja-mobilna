package pl.roseru.kalorie.photo

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import pl.roseru.kalorie.core.PhotoAnalysisSnapshot
import pl.roseru.kalorie.data.LocalOwnerEntity
import pl.roseru.kalorie.data.OwnerLease

/** Original decision/context never change. Read proof and explicit reopening are separate metadata. */
@Entity(tableName="photo_confirmation_history",primaryKeys=["ownerScope","confirmationKey"],
    foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,parentColumns=["storageScope"],
        childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)],
    indices=[Index(value=["ownerScope","sourceOperationId"])])
data class PhotoConfirmationHistory(val ownerScope:String,val confirmationKey:String,
    val sourceOperationId:String,val analysisId:String,val wireContext:String,val decisionJson:String,
    val archivedAt:String,val lastReadSnapshotHash:String?=null,val reopenedEditRevision:Long?=null) {
    override fun toString()="PhotoConfirmationHistory(redacted)"
}

@Dao interface PhotoConfirmationHistoryDao {
    @Query("SELECT * FROM photo_confirmation_history WHERE ownerScope=:scope AND confirmationKey=:key")
    suspend fun get(scope:String,key:String):PhotoConfirmationHistory?
    @Query("SELECT * FROM photo_confirmation_history WHERE ownerScope=:scope AND sourceOperationId=:operationId ORDER BY archivedAt, confirmationKey")
    suspend fun decisions(scope:String,operationId:String):List<PhotoConfirmationHistory>
    @Insert suspend fun insert(record:PhotoConfirmationHistory)
    @Query("UPDATE photo_confirmation_history SET lastReadSnapshotHash=:hash WHERE ownerScope=:scope AND confirmationKey=:key AND reopenedEditRevision IS NULL")
    suspend fun recordRead(scope:String,key:String,hash:String):Int
    @Query("UPDATE photo_confirmation_history SET reopenedEditRevision=:revision WHERE ownerScope=:scope AND confirmationKey=:key AND reopenedEditRevision IS NULL AND lastReadSnapshotHash=:hash")
    suspend fun markReopened(scope:String,key:String,hash:String,revision:Long):Int
}

val MIGRATION_12_13=object:Migration(12,13) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS photo_confirmation_history (ownerScope TEXT NOT NULL, confirmationKey TEXT NOT NULL, sourceOperationId TEXT NOT NULL, analysisId TEXT NOT NULL, wireContext TEXT NOT NULL, decisionJson TEXT NOT NULL, archivedAt TEXT NOT NULL, lastReadSnapshotHash TEXT, reopenedEditRevision INTEGER, PRIMARY KEY(ownerScope, confirmationKey), FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_photo_confirmation_history_ownerScope_sourceOperationId ON photo_confirmation_history(ownerScope, sourceOperationId)")
    }
}

internal class PreparedPhotoHistory(val before:PhotoConfirmationHistory?,val decision:PhotoConfirmationHistory,val readHash:String?) {
    override fun toString()="PreparedPhotoHistory(redacted)"
}
internal class PreparedPhotoConfirmationReopen(val source:PhotoAnalysisRequestEntity,val previous:PhotoAnalysisSnapshot,
    val snapshot:PhotoAnalysisSnapshot,val history:PhotoConfirmationHistory,val sourceHash:String,val lease:OwnerLease) {
    override fun toString()="PreparedPhotoConfirmationReopen(redacted)"
}
