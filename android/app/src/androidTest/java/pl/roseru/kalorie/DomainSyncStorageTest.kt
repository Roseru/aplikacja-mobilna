package pl.roseru.kalorie

import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import java.time.LocalDate
import java.util.UUID

/** Actual Room and public repository, with isolated synthetic server decisions. */
class DomainSyncStorageTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val schema get() = CanonicalMealRows.schema(context)
    private val epoch = "55555555-5555-4555-8555-555555555555"
    private fun uuid() = UUID.randomUUID().toString()
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java)
        .addCallback(DATABASE_GUARDS).build()
    private suspend fun account(db: CalorieDatabase): OwnerLease {
        val owners = LocalOwnerStore(db); owners.ensureGuest()
        val lease = owners.select(owners.registerIdentity("https://fixture.example/realms/domains", uuid()).id)
        val bootstrap = AccountBootstrapStore(db)
        bootstrap.apply(bootstrap.begin(lease), BootstrapResponse(uuid(), epoch, 1, "2026-10-23T12:00:00Z"))
        val page = JSONObject().put("sync_epoch", epoch).put("mode", "snapshot")
            .put("snapshot_token", "synthetic-snapshot").put("page_token", JSONObject.NULL)
            .put("checkpoint", "synthetic-checkpoint").put("server_time", "2026-10-23T12:00:00Z")
            .put("goal_timeline_revision", 0).put("entities", JSONArray())
            .put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray())
        val snapshots = ServerSnapshotStore(db, SnapshotProtocol(schema))
        assertNull(snapshots.apply(snapshots.begin(lease), page.toString().toByteArray()))
        return lease
    }
    private fun draft(name: String = "Synthetic private ration", kcal: Double = 100.125) =
        CustomProductDraft(name, kcal, null, 0.0, 12.5, "Synthetic label; not official")
    private suspend fun six(db: CalorieDatabase, lease: OwnerLease): Pair<String, String> {
        val repo = DiaryRepository(db, context, lease)
        repo.setProfile("Synthetic", 180.125, ActivityClass.LINE, DietAim.MAINTAIN)
        repo.setGoal(2500.125, null, 0.0, 200.5)
        val meal = uuid(); val product = uuid()
        repo.addCustomProduct(draft(), 100.0, MealType.LUNCH, LocalDate.now(), meal, product)
        repo.addWeight(80.125, LocalDate.now(), uuid())
        repo.setDayComplete(LocalDate.now(), true)
        return meal to product
    }
    private fun reply(request: MealPushRequest, status: String = "accepted"): ByteArray {
        val operations = request.batch.json().getJSONArray("operations"); val results = JSONArray()
        for (i in 0 until operations.length()) {
            val op = operations.getJSONObject(i)
            val item = JSONObject().put("operation_id", op.getString("operation_id"))
                .put("entity_id", op.getString("entity_id")).put("status", status)
                .put("recovery_mapping", JSONObject.NULL)
            if (status in setOf("accepted", "already_applied")) {
                item.put("revision", if (op.isNull("base_revision")) 1 else op.getInt("base_revision") + 1)
            } else item.put("code", if (status == "conflict") "revision_conflict" else "invalid_payload")
                .put("message", "Synthetic refusal").put("current", JSONObject.NULL).put("details_retained", true)
            results.put(item)
        }
        return JSONObject().put("sync_epoch", epoch).put("server_time", "2026-10-23T12:00:00Z")
            .put("results", results).toString().toByteArray()
    }
    private suspend fun rejected(action: suspend () -> Unit) {
        var refused = false
        try { action() } catch (e: CancellationException) { throw e } catch (_: Exception) { refused = true }
        assertTrue("Expected refusal without private diagnostics", refused)
    }
    private suspend fun send(store: MealPushStore, lease: OwnerLease, status: String = "accepted"): MealPushRequest {
        val request = store.prepare(lease)!!; store.markAttempted(request)
        store.applyAck(store.prepareAck(request, 200, reply(request, status)))
        return request
    }

    private fun snapshotRows(request: MealPushRequest): List<JSONObject> = request.operations.map { operation ->
        JSONObject().put("entity_type", operation.entityType).put("entity_id", operation.entityId)
            .put("revision", (operation.baseRevision ?: 0) + 1).put("deleted", operation.action == "delete")
            .put("payload", if (operation.action == "delete") JSONObject.NULL else JSONObject(operation.payload))
    }
    private suspend fun archive(db: CalorieDatabase, lease: OwnerLease, rows: List<JSONObject>,
        time: String = "2026-10-23T13:00:00Z"): String {
        val snapshots = ServerSnapshotStore(db, SnapshotProtocol(schema)); val request = snapshots.begin(lease)
        val page = JSONObject().put("sync_epoch", epoch).put("mode", "snapshot")
            .put("snapshot_token", "synthetic-${uuid()}").put("page_token", JSONObject.NULL)
            .put("checkpoint", "synthetic-${uuid()}").put("server_time", time)
            .put("goal_timeline_revision", 1).put("entities", JSONArray(rows))
            .put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray())
        assertNull(snapshots.apply(request, page.toString().toByteArray()))
        return request.runId
    }
    /** Independent SQL oracle: every persisted cell and rowid, without domain/ACK helpers. */
    private fun persistedCells(db: CalorieDatabase): Map<String, List<List<String?>>> {
        val sql = db.openHelper.readableDatabase
        val tables = sql.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            .use { cursor -> buildList { while (cursor.moveToNext()) add(cursor.getString(0)) } }
        return tables.associateWith { table ->
            sql.query("SELECT rowid,* FROM `${table.replace("`", "``")}` ORDER BY rowid").use { cursor ->
                buildList { while (cursor.moveToNext()) add((0 until cursor.columnCount).map { column ->
                    when (cursor.getType(column)) {
                        android.database.Cursor.FIELD_TYPE_NULL -> null
                        android.database.Cursor.FIELD_TYPE_FLOAT -> "real:" + cursor.getDouble(column).toString()
                        android.database.Cursor.FIELD_TYPE_BLOB -> "blob:" + cursor.getBlob(column).joinToString("") { "%02x".format(it) }
                        else -> cursor.getString(column)
                    }
                }) }
            }
        }
    }
    @Test fun mixedSixDomainBatchAcceptsAndReplaysAlreadyAppliedWithoutDuplicatingRevisions() = runBlocking<Unit> {
        for (status in listOf("accepted", "already_applied")) {
            val db = memory()
            try {
                val lease = account(db); val (meal, _) = six(db, lease); val store = MealPushStore(db, schema)
                val request = store.prepare(lease)!!; store.markAttempted(request)
                assertEquals(setOf("meal", "weight", "profile", "goal", "diary_day", "product_draft"), request.operations.map { it.entityType }.toSet())
                assertEquals(6, request.operations.size)
                if (status == "accepted") context.cacheDir.resolve("o2-six-domain-request.json").writeBytes(request.batch.body())
                assertTrue(request.operations.indexOfFirst { it.entityType == "diary_day" } < request.operations.indexOfFirst { it.entityType == "meal" })
                val prepared = store.prepareAck(request, 200, reply(request, status))
                assertEquals(6, store.applyAck(prepared).acknowledged)
                assertTrue(store.applyAck(prepared).replay)
                assertTrue(store.applyAck(store.prepareAck(request, 200, reply(request, "already_applied"))).replay)
                request.operations.filter { it.entityType in PrivateDomainsWire.types }.forEach {
                    assertEquals(1, db.domainSyncDao().state(lease.storageScope, it.entityType, it.entityId)!!.serverRevision)
                }
                assertEquals(1, db.dao().meal(meal, lease.storageScope)!!.meal.serverRevision)
                assertEquals(1, db.domainSyncDao().timeline(lease.storageScope)!!.revision)
                assertTrue(request.operations.all { db.dao().operation(it.operationId)!!.status == "acked" })
                assertTrue(store.status(lease).domains.values.all { it == DomainPushStatus(0, 0, 0) })
                assertNull(store.prepare(lease))
            } finally { db.close() }
        }
    }

    @Test fun laterProfileDayAndProductEditsSurviveRestartWhileFrozenEnvelopeAndHashRemainExact() = runBlocking<Unit> {
        val name = "domains-restart-${uuid()}"
        var db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
        try {
            val lease = account(db); val (_, product) = six(db, lease)
            val store = MealPushStore(db, schema); val frozen = store.prepare(lease)!!; store.markAttempted(frozen)
            val body = frozen.batch.body(); val hash = frozen.batch.sha256; val saved = frozen.operations.toList()
            val repo = DiaryRepository(db, context, lease)
            repo.setProfile("Later name", 181.5, ActivityClass.COMMANDO, DietAim.REDUCE)
            repo.setDayComplete(LocalDate.now(), false)
            repo.editCustomProduct(product, draft("Later product", 321.5))
            assertArrayEquals(body, store.open(lease, frozen.id).batch.body())
            saved.forEach { assertEquals(it, db.dao().operation(it.operationId)) }
            assertEquals(3, db.domainSyncDao().unsettled(lease.storageScope).count { it.status == "waiting_revision" })
            db.close()
            db = Room.databaseBuilder(context, CalorieDatabase::class.java, name).addCallback(DATABASE_GUARDS).build()
            val current = LocalOwnerStore(db).currentLease(); val reopenedStore = MealPushStore(db, schema)
            val request = reopenedStore.open(current, frozen.id)
            assertArrayEquals(body, request.batch.body()); assertEquals(hash, request.batch.sha256)
            reopenedStore.applyAck(reopenedStore.prepareAck(request, 200, reply(request, "already_applied")))
            assertEquals("Later name", db.dao().currentProfile(current.storageScope)!!.nickname)
            assertFalse(db.dao().currentDiaryDay(current.storageScope, LocalDate.now().toString())!!.declaredComplete)
            assertEquals("Later product", db.dao().product(product, current.storageScope)!!.name)
            val next = reopenedStore.prepare(current)!!
            assertEquals(setOf("profile", "diary_day", "product_draft"), next.operations.map { it.entityType }.toSet())
            assertTrue(next.operations.all { it.baseRevision == 1 && it.operationId !in saved.map { row -> row.operationId } })
            assertEquals("321.5", JSONObject(next.operations.single { it.entityType == "product_draft" }.payload).getJSONObject("nutrition_per_100").getString("energy_kcal"))
            assertArrayEquals(body, request.batch.body()); assertEquals(hash, request.batch.sha256)
            reopenedStore.markAttempted(next); reopenedStore.applyAck(reopenedStore.prepareAck(next, 200, reply(next)))
            assertNull(reopenedStore.prepare(current))
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun invalidLastAckAndDatabaseFailureNeverAcknowledgeEarlierDomains() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); six(db, lease); val store = MealPushStore(db, schema)
            val request = store.prepare(lease)!!; store.markAttempted(request)
            val before = persistedCells(db)
            val wrongIdentity = JSONObject(String(reply(request)))
            assertEquals("accepted", wrongIdentity.getJSONArray("results").getJSONObject(0).getString("status"))
            val originalLast = request.operations.last().operationId
            val unrelatedOperation = uuid()
            assertNotEquals(originalLast, unrelatedOperation)
            wrongIdentity.getJSONArray("results").getJSONObject(5).put("operation_id", unrelatedOperation)
            rejected { store.prepareAck(request, 200, wrongIdentity.toString().toByteArray()) }
            assertEquals("A wrong final operation_id must leave every persisted cell unchanged", before, persistedCells(db))
            val bad = JSONObject(String(reply(request)))
            bad.getJSONArray("results").getJSONObject(5).put("revision", 2)
            rejected { store.prepareAck(request, 200, bad.toString().toByteArray()) }
            assertEquals("A wrong final revision must leave every persisted cell unchanged", before, persistedCells(db))
            assertTrue(request.operations.all { db.dao().operation(it.operationId)!!.status == "pending" })
            assertNull(db.pushDao().batch(request.id)!!.responseJson)
            val prepared = store.prepareAck(request, 200, reply(request))
            db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_domain_ack BEFORE INSERT ON canonical_domains WHEN NEW.entityType='diary_day' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
            rejected { store.applyAck(prepared) }
            assertTrue(request.operations.all { db.dao().operation(it.operationId)!!.status == "pending" })
            request.operations.filter { it.entityType in PrivateDomainsWire.types }.forEach {
                assertEquals(0, db.domainSyncDao().state(lease.storageScope, it.entityType, it.entityId)!!.serverRevision)
            }
            assertEquals(0, db.domainSyncDao().timeline(lease.storageScope)!!.revision)
            assertNull(db.pushDao().batch(request.id)!!.responseJson)
            db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_domain_ack")
            assertEquals(6, store.applyAck(prepared).acknowledged)
        } finally { db.close() }
    }

    @Test fun naturalDayConflictRetainsProposedAndTombstonedCanonicalUuidsWithoutRebinding() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); six(db, lease); val store = MealPushStore(db, schema)
            val request = store.prepare(lease)!!; store.markAttempted(request)
            val index = request.operations.indexOfFirst { it.entityType == "diary_day" }
            assertTrue(index >= 0)
            val proposed = request.operations[index]; val canonicalId = uuid()
            assertNotEquals(proposed.entityId, canonicalId)
            val state = db.domainSyncDao().state(lease.storageScope, "diary_day", proposed.entityId)!!
            val day = db.dao().currentDiaryDay(lease.storageScope, LocalDate.now().toString())!!
            val body = JSONObject(String(reply(request)))
            val conflict = JSONObject().put("operation_id", proposed.operationId).put("entity_id", proposed.entityId)
                .put("status", "conflict").put("code", "revision_conflict").put("message", "Synthetic natural-key conflict")
                .put("current", JSONObject().put("entity_type", "diary_day").put("entity_id", canonicalId)
                    .put("revision", 4).put("deleted", true).put("payload", JSONObject.NULL))
                .put("recovery_mapping", JSONObject.NULL).put("details_retained", true)
            body.getJSONArray("results").put(index, conflict)
            val result = store.applyAck(store.prepareAck(request, 200, body.toString().toByteArray()))
            assertEquals(5, result.acknowledged); assertEquals(1, result.refused)
            assertEquals(state, db.domainSyncDao().state(lease.storageScope, "diary_day", proposed.entityId))
            assertEquals(day, db.dao().currentDiaryDay(lease.storageScope, LocalDate.now().toString()))
            assertNull(db.domainSyncDao().state(lease.storageScope, "diary_day", canonicalId))
            assertEquals("conflict", db.dao().operation(proposed.operationId)!!.status)
            val saved = JSONObject(db.pushDao().batch(request.id)!!.responseJson!!).getJSONArray("results").getJSONObject(index)
            assertEquals(proposed.entityId, saved.getString("entity_id"))
            assertEquals(canonicalId, saved.getJSONObject("current").getString("entity_id"))
            assertTrue(saved.getJSONObject("current").getBoolean("deleted"))
            assertEquals(4, saved.getJSONObject("current").getInt("revision"))
            assertEquals(DomainPushStatus(0, 0, 1), store.status(lease).domains.getValue("diary_day"))
            assertNull(store.prepare(lease))
        } finally { db.close() }
    }
    @Test fun goalTimelineVersionsWaitForConfirmedPredecessorAndKeepOriginalAudit() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val repo = DiaryRepository(db, context, lease); val store = MealPushStore(db, schema)
            val first = uuid(); val second = uuid(); val third = uuid()
            repo.setGoal(2500.0, null, null, null, first)
            repo.setGoal(2400.0, 100.0, null, null, second)
            repo.setGoal(2300.0, null, 50.0, null, third)
            val originals = db.domainSyncDao().unsettled(lease.storageScope)
            assertEquals(listOf("pending", "waiting_timeline", "waiting_timeline"), originals.map { it.status })
            assertEquals(listOf(0, 1, 2), originals.map { JSONObject(it.payload).getInt("timeline_base_revision") })
            assertEquals(first, JSONObject(originals[1].payload).getString("correction_of"))
            assertEquals(second, JSONObject(originals[2].payload).getString("correction_of"))
            for ((index, id) in listOf(first, second, third).withIndex()) {
                val request = send(store, lease)
                assertEquals(listOf(id), request.operations.map { it.entityId })
                assertEquals(index + 1, db.domainSyncDao().timeline(lease.storageScope)!!.revision)
            }
            originals.forEach { assertEquals(it.payload, db.dao().operation(it.operationId)!!.payload) }
            assertNull(store.prepare(lease))
        } finally { db.close() }
    }

    @Test fun refusalAndConflictKeepDependentGoalAndReplacementProfileBlocked() = runBlocking<Unit> {
        for (status in listOf("rejected", "conflict")) {
            val db = memory()
            try {
                val lease = account(db); val repo = DiaryRepository(db, context, lease); val store = MealPushStore(db, schema)
                repo.setGoal(2500.0, null, null, null)
                repo.setGoal(2400.0, null, null, null)
                send(store, lease, status)
                assertEquals(listOf(status, "waiting_timeline"), db.domainSyncDao().unsettled(lease.storageScope).map { it.status })
                assertEquals(0, db.domainSyncDao().timeline(lease.storageScope)!!.revision)
                assertNull(store.prepare(lease))
                repo.setProfile("Before", 180.0, ActivityClass.LINE, DietAim.MAINTAIN)
                send(store, lease)
                repo.deleteProfile(); repo.setProfile("After", 181.0, ActivityClass.LINE, DietAim.MAINTAIN)
                val request = send(store, lease, status)
                assertEquals("delete", request.operations.single().action)
                assertTrue(db.domainSyncDao().unsettled(lease.storageScope).any { it.entityType == "profile" && it.status == "waiting_profile" })
                assertNull(store.prepare(lease))
                assertEquals("After", db.dao().currentProfile(lease.storageScope)!!.nickname)
            } finally { db.close() }
        }
    }

    @Test fun acknowledgedProfileDeleteReleasesFreshIdentityAndCannotDeleteReplacement() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val repo = DiaryRepository(db, context, lease); val store = MealPushStore(db, schema)
            repo.setProfile("Before", 180.0, ActivityClass.LINE, DietAim.MAINTAIN); val initial = send(store, lease)
            val oldId = initial.operations.single().entityId
            repo.deleteProfile(); repo.setProfile("After", 181.0, ActivityClass.COMMANDO, DietAim.REDUCE)
            val replacement = db.dao().currentProfile(lease.storageScope)!!
            assertNotEquals(oldId, replacement.id)
            val deleted = send(store, lease)
            assertEquals(oldId, deleted.operations.single().entityId)
            assertTrue(db.domainSyncDao().state(lease.storageScope, "profile", oldId)!!.deleted)
            assertEquals(replacement, db.dao().currentProfile(lease.storageScope))
            val created = send(store, lease)
            assertEquals(replacement.id, created.operations.single().entityId)
            assertNull(created.operations.single().baseRevision)
            assertTrue(store.applyAck(store.prepareAck(deleted, 200, reply(deleted, "already_applied"))).replay)
            assertEquals(replacement, db.dao().currentProfile(lease.storageScope))
            assertNull(store.prepare(lease))
        } finally { db.close() }
    }

    @Test fun privateProductDeletionDuringAttemptKeepsMealSnapshotAndWaitsForRevision() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val repo = DiaryRepository(db, context, lease)
            val meal = uuid(); val product = uuid()
            repo.addCustomProduct(draft(), 75.125, MealType.SNACK, LocalDate.now(), meal, product)
            val snapshot = db.dao().meal(meal, lease.storageScope)!!.items.single().wirePayload
            assertNotNull(snapshot)
            val store = MealPushStore(db, schema); val request = store.prepare(lease)!!; store.markAttempted(request)
            val hash = request.batch.sha256
            repo.deleteCustomProduct(product)
            assertNull(db.dao().product(product, lease.storageScope))
            assertEquals(snapshot, db.dao().meal(meal, lease.storageScope)!!.items.single().wirePayload)
            val waiting = db.domainSyncDao().operations(lease.storageScope, "product_draft", product).last()
            assertEquals("waiting_revision", waiting.status); assertEquals("delete", waiting.action)
            store.applyAck(store.prepareAck(request, 200, reply(request, "already_applied")))
            val deletion = send(store, lease)
            assertEquals(listOf("product_draft"), deletion.operations.map { it.entityType })
            assertEquals("delete", deletion.operations.single().action)
            assertEquals(1, deletion.operations.single().baseRevision)
            assertEquals(2, db.domainSyncDao().state(lease.storageScope, "product_draft", product)!!.serverRevision)
            assertTrue(db.domainSyncDao().state(lease.storageScope, "product_draft", product)!!.deleted)
            assertEquals(snapshot, db.dao().meal(meal, lease.storageScope)!!.items.single().wirePayload)
            assertEquals(hash, request.batch.sha256); assertNull(store.prepare(lease))
        } finally { db.close() }
    }
    @Test fun firstPullTombstonesAfterLocalCreateAckRetireProfileAndResetDayWithoutPriorServerRecord() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); six(db, lease); val push = MealPushStore(db, schema)
            val accepted = send(push, lease)
            assertTrue(db.serverDiaryDao().records(lease.storageScope).isEmpty())
            val profile = accepted.operations.single { it.entityType == "profile" }
            val day = accepted.operations.single { it.entityType == "diary_day" }
            assertEquals(1, db.domainSyncDao().state(lease.storageScope, "profile", profile.entityId)!!.serverRevision)
            assertEquals(1, db.domainSyncDao().state(lease.storageScope, "diary_day", day.entityId)!!.serverRevision)
            assertNotNull(db.dao().currentProfile(lease.storageScope))
            assertTrue(db.dao().currentDiaryDay(lease.storageScope, LocalDate.now().toString())!!.declaredComplete)
            val outbox = accepted.operations.map { db.dao().operation(it.operationId)!! }
            val rows = snapshotRows(accepted)
            rows.filter { it.getString("entity_type") in setOf("profile", "diary_day") }.forEach {
                it.put("revision", 2).put("deleted", true).put("payload", JSONObject.NULL)
            }
            val run = archive(db, lease, rows)
            val applied = ServerDiaryStore(db, schema).apply(lease, run)
            assertEquals(6, applied.included); assertEquals(0, applied.held)
            assertNull(db.dao().currentProfile(lease.storageScope))
            val reset = db.dao().currentDiaryDay(lease.storageScope, LocalDate.now().toString())!!
            assertEquals(day.entityId, reset.id); assertFalse(reset.declaredComplete)
            for (operation in listOf(profile, day)) {
                val state = db.domainSyncDao().state(lease.storageScope, operation.entityType, operation.entityId)!!
                assertTrue(state.deleted); assertEquals(2, state.serverRevision)
                val record = db.serverDiaryDao().records(lease.storageScope).single { it.entityId == operation.entityId }
                assertEquals(operation.entityId, record.localId); assertEquals("applied", record.disposition)
                assertTrue(record.deleted); assertEquals(2, record.knownRevision)
            }
            assertEquals(outbox, accepted.operations.map { db.dao().operation(it.operationId)!! })
            assertEquals(applied, ServerDiaryStore(db, schema).apply(lease, run))
            assertNull(push.prepare(lease))
        } finally { db.close() }
    }

    @Test fun firstPullRetiredProfileTombstoneCannotRemoveAcknowledgedReplacementProfile() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); six(db, lease); val push = MealPushStore(db, schema)
            val initial = send(push, lease); val old = initial.operations.single { it.entityType == "profile" }
            val repo = DiaryRepository(db, context, lease)
            repo.deleteProfile(); val deletion = send(push, lease)
            repo.setProfile("Acknowledged replacement", 182.5, ActivityClass.COMMANDO, DietAim.MAINTAIN)
            val creation = send(push, lease); val fresh = creation.operations.single()
            assertNotEquals(old.entityId, fresh.entityId)
            assertTrue(db.serverDiaryDao().records(lease.storageScope).isEmpty())
            val replacement = db.dao().currentProfile(lease.storageScope)!!
            val rows = snapshotRows(initial).filter { it.getString("entity_type") != "profile" } +
                snapshotRows(deletion) + snapshotRows(creation)
            assertTrue(rows.single { it.getString("entity_id") == old.entityId }.getBoolean("deleted"))
            for (time in listOf("2026-10-23T13:00:00Z", "2026-10-23T14:00:00Z")) {
                val run = archive(db, lease, rows, time)
                val result = ServerDiaryStore(db, schema).apply(lease, run)
                assertEquals(7, result.included); assertEquals(0, result.held)
                assertEquals(replacement, db.dao().currentProfile(lease.storageScope))
                assertNull(db.serverDiaryDao().profile(old.entityId))
                assertTrue(db.domainSyncDao().state(lease.storageScope, "profile", old.entityId)!!.deleted)
                assertFalse(db.domainSyncDao().state(lease.storageScope, "profile", fresh.entityId)!!.deleted)
                assertEquals("applied", db.serverDiaryDao().records(lease.storageScope).single { it.entityId == old.entityId }.disposition)
            }
            assertNull(push.prepare(lease))
        } finally { db.close() }
    }
    @Test fun profileUiAimChangeCreatesExactGoalVersionButNicknameAndHeightAloneDoNot() = runBlocking<Unit> {
        val db = memory()
        try {
            val lease = account(db); val repo = DiaryRepository(db, context, lease); val push = MealPushStore(db, schema)
            repo.setProfile("Initial profile", 180.125, ActivityClass.LINE, DietAim.MAINTAIN)
            repo.setGoal(2500.125, null, 0.0, 200.5)
            val initial = send(push, lease)
            assertEquals(setOf("profile", "goal"), initial.operations.map { it.entityType }.toSet())
            val originalOperation = initial.operations.single { it.entityType == "goal" }
            val originalWire = JSONObject(originalOperation.payload)
            assertEquals("maintain", originalWire.getString("goal_type"))
            assertEquals("2500.125", originalWire.getString("energy_kcal"))
            assertTrue(originalWire.isNull("protein_g"))
            assertEquals("0", originalWire.getString("fat_g"))
            assertEquals("200.5", originalWire.getString("carbs_g"))
            val originalGoal = db.dao().goalById(lease.storageScope, originalOperation.entityId)!!
            assertEquals(1, db.domainSyncDao().timeline(lease.storageScope)!!.revision)
            assertEquals(listOf(originalGoal), db.serverDiaryDao().allGoals(lease.storageScope))

            repo.setProfileAndActivityGoal("Initial profile", 180.125, ActivityClass.LINE, DietAim.REDUCE)
            val pending = db.domainSyncDao().unsettled(lease.storageScope)
            val next = pending.single { it.entityType == "goal" }
            val nextWire = JSONObject(next.payload)
            assertNotEquals(originalOperation.entityId, next.entityId)
            assertEquals("reduce", nextWire.getString("goal_type"))
            assertEquals("2500.125", nextWire.getString("energy_kcal"))
            assertTrue(nextWire.isNull("protein_g"))
            assertEquals("0", nextWire.getString("fat_g"))
            assertEquals("200.5", nextWire.getString("carbs_g"))
            assertEquals("line", nextWire.getString("activity_class"))
            assertEquals(1, nextWire.getInt("timeline_base_revision"))
            assertEquals("history_correction", nextWire.getString("reason"))
            assertEquals(originalOperation.entityId, nextWire.getString("correction_of"))
            for (field in listOf("energy_kcal", "protein_g", "fat_g", "carbs_g")) {
                assertEquals("Aim change must preserve the exact nutrient value, including null: $field",
                    originalWire.get(field), nextWire.get(field))
            }
            val corrected = db.dao().goalById(lease.storageScope, next.entityId)!!
            assertEquals(originalGoal.kcal, corrected.kcal, 0.0)
            assertEquals(originalGoal.protein, corrected.protein)
            assertEquals(originalGoal.fat, corrected.fat)
            assertEquals(originalGoal.carbs, corrected.carbs)
            assertEquals(originalGoal, db.dao().goalById(lease.storageScope, originalGoal.id))
            val changed = send(push, lease)
            assertEquals(setOf("profile", "goal"), changed.operations.map { it.entityType }.toSet())
            assertEquals(next.operationId, changed.operations.single { it.entityType == "goal" }.operationId)
            assertEquals(2, db.domainSyncDao().timeline(lease.storageScope)!!.revision)

            val history = db.serverDiaryDao().allGoals(lease.storageScope)
            repo.setProfileAndActivityGoal("Renamed profile", 181.5, ActivityClass.LINE, DietAim.REDUCE)
            assertEquals(history, db.serverDiaryDao().allGoals(lease.storageScope))
            assertEquals(originalGoal, db.dao().goalById(lease.storageScope, originalGoal.id))
            assertEquals(corrected, db.dao().goalById(lease.storageScope, corrected.id))
            assertEquals(listOf("profile"), db.domainSyncDao().unsettled(lease.storageScope).map { it.entityType })
            val renamed = send(push, lease)
            assertEquals(listOf("profile"), renamed.operations.map { it.entityType })
            assertEquals("Renamed profile", db.dao().currentProfile(lease.storageScope)!!.nickname)
            assertEquals(181.5, db.dao().currentProfile(lease.storageScope)!!.heightCm!!, 0.0)
            assertEquals(history, db.serverDiaryDao().allGoals(lease.storageScope))
            assertEquals(2, db.domainSyncDao().timeline(lease.storageScope)!!.revision)
            assertNull(push.prepare(lease))
        } finally { db.close() }
    }
    @Test fun accountAToBToARejectsStaleAckAndPreservesBothOwners() = runBlocking<Unit> {
        val db = memory()
        try {
            val a = account(db); six(db, a); val store = MealPushStore(db, schema)
            val request = store.prepare(a)!!; store.markAttempted(request)
            val prepared = store.prepareAck(request, 200, reply(request))
            val b = account(db); val repoB = DiaryRepository(db, context, b)
            repoB.setProfile("Account B", 175.0, ActivityClass.GARRISON, DietAim.MAINTAIN)
            val bQueue = db.domainSyncDao().unsettled(b.storageScope)
            rejected { store.applyAck(prepared) }
            val aOwner = checkNotNull(db.ownerDao().byScope(a.storageScope))
            val returned = LocalOwnerStore(db).select(aOwner.id)
            assertNotEquals(a.generation, returned.generation)
            rejected { store.applyAck(prepared) }
            assertTrue(request.operations.all { db.dao().operation(it.operationId)!!.status == "pending" })
            val current = store.open(returned, request.id)
            assertArrayEquals(request.batch.body(), current.batch.body())
            store.applyAck(store.prepareAck(current, 200, reply(current, "already_applied")))
            assertEquals(bQueue, db.domainSyncDao().unsettled(b.storageScope))
            assertEquals("Account B", db.dao().currentProfile(b.storageScope)!!.nickname)
        } finally { db.close() }
    }
}
