package pl.roseru.kalorie.data

import androidx.room.*
import androidx.room.withTransaction
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.util.UUID

@Entity(tableName = "server_snapshot_runs", foreignKeys = [ForeignKey(entity = LocalOwnerEntity::class,
    parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT)], indices = [Index("ownerScope")])
data class ServerSnapshotRun(@PrimaryKey val id: String, val ownerScope: String, val leaseGeneration: Long,
    val accountId: String, val accountGeneration: Int, val syncEpoch: String, val contextRevision: Long,
    val snapshotToken: String?, val nextPage: String?, val checkpoint: String?, val serverTime: String?,
    val timelineRevision: Long?, val pageCount: Int, val itemCount: Int, val byteCount: Long,
    val limit: Int, val state: String) { override fun toString() = "ServerSnapshotRun(state=$state, pages=$pageCount)" }

@Entity(tableName = "server_snapshot_pages", primaryKeys = ["runId", "pageIndex"],
    foreignKeys = [ForeignKey(entity = ServerSnapshotRun::class, parentColumns = ["id"], childColumns = ["runId"], onDelete = ForeignKey.RESTRICT)])
data class ServerSnapshotPage(val runId: String, val pageIndex: Int, val queryJson: String, val responseJson: String) {
    override fun toString() = "ServerSnapshotPage(index=$pageIndex)"
}

@Entity(tableName = "server_snapshot_access", foreignKeys = [ForeignKey(entity = LocalOwnerEntity::class,
    parentColumns = ["storageScope"], childColumns = ["ownerScope"], onDelete = ForeignKey.RESTRICT)])
data class ServerSnapshotAccess(@PrimaryKey val ownerScope: String, val activeRunId: String?, val blocked: Boolean,
    val bootstrapAttemptId: String? = null)

@Entity(tableName = "server_snapshot_identities", primaryKeys = ["runId", "field", "identity"],
    foreignKeys = [ForeignKey(entity = ServerSnapshotRun::class, parentColumns = ["id"], childColumns = ["runId"], onDelete = ForeignKey.RESTRICT)])
data class ServerSnapshotIdentity(val runId: String, val field: String, val identity: String)

@Dao interface ServerSnapshotDao {
    @Query("SELECT * FROM server_snapshot_runs WHERE id = :id") suspend fun run(id: String): ServerSnapshotRun?
    @Query("SELECT * FROM server_snapshot_runs WHERE ownerScope = :owner ORDER BY rowid DESC") suspend fun runs(owner: String): List<ServerSnapshotRun>
    @Query("SELECT * FROM server_snapshot_pages WHERE runId = :run ORDER BY pageIndex") suspend fun pages(run: String): List<ServerSnapshotPage>
    @Query("SELECT * FROM server_snapshot_pages WHERE runId = :run AND pageIndex = :index") suspend fun page(run: String, index: Int): ServerSnapshotPage?
    @Query("SELECT * FROM server_snapshot_access WHERE ownerScope = :owner") suspend fun access(owner: String): ServerSnapshotAccess?
    @Insert suspend fun insert(run: ServerSnapshotRun)
    @Update suspend fun update(run: ServerSnapshotRun)
    @Insert suspend fun insert(page: ServerSnapshotPage)
    @Insert suspend fun insert(identities: List<ServerSnapshotIdentity>)
    @Query("SELECT COUNT(*) FROM server_snapshot_pages WHERE runId = :run AND queryJson = :query") suspend fun querySeen(run: String, query: String): Int
    @Upsert suspend fun save(access: ServerSnapshotAccess)
}

class SnapshotConflictException : IllegalStateException("Kopia serwera wymaga nowego pobrania; dane lokalne zachowane")
class SnapshotCapacityException : IllegalStateException("Brak miejsca na kolejną kopię serwera")
data class SnapshotStatus(val completedTime: String?, val completedItems: Int, val completedPages: Int,
    val pendingItems: Int, val pendingPages: Int, val blocked: Boolean, val needsBootstrap: Boolean = false)

/** A captured context, not authentication. The controller additionally checks its OIDC ticket. */
class SnapshotRequest internal constructor(val runId: String, val pageIndex: Int,
    internal val lease: OwnerLease, internal val binding: AccountBindingEntity, val query: SnapshotQuery) {
    override fun toString() = "SnapshotRequest(index=$pageIndex)"
}

/** Raw archive only. Every page, token and final active pointer is committed atomically.
 * Local diary, outbox, bootstrap mapping and requiresRecovery are never replaced or ACKed.
 */
class ServerSnapshotStore(private val db: CalorieDatabase, private val protocol: SnapshotProtocol) {
    private val dao = db.snapshotDao()
    private val owners = LocalOwnerStore(db)
    private suspend fun context(lease: OwnerLease, expected: AccountBindingEntity? = null): AccountBindingEntity {
        owners.requireCurrent(lease)
        val value = checkNotNull(db.bootstrapDao().binding(lease.storageScope))
        require(db.ownerDao().byScope(lease.storageScope)?.kind == "account")
        if (expected != null && (value.accountId != expected.accountId || value.accountGeneration != expected.accountGeneration ||
            value.syncEpoch != expected.syncEpoch || value.contextRevision != expected.contextRevision)) throw SnapshotConflictException()
        val access = dao.access(lease.storageScope)
        check(access?.blocked != true)
        if (needsBootstrap(access)) throw SnapshotConflictException()
        // Recovery permits a full read, never ordinary push or automatic recovery completion.
        return value
    }
    private fun same(run: ServerSnapshotRun, lease: OwnerLease, value: AccountBindingEntity) =
        run.ownerScope == lease.storageScope && run.leaseGeneration == lease.generation && run.accountId == value.accountId &&
            run.accountGeneration == value.accountGeneration && run.syncEpoch == value.syncEpoch && run.contextRevision == value.contextRevision
    private suspend fun request(run: ServerSnapshotRun, lease: OwnerLease, value: AccountBindingEntity): SnapshotRequest {
        val saved=if(run.pageCount==0)db.importDao().pull(run.id) else null
        val ids=saved?.let { org.json.JSONArray(it.operationIdsJson) }?.let { rows ->
            (0 until rows.length()).map { rows.getString(it) } } ?: emptyList()
        return SnapshotRequest(run.id, run.pageCount, lease, value,
            protocol.query(run.syncEpoch, run.limit, run.snapshotToken, run.nextPage,ids))
    }

    suspend fun begin(lease: OwnerLease, recoveryOperationIds:List<String> = emptyList(),
        planId:String? = null, groupIndex:Int = 0): SnapshotRequest = db.withTransaction {
        require(groupIndex>=0 && (recoveryOperationIds.isEmpty() || planId!=null))
        // Validate first-query bounds before persisting any run.
        protocol.query(checkNotNull(db.bootstrapDao().binding(lease.storageScope)).syncEpoch, recoveryOperationIds=recoveryOperationIds)
        if(planId!=null) {
            val plan=checkNotNull(db.importDao().plan(planId))
            check(plan.targetScope==lease.storageScope && plan.approvedAt!=null)
        }
        val value = context(lease)
        val runs = dao.runs(lease.storageScope)
        runs.firstOrNull { run ->
            val pull=db.importDao().pull(run.id)
            run.state == "pending" && same(run, lease, value) &&
                pull?.planId==planId && (pull==null || (pull.groupIndex==groupIndex &&
                pull.operationIdsJson==pl.roseru.kalorie.core.catalog.StrictJson.canonical(org.json.JSONArray(recoveryOperationIds))))
        }?.let { return@withTransaction request(it, lease, value) }
        // Bound retained archives without silently deleting older evidence or local history.
        if (runs.size >= 8 || runs.sumOf { it.byteCount } >= 128L * 1_048_576) throw SnapshotCapacityException()
        val run = ServerSnapshotRun(UUID.randomUUID().toString(), lease.storageScope, lease.generation, value.accountId,
            value.accountGeneration, value.syncEpoch, value.contextRevision, null, null, null, null, null, 0, 0, 0, 100, "pending")
        dao.insert(run)
        if(planId!=null)db.importDao().insert(ReconciliationPull(run.id,planId,groupIndex,
            pl.roseru.kalorie.core.catalog.StrictJson.canonical(org.json.JSONArray(recoveryOperationIds))))
        request(run, lease, value)
    }
    suspend fun requireCurrent(request: SnapshotRequest) = db.withTransaction {
        val value = context(request.lease, request.binding)
        val run = checkNotNull(dao.run(request.runId))
        if (!same(run, request.lease, value) || run.state != "pending" || run.pageCount != request.pageIndex ||
            this@ServerSnapshotStore.request(run, request.lease, value).query.canonical != request.query.canonical) throw SnapshotConflictException()
    }
    suspend fun apply(request: SnapshotRequest, bytes: ByteArray): SnapshotRequest? {
        // Validate bounded bytes before starting a write transaction.
        val page = protocol.response(request.query, bytes)
        return db.withTransaction {
            val value = context(request.lease, request.binding)
            val run = checkNotNull(dao.run(request.runId))
            if (!same(run, request.lease, value)) throw SnapshotConflictException()
            val old = dao.page(run.id, request.pageIndex)
            if (old != null) {
                if (old.queryJson != request.query.canonical || old.responseJson != page.canonical) throw SnapshotConflictException()
                if (run.state == "complete") return@withTransaction null
                if (run.state != "pending") throw SnapshotConflictException()
                return@withTransaction this@ServerSnapshotStore.request(run, request.lease, value)
            }
            requireCurrent(request)
            val json = page.json()
            val identities = mutableListOf<ServerSnapshotIdentity>()
            for ((field, keys) in SnapshotProtocol.IDENTITIES) {
                val records = json.getJSONArray(field)
                for (i in 0 until records.length()) identities.add(ServerSnapshotIdentity(run.id, field,
                    keys.joinToString(":") { records.getJSONObject(i).getString(it) }))
            }
            val timeline = json.getLong("goal_timeline_revision")
            if (run.timelineRevision != null && run.timelineRevision != timeline) throw SnapshotConflictException()
            val count = SnapshotProtocol.IDENTITIES.keys.sumOf { json.getJSONArray(it).length() }
            val itemCount = Math.addExact(run.itemCount, count)
            val bytesCount = Math.addExact(run.byteCount, page.canonical.toByteArray(Charsets.UTF_8).size.toLong())
            val ownerBytes = dao.runs(run.ownerScope).sumOf { it.byteCount } - run.byteCount + bytesCount
            if (itemCount > 100_000 || run.pageCount >= 2000 || bytesCount > 64L * 1_048_576 || ownerBytes > 128L * 1_048_576)
                throw SnapshotCapacityException()
            val final = json.isNull("page_token")
            val next = run.copy(snapshotToken = json.getString("snapshot_token"), nextPage = if (final) null else json.getString("page_token"),
                checkpoint = if (final) json.getString("checkpoint") else null, serverTime = json.getString("server_time"),
                timelineRevision = timeline, pageCount = run.pageCount + 1, itemCount = itemCount, byteCount = bytesCount,
                state = if (final) "complete" else "pending")
            val nextRequest = if (final) null else this@ServerSnapshotStore.request(next, request.lease, value)
            if (nextRequest != null && (nextRequest.query.canonical == request.query.canonical ||
                dao.querySeen(run.id, nextRequest.query.canonical) > 0)) throw SnapshotConflictException()
            dao.insert(identities) // A repeated identity aborts the entire page, including tokens.
            dao.insert(ServerSnapshotPage(run.id, request.pageIndex, request.query.canonical, page.canonical))
            dao.update(next)
            if (final) dao.save(ServerSnapshotAccess(run.ownerScope, run.id, false))
            nextRequest
        }
    }
    suspend fun expire(request: SnapshotRequest) = db.withTransaction {
        requireCurrent(request)
        dao.update(checkNotNull(dao.run(request.runId)).copy(state = "expired"))
    }
    suspend fun block(request: SnapshotRequest) = db.withTransaction {
        requireCurrent(request)
        val old = dao.access(request.lease.storageScope)
        dao.save(ServerSnapshotAccess(request.lease.storageScope, old?.activeRunId, true, old?.bootstrapAttemptId))
    }
    /** Bind a context error to the last bootstrap receipt. Only a new confirmed receipt lifts it. */
    suspend fun invalidate(request: SnapshotRequest) = db.withTransaction {
        requireCurrent(request)
        val value = checkNotNull(db.bootstrapDao().binding(request.lease.storageScope))
        val attempt = checkNotNull(db.bootstrapDao().attempt(request.lease.storageScope))
        require(attempt.responseJson != null)
        val old = dao.access(request.lease.storageScope)
        dao.save(ServerSnapshotAccess(request.lease.storageScope, old?.activeRunId, false, attempt.operationId))
        db.bootstrapDao().update(value.copy(requiresRecovery = true, contextRevision = Math.addExact(value.contextRevision, 1)))
    }
    private suspend fun needsBootstrap(access: ServerSnapshotAccess?): Boolean {
        val fence = access?.bootstrapAttemptId ?: return false
        val attempt = db.bootstrapDao().attempt(access.ownerScope)
        return attempt == null || attempt.operationId == fence || attempt.responseJson == null
    }
    suspend fun active(lease: OwnerLease): ServerSnapshotRun? = db.withTransaction {
        owners.requireCurrent(lease)
        val value = db.bootstrapDao().binding(lease.storageScope) ?: return@withTransaction null
        val id = dao.access(lease.storageScope)?.activeRunId ?: return@withTransaction null
        dao.run(id)?.takeIf { it.state == "complete" && it.ownerScope == lease.storageScope && it.accountId == value.accountId &&
            it.accountGeneration == value.accountGeneration && it.syncEpoch == value.syncEpoch && it.contextRevision == value.contextRevision }
    }
    suspend fun status(lease: OwnerLease): SnapshotStatus? = db.withTransaction {
        owners.requireCurrent(lease)
        val binding = db.bootstrapDao().binding(lease.storageScope) ?: return@withTransaction null
        val complete = active(lease)
        val pending = dao.runs(lease.storageScope).firstOrNull { it.state == "pending" && same(it, lease, binding) }
        val access = dao.access(lease.storageScope)
        SnapshotStatus(complete?.serverTime, complete?.itemCount ?: 0, complete?.pageCount ?: 0,
            pending?.itemCount ?: 0, pending?.pageCount ?: 0, access?.blocked == true, needsBootstrap(access))
    }
}

val MIGRATION_6_7 = object : Migration(6, 7) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS server_snapshot_runs (id TEXT NOT NULL PRIMARY KEY, ownerScope TEXT NOT NULL, leaseGeneration INTEGER NOT NULL, accountId TEXT NOT NULL, accountGeneration INTEGER NOT NULL, syncEpoch TEXT NOT NULL, contextRevision INTEGER NOT NULL, snapshotToken TEXT, nextPage TEXT, checkpoint TEXT, serverTime TEXT, timelineRevision INTEGER, pageCount INTEGER NOT NULL, itemCount INTEGER NOT NULL, byteCount INTEGER NOT NULL, `limit` INTEGER NOT NULL, state TEXT NOT NULL, FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_server_snapshot_runs_ownerScope ON server_snapshot_runs(ownerScope)")
        db.execSQL("CREATE TABLE IF NOT EXISTS server_snapshot_pages (runId TEXT NOT NULL, pageIndex INTEGER NOT NULL, queryJson TEXT NOT NULL, responseJson TEXT NOT NULL, PRIMARY KEY(runId,pageIndex), FOREIGN KEY(runId) REFERENCES server_snapshot_runs(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE TABLE IF NOT EXISTS server_snapshot_access (ownerScope TEXT NOT NULL PRIMARY KEY, activeRunId TEXT, blocked INTEGER NOT NULL, bootstrapAttemptId TEXT, FOREIGN KEY(ownerScope) REFERENCES local_owners(storageScope) ON UPDATE NO ACTION ON DELETE RESTRICT)")
        db.execSQL("CREATE TABLE IF NOT EXISTS server_snapshot_identities (runId TEXT NOT NULL, field TEXT NOT NULL, identity TEXT NOT NULL, PRIMARY KEY(runId,field,identity), FOREIGN KEY(runId) REFERENCES server_snapshot_runs(id) ON UPDATE NO ACTION ON DELETE RESTRICT)")
    }
}
