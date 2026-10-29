package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import java.util.UUID

/** Isolated SQLite only: completed transport/application and durable queue are independent facts. */
class AnalyticsSyncStorageTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get() = CanonicalMealRows.schema(context)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private val time = "2026-10-29T12:00:00Z"
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db: CalorieDatabase): OwnerLease {
        val owners = LocalOwnerStore(db)
        val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/analytics-sync", UUID.randomUUID().toString()).id)
        val boot = AccountBootstrapStore(db)
        boot.apply(boot.begin(lease), BootstrapResponse(UUID.randomUUID().toString(), epoch, 1, time))
        return lease
    }
    private fun page() = JSONObject().put("sync_epoch", epoch).put("mode", "snapshot")
        .put("snapshot_token", "synthetic-analytics-sync").put("page_token", JSONObject.NULL)
        .put("checkpoint", "synthetic-analytics-checkpoint").put("server_time", time).put("goal_timeline_revision", 0)
        .put("entities", JSONArray()).put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray()).toString().toByteArray()
    private suspend fun enqueue(db: CalorieDatabase, owner: String, status: String): OutboxEntity {
        val row = OutboxEntity(UUID.randomUUID().toString(), owner, "meal", UUID.randomUUID().toString(), "upsert", null, "{}", time, status)
        db.dao().enqueue(row)
        return row
    }

    @Test fun guestAndUnfetchedAccountExcludeSettledAndOtherOwnerOperations() = runBlocking {
        val db = memory()
        try {
            val owners = LocalOwnerStore(db)
            owners.ensureGuest()
            enqueue(db, DiaryRepository.GUEST, "pending")
            assertEquals(AnalyticsSyncState.Guest, AnalyticsSyncRepository(db, owners.currentLease()).read())
            val lease = account(db)
            val empty = AnalyticsSyncRepository(db, lease).read() as AnalyticsSyncState.Account
            assertNull(empty.lastAppliedAt); assertNull(empty.serverTime); assertEquals(0, empty.pendingOperations)
            enqueue(db, lease.storageScope, "pending"); enqueue(db, lease.storageScope, "waiting_recovery")
            enqueue(db, lease.storageScope, "rejected"); enqueue(db, lease.storageScope, "conflict")
            enqueue(db, lease.storageScope, "acked"); enqueue(db, lease.storageScope, "superseded"); enqueue(db, lease.storageScope, "local_only")
            val before = db.serverDiaryDao().unsettled(lease.storageScope)
            val value = AnalyticsSyncRepository(db, lease).read() as AnalyticsSyncState.Account
            assertEquals(2, value.pendingOperations); assertEquals(1, value.rejectedOperations); assertEquals(1, value.conflictedOperations)
            assertEquals(4, value.legacyOperations); assertNull(value.lastAppliedAt)
            assertEquals(before, db.serverDiaryDao().unsettled(lease.storageScope))
            assertEquals(7, db.dao().operationCount(lease.storageScope))
        } finally { db.close() }
    }

    @Test fun completedRawCopyIsNotAnAppliedReportAndRestartPreservesTimeAndRejectedQueue() = runBlocking {
        val name = "analytics-sync-${UUID.randomUUID()}.db"
        fun open() = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        var db = open()
        try {
            val lease = account(db)
            val snapshots = ServerSnapshotStore(db, SnapshotProtocol(schema))
            val request = snapshots.begin(lease)
            snapshots.apply(request, page())
            val staged = AnalyticsSyncRepository(db, lease).read() as AnalyticsSyncState.Account
            assertNull(staged.lastAppliedAt); assertNull(staged.serverTime); assertTrue(staged.copyAwaitingApplication)
            val application = ServerDiaryStore(db, schema).apply(lease, request.runId)
            val pending = enqueue(db, lease.storageScope, "pending")
            val rejected = enqueue(db, lease.storageScope, "rejected")
            val first = AnalyticsSyncRepository(db, lease).read() as AnalyticsSyncState.Account
            assertEquals(application.appliedAt, first.lastAppliedAt); assertEquals(time, first.serverTime)
            assertEquals(1, first.pendingOperations); assertEquals(1, first.rejectedOperations); assertFalse(first.copyAwaitingApplication)
            val run = db.snapshotDao().run(request.runId)
            db.close(); db = open()
            val restoredLease = LocalOwnerStore(db).currentLease()
            assertEquals(lease, restoredLease)
            assertEquals(first, AnalyticsSyncRepository(db, restoredLease).read())
            assertEquals(application, db.serverDiaryDao().application(request.runId)); assertEquals(run, db.snapshotDao().run(request.runId))
            assertEquals(listOf(pending, rejected), db.serverDiaryDao().unsettled(lease.storageScope))
            assertEquals(2, db.dao().operationCount(lease.storageScope))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun observingQueueAndOwnerAbaClearsOldMetadataAndContextChangeRequiresNewCopy() = runBlocking {
        val db = memory()
        try {
            val lease = account(db)
            val snapshots = ServerSnapshotStore(db, SnapshotProtocol(schema)); val request = snapshots.begin(lease)
            snapshots.apply(request, page()); ServerDiaryStore(db, schema).apply(lease, request.runId)
            coroutineScope {
                val states = Channel<AnalyticsSyncState>(Channel.UNLIMITED)
                val job = launch { AnalyticsSyncRepository(db, lease).observe().collect { states.send(it) } }
                suspend fun await(check: (AnalyticsSyncState) -> Boolean): AnalyticsSyncState = withTimeout(15_000) {
                    var state = states.receive()
                    while (!check(state)) state = states.receive()
                    state
                }
                try {
                    await { it is AnalyticsSyncState.Account && it.lastAppliedAt != null }
                    enqueue(db, lease.storageScope, "rejected")
                    await { it is AnalyticsSyncState.Account && it.rejectedOperations == 1 }
                    val owners = LocalOwnerStore(db)
                    val guest = owners.ensureGuest(); owners.select(guest.id)
                    await { it == AnalyticsSyncState.Stale }
                    val other = account(db)
                    val otherState = AnalyticsSyncRepository(db, other).read() as AnalyticsSyncState.Account
                    assertNull(otherState.lastAppliedAt); assertEquals(0, otherState.rejectedOperations)
                    val current = owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
                    assertNotEquals(lease.generation, current.generation)
                    assertNotNull((AnalyticsSyncRepository(db, current).read() as AnalyticsSyncState.Account).lastAppliedAt)
                    assertEquals(AnalyticsSyncState.Stale, AnalyticsSyncRepository(db, lease).observe().first())
                    val binding = db.bootstrapDao().binding(current.storageScope)!!
                    db.bootstrapDao().update(binding.copy(contextRevision = binding.contextRevision + 1, requiresRecovery = true))
                    val changed = AnalyticsSyncRepository(db, current).read() as AnalyticsSyncState.Account
                    assertNull(changed.lastAppliedAt); assertNull(changed.serverTime); assertTrue(changed.requiresRecovery)
                    assertEquals(1, changed.rejectedOperations)
                    assertNotNull(db.serverDiaryDao().application(request.runId))
                } finally { job.cancelAndJoin(); states.close() }
            }
        } finally { db.close() }
    }
}
