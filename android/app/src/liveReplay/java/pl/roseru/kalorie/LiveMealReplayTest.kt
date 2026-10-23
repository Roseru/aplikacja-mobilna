package pl.roseru.kalorie

import android.os.Process
import android.util.Log
import androidx.room.withTransaction
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID

/** Opt-in, one selected existing canonical Meal. No credentials, seed SQL or network substitutes. */
@RunWith(AndroidJUnit4::class)
class LiveMealReplayTest {
    private val app get() = ApplicationProvider.getApplicationContext<CalorieApplication>()
    private val args get() = InstrumentationRegistry.getArguments()
    private fun phase(name: String) {
        assumeTrue(args.getString("live_e4_replay") == "true" && args.getString("phase") == name)
        assertTrue("Dedicated synthetic account must be explicitly confirmed", args.getString("synthetic_account") == "true")
    }
    private fun uuid(name: String): String {
        val value = checkNotNull(args.getString(name)) { "Missing trial argument" }
        assertTrue("Invalid trial identifier", runCatching { UUID.fromString(value).toString() == value }.getOrDefault(false))
        return value
    }
    private fun directory(): File = File(app.noBackupFilesDir, "e4-replay/${uuid("trial_id")}").also {
        check(it.isDirectory || it.mkdirs())
    }
    private fun save(name: String, value: JSONObject) {
        val file = File(directory(), name)
        check(file.createNewFile()) { "Existing trial evidence preserved" }
        FileOutputStream(file).use { it.write(value.toString().toByteArray(Charsets.UTF_8)); it.fd.sync() }
    }
    private fun load(name: String): JSONObject {
        val file = File(directory(), name)
        check(file.length() in 1..5_000_000) { "Missing or invalid private trial evidence" }
        return StrictJson.read(file.readBytes())
    }
    private suspend fun lease(): OwnerLease {
        val view = withTimeout(10_000) { app.sessions.view.first { it.binding != null } }
        assertTrue("Trial requires an authenticated account and full snapshot", view.hasSession && view.serverLinked &&
            !view.requiresRecovery && view.binding?.owner?.kind == "account" && view.mealPush?.ready == true)
        val current = checkNotNull(view.binding).lease
        app.database.withTransaction {
            val gate = store().gate(current)
            val applied = app.database.serverDiaryDao().application(gate.run.id)
            assertTrue("The latest full copy must already be applied to this account's local diary",
                applied != null && applied.ownerScope == current.storageScope &&
                    applied.wireContext == CanonicalMealRows.context(gate.binding))
        }
        return current
    }
    private fun store() = MealPushStore(app.database, CanonicalMealRows.schema(app))
    private suspend fun verifySelected(request: MealPushRequest, meal: String, operation: String) {
        val operations = request.batch.json().getJSONArray("operations")
        assertTrue("Trial must contain exactly the selected Meal/create", operations.length() == 1)
        val selected = operations.getJSONObject(0)
        assertTrue("Unexpected operation in selected batch", selected.getString("entity_type") == "meal" &&
            selected.getString("entity_id") == meal && selected.getString("operation_id") == operation &&
            selected.getString("action") == "upsert" && selected.isNull("base_revision"))
        assertTrue("A small selected test payload is required", request.batch.body().size <= 65_536)
    }
    private suspend fun pending(plan: JSONObject, current: OwnerLease) = app.database.withTransaction {
        val row = checkNotNull(app.database.pushDao().batch(plan.getString("batch")))
        val meal = checkNotNull(app.database.dao().meal(plan.getString("meal"), current.storageScope))
        val operation = checkNotNull(app.database.dao().operation(plan.getString("operation")))
        assertTrue("Local ACK already exists or immutable trial data changed", row.ownerScope == current.storageScope &&
            row.requestJson == plan.getString("request") && row.requestHash == plan.getString("hash") &&
            row.wireContext == plan.getString("context") && row.state == "pending" && row.responseJson == null &&
            meal.meal.serverRevision == 0 && operation.status == "pending")
        row
    }
    /** Fingerprints include every protected row, including guests/other accounts and shared catalogue. */
    private suspend fun protected(plan: JSONObject): String = app.database.withTransaction {
        val database=app.database.openHelper.readableDatabase
        val tables=MealReplayFingerprint.tables(database.version)
        val planned=plan.getJSONArray("protected_tables")
        assertTrue("Database schema changed during the selected trial",plan.getInt("room")==database.version &&
            planned.length()==tables.size && tables.indices.all{planned.getString(it)==tables[it]})
        val result = JSONObject()
        for (table in tables) {
            val digest = MessageDigest.getInstance("SHA-256")
            app.database.openHelper.readableDatabase.query("SELECT rowid AS __rowid__, * FROM `$table` ORDER BY rowid").use { cursor ->
                while (cursor.moveToNext()) {
                    val row = org.json.JSONArray()
                    val idColumn = when (table) { "outbox" -> "operationId"; "meals", "sync_push_batches" -> "id"; else -> null }
                    val rowId = idColumn?.let { cursor.getString(cursor.getColumnIndexOrThrow(it)) }
                    for (index in 0 until cursor.columnCount) {
                        val column = cursor.getColumnName(index)
                        val value = if (cursor.isNull(index)) null else cursor.getString(index)
                        row.put(MealReplayFingerprint.normalize(table, rowId, column, value,
                            plan.getString("meal"), plan.getString("operation"), plan.getString("batch")) ?: JSONObject.NULL)
                    }
                    val bytes = row.toString().toByteArray(Charsets.UTF_8)
                    digest.update(java.nio.ByteBuffer.allocate(4).putInt(bytes.size).array()); digest.update(bytes)
                }
            }
            result.put(table, digest.digest().joinToString("") { "%02x".format(it) })
        }
        assertTrue("Foreign key check failed", !app.database.openHelper.readableDatabase.query("PRAGMA foreign_key_check").use { it.moveToFirst() })
        StrictJson.canonical(result)
    }
    /** Preserve the exact hash comparison point without exporting any row content to logs. */
    private suspend fun assertProtected(plan:JSONObject,phaseName:String) {
        require(phaseName in setOf("before-send","after-restart","after-ack"))
        val expected=plan.getString("protected")
        val actual=protected(plan)
        if(actual==expected)return
        val before=StrictJson.read(expected.toByteArray(Charsets.UTF_8))
        val after=StrictJson.read(actual.toByteArray(Charsets.UTF_8))
        val changed=MealReplayFingerprint.tables(plan.getInt("room")).filter{before.getString(it)!=after.getString(it)}
        save("guard-failed-$phaseName.json",JSONObject().put("phase",phaseName).put("room",plan.getInt("room"))
            .put("changed_tables",org.json.JSONArray(changed)).put("expected",before).put("actual",after))
        assertTrue("Protected data changed at $phaseName: ${changed.joinToString(",")}",false)
    }
    private fun marker(name: String, run: String? = null) {
        // Fixed marker names and validated/random trial references only.
        Log.i("O1MealReplayDriver", "phase=$name trial=${uuid("trial_id")} run=${run ?: "none"} utc=${Instant.now()}")
    }

    @Test fun prepareSelectedExistingMealWithoutSending() = runBlocking<Unit> {
        phase("prepare")
        val current = lease(); val meal = uuid("meal_id"); val operation = uuid("operation_id")
        val room=app.database.openHelper.readableDatabase.version
        val tables=MealReplayFingerprint.tables(room)
        val eligible = app.database.pushDao().eligible(current.storageScope)
        assertTrue("Exactly one selected pending canonical operation is required", eligible.size == 1 &&
            eligible.single().entityId == meal && eligible.single().operationId == operation &&
            eligible.single().baseRevision == null && eligible.single().action == "upsert")
        val request = checkNotNull(store().prepare(current))
        verifySelected(request, meal, operation)
        val plan = JSONObject().put("trial", uuid("trial_id")).put("owner", current.storageScope)
            .put("meal", meal).put("operation", operation).put("batch", request.id)
            .put("request", request.row.requestJson).put("hash", request.row.requestHash).put("context", request.row.wireContext)
            .put("room",room).put("protected_tables",org.json.JSONArray(tables))
        val row = pending(plan, current)
        assertTrue("Preparation cannot reuse an attempted HTTP batch", !row.attempted)
        plan.put("protected", protected(plan))
        save("prepared.json", plan); marker("prepared")
    }

    @Test fun holdValidatedAckForExternalC1AndRealProcessKill() = runBlocking<Unit> {
        phase("hold")
        val plan = load("prepared.json"); val current = lease()
        assertTrue("Wrong account for selected trial", plan.getString("owner") == current.storageScope)
        pending(plan, current)
        assertProtected(plan,"before-send")
        val request = store().open(current, plan.getString("batch"))
        verifySelected(request, plan.getString("meal"), plan.getString("operation"))
        val ticket = MealPushObservation.ack.arm(request.id, request.row.requestHash)
        val send = app.sessionScope.async { app.sessions.synchronizeMealsWithoutPull(current) }
        try {
            try { withTimeout(90_000) { ticket.held.await() } } catch (_: TimeoutCancellationException) {
                save("not-run.json", JSONObject().put("reason", "no_validated_ack_hold").put("utc", Instant.now().toString()))
                assumeTrue("NOT_RUN: no validated ACK reached hold", false)
            }
            assertTrue("Response escaped the barrier", !send.isCompleted && ticket.events() == listOf("held"))
            val http = ticket.httpReceipts().lastOrNull()
            assertTrue("Missing real HTTP200/no-store receipt", !ticket.httpOverflow && http?.status == 200 && http.noStore &&
                http.requestId != "missing" && http.requestId != "invalid")
            val row = pending(plan, current)
            assertTrue("Network attempt was not persisted", row.attempted)
            val deadline = checkNotNull(ticket.holdDeadlineNanos)
            assertTrue("Insufficient time for independent C1 and kill", deadline - System.nanoTime() >= 20_000_000_000)
            val heldUtc = Instant.now()
            val deadlineUtc = heldUtc.plusNanos(deadline - System.nanoTime())
            save("held.json", JSONObject().put("run", ticket.run).put("pid", Process.myPid())
                .put("process_start", Process.getStartElapsedRealtime()).put("deadline_utc", deadlineUtc.toString())
                .put("held_utc", heldUtc.toString())
                .put("http_utc", http!!.utc).put("request_id", http.requestId).put("no_local_ack", true))
            marker("held_for_external_kill", ticket.run)
            // This instrumentation invocation is expected to be terminated by the external operator.
            try { withTimeout(46_000) { send.await() } } catch (_: CancellationException) { }
            save("not-run.json", JSONObject().put("reason", "process_not_killed_while_held").put("utc", Instant.now().toString()))
            marker("not_run", ticket.run)
            assumeTrue("NOT_RUN: real external process kill was not observed", false)
        } finally {
            MealPushObservation.ack.disarm(ticket)
            send.cancelAndJoin()
        }
    }

    @Test fun restartResendsIdenticalPersistedBatchAndAppliesOriginalRevision() = runBlocking<Unit> {
        phase("replay")
        val plan = load("prepared.json"); val held = load("held.json"); val current = lease()
        assertTrue("Previous hold expired or completed without real kill", !File(directory(), "not-run.json").exists())
        assertTrue("Client process was not restarted", Process.myPid() != held.getInt("pid") &&
            Process.getStartElapsedRealtime() > held.getLong("process_start"))
        val kill = runCatching { Instant.parse(checkNotNull(args.getString("external_kill_utc"))) }
            .getOrElse { error("Invalid or missing independent kill receipt") }
        assertTrue("External kill must follow the received response and precede hold expiry",
            !kill.isBefore(Instant.parse(held.getString("held_utc"))) && kill.isBefore(Instant.parse(held.getString("deadline_utc"))))
        assertTrue("Wrong account after restart", current.storageScope == plan.getString("owner"))
        pending(plan, current)
        assertProtected(plan,"after-restart")
        val request = store().open(current, plan.getString("batch"))
        assertTrue("Persisted wire changed after restart", request.row.requestJson == plan.getString("request") &&
            request.batch.sha256 == plan.getString("hash"))
        // Observe but release the validated replay immediately; the existing controller persists ACK.
        val ticket = MealPushObservation.ack.arm(request.id, request.row.requestHash)
        val send = app.sessionScope.async { app.sessions.synchronizeMealsWithoutPull(current) }
        try {
            withTimeout(90_000) { ticket.held.await() }
            pending(plan, current)
            val http = ticket.httpReceipts().lastOrNull()
            assertTrue("Replay lacks a fresh successful HTTP receipt", !ticket.httpOverflow && http?.status == 200 && http.noStore &&
                http.requestId != held.getString("request_id") && http.requestId != "missing" && http.requestId != "invalid")
            ticket.release.complete(Unit)
            withTimeout(90_000) { send.await() }
            val row = checkNotNull(app.database.pushDao().batch(request.id))
            assertTrue("Frozen envelope changed while accepting replay", row.requestJson == plan.getString("request") &&
                row.requestHash == plan.getString("hash") && row.wireContext == plan.getString("context"))
            val answer = StrictJson.read(checkNotNull(row.responseJson).toByteArray(Charsets.UTF_8))
            val results = answer.getJSONArray("results"); val result = results.getJSONObject(0)
            assertTrue("Replay did not preserve the original operation and revision", row.state == "complete" && row.attempted && results.length() == 1 &&
                result.getString("operation_id") == plan.getString("operation") && result.getString("entity_id") == plan.getString("meal") &&
                result.getString("status") == "already_applied" && result.getInt("revision") == 1 && result.isNull("recovery_mapping"))
            assertTrue("Local revision/queue were not atomically confirmed", app.database.dao().meal(plan.getString("meal"), current.storageScope)?.meal?.serverRevision == 1 &&
                app.database.dao().operation(plan.getString("operation"))?.status == "acked")
            assertProtected(plan,"after-ack")
            save("replayed.json", JSONObject().put("run", ticket.run).put("request_id", http!!.requestId)
                .put("utc", Instant.now().toString()).put("local_observations", "PASS")
                .put("following_pull", "NOT_RUN_SEPARATE_OPERATION").put("server_observations", "REQUIRED_SEPARATELY"))
            marker("local_replay_pass", ticket.run)
        } finally { MealPushObservation.ack.disarm(ticket); send.cancelAndJoin() }
    }
}
