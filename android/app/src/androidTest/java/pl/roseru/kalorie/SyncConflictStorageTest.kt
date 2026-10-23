package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

/** Actual Room transactions, complete synthetic HTTP receipts; never contacts a server. */
class SyncConflictStorageTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get() = CanonicalMealRows.schema(context)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private fun uuid() = UUID.randomUUID().toString()
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private suspend fun refused(action: suspend () -> Unit) {
        var failed = false
        try { action() } catch (error: CancellationException) { throw error } catch (_: Exception) { failed = true }
        assertTrue("Expected atomic refusal; private values suppressed", failed)
    }
    private suspend fun snapshot(db: CalorieDatabase, lease: OwnerLease, time: String, entities: JSONArray = JSONArray()) {
        val page = JSONObject().put("sync_epoch", epoch).put("mode", "snapshot").put("snapshot_token", uuid())
            .put("page_token", JSONObject.NULL).put("checkpoint", uuid()).put("server_time", time)
            .put("goal_timeline_revision", 0).put("entities", entities).put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray())
        val store = ServerSnapshotStore(db, SnapshotProtocol(schema))
        assertNull(store.apply(store.begin(lease), page.toString().toByteArray()))
    }
    private suspend fun account(db: CalorieDatabase): OwnerLease {
        val owners = LocalOwnerStore(db); owners.ensureGuest()
        val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/conflicts", uuid()).id)
        val boot = AccountBootstrapStore(db)
        boot.apply(boot.begin(lease), BootstrapResponse(uuid(), epoch, 1, "2026-10-21T10:00:00Z"))
        snapshot(db, lease, "2026-10-21T10:00:00Z")
        return lease
    }
    private suspend fun create(db: CalorieDatabase, lease: OwnerLease, type: String): String {
        val id = uuid(); val repo = DiaryRepository(db, context, lease)
        if (type == "weight") repo.addWeight(80.125, LocalDate.now(), id)
        else {
            // This fixture isolates Meal conflict decisions; the private product already exists.
            // New public product creation and mixed-domain receipts are covered by DomainSyncStorageTest.
            val productId = uuid()
            db.dao().insertProduct(ProductEntity(productId, "Synthetic soup", "synthetic soup", 100.0, 2.0, null, 10.0,
                100.0, "Fixture", "fixture", 0, lease.storageScope))
            repo.add(productId, 150.5, MealType.LUNCH, LocalDate.now(), id)
        }
        return id
    }
    private suspend fun edit(db: CalorieDatabase, lease: OwnerLease, type: String, id: String, value: Double) {
        val repo = DiaryRepository(db, context, lease)
        if (type == "weight") repo.editWeight(id, value)
        else repo.editItem(id, db.dao().meal(id, lease.storageScope)!!.items.single().id, value, value.toString())
    }
    private fun response(request: MealPushRequest, deleted: Boolean = false, retained: Boolean = true): ByteArray {
        val operation = request.batch.json().getJSONArray("operations").getJSONObject(0)
        val payload = JSONObject(operation.getJSONObject("payload").toString())
        if (operation.getString("entity_type") == "weight") payload.put("weight_kg", "82.375")
        else payload.getJSONArray("items").getJSONObject(0).getJSONObject("quantity").put("amount", "175.25")
        val current = JSONObject().put("entity_id", operation.getString("entity_id")).put("entity_type", operation.getString("entity_type"))
            .put("revision", 4).put("deleted", deleted).put("payload", if (deleted) JSONObject.NULL else payload)
        val result = JSONObject().put("operation_id", operation.getString("operation_id")).put("entity_id", operation.getString("entity_id"))
            .put("status", "conflict").put("code", if (deleted) "entity_id_reserved" else "revision_conflict")
            .put("message", "Synthetic conflict").put("current", if (retained) current else JSONObject.NULL)
            .put("details_retained", retained).put("recovery_mapping", JSONObject.NULL)
        return JSONObject().put("sync_epoch", epoch).put("server_time", "2026-10-21T11:00:00Z")
            .put("results", JSONArray().put(result)).toString().toByteArray()
    }
    private suspend fun conflict(db: CalorieDatabase, lease: OwnerLease, deleted: Boolean = false, retained: Boolean = true): MealPushRequest {
        val push = MealPushStore(db, schema); val request = push.prepare(lease)!!; push.markAttempted(request)
        push.applyAck(push.prepareAck(request, 200, response(request, deleted, retained)))
        return request
    }

    @Test fun latestLocalEditBecomesANewOperationAtServerRevisionAndPreservesFrozenReceipt() = runBlocking<Unit> {
        for (type in listOf("meal", "weight")) {
            val db = memory()
            try {
                val lease = account(db); val id = create(db, lease, type)
                val request = conflict(db, lease); val batch = db.pushDao().batch(request.id)!!
                edit(db, lease, type, id, 88.5)
                val store = SyncConflictStore(db, schema); val op = request.operations.single()
                val ticket = store.open(lease, op.operationId)
                assertTrue(ticket.localPayload.contains("88.5")); assertFalse(ticket.evidence.originalPayload!!.contains("88.5"))
                val nextId = store.choose(ticket, ConflictChoice.LOCAL)!!
                assertNotEquals(op.operationId, nextId)
                val next = db.dao().operation(nextId)!!
                assertEquals(4, next.baseRevision); assertEquals("pending", next.status); assertFalse(next.attempted)
                assertEquals(ticket.localPayload, next.payload); assertEquals(batch, db.pushDao().batch(request.id))
                assertEquals("superseded", db.dao().operation(op.operationId)!!.status)
                val decision = db.conflictDao().decision(op.operationId)!!
                assertEquals(ticket.localPayload, decision.localPayload); assertEquals(ticket.serverPayload, decision.serverPayload)
                assertEquals(nextId, decision.newOperationId); assertEquals("SyncConflictDecision(redacted)", decision.toString())
                refused { store.choose(ticket, ConflictChoice.LOCAL) }
                assertEquals(nextId, MealPushStore(db, schema).prepare(lease)!!.operations.single().operationId)
            } finally { db.close() }
        }
    }

    @Test fun acceptServerReplacesProjectionAndRetainsLatestLocalVersionWithoutFakeAck() = runBlocking<Unit> {
        for (type in listOf("meal", "weight")) {
            val db = memory()
            try {
                val lease = account(db); val id = create(db, lease, type); val request = conflict(db, lease)
                edit(db, lease, type, id, 90.25)
                val store = SyncConflictStore(db, schema); val op = request.operations.single()
                val ticket = store.open(lease, op.operationId); assertNull(store.choose(ticket, ConflictChoice.SERVER))
                assertEquals(ticket.localPayload, db.conflictDao().decision(op.operationId)!!.localPayload)
                assertEquals("superseded", db.dao().operation(op.operationId)!!.status)
                if (type == "weight") {
                    assertEquals(82.375, db.dao().weight(id, lease.storageScope)!!.kg, 0.0)
                    assertEquals(ticket.serverPayload, db.weightSyncDao().state(lease.storageScope, id)!!.wirePayload)
                } else {
                    val meal = db.dao().meal(id, lease.storageScope)!!
                    assertEquals(4, meal.meal.serverRevision); assertEquals("175.25", meal.items.single().amountText)
                    assertEquals(ticket.serverPayload, meal.meal.wirePayload)
                }
                assertNull(MealPushStore(db, schema).prepare(lease))
            } finally { db.close() }
        }
    }

    @Test fun deletedServerIdentityIsNeverResurrectedAndRestoredMealItemsAlsoGetNewIds() = runBlocking<Unit> {
        for (type in listOf("meal", "weight")) {
            val db = memory()
            try {
                val lease = account(db); val id = create(db, lease, type); val request = conflict(db, lease, deleted = true, retained = false)
                val oldItems = if (type == "meal") db.dao().meal(id, lease.storageScope)!!.items.map { it.id } else emptyList()
                val store = SyncConflictStore(db, schema); val op = request.operations.single()
                val ticket = store.open(lease, op.operationId); assertTrue(ticket.restoresAsCopy); assertNull(ticket.serverRevision)
                val newOp = db.dao().operation(store.choose(ticket, ConflictChoice.LOCAL)!!)!!
                assertNotEquals(id, newOp.entityId); assertNull(newOp.baseRevision)
                if (type == "meal") {
                    assertTrue(db.dao().meal(id, lease.storageScope)!!.meal.deleted)
                    val restored = db.dao().meal(newOp.entityId, lease.storageScope)!!
                    assertFalse(restored.meal.deleted); assertTrue(restored.items.none { it.id in oldItems })
                } else {
                    assertTrue(db.dao().weight(id, lease.storageScope)!!.deleted)
                    assertFalse(db.dao().weight(newOp.entityId, lease.storageScope)!!.deleted)
                }
                assertEquals(newOp.entityId, db.conflictDao().decision(op.operationId)!!.replacementId)
                assertFalse(db.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
            } finally { db.close() }
        }
    }

    @Test fun localAndServerDeletionNeedNoNewOperationAndNeverBecomeAnAcknowledgement() = runBlocking<Unit> {
        for(type in listOf("meal","weight")) {
            val db=memory()
            try {
                val lease=account(db);val id=create(db,lease,type);val request=conflict(db,lease,deleted=true,retained=false)
                val repo=DiaryRepository(db,context,lease)
                if(type=="weight")repo.deleteWeight(id) else repo.delete(id)
                val store=SyncConflictStore(db,schema);val op=request.operations.single()
                val ticket=store.open(lease,op.operationId)
                assertTrue(ticket.localDeleted);assertFalse(ticket.restoresAsCopy)
                assertNull(store.choose(ticket,ConflictChoice.LOCAL));assertNull(MealPushStore(db,schema).prepare(lease))
                val decision=db.conflictDao().decision(op.operationId)!!
                assertEquals("LOCAL",decision.choice);assertNull(decision.newOperationId);assertNull(decision.replacementId)
                assertEquals("superseded",db.dao().operation(op.operationId)!!.status)
                assertEquals("complete",db.pushDao().batch(request.id)!!.state)
            }finally{db.close()}
        }
    }

    @Test fun localEditAndAccountRoundTripInvalidateHeldDecisionWithoutChangingQueue() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val id = create(db, lease, "weight"); val request = conflict(db, lease)
            val store = SyncConflictStore(db, schema); val op = request.operations.single()
            val held = store.open(lease, op.operationId); edit(db, lease, "weight", id, 91.125)
            refused { store.choose(held, ConflictChoice.SERVER) }; assertNull(db.conflictDao().decision(op.operationId))
            val latest = store.open(lease, op.operationId); val owners = LocalOwnerStore(db)
            val a = db.ownerDao().byScope(lease.storageScope)!!
            owners.select(owners.ensureGuest().id); val returned = owners.select(a.id)
            refused { store.choose(latest, ConflictChoice.LOCAL) }
            assertEquals(91.125, db.dao().weight(id, returned.storageScope)!!.kg, 0.0)
            assertEquals("conflict", db.dao().operation(op.operationId)!!.status)
            val current = store.open(returned, op.operationId)
            val binding = db.bootstrapDao().binding(returned.storageScope)!!
            db.bootstrapDao().update(binding.copy(requiresRecovery = true, contextRevision = binding.contextRevision + 1))
            refused { store.choose(current, ConflictChoice.LOCAL) }; assertNull(db.conflictDao().decision(op.operationId))
        } finally { db.close() }
    }

    @Test fun expiredDetailsRequireFreshCompleteSnapshotAndRespectItsCurrentRevision() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val id = create(db, lease, "weight"); val request = conflict(db, lease, retained = false)
            val op = request.operations.single(); val store = SyncConflictStore(db, schema)
            val absent = store.open(lease, op.operationId); assertFalse(absent.canChoose)
            refused { store.choose(absent, ConflictChoice.LOCAL) }
            val payload = JSONObject(op.payload).put("weight_kg", "95.625")
            val entity = JSONObject().put("entity_id", id).put("entity_type", "weight").put("revision", 9).put("deleted", false).put("payload", payload)
            snapshot(db, lease, "2026-10-21T12:00:00Z", JSONArray().put(entity))
            val refreshed = store.open(lease, op.operationId)
            assertTrue(refreshed.canChoose); assertEquals(9, refreshed.serverRevision)
            assertEquals("95.625", JSONObject(refreshed.serverPayload!!).getString("weight_kg"))
            assertEquals(9, db.dao().operation(store.choose(refreshed, ConflictChoice.LOCAL)!!)!!.baseRevision)
        } finally { db.close() }
    }

    @Test fun failedDecisionCommitRollsBackProjectionQueueAndEvidenceAndCanRetryAfterRestart() = runBlocking<Unit> {
        val name = "conflict-${uuid()}"; var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            val lease = account(db); val id = create(db, lease, "weight"); val request = conflict(db, lease)
            val op = request.operations.single(); val before = db.dao().weight(id, lease.storageScope)!!
            val store = SyncConflictStore(db, schema); val ticket = store.open(lease, op.operationId)
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_conflict BEFORE INSERT ON sync_conflict_decisions BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
            refused { store.choose(ticket, ConflictChoice.SERVER) }
            assertEquals(before, db.dao().weight(id, lease.storageScope)); assertNull(db.conflictDao().decision(op.operationId))
            assertEquals("conflict", db.dao().operation(op.operationId)!!.status)
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_conflict")
            db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            val restored = SyncConflictStore(db, schema); val current = LocalOwnerStore(db).currentLease()
            restored.choose(restored.open(current, op.operationId), ConflictChoice.SERVER)
            db.close(); db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            assertEquals(82.375, db.dao().weight(id, current.storageScope)!!.kg, 0.0)
            assertEquals("SERVER", db.conflictDao().decision(op.operationId)!!.choice)
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun migrationFrom15PreservesEveryTableValueAndRowidIncludingRefusedAndWaitingOperations() = runBlocking<Unit> {
        val source = memory(); val name = "conflict-migration-${uuid()}"; var target: CalorieDatabase? = null
        try {
            val lease = account(source); val id = create(source, lease, "weight")
            conflict(source, lease); edit(source, lease, "weight", id, 91.125)
            val schema15 = InstrumentationRegistry.getInstrumentation().context.assets
                .open("pl.roseru.kalorie.data.CalorieDatabase/15.json").use { JSONObject(String(it.readBytes())).getJSONObject("database") }
            val entities = schema15.getJSONArray("entities")
            fun dump(query: (String) -> android.database.Cursor) = buildMap<String, List<List<String?>>> {
                for (i in 0 until entities.length()) {
                    val e = entities.getJSONObject(i); val fields = e.getJSONArray("fields")
                    val columns = "rowid," + (0 until fields.length()).joinToString(",") { "`" + fields.getJSONObject(it).getString("columnName") + "`" }
                    put(e.getString("tableName"), query("SELECT $columns FROM `${e.getString("tableName")}` ORDER BY rowid").use { c -> buildList {
                        while (c.moveToNext()) add((0 until c.columnCount).map { column -> when {
                            c.isNull(column) -> null
                            c.getType(column) == android.database.Cursor.FIELD_TYPE_FLOAT -> c.getDouble(column).toString()
                            else -> c.getString(column)
                        } })
                    } })
                }
            }
            val rows = dump { source.openHelper.readableDatabase.query(it) }
            context.getDatabasePath(name).parentFile!!.mkdirs()
            var before = emptyMap<String, List<List<String?>>>()
            android.database.sqlite.SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath(name), null).use { old ->
                old.execSQL("PRAGMA foreign_keys=OFF")
                for (i in 0 until entities.length()) {
                    val e = entities.getJSONObject(i); val table = e.getString("tableName")
                    old.execSQL(e.getString("createSql").replace("\${TABLE_NAME}", table))
                    val indices = e.optJSONArray("indices") ?: JSONArray()
                    for (j in 0 until indices.length()) old.execSQL(indices.getJSONObject(j).getString("createSql").replace("\${TABLE_NAME}", table))
                    val fields = e.getJSONArray("fields")
                    val columns = "rowid," + (0 until fields.length()).joinToString(",") { "`" + fields.getJSONObject(it).getString("columnName") + "`" }
                    val marks = (0..fields.length()).joinToString(",") { "?" }
                    rows.getValue(table).forEach { old.execSQL("INSERT INTO `$table` ($columns) VALUES ($marks)", it.toTypedArray()) }
                }
                old.execSQL("UPDATE weights SET rowid=501 WHERE id=?", arrayOf(id))
                old.execSQL("CREATE TABLE room_master_table (id INTEGER PRIMARY KEY,identity_hash TEXT)")
                old.execSQL("INSERT INTO room_master_table VALUES (42,?)", arrayOf(schema15.getString("identityHash"))); old.version = 15
                before = dump { old.rawQuery(it, null) }
            }
            target = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addMigrations(MIGRATION_15_16, pl.roseru.kalorie.data.MIGRATION_16_17, pl.roseru.kalorie.data.MIGRATION_17_18, pl.roseru.kalorie.data.MIGRATION_18_19).addCallback(DATABASE_GUARDS).build()
            val sql = target!!.openHelper.readableDatabase
            assertEquals(18, sql.version); assertEquals(before, dump { sql.query(it) })
            assertEquals(0L, sql.query("SELECT COUNT(*) FROM sync_conflict_decisions").use { assertTrue(it.moveToFirst()); it.getLong(0) })
            assertFalse(sql.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        } finally { target?.close(); source.close(); context.deleteDatabase(name) }
    }
}
