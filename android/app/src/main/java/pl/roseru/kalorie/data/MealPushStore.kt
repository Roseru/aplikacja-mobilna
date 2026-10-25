package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.time.Instant
import java.util.UUID

@Entity(tableName = "sync_push_batches", foreignKeys = [
    ForeignKey(entity = LocalOwnerEntity::class, parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT),
    ForeignKey(entity = ServerSnapshotRun::class, parentColumns = ["id"], childColumns = ["snapshotRunId"], onDelete = ForeignKey.RESTRICT)
], indices = [Index("ownerScope"), Index("snapshotRunId")])
data class SyncPushBatch(@PrimaryKey val id: String, val ownerScope: String, val wireContext: String,
    val snapshotRunId: String, val requestJson: String, val requestHash: String, val createdAt: String,
    val attempted: Boolean = false, val responseJson: String? = null, val state: String = "pending",
    @ColumnInfo(defaultValue="0") val retryAtMillis:Long=0,
    @ColumnInfo(defaultValue="'calorie-app'") val protocolScope:String="calorie-app") {
    override fun toString() = "SyncPushBatch(redacted)"
}

@Dao interface MealPushDao {
    @Query("SELECT * FROM sync_push_batches WHERE ownerScope=:owner AND responseJson IS NOT NULL AND state IN ('complete','archived_reconciled') ORDER BY rowid") suspend fun received(owner:String):List<SyncPushBatch>
    @Query("SELECT * FROM sync_push_batches WHERE id=:id") suspend fun batch(id: String): SyncPushBatch?
    @Query("SELECT * FROM sync_push_batches WHERE ownerScope=:owner AND state='pending' ORDER BY rowid LIMIT 2")
    suspend fun pending(owner: String): List<SyncPushBatch>
    @Insert suspend fun insert(row: SyncPushBatch)
    @Update suspend fun update(row: SyncPushBatch)
    @Query("SELECT * FROM outbox WHERE ownerScope=:owner AND entityType IN ('meal','weight','profile','goal','diary_day','product_draft') AND wireFormat='sync-v1' AND status='pending' ORDER BY CASE WHEN entityType='diary_day' AND baseRevision IS NULL THEN 0 ELSE 1 END,rowid LIMIT 100")
    suspend fun eligible(owner: String): List<OutboxEntity>
    @Query("SELECT COUNT(*) FROM outbox WHERE ownerScope=:owner AND entityType IN ('meal','weight','profile','goal','diary_day','product_draft') AND wireFormat='sync-v1' AND status=:status")
    suspend fun count(owner: String, status: String): Int
    @Query("SELECT COUNT(*) FROM outbox WHERE ownerScope=:owner AND wireFormat!='sync-v1' AND status!='acked'")
    suspend fun legacyCount(owner: String): Int
}

/** A local lease is a write fence, not an authenticated API ticket. */
class MealPushRequest internal constructor(val id: String, internal val lease: OwnerLease,
    internal val row: SyncPushBatch, val batch: PushBatch, internal val operations: List<OutboxEntity>) {
    internal val epoch: String = batch.json().getString("sync_epoch")
    internal val checkpoint: String = batch.json().getString("checkpoint")
    override fun toString() = "MealPushRequest(redacted)"
}

internal data class MealPushGate(val binding: AccountBindingEntity, val access: ServerSnapshotAccess,
    val run: ServerSnapshotRun, val bootstrap: BootstrapAttemptEntity) {
    override fun toString() = "MealPushGate(redacted)"
}
internal sealed interface PushEntitySource {
    val id: String
    val context: String?
    val revision: Int
    val deleted: Boolean
    val payload: String?
    val queue: List<OutboxEntity>
}
internal data class MealPushEntitySource(val meal: MealWithItems, override val queue: List<OutboxEntity>, val wireId:String=meal.meal.id): PushEntitySource {
    override val id get() = wireId
    override val context get() = meal.meal.wireContext
    override val revision get() = meal.meal.serverRevision
    override val deleted get() = meal.meal.deleted
    override val payload get() = meal.meal.wirePayload
    override fun toString() = "MealPushEntitySource(redacted)"
}
internal data class WeightPushEntitySource(val point: WeightEntity, val state: CanonicalWeightState,
    override val queue: List<OutboxEntity>, val wireId:String=point.id): PushEntitySource {
    override val id get() = wireId
    override val context get() = state.wireContext
    override val revision get() = state.serverRevision
    override val deleted get() = point.deleted
    override val payload get() = state.wirePayload
    override fun toString() = "WeightPushEntitySource(redacted)"
}
internal data class DomainPushEntitySource(val state: CanonicalDomainState,
    override val queue: List<OutboxEntity>): PushEntitySource {
    override val id get() = state.entityId
    override val context get() = state.wireContext
    override val revision get() = state.serverRevision
    override val deleted get() = state.deleted
    override val payload get() = state.wirePayload
    override fun toString() = "DomainPushEntitySource(redacted)"
}
internal data class MealPushAckSource(val gate: MealPushGate, val row: SyncPushBatch,
    val operations: List<OutboxEntity>, val entities: List<PushEntitySource>,
    val domainQueue: List<OutboxEntity> = emptyList(), val timeline: CanonicalGoalTimeline? = null) {
    override fun toString() = "MealPushAckSource(redacted)"
}
data class MealPushAckResult(val acknowledged: Int, val refused: Int, val replay: Boolean)
data class MealPushStatus(val pending: Int, val waiting: Int, val refused: Int, val legacy: Int,
    val persistedBatch: Boolean, val ready: Boolean, val retryAtMillis:Long=0,
    val domains: Map<String, DomainPushStatus> = emptyMap())
data class DomainPushStatus(val pending: Int, val waiting: Int, val refused: Int)
class PreparedMealPushAck internal constructor(internal val request: MealPushRequest,
    internal val source: MealPushAckSource, internal val batch: SyncPushBatch,
    internal val meals: List<MealEntity>, internal val operations: List<OutboxEntity>, val result: MealPushAckResult,
    internal val weights: List<CanonicalWeightState> = emptyList(),
    internal val domains: List<CanonicalDomainState> = emptyList(), internal val timeline: CanonicalGoalTimeline? = null) {
    override fun toString() = "PreparedMealPushAck(redacted)"
}

/** Ordinary canonical six-domain batch. Legacy conversion and recovery remain separate adapters. */
class MealPushStore(private val db: CalorieDatabase, private val schema: SyncWireSchema) {
    private val protocol = PushProtocol(schema)
    private val owners = LocalOwnerStore(db)
    private val dao = db.pushDao()

    /** Public counters only; no JSON, identity, checkpoint or credentials in UI state. */
    suspend fun status(lease: OwnerLease): MealPushStatus = db.withTransaction {
        owners.requireCurrent(lease)
        val ready = try { gate(lease); true } catch (error: kotlinx.coroutines.CancellationException) { throw error }
            catch (_: Exception) { false }
        val waiting = listOf("waiting_revision", "waiting_timeline", "waiting_profile", "waiting_recovery")
        val domains = (listOf("meal", "weight") + PrivateDomainsWire.types).associateWith { type ->
            val rows = db.serverDiaryDao().unsettled(lease.storageScope).filter { it.entityType == type && it.wireFormat == "sync-v1" }
            DomainPushStatus(rows.count { it.status == "pending" }, rows.count { it.status in waiting },
                rows.count { it.status in setOf("conflict", "rejected") })
        }
        MealPushStatus(dao.count(lease.storageScope,"pending"), waiting.sumOf { dao.count(lease.storageScope,it) },
            dao.count(lease.storageScope,"conflict") + dao.count(lease.storageScope,"rejected"),
            dao.legacyCount(lease.storageScope),dao.pending(lease.storageScope).isNotEmpty(),ready,
            dao.pending(lease.storageScope).maxOfOrNull {it.retryAtMillis}?:0, domains)
    }

    /** A normative preflight refusal never ACKs a prefix or rewrites the original envelope. */
    suspend fun requireReconciliation(request: MealPushRequest, deleting: Boolean = false) = db.withTransaction {
        val (gate,row)=current(request)
        check(row.state=="pending" && row.responseJson==null && row.attempted)
        if(deleting) db.snapshotDao().save(gate.access.copy(blocked=true))
        else {
            db.snapshotDao().save(gate.access.copy(bootstrapAttemptId=gate.bootstrap.operationId))
            db.bootstrapDao().update(gate.binding.copy(requiresRecovery=true,
                contextRevision=Math.addExact(gate.binding.contextRevision,1)))
        }
    }

    internal suspend fun gate(lease: OwnerLease, reconciliationPlanId:String?=null,stagedRunId:String?=null): MealPushGate {
        owners.requireCurrent(lease)
        check(db.ownerDao().byScope(lease.storageScope)?.kind == "account")
        val binding = checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        if(binding.requiresRecovery) {
            val plan=checkNotNull(reconciliationPlanId?.let {db.importDao().plan(it)})
            check(plan.targetScope==lease.storageScope && plan.wireContext==CanonicalMealRows.context(binding) &&
                plan.approvedAt!=null && plan.state=="ready_to_apply")
        }
        val bootstrap = checkNotNull(db.bootstrapDao().attempt(lease.storageScope))
        check(bootstrap.responseJson != null)
        val access = db.snapshotDao().access(lease.storageScope) ?: if(stagedRunId!=null)
            ServerSnapshotAccess(lease.storageScope,null,false) else error("Missing server snapshot")
        check(!access.blocked && access.bootstrapAttemptId != bootstrap.operationId)
        val run = checkNotNull((stagedRunId?:access.activeRunId)?.let { db.snapshotDao().run(it) })
        check(run.ownerScope == lease.storageScope && run.state == "complete" && run.checkpoint != null &&
            run.accountId == binding.accountId && run.accountGeneration == binding.accountGeneration &&
            run.syncEpoch == binding.syncEpoch && run.contextRevision == binding.contextRevision)
        if(stagedRunId!=null && stagedRunId!=access.activeRunId) {
            check(run.protocolScope==SyncProtocolScope.ENERGY_V1.installationId)
            SyncProtocolStore(db).requireReadScope(lease,binding,SyncProtocolScope.ENERGY_V1)
        }
        return MealPushGate(binding, access, run, bootstrap)
    }

    /** Freeze operations and envelope together before the first possible network side effect. */
    suspend fun prepare(lease: OwnerLease): MealPushRequest? = withContext(Dispatchers.IO) {
        val source = db.withTransaction {
            val gate = gate(lease)
            val pending = dao.pending(lease.storageScope); check(pending.size <= 1)
            if(pending.isEmpty() && !newPushAllowed(lease,gate))return@withTransaction null
            Triple(gate, pending.singleOrNull(), dao.eligible(lease.storageScope))
        } ?: return@withContext null
        source.second?.let { return@withContext open(lease, it.id) }
        if (source.third.isEmpty()) return@withContext null
        val context = CanonicalMealRows.context(source.first.binding)
        // Meal can implicitly create a different server DiaryDay UUID. An explicit new day in
        // this unattempted batch must establish its identity first; no operation bytes change.
        val candidates = source.third.sortedBy { if (it.entityType == "diary_day" && it.baseRevision == null) 0 else 1 }
        val batch = protocol.prepare(source.first.binding.syncEpoch, checkNotNull(source.first.run.checkpoint),
            candidates.map { checkNotNull(it.wireJson) }).withScope(SyncProtocolScope.parse(source.first.run.protocolScope))
        val wire = batch.json().getJSONArray("operations")
        val selected = (0 until wire.length()).map { candidates[it] }
        selected.forEachIndexed { i, row ->
            validateRow(row, context, StrictJson.canonical(wire.getJSONObject(i)))
            check(!row.attempted)
        }
        val row = SyncPushBatch(UUID.randomUUID().toString(), lease.storageScope, context, source.first.run.id,
            batch.canonical, batch.sha256, Instant.now().toString(),protocolScope=batch.protocolScope.installationId)
        val frozen = selected.map { it.copy(attempted = true) }
        db.withTransaction {
            check(gate(lease) == source.first && dao.pending(lease.storageScope).isEmpty() && newPushAllowed(lease,source.first))
            selected.forEach { expected ->
                check(db.dao().operation(expected.operationId) == expected)
                val entity = entity(lease.storageScope, expected)
                check(entity.context == context && entity.revision.takeIf { it > 0 } == expected.baseRevision)
                check(if (expected.action == "delete") entity.deleted else !entity.deleted && entity.payload == expected.payload)
            }
            frozen.forEach { db.dao().updateOperation(it) }
            dao.insert(row)
        }
        MealPushRequest(row.id, lease, row, batch, frozen)
    }

    /** Resume the persisted body, including its original checkpoint, after process death. */
    suspend fun open(lease: OwnerLease, id: String): MealPushRequest = withContext(Dispatchers.IO) {
        val source = db.withTransaction { gate(lease) to checkNotNull(dao.batch(id)) }
        val row = source.second
        check(row.ownerScope == lease.storageScope && row.wireContext == CanonicalMealRows.context(source.first.binding))
        val batch = protocol.restore(row.requestJson.toByteArray(Charsets.UTF_8)).withScope(SyncProtocolScope.parse(row.protocolScope)); check(batch.sha256 == row.requestHash)
        val wire = batch.json().getJSONArray("operations")
        val ids = (0 until wire.length()).map { wire.getJSONObject(it).getString("operation_id") }
        val operations = db.withTransaction {
            check(gate(lease) == source.first && dao.batch(id) == row)
            ids.map { checkNotNull(db.dao().operation(it)) }
        }
        operations.forEachIndexed { i, operation ->
            validateRow(operation, row.wireContext, StrictJson.canonical(wire.getJSONObject(i)))
            check(operation.ownerScope == lease.storageScope && operation.attempted)
        }
        MealPushRequest(id, lease, row, batch, operations)
    }

    private fun validateRow(row: OutboxEntity, context: String, wire: String) {
        val value = StrictJson.read(wire.toByteArray(Charsets.UTF_8))
        check(row.wireFormat == "sync-v1" && row.wireContext == context && row.wireJson == wire && row.entityType in (setOf("meal", "weight") + PrivateDomainsWire.types))
        check(row.entityType == value.getString("entity_type"))
        check(row.operationId == value.getString("operation_id") && row.entityId == value.getString("entity_id") &&
            row.action == value.getString("action") && row.payload == StrictJson.canonical(value.get("payload")))
        check(row.baseRevision == if (value.isNull("base_revision")) null else value.getInt("base_revision"))
    }
    private suspend fun newPushAllowed(lease:OwnerLease,gate:MealPushGate):Boolean {
        val state=SyncProtocolStore(db).current(lease,gate.binding)?:return gate.run.protocolScope==SyncProtocolScope.LEGACY.installationId
        return state.phase=="active" && state.activeScope==gate.run.protocolScope
    }

    private suspend fun entity(owner: String, operation: OutboxEntity): PushEntitySource = when (operation.entityType) {
        "meal" -> MealPushEntitySource(checkNotNull(db.dao().meal(db.localSyncId(owner,"meal",operation.entityId), owner)),
            db.dao().canonicalMealOperations(owner, operation.entityId),operation.entityId)
        "weight" -> WeightPushEntitySource(checkNotNull(db.dao().weight(db.localSyncId(owner,"weight",operation.entityId), owner)),
            checkNotNull(db.weightSyncDao().state(owner, db.localSyncId(owner,"weight",operation.entityId))), db.weightSyncDao().operations(owner, operation.entityId),operation.entityId)
        in PrivateDomainsWire.types -> DomainPushEntitySource(
            checkNotNull(db.domainSyncDao().state(owner, operation.entityType, operation.entityId)),
            db.domainSyncDao().operations(owner, operation.entityType, operation.entityId))
        else -> error("Unsupported canonical entity")
    }

    private fun wireOperation(row: OutboxEntity, epoch: String, revision: Int?, payload: String?): String = when (row.entityType) {
        "meal" -> MealWire.operation(row.operationId, row.entityId, epoch, revision, payload, schema)
        "weight" -> WeightWire.operation(row.operationId, row.entityId, epoch, revision, payload, schema)
        in PrivateDomainsWire.types -> PrivateDomainsWire.operation(row.operationId, row.entityType, row.entityId, epoch, revision, payload, schema)
        else -> error("Unsupported canonical entity")
    }

    private suspend fun current(request: MealPushRequest): Pair<MealPushGate, SyncPushBatch> {
        val gate = gate(request.lease)
        val row = checkNotNull(dao.batch(request.id))
        check(row.ownerScope == request.lease.storageScope && row.copy(attempted = request.row.attempted,
            responseJson = request.row.responseJson, state = request.row.state) == request.row)
        // Compare the captured binding by fields, without JSON parsing inside the transaction.
        val original = checkNotNull(db.snapshotDao().run(row.snapshotRunId))
        check(original.ownerScope == request.lease.storageScope && original.state == "complete" &&
            original.accountId == gate.binding.accountId && original.accountGeneration == gate.binding.accountGeneration &&
            original.syncEpoch == gate.binding.syncEpoch && original.contextRevision == gate.binding.contextRevision &&
            original.checkpoint == request.checkpoint && request.epoch == gate.binding.syncEpoch &&
            original.protocolScope==row.protocolScope && request.batch.protocolScope.installationId==row.protocolScope)
        request.operations.forEach { expected ->
            val actual = checkNotNull(db.dao().operation(expected.operationId))
            check(actual.copy(status = "pending") == expected.copy(status = "pending") && actual.attempted)
        }
        return gate to row
    }

    suspend fun requireCurrent(request: MealPushRequest) = db.withTransaction {
        val (_, row) = current(request)
        check(row.state == "pending" && row.responseJson == null)
    }
    suspend fun markAttempted(request: MealPushRequest,nowMillis:Long=System.currentTimeMillis()) {
        db.withTransaction {
            val (_, row) = current(request)
            check(row.state == "pending" && row.responseJson == null)
            check(row.retryAtMillis<=nowMillis)
            dao.update(row.copy(attempted = true))
        }
    }

    /** The delay belongs to the frozen batch and survives logout, not just controller restart. */
    suspend fun defer(request:MealPushRequest,retryAtMillis:Long)=db.withTransaction {
        val (_,row)=current(request)
        check(row.state=="pending" && row.responseJson==null && row.attempted)
        require(retryAtMillis>=row.retryAtMillis && retryAtMillis>=0)
        dao.update(row.copy(retryAtMillis=retryAtMillis))
    }

    /** All JSON/domain work precedes the DB-only commit used under the session guard. */
    suspend fun prepareAck(request: MealPushRequest, httpStatus: Int, bytes: ByteArray): PreparedMealPushAck = withContext(Dispatchers.IO) {
        val receipt = protocol.response(request.batch, httpStatus, bytes)
        val source = db.withTransaction {
            val (gate, row) = current(request); check(row.attempted)
            val operations = request.operations.map { checkNotNull(db.dao().operation(it.operationId)) }
            val entities = if (row.state == "complete") emptyList() else operations.map { entity(request.lease.storageScope, it) }
            MealPushAckSource(gate, row, operations, entities, db.domainSyncDao().unsettled(request.lease.storageScope),
                db.domainSyncDao().timeline(request.lease.storageScope))
        }
        check(source.row.wireContext == CanonicalMealRows.context(source.gate.binding))
        if (source.row.responseJson != null) {
            check(source.row.state == "complete" && protocol.sameDecision(request.batch,
                protocol.response(request.batch, 200, source.row.responseJson.toByteArray(Charsets.UTF_8)), receipt))
            return@withContext PreparedMealPushAck(request, source, source.row, emptyList(), emptyList(), result(receipt, true))
        }
        check(source.row.state == "pending")
        val results = receipt.json().getJSONArray("results")
        val meals = mutableListOf<MealEntity>(); val weights = mutableListOf<CanonicalWeightState>()
        val operations = mutableListOf<OutboxEntity>()
        val domains = mutableListOf<CanonicalDomainState>()
        var timeline = source.timeline
        source.operations.forEachIndexed { i, operation ->
            val entity = source.entities[i]; val queue = entity.queue
            check(operation.status == "pending" && queue.filter { it.attempted } == listOf(operation))
            check(entity.context == source.row.wireContext)
            val outcome = results.getJSONObject(i); val status = outcome.getString("status")
            if (status in setOf("accepted", "already_applied")) {
                val revision = outcome.getInt("revision"); check(entity.revision <= revision)
                when (entity) {
                    is MealPushEntitySource -> meals += entity.meal.meal.copy(serverRevision = revision)
                    is WeightPushEntitySource -> weights += entity.state.copy(serverRevision = revision)
                    is DomainPushEntitySource -> {
                        domains += entity.state.copy(serverRevision = revision)
                        if (operation.entityType == "goal") {
                            val base = StrictJson.read(operation.payload.toByteArray()).getInt("timeline_base_revision")
                            val old = checkNotNull(timeline)
                            check(old.wireContext == source.row.wireContext)
                            timeline = old.copy(revision = maxOf(old.revision, Math.addExact(base, 1)))
                        }
                    }
                }
                operations += operation.copy(status = "acked")
                val waiting = queue.filter { !it.attempted }; check(waiting.size <= 1)
                waiting.singleOrNull()?.let { next ->
                    check(next.status == "waiting_revision" && next.wireJson == null && next.wireContext == source.row.wireContext &&
                        next.action in setOf("upsert", "delete"))
                    val payload = if (next.action == "delete") {
                        check(entity.deleted && next.payload == "null"); null
                    } else {
                        check(!entity.deleted && next.payload == entity.payload); next.payload
                    }
                    val wire = wireOperation(next, source.gate.binding.syncEpoch, revision, payload)
                    operations += next.copy(baseRevision = revision, wireJson = wire, status = "pending")
                }
                if (waiting.isEmpty()) check(if (operation.action == "delete") entity.deleted
                    else !entity.deleted && entity.payload == operation.payload)
            } else {
                check(status in setOf("conflict", "rejected"))
                operations += operation.copy(status = status)
            }
        }
        // Only a confirmed predecessor releases the next axis/profile operation. A refusal blocks it.
        val changes = operations.associateBy { it.operationId }
        val remaining = source.domainQueue.map { changes[it.operationId] ?: it }
            .filter { it.status !in setOf("acked", "superseded", "local_only") }
        remaining.firstOrNull { it.entityType == "goal" }?.let { next ->
            if (next.status == "waiting_timeline" && timeline?.wireContext == next.wireContext &&
                StrictJson.read(next.payload.toByteArray()).getInt("timeline_base_revision") == timeline?.revision)
                operations += next.copy(status = "pending")
        }
        remaining.firstOrNull { it.entityType == "profile" }?.let { next ->
            if (next.status == "waiting_profile") {
                check(!next.attempted && next.wireJson == null)
                val payload = if (next.action == "delete") null else next.payload
                operations += next.copy(status = "pending", wireJson = wireOperation(next, source.gate.binding.syncEpoch, next.baseRevision, payload))
            }
        }
        PreparedMealPushAck(request, source, source.row.copy(responseJson = receipt.canonical, state = "complete"),
            meals.toList(), operations.toList(), result(receipt, false), weights.toList(), domains.toList(), timeline)
    }

    private fun result(receipt: PushReceipt, replay: Boolean): MealPushAckResult {
        val rows = receipt.json().getJSONArray("results")
        val count = (0 until rows.length()).count { rows.getJSONObject(it).getString("status") in setOf("accepted", "already_applied") }
        return MealPushAckResult(count, rows.length() - count, replay)
    }

    suspend fun applyAck(prepared: PreparedMealPushAck): MealPushAckResult = db.withTransaction {
        val request = prepared.request
        val (gate, row) = current(request)
        check(gate == prepared.source.gate)
        if (!prepared.result.replay && row == prepared.batch) return@withTransaction prepared.result.copy(replay = true)
        check(row == prepared.source.row)
        prepared.source.operations.forEach { check(db.dao().operation(it.operationId) == it) }
        prepared.source.entities.forEachIndexed { index, expected ->
            check(entity(request.lease.storageScope, prepared.source.operations[index]) == expected)
        }
        check(db.domainSyncDao().unsettled(request.lease.storageScope) == prepared.source.domainQueue &&
            db.domainSyncDao().timeline(request.lease.storageScope) == prepared.source.timeline)
        if (!prepared.result.replay) {
            prepared.domains.forEach { db.domainSyncDao().save(it) }
            prepared.timeline?.let { db.domainSyncDao().save(it) }
            prepared.meals.forEach { db.dao().updateMeal(it) }
            prepared.weights.forEach { db.weightSyncDao().update(it) }
            prepared.operations.forEach { db.dao().updateOperation(it) }
            dao.update(prepared.batch)
        }
        prepared.result
    }
}

val MIGRATION_11_12 = object : Migration(11, 12) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS sync_push_batches (id TEXT NOT NULL, ownerScope TEXT NOT NULL, wireContext TEXT NOT NULL, snapshotRunId TEXT NOT NULL, requestJson TEXT NOT NULL, requestHash TEXT NOT NULL, createdAt TEXT NOT NULL, attempted INTEGER NOT NULL, responseJson TEXT, state TEXT NOT NULL, PRIMARY KEY(id), FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT, FOREIGN KEY(snapshotRunId) REFERENCES server_snapshot_runs(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX index_sync_push_batches_ownerScope ON sync_push_batches(ownerScope)")
        db.execSQL("CREATE INDEX index_sync_push_batches_snapshotRunId ON sync_push_batches(snapshotRunId)")
    }
}

val MIGRATION_13_14=object:Migration(13,14) {
    override fun migrate(db:SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE sync_push_batches ADD COLUMN retryAtMillis INTEGER NOT NULL DEFAULT 0")
    }
}
