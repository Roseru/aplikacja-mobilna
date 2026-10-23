package pl.roseru.kalorie.data

import android.content.Context
import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.time.Instant
import java.util.UUID

/** Sidecar preserves every legacy weight row and its original precision during migration. */
@Entity(tableName = "canonical_weights", foreignKeys = [ForeignKey(entity = WeightEntity::class,
    parentColumns = ["id"], childColumns = ["id"], onDelete = ForeignKey.RESTRICT)], indices = [Index("ownerScope")])
data class CanonicalWeightState(@PrimaryKey val id: String, val ownerScope: String,
    val wirePayload: String, val wireContext: String, val serverRevision: Int = 0) {
    override fun toString() = "CanonicalWeightState(redacted)"
}

@Dao interface CanonicalWeightDao {
    @Query("SELECT * FROM canonical_weights WHERE ownerScope=:owner AND id=:id")
    suspend fun state(owner: String, id: String): CanonicalWeightState?
    @Insert suspend fun insert(state: CanonicalWeightState)
    @Update suspend fun update(state: CanonicalWeightState)
    @Query("SELECT * FROM outbox WHERE ownerScope=:owner AND entityType='weight' AND entityId=:id AND wireFormat='sync-v1' AND status NOT IN ('acked','superseded','local_only') ORDER BY rowid")
    suspend fun operations(owner: String, id: String): List<OutboxEntity>
}

internal class CanonicalWeightEditor(private val db: CalorieDatabase, private val context: Context, private val lease: OwnerLease) {
    /** Caller owns the local write transaction: projection, exact state and outbox commit together. */
    suspend fun create(point: WeightEntity): Boolean {
        LocalOwnerStore(db).requireCurrent(lease)
        check(point.ownerScope == lease.storageScope)
        if (db.ownerDao().byScope(lease.storageScope)?.kind != "account") return false
        val binding = db.bootstrapDao().binding(lease.storageScope) ?: return false
        if (binding.requiresRecovery) return false
        val schema = CanonicalMealRows.schema(context)
        val wire = try { WeightWire.create(point.kg, point.occurredAt, point.zoneId, point.localDate, schema) }
            catch (_: SyncWireException) { return false } // Preserve the old local precision, never round it.
        val operationId = UUID.randomUUID().toString()
        val operation = WeightWire.operation(operationId, point.id, binding.syncEpoch, null, wire.canonical, schema)
        val wireContext = CanonicalMealRows.context(binding)
        db.dao().saveWeight(point.copy(occurredAt = wire.json().getString("occurred_at")))
        db.weightSyncDao().insert(CanonicalWeightState(point.id, lease.storageScope, wire.canonical, wireContext))
        db.dao().enqueue(OutboxEntity(operationId, lease.storageScope, "weight", point.id, "upsert", null,
            wire.canonical, Instant.now().toString(), "pending", "sync-v1", operation, wireContext))
        return true
    }

    /** Edits during a frozen request wait for its original ACK; the request is never rewritten. */
    suspend fun change(id: String, kg: Double? = null): Boolean = withContext(Dispatchers.IO) {
        val owners = LocalOwnerStore(db)
        val source = db.withTransaction {
            owners.requireCurrent(lease)
            val state = db.weightSyncDao().state(lease.storageScope, id) ?: return@withTransaction null
            val point = checkNotNull(db.dao().weight(id, lease.storageScope))
            Source(point, state, db.weightSyncDao().operations(lease.storageScope, db.wireSyncId(lease.storageScope,"weight",id)), db.bootstrapDao().binding(lease.storageScope))
        } ?: return@withContext false
        if (source.point.deleted) { require(kg == null); return@withContext true }
        val schema = CanonicalMealRows.schema(context)
        val original = WeightWire.read(source.state.wirePayload, schema)
        val wire = kg?.let { original.withWeight(it, schema) } ?: original
        val deleted = kg == null
        val base = source.state.serverRevision.takeIf { it > 0 }
        val binding = source.binding
        val current = binding != null && !binding.requiresRecovery && source.state.wireContext == CanonicalMealRows.context(binding)
        val status = when {
            !current -> "waiting_recovery"
            source.queue.any { it.attempted } -> "waiting_revision"
            deleted && base == null -> "local_only"
            else -> "pending"
        }
        val epoch = StrictJson.read(source.state.wireContext.toByteArray(Charsets.UTF_8)).getString("sync_epoch")
        val operationId = UUID.randomUUID().toString()
        val payload = if (deleted) null else wire.canonical
        val wireId=db.wireSyncId(lease.storageScope,"weight",id)
        val operation = if (status == "pending") WeightWire.operation(operationId, wireId, epoch, base, payload, schema) else null
        val point = source.point.copy(kg = kg ?: source.point.kg, deleted = deleted,
            localRevision = Math.addExact(source.point.localRevision, 1))
        val outbox = OutboxEntity(operationId, lease.storageScope, "weight", wireId, if (deleted) "delete" else "upsert",
            base, payload ?: "null", Instant.now().toString(), status, "sync-v1", operation, source.state.wireContext)
        db.withTransaction {
            owners.requireCurrent(lease)
            check(db.dao().weight(id, lease.storageScope) == source.point && db.weightSyncDao().state(lease.storageScope, id) == source.state &&
                db.weightSyncDao().operations(lease.storageScope, wireId) == source.queue && db.bootstrapDao().binding(lease.storageScope) == binding)
            db.dao().saveWeight(point)
            db.weightSyncDao().update(source.state.copy(wirePayload = wire.canonical))
            source.queue.filter { !it.attempted }.forEach { db.dao().updateOperation(it.copy(status = "superseded")) }
            db.dao().enqueue(outbox)
        }
        true
    }
    private data class Source(val point: WeightEntity, val state: CanonicalWeightState,
        val queue: List<OutboxEntity>, val binding: AccountBindingEntity?)
}

val MIGRATION_14_15 = object : Migration(14, 15) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS canonical_weights (id TEXT NOT NULL, ownerScope TEXT NOT NULL, wirePayload TEXT NOT NULL, wireContext TEXT NOT NULL, serverRevision INTEGER NOT NULL, PRIMARY KEY(id), FOREIGN KEY(id) REFERENCES weights(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_canonical_weights_ownerScope ON canonical_weights(ownerScope)")
    }
}
