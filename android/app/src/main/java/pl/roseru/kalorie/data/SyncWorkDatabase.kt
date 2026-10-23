package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.flow.Flow

/** Immutable receipt replaces raw storage, never the run identity, checkpoint or frozen request. */
@Entity(tableName="snapshot_archive_receipts",foreignKeys=[ForeignKey(entity=ServerSnapshotRun::class,
    parentColumns=["id"],childColumns=["runId"],onDelete=ForeignKey.RESTRICT)])
data class SnapshotArchiveReceipt(@PrimaryKey val runId:String,val originalPages:Int,val originalItems:Int,
    val originalByteCount:Long,val releasedRawBytes:Long,val manifestJson:String,val manifestHash:String,val compactedAt:String) {
    override fun toString()="SnapshotArchiveReceipt(redacted)"
}

/** Durable state is account-specific; it contains no authentication material. */
@Entity(tableName="sync_work_state",foreignKeys=[ForeignKey(entity=LocalOwnerEntity::class,
    parentColumns=["storageScope"],childColumns=["ownerScope"],onDelete=ForeignKey.RESTRICT)])
data class SyncWorkState(@PrimaryKey val ownerScope:String,val leaseGeneration:Long,val wireContext:String,
    val cycleId:String,val phase:String,val status:String,val retryAtMillis:Long,val consecutiveFailures:Int,
    val requestedVersion:Long,val activeVersion:Long,val handledVersion:Long,val acknowledged:Int,val refused:Int,val updatedAtMillis:Long) {
    override fun toString()="SyncWorkState(phase=$phase,status=$status)"
}

data class SyncQueueSignal(val ownerScope:String,val leaseGeneration:Long,val operationId:String,val action:String,
    val payload:String,val wireContext:String?) {override fun toString()="SyncQueueSignal(redacted)"}

data class SyncContextSignal(val leaseGeneration:Long,@Embedded val binding:AccountBindingEntity) {
    fun lease()=OwnerLease(binding.ownerScope,leaseGeneration)
    override fun toString()="SyncContextSignal(redacted)"
}
@Dao interface SyncWorkDao {
    @Query("SELECT a.generation AS leaseGeneration,b.* FROM local_active_owner a JOIN local_owners o ON o.storageScope=a.storageScope JOIN account_bindings b ON b.ownerScope=o.storageScope WHERE a.id=1 AND o.kind='account'")
    fun contexts():Flow<SyncContextSignal?>
    @Query("SELECT COUNT(*) FROM outbox WHERE ownerScope=:owner AND wireFormat='sync-v1' AND status IN ('pending','waiting_revision','waiting_timeline','waiting_profile')")
    suspend fun remaining(owner:String):Int
    @Query("SELECT * FROM sync_work_state WHERE ownerScope=:owner") suspend fun state(owner:String):SyncWorkState?
    @Query("SELECT * FROM sync_work_state WHERE ownerScope=:owner") fun observe(owner:String):Flow<SyncWorkState?>
    @Upsert suspend fun save(state:SyncWorkState)
    @Query("SELECT q.ownerScope,a.generation AS leaseGeneration,q.operationId,q.action,q.payload,q.wireContext FROM local_active_owner a JOIN local_owners o ON o.storageScope=a.storageScope JOIN account_bindings b ON b.ownerScope=o.storageScope JOIN outbox q ON q.ownerScope=o.storageScope WHERE a.id=1 AND o.kind='account' AND b.requiresRecovery=0 AND q.wireFormat='sync-v1' AND q.status IN ('pending','waiting_revision','waiting_timeline','waiting_profile') ORDER BY q.rowid LIMIT 100")
    fun wakeups():Flow<List<SyncQueueSignal>>
}

@Dao interface SnapshotArchiveDao {
    @Query("SELECT * FROM snapshot_archive_receipts WHERE runId=:id") suspend fun receipt(id:String):SnapshotArchiveReceipt?
    @Insert suspend fun insert(receipt:SnapshotArchiveReceipt)
    @Query("SELECT r.* FROM server_snapshot_runs r LEFT JOIN snapshot_archive_receipts c ON c.runId=r.id WHERE r.ownerScope=:owner AND c.runId IS NULL ORDER BY r.rowid")
    suspend fun rawRuns(owner:String):List<ServerSnapshotRun>
    @Query("SELECT COALESCE(SUM(LENGTH(CAST(p.queryJson AS BLOB))+LENGTH(CAST(p.responseJson AS BLOB))),0) FROM server_snapshot_pages p JOIN server_snapshot_runs r ON r.id=p.runId WHERE r.ownerScope=:owner")
    suspend fun ownerRawBytes(owner:String):Long
    @Query("SELECT COALESCE(SUM(LENGTH(CAST(queryJson AS BLOB))+LENGTH(CAST(responseJson AS BLOB))),0) FROM server_snapshot_pages WHERE runId=:id")
    suspend fun rawBytes(id:String):Long
    @Query("DELETE FROM server_snapshot_pages WHERE runId=:id") suspend fun releasePages(id:String)
    @Query("DELETE FROM server_snapshot_identities WHERE runId=:id") suspend fun releaseIdentities(id:String)
    @Query("SELECT COUNT(*) FROM server_snapshot_pages WHERE runId=:id") suspend fun pageCount(id:String):Int
    @Query("SELECT DISTINCT snapshotRunId FROM sync_push_batches WHERE ownerScope=:owner AND state='pending'")
    suspend fun frozenOrigins(owner:String):List<String>
    @Query("SELECT DISTINCT b.snapshotRunId FROM sync_push_batches b JOIN outbox q ON q.ownerScope=b.ownerScope LEFT JOIN sync_conflict_decisions d ON d.operationId=q.operationId WHERE b.ownerScope=:owner AND q.status NOT IN ('acked','superseded','local_only') AND d.operationId IS NULL AND instr(b.requestJson,q.operationId)>0")
    suspend fun unresolvedOrigins(owner:String):List<String>
    @Query("SELECT DISTINCT d.snapshotRunId FROM sync_conflict_decisions d JOIN outbox q ON q.operationId=d.newOperationId WHERE d.ownerScope=:owner AND d.snapshotRunId IS NOT NULL AND q.status NOT IN ('acked','superseded','local_only') UNION SELECT DISTINCT b.snapshotRunId FROM sync_conflict_decisions d JOIN outbox q ON q.operationId=d.newOperationId JOIN sync_push_batches b ON b.id=d.batchId WHERE d.ownerScope=:owner AND q.status NOT IN ('acked','superseded','local_only')")
    suspend fun conflictOrigins(owner:String):List<String>
    @Query("SELECT DISTINCT runId FROM server_diary_records WHERE ownerScope=:owner AND disposition!='applied'")
    suspend fun pendingRecordOrigins(owner:String):List<String>
    @Query("SELECT DISTINCT runId FROM reconciliation_evidence WHERE planId=:plan") suspend fun evidenceOrigins(plan:String):List<String>
}

internal fun snapshotArchiveGuards(db:SupportSQLiteDatabase) {
    db.execSQL("CREATE TRIGGER IF NOT EXISTS snapshot_receipts_no_update BEFORE UPDATE ON snapshot_archive_receipts BEGIN SELECT RAISE(ABORT,'immutable snapshot receipt'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS snapshot_receipts_no_delete BEFORE DELETE ON snapshot_archive_receipts BEGIN SELECT RAISE(ABORT,'immutable snapshot receipt'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS snapshot_receipts_no_replace BEFORE INSERT ON snapshot_archive_receipts WHEN EXISTS (SELECT 1 FROM snapshot_archive_receipts WHERE runId=NEW.runId) BEGIN SELECT RAISE(ABORT,'immutable snapshot receipt'); END")
    db.execSQL("CREATE TRIGGER IF NOT EXISTS snapshot_receipts_protected BEFORE INSERT ON snapshot_archive_receipts WHEN EXISTS (SELECT 1 FROM server_snapshot_access WHERE activeRunId=NEW.runId) OR EXISTS (SELECT 1 FROM server_snapshot_runs WHERE id=NEW.runId AND state='pending') BEGIN SELECT RAISE(ABORT,'protected snapshot'); END")
    for(table in listOf("server_snapshot_pages","server_snapshot_identities"))
        db.execSQL("CREATE TRIGGER IF NOT EXISTS ${table}_release_receipt BEFORE DELETE ON $table WHEN NOT EXISTS (SELECT 1 FROM snapshot_archive_receipts WHERE runId=OLD.runId) BEGIN SELECT RAISE(ABORT,'snapshot receipt required'); END")
}

val MIGRATION_20_21=object:Migration(20,21) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE snapshot_archive_receipts (runId TEXT NOT NULL PRIMARY KEY, originalPages INTEGER NOT NULL, originalItems INTEGER NOT NULL, originalByteCount INTEGER NOT NULL, releasedRawBytes INTEGER NOT NULL, manifestJson TEXT NOT NULL, manifestHash TEXT NOT NULL, compactedAt TEXT NOT NULL, FOREIGN KEY(runId) REFERENCES server_snapshot_runs(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE TABLE sync_work_state (ownerScope TEXT NOT NULL PRIMARY KEY, leaseGeneration INTEGER NOT NULL, wireContext TEXT NOT NULL, cycleId TEXT NOT NULL, phase TEXT NOT NULL, status TEXT NOT NULL, retryAtMillis INTEGER NOT NULL, consecutiveFailures INTEGER NOT NULL, requestedVersion INTEGER NOT NULL, activeVersion INTEGER NOT NULL, handledVersion INTEGER NOT NULL, acknowledged INTEGER NOT NULL, refused INTEGER NOT NULL, updatedAtMillis INTEGER NOT NULL, FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        snapshotArchiveGuards(db)
    }
}