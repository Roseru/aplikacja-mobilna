package pl.roseru.kalorie.data

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

/** A decision retains both versions; it never rewrites a frozen request or its receipt. */
@Entity(tableName = "sync_conflict_decisions", foreignKeys = [
    ForeignKey(entity = LocalOwnerEntity::class, parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT),
    ForeignKey(entity = OutboxEntity::class, parentColumns = ["operationId"], childColumns = ["operationId"], onDelete = ForeignKey.RESTRICT),
    ForeignKey(entity = SyncPushBatch::class, parentColumns = ["id"], childColumns = ["batchId"], onDelete = ForeignKey.RESTRICT)
], indices = [Index("ownerScope"), Index("batchId")])
data class SyncConflictDecision(@PrimaryKey val operationId: String, val ownerScope: String,
    val batchId: String, val entityType: String, val entityId: String, val wireContext: String,
    val choice: String, val localPayload: String, val localDeleted: Boolean, val serverPayload: String?,
    val serverState: String, val serverRevision: Int?, val resultJson: String, val snapshotRunId: String?,
    val replacementId: String?, val newOperationId: String?, val decidedAt: String) {
    override fun toString() = "SyncConflictDecision(redacted)"
}

@Dao interface SyncConflictDao {
    @Query("SELECT * FROM outbox WHERE ownerScope=:owner AND entityType IN ('meal','weight') AND wireFormat='sync-v1' AND status IN ('conflict','rejected') ORDER BY rowid LIMIT 21 OFFSET :offset")
    suspend fun refused(owner: String, offset: Int): List<OutboxEntity>
    @Query("SELECT * FROM sync_push_batches WHERE ownerScope=:owner AND state='complete' AND responseJson IS NOT NULL AND instr(requestJson,:needle)>0 LIMIT 2")
    suspend fun batches(owner: String, needle: String): List<SyncPushBatch>
    @Query("SELECT * FROM sync_conflict_decisions WHERE operationId=:id") suspend fun decision(id: String): SyncConflictDecision?
    @Insert suspend fun insert(decision: SyncConflictDecision)
}

enum class ConflictChoice { LOCAL, SERVER }
class ConflictChangedException : IllegalStateException("Wpis zmienił się od otwarcia porównania")

internal data class ConflictSource(val gate: MealPushGate, val batch: SyncPushBatch,
    val operation: OutboxEntity, val entity: PushEntitySource, val pages: List<ServerSnapshotPage>) {
    override fun toString() = "ConflictSource(redacted)"
}
class ConflictTicket internal constructor(internal val lease: OwnerLease, internal val source: ConflictSource,
    val evidence: SyncConflictEvidence, val localPayload: String, val localDeleted: Boolean,
    val serverState: ConflictServerState, val serverPayload: String?, val serverRevision: Int?,
    internal val snapshotRunId: String?) {
    val restoresAsCopy get() = serverState == ConflictServerState.DELETED && !localDeleted
    val canChoose get() = serverState != ConflictServerState.UNAVAILABLE &&
        evidence.code in setOf("revision_conflict", "entity_deleted", "entity_id_reserved")
    /** An explicit new intent after a final rejection, never a retry of the rejected UUID/body. */
    val canRetryCorrected get() = evidence.entityType == "meal" && evidence.status == "rejected" &&
        evidence.code !in setOf("revision_conflict", "entity_deleted", "entity_id_reserved") &&
        evidence.originalAction == "upsert" && !localDeleted && serverState != ConflictServerState.DELETED &&
        localPayload != evidence.originalPayload
    override fun toString() = "ConflictTicket(redacted)"
}

/** Works from durable account data offline. Network access and authentication are separate. */
class SyncConflictStore(private val db: CalorieDatabase, private val schema: SyncWireSchema) {
    private val owners = LocalOwnerStore(db)
    private val push = MealPushStore(db, schema)
    private val protocol = PushProtocol(schema)
    private val conflicts = ConflictProtocol(schema)

    suspend fun candidates(lease: OwnerLease, offset: Int = 0): List<OutboxEntity> = db.withTransaction {
        require(offset >= 0 && offset <= Int.MAX_VALUE - 21 && offset % 20 == 0)
        owners.requireCurrent(lease)
        check(db.ownerDao().byScope(lease.storageScope)?.kind == "account")
        db.conflictDao().refused(lease.storageScope, offset)
    }

    private suspend fun entity(lease: OwnerLease, operation: OutboxEntity): PushEntitySource = when (operation.entityType) {
        "meal" -> MealPushEntitySource(checkNotNull(db.dao().meal(db.localSyncId(lease.storageScope,"meal",operation.entityId), lease.storageScope)),
            db.dao().canonicalMealOperations(lease.storageScope, operation.entityId),operation.entityId)
        "weight" -> WeightPushEntitySource(checkNotNull(db.dao().weight(db.localSyncId(lease.storageScope,"weight",operation.entityId), lease.storageScope)),
            checkNotNull(db.weightSyncDao().state(lease.storageScope, db.localSyncId(lease.storageScope,"weight",operation.entityId))),
            db.weightSyncDao().operations(lease.storageScope, operation.entityId),operation.entityId)
        else -> error("Unsupported conflict")
    }

    suspend fun open(lease: OwnerLease, operationId: String): ConflictTicket = withContext(Dispatchers.IO) {
        // IDs are generated UUIDs, never arbitrary JSON/SQL fragments supplied by the view.
        require(UUID.fromString(operationId).toString() == operationId)
        val source = db.withTransaction {
            val gate = push.gate(lease)
            val operation = checkNotNull(db.dao().operation(operationId))
            check(operation.ownerScope == lease.storageScope && operation.status in setOf("conflict", "rejected") &&
                operation.wireFormat == "sync-v1" && operation.attempted && db.conflictDao().decision(operationId) == null)
            val batch = db.conflictDao().batches(lease.storageScope, "\"operation_id\":\"$operationId\"").single()
            check(batch.wireContext == operation.wireContext && operation.wireContext == CanonicalMealRows.context(gate.binding))
            ConflictSource(gate, batch, operation, entity(lease, operation), db.snapshotDao().pages(gate.run.id))
        }
        val batch = protocol.restore(source.batch.requestJson.toByteArray(Charsets.UTF_8))
        check(batch.sha256 == source.batch.requestHash)
        val origin = checkNotNull(db.snapshotDao().run(source.batch.snapshotRunId))
        check(origin.ownerScope == lease.storageScope && origin.state == "complete" &&
            origin.accountId == source.gate.binding.accountId && origin.accountGeneration == source.gate.binding.accountGeneration &&
            origin.syncEpoch == source.gate.binding.syncEpoch && origin.contextRevision == source.gate.binding.contextRevision &&
            origin.checkpoint == batch.json().getString("checkpoint"))
        val evidence = conflicts.read(batch, checkNotNull(source.batch.responseJson).toByteArray(Charsets.UTF_8), operationId)
        check(evidence.operationJson == source.operation.wireJson && evidence.epoch == source.gate.binding.syncEpoch &&
            evidence.entityId == source.entity.id && evidence.entityType == source.operation.entityType &&
            evidence.status == source.operation.status && evidence.originalAction == source.operation.action &&
            (evidence.originalPayload ?: "null") == source.operation.payload && source.entity.context == source.batch.wireContext)
        check(source.entity.queue.filter { it.attempted } == listOf(source.operation))
        val local = checkNotNull(source.entity.payload)
        validate(evidence.entityType, local)
        var state = evidence.serverState; var payload = evidence.serverPayload; var revision = evidence.serverRevision
        var snapshotRun: String? = null
        // Only a complete same-epoch snapshot begun after this receipt may replace its current version.
        // Absence in an older copy says nothing about a later conflict.
        val first = source.pages.firstOrNull()?.let { StrictJson.read(it.responseJson.toByteArray(Charsets.UTF_8)) }
        if (source.gate.run.id != source.batch.snapshotRunId && first != null &&
            !Instant.parse(first.getString("server_time")).isBefore(Instant.parse(evidence.serverTime))) {
            val records = source.pages.flatMap { page ->
                val rows = StrictJson.read(page.responseJson.toByteArray(Charsets.UTF_8)).getJSONArray("entities")
                (0 until rows.length()).map { rows.getJSONObject(it) }.filter { it.getString("entity_id") == evidence.entityId }
            }
            check(records.size <= 1)
            records.singleOrNull()?.let { current ->
                check(current.getString("entity_type") == evidence.entityType)
                val rev = current.getLong("revision"); check(rev in 1..Int.MAX_VALUE.toLong())
                revision = rev.toInt()
                state = if (current.getBoolean("deleted")) ConflictServerState.DELETED else ConflictServerState.PRESENT
                payload = if (state == ConflictServerState.PRESENT) StrictJson.canonical(current.getJSONObject("payload")) else null
                payload?.let { validate(evidence.entityType, it) }
                snapshotRun = source.gate.run.id
            } ?: run {
                if (source.operation.baseRevision != null || evidence.code in setOf("revision_conflict", "entity_deleted", "entity_id_reserved")) {
                    state = ConflictServerState.DELETED; payload = null; revision = null; snapshotRun = source.gate.run.id
                }
            }
        }
        revision?.let { check(it >= source.entity.revision) }
        ConflictTicket(lease, source, evidence, local, source.entity.deleted, state, payload, revision, snapshotRun)
    }

    private fun validate(type: String, payload: String) {
        when (type) { "meal" -> MealWire.read(payload, schema); "weight" -> WeightWire.read(payload, schema)
            else -> error("Unsupported conflict") }
    }

    /** The entire decision is one transaction, including replacement identity and queue changes. */
    suspend fun choose(ticket: ConflictTicket, choice: ConflictChoice): String? = withContext(Dispatchers.IO) {
        val retryCorrected = choice == ConflictChoice.LOCAL && ticket.canRetryCorrected
        check(ticket.canChoose || retryCorrected)
        val source = ticket.source; val lease = ticket.lease
        val restore = choice == ConflictChoice.LOCAL && ticket.restoresAsCopy
        val target = if (restore) UUID.randomUUID().toString() else source.entity.id
        val localWins = choice == ConflictChoice.LOCAL
        val deleted = if (localWins) ticket.localDeleted else ticket.serverState == ConflictServerState.DELETED
        var payload = if (localWins) ticket.localPayload else ticket.serverPayload ?: ticket.localPayload
        if (restore && source.operation.entityType == "meal") {
            val value = StrictJson.read(payload.toByteArray(Charsets.UTF_8)); val items = value.getJSONArray("items")
            for (i in 0 until items.length()) items.getJSONObject(i).put("item_id", UUID.randomUUID().toString())
            payload = MealWire.read(StrictJson.canonical(value), schema).canonical
        }
        // A rejection did not apply the old mutation. With no observed current version, retain
        // its original base (including null for create) instead of inventing an acknowledgement.
        val base = if (restore) null else if (retryCorrected) ticket.serverRevision ?: source.operation.baseRevision else ticket.serverRevision
        val send = localWins && !(deleted && ticket.serverState == ConflictServerState.DELETED)
        if (send && !restore && !retryCorrected) checkNotNull(base)
        val operationId = if (send) UUID.randomUUID().toString() else null
        val wire = operationId?.let { id -> when (source.operation.entityType) {
            "meal" -> MealWire.operation(id, target, ticket.evidence.epoch, base, payload.takeUnless { deleted }, schema)
            "weight" -> WeightWire.operation(id, target, ticket.evidence.epoch, base, payload.takeUnless { deleted }, schema)
            else -> error("Unsupported conflict")
        } }
        val mealWire = if (source.entity is MealPushEntitySource && !deleted) MealWire.read(payload, schema) else null
        val weightWire = if (source.entity is WeightPushEntitySource && !deleted) WeightWire.read(payload, schema) else null
        val at = Instant.now().toString()
        val decision = SyncConflictDecision(source.operation.operationId, lease.storageScope, source.batch.id,
            source.operation.entityType, source.entity.id, source.batch.wireContext, choice.name, ticket.localPayload,
            ticket.localDeleted, ticket.serverPayload, ticket.serverState.name, ticket.serverRevision, ticket.evidence.resultJson,
            ticket.snapshotRunId, target.takeIf { restore }, operationId, at)
        db.withTransaction {
            owners.requireCurrent(lease)
            // Do not accept an old preview after a local edit, account switch, new pull or recovery.
            if (push.gate(lease) != source.gate || db.pushDao().batch(source.batch.id) != source.batch ||
                db.dao().operation(source.operation.operationId) != source.operation || entity(lease, source.operation) != source.entity ||
                db.snapshotDao().pages(source.gate.run.id) != source.pages || db.conflictDao().decision(source.operation.operationId) != null)
                throw ConflictChangedException()
            val revision = base ?: source.entity.revision
            when (val entity = source.entity) {
                is MealPushEntitySource -> {
                    val old = entity.meal.meal
                    if (restore) db.dao().updateMeal(old.copy(deleted = true, localRevision = Math.addExact(old.localRevision, 1)))
                    val localTarget=if(restore)target else old.id
                    val row = mealWire?.let { CanonicalMealRows.meal(localTarget, lease.storageScope, it, source.batch.wireContext,
                        if (restore) 0 else revision, if (restore) 1 else Math.addExact(old.localRevision, 1)) }
                        ?: old.copy(deleted = true, serverRevision = revision, localRevision = Math.addExact(old.localRevision, 1))
                    if (restore) db.dao().insertMeal(row) else db.dao().updateMeal(row)
                    if (mealWire != null) {
                        val items = db.localMealItems(lease.storageScope,localTarget,mealWire).map { fresh ->
                            val original = entity.meal.items.singleOrNull { it.id == fresh.id }
                            when {
                                localWins && !restore && original != null -> original.copy(grams = fresh.grams, wirePayload = fresh.wirePayload)
                                !restore && original != null -> fresh.copy(snapshotJson = original.snapshotJson)
                                else -> fresh
                            }
                        }
                        items.forEach { fresh -> check(db.dao().itemById(fresh.id)?.mealId.let { it == null || it == localTarget }) }
                        if (!restore) entity.meal.items.forEach { db.dao().removeItem(it) }
                        items.forEach { db.dao().insertItem(it) }
                    }
                }
                is WeightPushEntitySource -> {
                    val old = entity.point
                    if (restore) db.dao().saveWeight(old.copy(deleted = true, localRevision = Math.addExact(old.localRevision, 1)))
                    val value = weightWire?.json()
                    val row = if (value == null) old.copy(deleted = true, localRevision = Math.addExact(old.localRevision, 1))
                        else WeightEntity(if(restore)target else old.id, lease.storageScope, value.getString("local_date"), value.getString("occurred_at"),
                            value.getString("time_zone"), value.getString("weight_kg").toDouble(), false,
                            if (restore) 1 else Math.addExact(old.localRevision, 1))
                    db.dao().saveWeight(row)
                    val state = CanonicalWeightState(if(restore)target else old.id, lease.storageScope, payload, source.batch.wireContext, if (restore) 0 else revision)
                    if (restore) db.weightSyncDao().insert(state) else db.weightSyncDao().update(state)
                }
                is DomainPushEntitySource -> error("Private-domain reconciliation requires its explicit adapter")
            }
            source.entity.queue.forEach { db.dao().updateOperation(it.copy(status = "superseded")) }
            if (operationId != null) db.dao().enqueue(OutboxEntity(operationId, lease.storageScope, source.operation.entityType,
                target, if (deleted) "delete" else "upsert", base, if (deleted) "null" else payload, at,
                "pending", "sync-v1", wire, source.batch.wireContext))
            db.conflictDao().insert(decision)
        }
        operationId
    }
}

val MIGRATION_15_16 = object : Migration(15, 16) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS sync_conflict_decisions (operationId TEXT NOT NULL, ownerScope TEXT NOT NULL, batchId TEXT NOT NULL, entityType TEXT NOT NULL, entityId TEXT NOT NULL, wireContext TEXT NOT NULL, choice TEXT NOT NULL, localPayload TEXT NOT NULL, localDeleted INTEGER NOT NULL, serverPayload TEXT, serverState TEXT NOT NULL, serverRevision INTEGER, resultJson TEXT NOT NULL, snapshotRunId TEXT, replacementId TEXT, newOperationId TEXT, decidedAt TEXT NOT NULL, PRIMARY KEY(operationId), FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT, FOREIGN KEY(operationId) REFERENCES outbox(operationId) ON UPDATE NO ACTION ON DELETE RESTRICT, FOREIGN KEY(batchId) REFERENCES sync_push_batches(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_sync_conflict_decisions_ownerScope ON sync_conflict_decisions(ownerScope)")
        db.execSQL("CREATE INDEX index_sync_conflict_decisions_batchId ON sync_conflict_decisions(batchId)")
    }
}
