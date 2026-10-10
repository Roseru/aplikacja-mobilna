package pl.roseru.kalorie

import android.content.Context
import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.objects
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class BootstrapGoalStorageTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val date = LocalDate.now()
    private val accountId = "a1111111-1111-4111-8111-111111111111"
    private val epoch = "e1111111-1111-4111-8111-111111111111"
    private fun response(generation: Int = 1, syncEpoch: String = epoch, id: String = accountId,
        time: String = "2026-10-10T10:00:00Z") = BootstrapResponse(id, syncEpoch, generation, time)
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db: CalorieDatabase, subject: String = "A"): OwnerLease {
        val owners = LocalOwnerStore(db)
        return owners.select(owners.registerIdentity("https://identity.example", subject).id)
    }
    private suspend fun rejected(action: suspend () -> Unit): Exception {
        val error = try { action(); null } catch (error: Exception) { error }
        assertNotNull("Expected rejected action", error)
        return error!!
    }

    @Test fun bootstrapBindsExactOwnerWithDurableKeyAndIdempotentReceiptWithoutPrivateWrites() = runBlocking {
        val db = memory()
        try {
            val guest = DiaryRepository(db, context); guest.initialize()
            guest.add("basic-banana", 100.0, MealType.LUNCH, date, "guest-preserved")
            val store = AccountBootstrapStore(db)
            rejected { store.begin(LocalOwnerStore(db).currentLease()) }
            val lease = account(db)
            val request = store.begin(lease)
            assertEquals(request, store.begin(lease))
            UUID.fromString(request.operationId)
            val value = store.apply(request, response())
            assertEquals(value, store.apply(request, response()))
            assertEquals(accountId, value.accountId)
            assertEquals(lease.storageScope, value.ownerScope)
            assertNotEquals(value.accountId, value.ownerScope)
            assertEquals(1L, value.contextRevision)
            assertFalse(value.requiresRecovery)
            assertEquals(value, store.requireReady(lease, 1))
            assertEquals(1, db.dao().operationCount("guest"))
            assertEquals(0, db.dao().operationCount(lease.storageScope))
            assertNull(db.dao().currentProfile(lease.storageScope))
            assertTrue(db.dao().goalsThrough(lease.storageScope, date.toString()).first().isEmpty())
            assertTrue(db.dao().day(lease.storageScope, date.toString()).first().isEmpty())
            assertEquals(lease, LocalOwnerStore(db).currentLease())
        } finally { db.close() }
    }

    @Test fun pendingRequestAndAcceptedBindingSurviveRestartWithoutChangingIdempotencyKey() = runBlocking {
        val name = "bootstrap-restart-${UUID.randomUUID()}.db"
        fun open() = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        var db = open()
        try {
            val lease = account(db)
            val request = AccountBootstrapStore(db).begin(lease)
            db.close(); db = open()
            assertEquals(request, AccountBootstrapStore(db).begin(lease))
            val binding = AccountBootstrapStore(db).apply(request, response())
            db.close(); db = open()
            assertEquals(binding, db.bootstrapDao().binding(lease.storageScope))
            assertEquals(response().canonical(), db.bootstrapDao().attempt(lease.storageScope)!!.responseJson)
            assertEquals(binding, AccountBootstrapStore(db).apply(request, response()))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun switchedOwnerAndOldRequestCannotAcceptLateResponseEvenAfterReturning() = runBlocking {
        val db = memory()
        try {
            val owners = LocalOwnerStore(db); val store = AccountBootstrapStore(db)
            val a = account(db); val request = store.begin(a)
            val b = account(db, "B")
            assertTrue(rejected { store.apply(request, response()) } is StaleOwnerException)
            assertNull(db.bootstrapDao().binding(a.storageScope))
            assertNull(db.bootstrapDao().binding(b.storageScope))
            val currentA = owners.select(db.ownerDao().byScope(a.storageScope)!!.id)
            val next = store.begin(currentA)
            assertNotEquals(request.operationId, next.operationId)
            assertTrue(rejected { store.apply(request, response()) } is StaleOwnerException)
            val binding = store.apply(next, response())
            val newerRequest = store.begin(currentA)
            assertNotEquals(next.operationId, newerRequest.operationId)
            assertTrue(rejected { store.apply(next, response()) } is BootstrapConflictException)
            assertEquals(binding, db.bootstrapDao().binding(a.storageScope))
            val renewed = store.renew(newerRequest)
            assertNotEquals(newerRequest.operationId, renewed.operationId)
            assertTrue(rejected { store.apply(newerRequest, response()) } is BootstrapConflictException)
            assertEquals(binding, store.apply(renewed, response()))
        } finally { db.close() }
    }

    @Test fun changedRemoteContextBlocksFutureSyncAndCannotBeSilentlyClearedOrRebound() = runBlocking {
        val db = memory()
        try {
            val lease = account(db); val store = AccountBootstrapStore(db)
            val first = store.apply(store.begin(lease), response())
            val second = store.apply(store.begin(lease), response(generation = 2))
            assertEquals(2L, second.contextRevision)
            assertTrue(second.requiresRecovery)
            assertTrue(rejected { store.requireReady(lease, first.contextRevision) } is BootstrapRecoveryRequiredException)
            assertTrue(rejected { store.requireReady(lease, second.contextRevision) } is BootstrapRecoveryRequiredException)
            val retry = store.apply(store.begin(lease), response(generation = 2))
            assertEquals(2L, retry.contextRevision); assertTrue(retry.requiresRecovery)
            val bad = store.begin(lease)
            assertTrue(rejected { store.apply(bad, response()) } is BootstrapConflictException)
            assertTrue(rejected { store.apply(bad, response(id = "a2222222-2222-4222-8222-222222222222")) } is BootstrapConflictException)
            assertEquals(retry, db.bootstrapDao().binding(lease.storageScope))
            val restored = store.apply(bad, response(syncEpoch = "e2222222-2222-4222-8222-222222222222"))
            assertEquals(3L, restored.contextRevision); assertTrue(restored.requiresRecovery)
            assertEquals(1, restored.accountGeneration)
            assertEquals(lease, LocalOwnerStore(db).currentLease())
        } finally { db.close() }
    }

    @Test fun conflictingReplayDuplicateServerAccountAndFailedReceiptWriteAreAtomic() = runBlocking {
        val db = memory()
        try {
            val leaseA = account(db); val store = AccountBootstrapStore(db)
            val requestA = store.begin(leaseA); val before = store.apply(requestA, response())
            assertTrue(rejected { store.apply(requestA, response(time = "2026-10-10T11:00:00Z")) } is BootstrapConflictException)
            assertEquals(before, db.bootstrapDao().binding(leaseA.storageScope))
            val leaseB = account(db, "B"); val requestB = store.begin(leaseB)
            rejected { store.apply(requestB, response()) }
            assertNull(db.bootstrapDao().binding(leaseB.storageScope))
            assertNull(db.bootstrapDao().attempt(leaseB.storageScope)!!.responseJson)
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_receipt BEFORE UPDATE ON bootstrap_attempts BEGIN SELECT RAISE(ABORT, 'receipt failure'); END")
            val resultB = response(id = "a2222222-2222-4222-8222-222222222222")
            rejected { store.apply(requestB, resultB) }
            assertNull(db.bootstrapDao().binding(leaseB.storageScope))
            assertNull(db.bootstrapDao().attempt(leaseB.storageScope)!!.responseJson)
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_receipt")
            assertEquals(resultB.accountId, store.apply(requestB, resultB).accountId)
            assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        } finally { db.close() }
    }

    @Test fun goalChangesAppendImmutableVersionsAndQueueFailureDoesNotConsumeSequence() = runBlocking {
        val db = memory()
        try {
            val repo = DiaryRepository(db, context); repo.initialize()
            repo.setGoal(3000.0, null, null, null, "first")
            val old = db.dao().goalById("guest", "first")!!
            repo.setGoal(3100.0, 150.0, 90.0, 350.0, "second")
            repo.setGoal(3100.0, 150.0, 90.0, 350.0, "second")
            rejected { repo.setGoal(3200.0, 150.0, 90.0, 350.0, "second") }
            val second = db.dao().goalById("guest", "second")!!
            assertEquals(old, db.dao().goalById("guest", "first"))
            assertEquals(1, old.localSequence); assertEquals(2, second.localSequence)
            assertEquals("first", second.correctionOf); assertEquals("history_correction", second.reason)
            assertNotNull(second.decidedAt); assertNotNull(second.zoneId)
            assertEquals(second, db.dao().goal("guest", date.toString()).first())
            assertEquals(2800.0, db.dao().goal("guest", date.minusDays(1).toString()).first()!!.kcal, 0.0)
            val analytics = AnalyticsRepository(db.dao()).observe("guest", AnalyticsWindow(date, AnalyticsPeriod.WEEK)).first()
            assertEquals("3100.0", analytics.days.last().goal!!.toPlainString())
            assertEquals(2, db.dao().operationCount("guest"))
            val sql = db.openHelper.writableDatabase
            rejected { sql.execSQL("UPDATE goals SET kcal = 9000 WHERE id = 'first'") }
            rejected { sql.execSQL("DELETE FROM goals WHERE id = 'first'") }
            sql.execSQL("PRAGMA recursive_triggers=OFF")
            rejected { sql.execSQL("INSERT OR REPLACE INTO goals (id,ownerScope,validFrom,kcal) VALUES ('second','guest',?,9000)", arrayOf(date.toString())) }
            rejected { db.dao().saveGoal(second.copy(id = "foreign-correction", ownerScope = "another-account")) }
            sql.execSQL("CREATE TRIGGER fail_goal_queue BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT, 'queue failure'); END")
            rejected { repo.setGoal(3200.0, null, null, null, "rollback") }
            assertNull(db.dao().goalById("guest", "rollback")); assertEquals(2, db.dao().goalSequence("guest"))
            sql.execSQL("DROP TRIGGER fail_goal_queue")
            repo.setGoal(3200.0, null, null, null, "retry")
            assertEquals(3, db.dao().goalById("guest", "retry")!!.localSequence)
            assertEquals(3, db.dao().operationCount("guest"))
        } finally { db.close() }
    }

    @Test fun simultaneousGoalDecisionsHaveOrderedVersionsAndCorrectionChain() = runBlocking {
        val db = memory()
        try {
            val repo = DiaryRepository(db, context); repo.initialize()
            awaitAll(async(Dispatchers.Default) { repo.setGoal(3000.0, null, null, null, "parallel-A") },
                async(Dispatchers.Default) { repo.setGoal(3100.0, null, null, null, "parallel-B") })
            val versions = db.dao().goalsThrough("guest", date.toString()).first().filter { it.validFrom == date.toString() }
            assertEquals(listOf(1, 2), versions.map { it.localSequence })
            assertEquals(versions.first().id, versions.last().correctionOf)
            assertEquals(versions.last(), db.dao().goal("guest", date.toString()).first())
            assertEquals(2, db.dao().operationCount("guest"))
        } finally { db.close() }
    }

    @Test fun actualV5MigrationPreservesAllOldColumnsOwnersAndPayloadsAndAddsNoBinding() = runBlocking {
        val name = "migration-v5-${UUID.randomUUID()}.db"
        val schema = JSONObject(InstrumentationRegistry.getInstrumentation().context.assets
            .open("pl.roseru.kalorie.data.CalorieDatabase/5.json").bufferedReader().use { it.readText() }).getJSONObject("database")
        val entities = schema.getJSONArray("entities").objects()
        val queries = entities.associate { row -> row.getString("tableName") to
            "SELECT " + row.getJSONArray("fields").objects().joinToString(",") { "`${it.getString("columnName")}`" } +
            " FROM `${row.getString("tableName")}` ORDER BY 1,2" }
        val expected = mutableMapOf<String, List<List<String?>>>()
        val fixture = memory()
        try {
            val repo = DiaryRepository(fixture, context); repo.initialize()
            repo.add("basic-banana", 100.0, MealType.LUNCH, date, "old-meal")
            repo.setGoal(3000.0, null, null, null, "old-goal")
            repo.setProfile("Poligon", 180.0, ActivityClass.LINE, DietAim.REDUCE)
            repo.addWeight(80.0, date, "old-weight"); repo.setDayComplete(date, true)
            val source = fixture.openHelper.readableDatabase
            val file = context.getDatabasePath(name); file.parentFile!!.mkdirs()
            SQLiteDatabase.openOrCreateDatabase(file, null).use { old ->
                entities.forEach { row ->
                    fun resolve(sql: String) = sql.replace("\${TABLE_NAME}", row.getString("tableName"))
                    old.execSQL(resolve(row.getString("createSql")))
                    row.optJSONArray("indices")?.objects()?.forEach { old.execSQL(resolve(it.getString("createSql"))) }
                }
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY, identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42, ?)", arrayOf(schema.getString("identityHash")))
                queries.forEach { (table, query) ->
                    source.query(query).use { cursor -> while (cursor.moveToNext()) {
                        val values: Array<Any?> = (0 until cursor.columnCount).map { index -> when (cursor.getType(index)) {
                            Cursor.FIELD_TYPE_NULL -> null
                            Cursor.FIELD_TYPE_INTEGER -> cursor.getLong(index)
                            Cursor.FIELD_TYPE_FLOAT -> cursor.getDouble(index)
                            else -> cursor.getString(index)
                        } }.toTypedArray()
                        val columns = cursor.columnNames.joinToString(",") { "`$it`" }
                        old.execSQL("INSERT INTO `$table` ($columns) VALUES (${values.joinToString(",") { "?" }})", values)
                    } }
                    expected[table] = old.rawQuery(query, null).use(::rows)
                }
                old.version = 5
            }
        } finally { fixture.close() }
        val db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addMigrations(MIGRATION_5_6).addCallback(DATABASE_GUARDS).build()
        try {
            val sql = db.openHelper.readableDatabase
            queries.forEach { (table, query) -> assertEquals(table, expected.getValue(table), sql.query(query).use(::rows)) }
            assertEquals(6, sql.version)
            assertEquals("legacy", db.dao().goalById("guest", "old-goal")!!.reason)
            assertEquals(0, db.dao().goalById("guest", "old-goal")!!.localSequence)
            assertNull(db.bootstrapDao().binding("guest"))
            assertNull(db.bootstrapDao().attempt("guest"))
            rejected { sql.execSQL("UPDATE goals SET kcal = 9000 WHERE id = 'old-goal'") }
            DiaryRepository(db, context).initialize()
            assertEquals(expected.getValue("outbox"), sql.query(queries.getValue("outbox")).use(::rows))
            assertFalse(sql.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        } finally { db.close(); context.deleteDatabase(name) }
    }

    private fun rows(cursor: Cursor): List<List<String?>> = buildList {
        while (cursor.moveToNext()) add((0 until cursor.columnCount).map { if (cursor.isNull(it)) null else cursor.getString(it) })
    }
}
