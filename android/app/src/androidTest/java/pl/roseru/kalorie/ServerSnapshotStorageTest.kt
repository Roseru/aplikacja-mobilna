package pl.roseru.kalorie

import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteFullException
import androidx.room.Room
import androidx.room.withTransaction
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.MealType
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

class ServerSnapshotStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val epoch = "e1111111-1111-4111-8111-111111111111"
    private val accountId = "a1111111-1111-4111-8111-111111111111"
    private val protocol = SnapshotProtocol(SyncWireSchema(SyncWireSchema.FILES.associateWith { context.assets.open("sync/$it").use { input -> input.readBytes() } }))
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db: CalorieDatabase): OwnerLease {
        val owners = LocalOwnerStore(db); val lease = owners.select(owners.registerIdentity("https://id.example", "A").id)
        val bootstrap = AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(accountId, epoch, 1, "2026-10-11T10:00:00Z"))
        return lease
    }
    private fun response(next: String? = null, id: String? = null, timeline: Int = 0, token: String = "snapshot-A"): ByteArray {
        val entities = JSONArray()
        id?.let { entities.put(JSONObject().put("entity_type", "weight").put("entity_id", it).put("revision", 1).put("deleted", false)
            .put("payload", JSONObject().put("weight_kg", "80").put("occurred_at", "2026-10-11T08:00:00Z")
                .put("time_zone", "Europe/Warsaw").put("local_date", "2026-10-11"))) }
        return JSONObject().put("sync_epoch", epoch).put("mode", "snapshot").put("snapshot_token", token)
            .put("page_token", next ?: JSONObject.NULL).put("checkpoint", if (next == null) "checkpoint-A" else JSONObject.NULL)
            .put("server_time", "2026-10-11T10:00:00Z").put("entities", entities).put("goal_timeline_revision", timeline)
            .put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray()).toString().toByteArray()
    }
    private suspend fun rejected(block: suspend () -> Unit) { val error = try { block(); null } catch (e: Exception) { e }; assertNotNull(error) }
    private val weightId = "b1111111-1111-4111-8111-111111111111"

    @Test fun pagesAndContinuationSurviveReopenAndActivateOnlyAtEnd() = runBlocking<Unit> {
        val name = "snapshot-${UUID.randomUUID()}.db"
        fun open() = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        var db = open()
        try {
            val lease = account(db); val first = ServerSnapshotStore(db, protocol).begin(lease)
            val next = ServerSnapshotStore(db, protocol).apply(first, response("next", weightId))!!
            assertNull(ServerSnapshotStore(db, protocol).active(lease))
            assertNull(db.snapshotDao().run(first.runId)!!.checkpoint)
            db.close(); db = open()
            val store = ServerSnapshotStore(db, protocol)
            val resumed = store.begin(lease)
            assertEquals(next.runId, resumed.runId); assertEquals(next.query.encoded(), resumed.query.encoded())
            assertEquals(1, resumed.pageIndex)
            assertNull(store.apply(resumed, response()))
            assertEquals("checkpoint-A", store.active(lease)!!.checkpoint)
            assertEquals(2, store.active(lease)!!.pageCount)
            db.close(); db = open()
            assertEquals(first.runId, ServerSnapshotStore(db, protocol).active(lease)!!.id)
            assertEquals(2, db.snapshotDao().pages(first.runId).size)
        } finally { db.close(); context.deleteDatabase(name) }
    }
    @Test fun replayIsIdempotentAndDifferentReplayOrRepeatedIdentityRollsBackPage() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val store = ServerSnapshotStore(db, protocol); val first = store.begin(lease)
            val next = store.apply(first, response("next", weightId))!!
            assertEquals(next.pageIndex, store.apply(first, response("next", weightId))!!.pageIndex)
            rejected { store.apply(first, response("other", weightId)) }
            rejected { store.apply(next, response(id = weightId)) }
            assertEquals(1, db.snapshotDao().pages(first.runId).size)
            assertEquals("next", db.snapshotDao().run(first.runId)!!.nextPage)
            assertNull(store.active(lease))
            assertNull(store.apply(next, response()))
            assertNull(store.apply(next, response()))
            assertEquals(2, db.snapshotDao().pages(first.runId).size)
        } finally { db.close() }
    }
    @Test fun newIncompleteOrInvalidCopyPreservesPreviousActiveAndAllLocalTables() = runBlocking<Unit> {
        val db = memory()
        try {
            val guest = DiaryRepository(db, context).apply { initialize() }
            guest.add("basic-banana", 100.0, MealType.LUNCH, LocalDate.now(), "guest-fixture")
            val lease = account(db); val repo = DiaryRepository(db, context, lease).apply { initialize() }
            repo.add("basic-banana", 150.0, MealType.LUNCH, LocalDate.now(), "account-fixture")
            val before = originalTables(db)
            val store = ServerSnapshotStore(db, protocol); val initial = store.begin(lease)
            store.apply(initial, response(id = weightId))
            val start = store.begin(lease); val next = store.apply(start, response("next"))!!
            rejected { store.apply(next, response(timeline = 1)) }
            rejected { store.apply(next, response(token = "different")) }
            assertEquals(initial.runId, store.active(lease)!!.id)
            assertEquals(before, originalTables(db))
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        } finally { db.close() }
    }
    @Test fun ownerAbaAndContextChangesFenceResultsButPreserveCompletedEvidence() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val store = ServerSnapshotStore(db, protocol); val request = store.begin(lease)
            val owners = LocalOwnerStore(db); owners.select(owners.ensureGuest().id)
            val again = owners.select(db.ownerDao().byScope(lease.storageScope)!!.id)
            rejected { store.apply(request, response()) }
            val current = store.begin(again); assertNotEquals(request.runId, current.runId)
            val binding = db.bootstrapDao().binding(again.storageScope)!!
            db.bootstrapDao().update(binding.copy(contextRevision = binding.contextRevision + 1, requiresRecovery = true))
            rejected { store.apply(current, response()) }
            val recovery = store.begin(again); assertNull(store.apply(recovery, response()))
            assertTrue(db.bootstrapDao().binding(again.storageScope)!!.requiresRecovery)
            assertEquals(1, store.active(again)!!.pageCount)
        } finally { db.close() }
    }
    @Test fun expiryStartsNewRunAndDeletingBlockSurvivesRestartAndBootstrap() = runBlocking<Unit> {
        val name = "snapshot-block-${UUID.randomUUID()}.db"
        fun open() = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        var db = open()
        try {
            val lease = account(db); val store = ServerSnapshotStore(db, protocol)
            val first = store.begin(lease); val next = store.apply(first, response("next"))!!; store.expire(next)
            val restart = store.begin(lease); assertNotEquals(first.runId, restart.runId)
            assertEquals(1, db.snapshotDao().pages(first.runId).size)
            store.block(restart)
            db.close(); db = open()
            val bootstrap = AccountBootstrapStore(db)
            bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(accountId, epoch, 1, "2026-10-11T11:00:00Z"))
            rejected { ServerSnapshotStore(db, protocol).begin(lease) }
            assertTrue(ServerSnapshotStore(db, protocol).status(lease)!!.blocked)
        } finally { db.close(); context.deleteDatabase(name) }
    }
    @Test fun cyclesAndRetentionBoundNeverReplaceLastCompleteArchive() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val store = ServerSnapshotStore(db, protocol)
            val first = store.begin(lease); val second = store.apply(first, response("two"))!!
            val third = store.apply(second, response("three"))!!
            rejected { store.apply(third, response("two")) }
            assertEquals(2, db.snapshotDao().pages(first.runId).size)
            store.expire(third)
            repeat(7) { store.apply(store.begin(lease), response()) }
            val active = store.active(lease)!!.id
            rejected { store.begin(lease) }
            assertEquals(active, store.active(lease)!!.id)
            assertEquals(8, db.snapshotDao().runs(lease.storageScope).size)
        } finally { db.close() }
    }
    @Test fun contextErrorRequiresNewConfirmedBootstrapAndPreservesRecoveryAfterward() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val store = ServerSnapshotStore(db, protocol)
            val first = store.begin(lease); store.invalidate(first)
            assertTrue(store.status(lease)!!.needsBootstrap); rejected { store.begin(lease) }
            val bootstrap = AccountBootstrapStore(db); val pending = bootstrap.begin(lease)
            assertTrue(store.status(lease)!!.needsBootstrap); rejected { store.begin(lease) }
            bootstrap.apply(pending, BootstrapResponse(accountId, epoch, 1, "2026-10-11T11:00:00Z"))
            assertFalse(store.status(lease)!!.needsBootstrap)
            store.apply(store.begin(lease), response())
            assertTrue(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            assertEquals(1, store.active(lease)!!.pageCount)
        } finally { db.close() }
    }
    @Test fun migrationSixToSevenPreservesEveryColumnOfAllEighteenTables() = runBlocking<Unit> {
        val name = "snapshot-migration-${UUID.randomUUID()}.db"
        val fixture = memory(); val file = context.getDatabasePath(name); file.parentFile!!.mkdirs()
        lateinit var expected: Map<String, List<List<String?>>>
        try {
            DiaryRepository(fixture, context).apply { initialize(); add("basic-banana", 100.0, MealType.LUNCH, LocalDate.now(), "migration-guest") }
            val lease = account(fixture)
            DiaryRepository(fixture, context, lease).apply { initialize(); add("basic-banana", 150.0, MealType.LUNCH, LocalDate.now(), "migration-account") }
            val schema = JSONObject(InstrumentationRegistry.getInstrumentation().context.assets.open("pl.roseru.kalorie.data.CalorieDatabase/6.json").bufferedReader().use { it.readText() }).getJSONObject("database")
            val entities = schema.getJSONArray("entities")
            SQLiteDatabase.openOrCreateDatabase(file, null).use { old ->
                for (i in 0 until entities.length()) {
                    val entity = entities.getJSONObject(i); val table = entity.getString("tableName")
                    fun resolve(sql: String) = sql.replace("\${TABLE_NAME}", table)
                    old.execSQL(resolve(entity.getString("createSql")))
                    val indices = entity.optJSONArray("indices") ?: JSONArray()
                    for (j in 0 until indices.length()) old.execSQL(resolve(indices.getJSONObject(j).getString("createSql")))
                    val fields = entity.getJSONArray("fields")
                    val oldColumns = (0 until fields.length()).joinToString(",") { "`${fields.getJSONObject(it).getString("columnName")}`" }
                    fixture.openHelper.readableDatabase.query("SELECT $oldColumns FROM `$table`").use { cursor ->
                        while (cursor.moveToNext()) {
                            val values: Array<Any?> = (0 until cursor.columnCount).map { index -> when(cursor.getType(index)) {
                                Cursor.FIELD_TYPE_NULL -> null; Cursor.FIELD_TYPE_INTEGER -> cursor.getLong(index)
                                Cursor.FIELD_TYPE_FLOAT -> cursor.getDouble(index); else -> cursor.getString(index)
                            } }.toTypedArray()
                            old.execSQL("INSERT INTO `$table` (${cursor.columnNames.joinToString(",") { "`$it`" }}) VALUES (${values.joinToString(",") { "?" }})", values)
                        }
                    }
                }
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY, identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42, ?)", arrayOf(schema.getString("identityHash")))
                old.version = 6
            }
            expected = originalTables(fixture); assertEquals(18, expected.size)
        } finally { fixture.close() }
        val migrated = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addMigrations(MIGRATION_6_7, MIGRATION_7_8, pl.roseru.kalorie.photo.MIGRATION_8_9, pl.roseru.kalorie.photo.MIGRATION_9_10, pl.roseru.kalorie.data.MIGRATION_10_11, pl.roseru.kalorie.data.MIGRATION_11_12, pl.roseru.kalorie.photo.MIGRATION_12_13, pl.roseru.kalorie.data.MIGRATION_13_14, pl.roseru.kalorie.data.MIGRATION_14_15, pl.roseru.kalorie.data.MIGRATION_15_16, pl.roseru.kalorie.data.MIGRATION_16_17).addCallback(DATABASE_GUARDS).build()
        try {
            assertEquals(expected, originalTables(migrated)); assertEquals(17, migrated.openHelper.readableDatabase.version)
            assertTrue(migrated.snapshotDao().runs("guest").isEmpty())
            assertFalse(migrated.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        } finally { migrated.close(); context.deleteDatabase(name) }
    }
    @Test fun actualSqliteFullRollsBackPageAndKeepsActiveCopyAndLocalOriginals() = runBlocking<Unit> {
        val name = "snapshot-full-${UUID.randomUUID()}.db"
        val db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            DiaryRepository(db, context).apply { initialize(); add("basic-banana", 100.0, MealType.LUNCH, LocalDate.now(), "full-preserved") }
            val lease = account(db); val store = ServerSnapshotStore(db, protocol)
            val complete = store.begin(lease); store.apply(complete, response())
            val pending = store.begin(lease); val before = originalTables(db)
            val large = JSONObject(String(response(id = weightId)))
            val entities = large.getJSONArray("entities"); val entity = entities.getJSONObject(0)
            repeat(99) { entities.put(JSONObject(entity.toString()).put("entity_id", UUID.randomUUID().toString())) }
            val sql = db.openHelper.writableDatabase
            val pages = sql.query("PRAGMA page_count").use { it.moveToFirst(); it.getInt(0) }
            var writerFailure: Throwable? = null
            try {
                db.withTransaction {
                    sql.query("PRAGMA max_page_count=$pages").use { assertTrue(it.moveToFirst()); assertEquals(pages, it.getInt(0)) }
                    try { store.apply(pending, large.toString().toByteArray()) }
                    catch (error: Throwable) { writerFailure = error; throw error }
                }
                fail("Expected SQLiteFullException")
            } catch (error: Exception) {
                val original = writerFailure ?: error
                assertTrue(original.toString(), generateSequence(original) { it.cause }.any { it is SQLiteFullException })
            } finally { db.withTransaction { sql.query("PRAGMA max_page_count=2147483646").use { it.moveToFirst() } } }
            assertEquals(before, originalTables(db)); assertEquals(complete.runId, store.active(lease)!!.id)
            assertEquals(0, db.snapshotDao().run(pending.runId)!!.pageCount)
            assertTrue(db.snapshotDao().pages(pending.runId).isEmpty())
            store.apply(pending, response()); assertEquals(pending.runId, store.active(lease)!!.id)
        } finally { db.close(); context.deleteDatabase(name) }
    }
    private fun originalTables(db: CalorieDatabase): Map<String, List<List<String?>>> {
        val schema = JSONObject(InstrumentationRegistry.getInstrumentation().context.assets.open("pl.roseru.kalorie.data.CalorieDatabase/6.json").bufferedReader().use { it.readText() }).getJSONObject("database")
        val entities = schema.getJSONArray("entities")
        return (0 until entities.length()).associate { i ->
            val table = entities.getJSONObject(i).getString("tableName")
            val fields=entities.getJSONObject(i).getJSONArray("fields")
            val columns=(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
            table to db.openHelper.readableDatabase.query("SELECT $columns FROM `$table` ORDER BY rowid").use { cursor -> buildList {
                while (cursor.moveToNext()) add((0 until cursor.columnCount).map { if (cursor.isNull(it)) null else cursor.getString(it) })
            } }
        }
    }
}
