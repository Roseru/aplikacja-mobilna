package pl.roseru.kalorie

import androidx.room.Room
import androidx.room.withTransaction
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.util.UUID

/** Actual Room transactions, synthetic server receipts; no HTTP/authentication acceptance. */
class MealPushStorageTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get() = CanonicalMealRows.schema(context)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private fun fixture(name: String) = InstrumentationRegistry.getInstrumentation().context.assets.open(name).use { it.readBytes() }
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun rejected(action: suspend () -> Unit) {
        var failed = false
        try { action() } catch (e: CancellationException) { throw e } catch (_: Exception) { failed = true }
        assertTrue("Expected refusal; private values suppressed", failed)
    }
    private suspend fun account(db: CalorieDatabase, subject: String = "A", full: Boolean = true): OwnerLease {
        val owners = LocalOwnerStore(db); owners.ensureGuest()
        val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/push", subject).id)
        val bootstrap = AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(UUID.randomUUID().toString(), epoch, 1, "2026-10-17T12:00:00Z"))
        if (full) snapshot(db, lease)
        return lease
    }
    private fun page(checkpoint: String, next: String? = null) = JSONObject().put("sync_epoch", epoch).put("mode", "snapshot")
        .put("snapshot_token", "fixture-snapshot").put("page_token", next ?: JSONObject.NULL)
        .put("checkpoint", if (next == null) checkpoint else JSONObject.NULL).put("server_time", "2026-10-17T12:00:00Z")
        .put("goal_timeline_revision", 0).put("entities", JSONArray()).put("recovery_mappings", JSONArray())
        .put("operation_receipts", JSONArray()).toString().toByteArray()
    private suspend fun snapshot(db: CalorieDatabase, lease: OwnerLease, checkpoint: String = "fixture-checkpoint") {
        val store = ServerSnapshotStore(db, SnapshotProtocol(schema)); assertNull(store.apply(store.begin(lease), page(checkpoint)))
    }
    private suspend fun meal(db: CalorieDatabase, lease: OwnerLease): Pair<String, String> {
        val operation = StrictJson.read(fixture("materialized-meal-operation.json"))
        val payload = operation.getJSONObject("payload"); val id = UUID.randomUUID().toString(); val item = UUID.randomUUID().toString()
        payload.getJSONArray("items").getJSONObject(0).put("item_id", item)
        val wire = MealWire.read(StrictJson.canonical(payload), schema)
        val binding = checkNotNull(db.bootstrapDao().binding(lease.storageScope)); val context = CanonicalMealRows.context(binding)
        val op = UUID.randomUUID().toString()
        db.withTransaction {
            db.dao().insertMeal(CanonicalMealRows.meal(id, lease.storageScope, wire, context))
            CanonicalMealRows.items(id, wire).forEach { db.dao().insertItem(it) }
            db.dao().enqueue(OutboxEntity(op, lease.storageScope, "meal", id, "upsert", null, wire.canonical,
                "2026-10-17T12:00:00Z", "pending", "sync-v1", MealWire.operation(op, id, epoch, null, wire.canonical, schema), context))
        }
        return id to item
    }
    private fun reply(request: MealPushRequest, status: String = "accepted"): ByteArray {
        val value = StrictJson.read(fixture("materialized-meal-push-response.json")); val operations = request.batch.json().getJSONArray("operations")
        val results = JSONArray()
        for (i in 0 until operations.length()) {
            val row = operations.getJSONObject(i)
            results.put(JSONObject().put("operation_id", row.getString("operation_id")).put("entity_id", row.getString("entity_id"))
                .put("status", status).put("revision", if (row.isNull("base_revision")) 1 else row.getInt("base_revision") + 1)
                .put("recovery_mapping", JSONObject.NULL))
        }
        return value.put("results", results).toString().toByteArray()
    }
    private suspend fun apply(store: MealPushStore, request: MealPushRequest, status: String = "accepted") =
        store.applyAck(store.prepareAck(request, 200, reply(request, status)))

    @Test fun persistedBatchAndOriginalCheckpointSurviveProcessDeathAndLostAck() = runBlocking<Unit> {
        val name = "push-${UUID.randomUUID()}"; var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).build()
        try {
            val lease = account(db); val (id, _) = meal(db, lease); var store = MealPushStore(db, schema)
            val request = checkNotNull(store.prepare(lease)); val bytes = request.batch.body(); val hash = request.batch.sha256
            assertTrue(db.dao().canonicalMealOperations(lease.storageScope, id).single().attempted)
            assertFalse(db.pushDao().batch(request.id)!!.attempted)
            rejected { apply(store, request) }
            store.markAttempted(request); db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).build()
            store = MealPushStore(db, schema); val restored = checkNotNull(store.prepare(LocalOwnerStore(db).currentLease()))
            assertEquals(request.id, restored.id); assertArrayEquals(bytes, restored.batch.body()); assertEquals(hash, restored.batch.sha256)
            assertEquals("MealPushRequest(redacted)", restored.toString()); assertEquals("SyncPushBatch(redacted)", restored.row.toString())
            assertEquals(MealPushAckResult(1, 0, false), apply(store, restored, "already_applied"))
            assertEquals(1, db.dao().meal(id, lease.storageScope)!!.meal.serverRevision)
            assertEquals("complete", db.pushDao().batch(request.id)!!.state); assertNull(store.prepare(lease))
        } finally { db.close(); context.deleteDatabase(name) }
    }
    @Test fun laterPortionEditsCoalesceAndAckActivatesOnlyLatestIntentWithServerBase() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val (id, item) = meal(db, lease); val store = MealPushStore(db, schema)
            val original = checkNotNull(store.prepare(lease)); store.markAttempted(original)
            val repository = DiaryRepository(db, context, lease)
            repository.editItem(id, item, 175.5, "175.5"); repository.editItem(id, item, 200.000001, "200.000001")
            val before = db.dao().meal(id, lease.storageScope)!!; val pending = db.dao().canonicalMealOperations(lease.storageScope, id).last()
            assertEquals("waiting_revision", pending.status); assertNull(pending.wireJson)
            val prepared = store.prepareAck(original, 200, reply(original)); assertEquals("PreparedMealPushAck(redacted)", prepared.toString())
            assertEquals(MealPushAckResult(1, 0, false), store.applyAck(prepared))
            val after = db.dao().meal(id, lease.storageScope)!!
            assertEquals(before.items, after.items); assertEquals(before.meal.copy(serverRevision = 1), after.meal)
            val next = db.dao().operation(pending.operationId)!!
            assertEquals("pending", next.status); assertEquals(1, next.baseRevision); assertFalse(next.attempted)
            assertEquals("200.000001", JSONObject(next.wireJson!!).getJSONObject("payload").getJSONArray("items").getJSONObject(0).getJSONObject("quantity").getString("amount"))
            assertEquals(original.batch.canonical, db.pushDao().batch(original.id)!!.requestJson)
            assertTrue(store.applyAck(prepared).replay)
            val second = checkNotNull(store.prepare(lease)); store.markAttempted(second); apply(store, second)
            assertEquals(2, db.dao().meal(id, lease.storageScope)!!.meal.serverRevision)
            assertTrue(apply(store, store.open(lease, original.id), "already_applied").replay)
            assertEquals(2, db.dao().meal(id, lease.storageScope)!!.meal.serverRevision); assertNull(store.prepare(lease))
            assertEquals(3, db.dao().operationCount(lease.storageScope))
        } finally { db.close() }
    }
    @Test fun deletionDuringCreateWaitsForItsAckThenUsesPositiveRevisionWithoutResurrection() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val (id, _) = meal(db, lease); val store = MealPushStore(db, schema)
            val create = checkNotNull(store.prepare(lease)); store.markAttempted(create)
            DiaryRepository(db, context, lease).delete(id)
            val history = db.dao().meal(id, lease.storageScope)!!; assertTrue(history.meal.deleted)
            apply(store, create)
            val next = checkNotNull(store.prepare(lease)); val wire = next.batch.json().getJSONArray("operations").getJSONObject(0)
            assertEquals("delete", wire.getString("action")); assertEquals(1, wire.getInt("base_revision")); assertTrue(wire.isNull("payload"))
            store.markAttempted(next); apply(store, next); val after = db.dao().meal(id, lease.storageScope)!!
            assertEquals(history.items, after.items); assertTrue(after.meal.deleted); assertEquals(2, after.meal.serverRevision)
            assertTrue(apply(store, create, "already_applied").replay); assertEquals(after, db.dao().meal(id, lease.storageScope))
        } finally { db.close() }
    }
    @Test fun non200IncompleteAndBadLastResultsNeverAckAnyPrefix() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val a = meal(db, lease).first; val b = meal(db, lease).first; val store = MealPushStore(db, schema)
            val request = checkNotNull(store.prepare(lease)); store.markAttempted(request)
            val before = db.pushDao().batch(request.id); val operations = request.operations.map { db.dao().operation(it.operationId) }
            rejected { store.prepareAck(request, 503, reply(request)) }
            val incomplete = JSONObject(String(reply(request))); incomplete.getJSONArray("results").remove(1)
            rejected { store.prepareAck(request, 200, incomplete.toString().toByteArray()) }
            val invalid = JSONObject(String(reply(request))); invalid.getJSONArray("results").getJSONObject(1).put("revision", 0)
            rejected { store.prepareAck(request, 200, invalid.toString().toByteArray()) }
            assertEquals(before, db.pushDao().batch(request.id)); assertEquals(operations, request.operations.map { db.dao().operation(it.operationId) })
            assertEquals(0, db.dao().meal(a, lease.storageScope)!!.meal.serverRevision); assertEquals(0, db.dao().meal(b, lease.storageScope)!!.meal.serverRevision)
        } finally { db.close() }
    }
    @Test fun mixedAcceptedAndConflictPersistTogetherWithoutOverwritingServerOrLocalVersion() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val a = meal(db, lease).first; val (b, item) = meal(db, lease); val store = MealPushStore(db, schema)
            val request = checkNotNull(store.prepare(lease)); store.markAttempted(request)
            DiaryRepository(db, context, lease).editItem(b, item, 199.0, "199"); val local = db.dao().meal(b, lease.storageScope)
            val response = JSONObject(String(reply(request))); val conflict = response.getJSONArray("results").getJSONObject(1)
            conflict.remove("revision"); conflict.put("status", "conflict").put("code", "revision_conflict").put("message", "fixture")
                .put("current", JSONObject.NULL).put("details_retained", true)
            val result = store.applyAck(store.prepareAck(request, 200, response.toString().toByteArray()))
            assertEquals(MealPushAckResult(1, 1, false), result); assertEquals(1, db.dao().meal(a, lease.storageScope)!!.meal.serverRevision)
            assertEquals(local, db.dao().meal(b, lease.storageScope)); assertEquals("conflict", db.dao().operation(request.operations[1].operationId)!!.status)
            assertEquals("waiting_revision", db.dao().canonicalMealOperations(lease.storageScope, b).last().status)
            assertNotNull(db.pushDao().batch(request.id)!!.responseJson); assertNull(store.prepare(lease))
        } finally { db.close() }
    }
    @Test fun commitFailureRollsBackRevisionOperationReceiptAndWaitingActivation() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val (id, item) = meal(db, lease); val store = MealPushStore(db, schema)
            val request = checkNotNull(store.prepare(lease)); store.markAttempted(request); DiaryRepository(db, context, lease).editItem(id, item, 177.0, "177")
            val before = db.dao().meal(id, lease.storageScope); val queue = db.dao().canonicalMealOperations(lease.storageScope, id); val batch = db.pushDao().batch(request.id)
            val prepared = store.prepareAck(request, 200, reply(request))
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_push_ack BEFORE UPDATE ON sync_push_batches WHEN NEW.responseJson IS NOT NULL BEGIN SELECT RAISE(ABORT,'synthetic commit failure'); END")
            rejected { store.applyAck(prepared) }
            assertEquals(before, db.dao().meal(id, lease.storageScope)); assertEquals(queue, db.dao().canonicalMealOperations(lease.storageScope, id)); assertEquals(batch, db.pushDao().batch(request.id))
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_push_ack"); assertFalse(store.applyAck(prepared).replay)
        } finally { db.close() }
    }
    @Test fun preparedAckCasRejectsAnInterveningEditAndRetryPreservesThatExactPortion() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val (id, item) = meal(db, lease); val store = MealPushStore(db, schema)
            val request = checkNotNull(store.prepare(lease)); store.markAttempted(request); val prepared = store.prepareAck(request, 200, reply(request))
            DiaryRepository(db, context, lease).editItem(id, item, 188.000001, "188.000001")
            val local = db.dao().meal(id, lease.storageScope); val queue = db.dao().canonicalMealOperations(lease.storageScope, id)
            rejected { store.applyAck(prepared) }
            assertEquals(local, db.dao().meal(id, lease.storageScope)); assertEquals(queue, db.dao().canonicalMealOperations(lease.storageScope, id)); assertNull(db.pushDao().batch(request.id)!!.responseJson)
            apply(store, request); assertEquals("188.000001", db.dao().meal(id, lease.storageScope)!!.items.single().amountText)
            assertEquals("pending", db.dao().canonicalMealOperations(lease.storageScope, id).single().status)
        } finally { db.close() }
    }
    @Test fun contextRecoveryAndAbaFenceOldRequestsWithoutTouchingGuestOrAnotherAccount() = runBlocking<Unit> {
        val db = memory()
        try {
            val owners = LocalOwnerStore(db); owners.ensureGuest()
            val guestId = UUID.randomUUID().toString(); db.dao().insertMeal(MealEntity(guestId, "guest", "2026-10-17", "2026-10-17T12:00:00Z", "UTC", "LUNCH"))
            val guest = db.dao().meal(guestId, "guest"); val lease = account(db); val (id, _) = meal(db, lease); val store = MealPushStore(db, schema)
            val request = checkNotNull(store.prepare(lease)); store.markAttempted(request); val prepared = store.prepareAck(request, 200, reply(request))
            val binding = db.bootstrapDao().binding(lease.storageScope)!!
            for (changed in listOf(binding.copy(requiresRecovery = true), binding.copy(contextRevision = 2), binding.copy(accountGeneration = 2),
                binding.copy(syncEpoch = UUID.randomUUID().toString()), binding.copy(accountId = UUID.randomUUID().toString()))) {
                db.bootstrapDao().update(changed); rejected { store.applyAck(prepared) }; rejected { store.markAttempted(request) }; rejected { store.prepare(lease) }
                db.bootstrapDao().update(binding)
            }
            val other = account(db, "B"); val otherId = meal(db, other).first; val otherBefore = db.dao().meal(otherId, other.storageScope)
            rejected { store.applyAck(prepared) }; val back = owners.select(lease.storageScope)
            rejected { MealPushStore(db, schema).applyAck(prepared) }; rejected { store.markAttempted(request) }
            val resumed = store.open(back, request.id); apply(store, resumed)
            assertEquals(1, db.dao().meal(id, lease.storageScope)!!.meal.serverRevision)
            assertEquals(guest, db.dao().meal(guestId, "guest")); assertEquals(otherBefore, db.dao().meal(otherId, other.storageScope))
        } finally { db.close() }
    }
    @Test fun fullSnapshotAndConfirmedBootstrapAreRequiredBeforeQueueCanBeFrozen() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db, full = false); val (id, _) = meal(db, lease); val store = MealPushStore(db, schema)
            rejected { store.prepare(lease) }; assertFalse(db.dao().canonicalMealOperations(lease.storageScope, id).single().attempted)
            val snapshots = ServerSnapshotStore(db, SnapshotProtocol(schema)); val next = snapshots.apply(snapshots.begin(lease), page("unused", "next"))!!
            rejected { store.prepare(lease) }; assertNull(db.snapshotDao().access(lease.storageScope))
            snapshots.apply(next, page("checkpoint-final")); val request = checkNotNull(store.prepare(lease))
            assertEquals("checkpoint-final", request.batch.json().getString("checkpoint"))
            val access = db.snapshotDao().access(lease.storageScope)!!; db.snapshotDao().save(access.copy(blocked = true))
            rejected { store.markAttempted(request) }; db.snapshotDao().save(access)
            val bootstrap = db.bootstrapDao().attempt(lease.storageScope)!!; db.bootstrapDao().update(bootstrap.copy(responseJson = null))
            rejected { store.markAttempted(request) }; db.bootstrapDao().update(bootstrap)
            store.markAttempted(request); apply(store, request)
        } finally { db.close() }
    }
    @Test fun refreshedSnapshotCannotReplaceAnAlreadyFrozenEnvelopeCheckpoint() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); meal(db, lease); val store = MealPushStore(db, schema)
            val original = checkNotNull(store.prepare(lease)); val bytes = original.batch.body()
            snapshot(db, lease, "fresh-checkpoint")
            val resumed = checkNotNull(store.prepare(lease)); assertArrayEquals(bytes, resumed.batch.body()); assertEquals(original.id, resumed.id)
            assertEquals("fixture-checkpoint", resumed.batch.json().getString("checkpoint")); store.markAttempted(resumed); apply(store, resumed)
        } finally { db.close() }
    }
    @Test fun concurrentPreparationCannotFreezeOrPersistDuplicateBatches() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val (id, _) = meal(db, lease)
            val results = coroutineScope { (1..2).map { async(Dispatchers.IO) { runCatching { MealPushStore(db, schema).prepare(lease) } } }.awaitAll() }
            val successes = results.mapNotNull { it.getOrNull() }; assertTrue(successes.isNotEmpty()); assertEquals(1, successes.map { it.id }.toSet().size)
            assertEquals(1, db.pushDao().pending(lease.storageScope).size); assertEquals(1, db.dao().operationCount(lease.storageScope))
            assertTrue(db.dao().canonicalMealOperations(lease.storageScope, id).single().attempted)
        } finally { db.close() }
    }
    @Test fun mutatedImmutableOutboxCannotBeAcknowledgedOrOverwritten() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val (id, _) = meal(db, lease); val store = MealPushStore(db, schema)
            val request = checkNotNull(store.prepare(lease)); store.markAttempted(request); val prepared = store.prepareAck(request, 200, reply(request))
            val operation = db.dao().operation(request.operations.single().operationId)!!
            db.dao().updateOperation(operation.copy(payload = "tampered"))
            rejected { store.applyAck(prepared) }; rejected { store.open(lease, request.id) }
            assertEquals(0, db.dao().meal(id, lease.storageScope)!!.meal.serverRevision); assertNull(db.pushDao().batch(request.id)!!.responseJson)
            db.dao().updateOperation(operation); apply(store, request)
        } finally { db.close() }
    }

    @Test fun pushStatusCountsCanonicalWaitingRefusalsAndLegacyWithoutExposingBodies()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);val (id,item)=meal(db,lease);val store=MealPushStore(db,schema)
            db.dao().enqueue(OutboxEntity(UUID.randomUUID().toString(),lease.storageScope,"profile",UUID.randomUUID().toString(),"create",null,"{}","2026-10-19T00:00:00Z"))
            assertEquals(MealPushStatus(1,0,0,1,false,true),store.status(lease))
            val request=store.prepare(lease)!!;store.markAttempted(request)
            DiaryRepository(db,context,lease).editItem(id,item,175.5,"175.5")
            assertEquals(MealPushStatus(1,1,0,1,true,true),store.status(lease))
            apply(store,request);assertEquals(MealPushStatus(1,0,0,1,false,true),store.status(lease))
            val pending=db.dao().canonicalMealOperations(lease.storageScope,id).single()
            assertEquals("pending",pending.status);assertEquals(1,pending.baseRevision);assertFalse(pending.attempted)
            val acknowledged=db.dao().operation(request.operations.single().operationId)!!
            assertEquals("acked",acknowledged.status)
            assertEquals(3,db.dao().operationCount(lease.storageScope))
        }finally{db.close()}
    }
    @Test fun reconciliationRefusalRollsBackAccessAndBindingTogetherAndKeepsOriginalBatch()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);meal(db,lease);val store=MealPushStore(db,schema);val request=store.prepare(lease)!!;store.markAttempted(request)
            val batch=db.pushDao().batch(request.id)!!;val binding=db.bootstrapDao().binding(lease.storageScope)!!;val access=db.snapshotDao().access(lease.storageScope)!!
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_recovery BEFORE UPDATE ON account_bindings BEGIN SELECT RAISE(ABORT,'synthetic full'); END")
            rejected{store.requireReconciliation(request)}
            assertEquals(binding,db.bootstrapDao().binding(lease.storageScope));assertEquals(access,db.snapshotDao().access(lease.storageScope));assertEquals(batch,db.pushDao().batch(request.id))
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_recovery");store.requireReconciliation(request)
            assertTrue(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            assertEquals(binding.contextRevision+1,db.bootstrapDao().binding(lease.storageScope)!!.contextRevision)
            assertEquals(db.bootstrapDao().attempt(lease.storageScope)!!.operationId,db.snapshotDao().access(lease.storageScope)!!.bootstrapAttemptId)
            assertEquals(batch,db.pushDao().batch(request.id));assertFalse(store.status(lease).ready)
            rejected{store.markAttempted(request)};rejected{store.prepare(lease)}
        }finally{db.close()}
    }


    @Test fun batchDelayCannotBeShortenedOrBypassedAndSurvivesStoreReopen()=runBlocking<Unit> {
        val db=memory()
        try {
            val lease=account(db);meal(db,lease);val store=MealPushStore(db,schema)
            val request=store.prepare(lease)!!;store.markAttempted(request,2_000)
            store.defer(request,10_000);val saved=db.pushDao().batch(request.id)!!
            assertEquals(10_000L,saved.retryAtMillis);assertEquals(request.row.requestJson,saved.requestJson)
            val reopened=MealPushStore(db,schema).open(lease,request.id)
            rejected{store.markAttempted(reopened,9_999)};rejected{store.defer(reopened,9_999)}
            assertEquals(saved,db.pushDao().batch(request.id));assertEquals(10_000L,store.status(lease).retryAtMillis)
            store.markAttempted(reopened,10_000);assertArrayEquals(request.batch.body(),reopened.batch.body())
        }finally{db.close()}
    }
    @Test fun migration13To14PreservesAll27TablesFrozenBatchAndItemRowidsWithZeroDelay()=runBlocking<Unit> {
        val source=memory();val name="push-migration-${UUID.randomUUID()}";var target:CalorieDatabase?=null
        try {
            val lease=account(source);val (id,item)=meal(source,lease);val store=MealPushStore(source,schema)
            val request=store.prepare(lease)!!;store.markAttempted(request)
            DiaryRepository(source,context,lease).editItem(id,item,175.5,"175.5")
            val oldSchema=JSONObject(String(fixture("pl.roseru.kalorie.data.CalorieDatabase/13.json"))).getJSONObject("database")
            val entities=oldSchema.getJSONArray("entities")
            fun snapshot(sql:androidx.sqlite.db.SupportSQLiteDatabase)=buildMap<String,List<List<String?>>>{
                for(i in 0 until entities.length()) {
                    val entity=entities.getJSONObject(i);val table=entity.getString("tableName");val fields=entity.getJSONArray("fields")
                    val columns=(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    put(table,sql.query("SELECT $columns FROM `$table` ORDER BY rowid").use {cursor->buildList {
                        while(cursor.moveToNext())add((0 until cursor.columnCount).map {if(cursor.isNull(it))null else cursor.getString(it)})
                    }})
                }
            }
            val before=snapshot(source.openHelper.readableDatabase);assertEquals(27,before.size)
            context.getDatabasePath(name).parentFile!!.mkdirs()
            var rowids=emptyMap<String,Long>()
            android.database.sqlite.SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name),null).use {old->
                old.execSQL("PRAGMA foreign_keys=OFF")
                for(i in 0 until entities.length()) {
                    val entity=entities.getJSONObject(i);val table=entity.getString("tableName")
                    old.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}",table))
                    if(entity.has("indices")) {
                        val indices=entity.getJSONArray("indices")
                        for(j in 0 until indices.length())old.execSQL(indices.getJSONObject(j).getString("createSql").replace("\${TABLE_NAME}",table))
                    }
                    val fields=entity.getJSONArray("fields")
                    val columns=(0 until fields.length()).joinToString(","){"`"+fields.getJSONObject(it).getString("columnName")+"`"}
                    val marks=(0 until fields.length()).joinToString(","){"?"}
                    before.getValue(table).forEach {row->old.execSQL("INSERT INTO `$table` ($columns) VALUES ($marks)",row.toTypedArray())}
                }
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)",arrayOf(oldSchema.getString("identityHash")));old.version=13
                rowids=old.rawQuery("SELECT id,rowid FROM meal_items",null).use {c->buildMap {while(c.moveToNext())put(c.getString(0),c.getLong(1))}}
            }
            target=Room.databaseBuilder(context,CalorieDatabase::class.java,name).addMigrations(MIGRATION_13_14, MIGRATION_14_15, pl.roseru.kalorie.data.MIGRATION_15_16, pl.roseru.kalorie.data.MIGRATION_16_17).addCallback(DATABASE_GUARDS).build()
            val migrated=target!!;val sql=migrated.openHelper.readableDatabase
            assertEquals(17, sql.version);assertEquals(before,snapshot(sql))
            assertEquals(rowids,sql.query("SELECT id,rowid FROM meal_items").use {c->buildMap<String,Long>{while(c.moveToNext())put(c.getString(0),c.getLong(1))}})
            assertFalse(sql.query("PRAGMA foreign_key_check").use {it.moveToFirst()})
            val row=migrated.pushDao().batch(request.id)!!;assertEquals(0L,row.retryAtMillis)
            assertEquals(request.batch.canonical,row.requestJson);assertTrue(row.attempted);assertNull(row.responseJson)
            val reopened=MealPushStore(migrated,schema).open(LocalOwnerStore(migrated).currentLease(),row.id)
            assertArrayEquals(request.batch.body(),reopened.batch.body())
        }finally{target?.close();source.close();context.deleteDatabase(name)}
    }

}
