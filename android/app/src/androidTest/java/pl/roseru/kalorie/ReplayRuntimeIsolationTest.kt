package pl.roseru.kalorie

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.session.MealReplayFingerprint
import pl.roseru.kalorie.sync.ReplayRuntimeIsolation
import pl.roseru.kalorie.sync.SyncRuntimeEntry
import java.io.File
import java.util.UUID

/** Tests isolated admission/storage only; these do not qualify WorkManager, OIDC or live E4. */
@RunWith(AndroidJUnit4::class)
class ReplayRuntimeIsolationTest {
    private val context get() = ApplicationProvider.getApplicationContext<Context>()
    private suspend fun fixture(block: suspend (File, CoroutineScope) -> Unit) {
        val directory = File(context.cacheDir, "replay-isolation-${UUID.randomUUID()}")
        check(directory.mkdir())
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        try { block(File(directory, "fence.json"), scope) }
        finally { scope.cancel(); directory.deleteRecursively() }
    }

    @Test fun durablePausePrecedesCancellationAndWaitsForRuntimeFinallyBlocks() = runBlocking {
        fixture { file, scope ->
            val gate = ReplayRuntimeIsolation(file, scope)
            val trial = UUID.randomUUID().toString()
            assertThrows(IllegalStateException::class.java) { gate.requireHeld(trial, "owner", "epoch-1") }
            // The real driver cannot claim support while O2 has not connected the runtime contract.
            val refused = runCatching { gate.arm(trial, "owner", "epoch-1") }
            assertTrue(refused.exceptionOrNull() is IllegalStateException)
            assertFalse(file.exists())
            gate.attach(1)
            val started = CompletableDeferred<Unit>(); val finalizing = CompletableDeferred<Unit>()
            val finish = CompletableDeferred<Unit>()
            val worker = scope.async {
                gate.run {
                    started.complete(Unit)
                    try { awaitCancellation() }
                    finally { withContext(NonCancellable) { finalizing.complete(Unit); finish.await() } }
                }
            }
            withTimeout(5_000) { started.await() }
            val arming = scope.async { gate.arm(trial, "owner", "epoch-1") }
            try {
                withTimeout(5_000) { finalizing.await() }
                assertFalse(arming.isCompleted)
                var writes = 0
                assertEquals(SyncRuntimeEntry.Paused, gate.run { writes++ })
                val restarted = ReplayRuntimeIsolation(file, scope).also { it.attach(1) }
                assertEquals(SyncRuntimeEntry.Paused, restarted.run { writes++ })
                assertThrows(IllegalStateException::class.java) { restarted.requireHeld(trial, "owner", "epoch-1") }
                assertEquals(0, writes)
                finish.complete(Unit)
                withTimeout(5_000) { arming.await() }
                assertTrue(worker.isCancelled)
                gate.requireHeld(trial, "owner", "epoch-1")
                restarted.requireHeld(trial, "owner", "epoch-1")
            } finally { finish.complete(Unit); arming.cancelAndJoin(); worker.cancelAndJoin() }
        }
    }

    @Test fun restartPreservesAccountDeadlineAndExpiredOrCorruptTrialsCannotPass() = runBlocking {
        fixture { file, scope ->
            var instant = 1_800_000_000_000L
            val trial = UUID.randomUUID().toString()
            val gate = ReplayRuntimeIsolation(file, scope) { instant }.also { it.attach(1) }
            gate.arm(trial, "owner", "epoch-1", 60_000)
            val deadline = gate.requireHeld(trial, "owner", "epoch-1")
            val restarted = ReplayRuntimeIsolation(file, scope) { instant }.also { it.attach(1) }
            assertEquals(deadline, restarted.requireHeld(trial, "owner", "epoch-1"))
            assertThrows(IllegalStateException::class.java) { restarted.requireHeld(trial, "other-owner", "epoch-1") }
            assertThrows(IllegalStateException::class.java) { restarted.requireHeld(trial, "owner", "epoch-2") }
            assertThrows(IllegalStateException::class.java) { restarted.release(UUID.randomUUID().toString(), "owner", "epoch-1") }
            instant += 60_000
            assertThrows(IllegalStateException::class.java) { restarted.requireHeld(trial, "owner", "epoch-1") }
            assertTrue(restarted.run { "normal-runtime" } is SyncRuntimeEntry.Admitted)
            assertTrue(runCatching { restarted.arm(trial, "owner", "epoch-1") }.isFailure)
            restarted.release(trial, "owner", "epoch-1")
            file.writeText("{broken")
            assertEquals(SyncRuntimeEntry.Paused, restarted.run { error("Corrupt fence admitted runtime") })
            assertTrue(runCatching { restarted.arm(UUID.randomUUID().toString(), "owner", "epoch-1") }.isFailure)
        }
    }

    @Test fun everyNewExportedRoomLedgerIsProtectedWithoutNormalizingOperationalFields() {
        fun tables(version: Int): List<JSONObject> = InstrumentationRegistry.getInstrumentation().context.assets
            .open("pl.roseru.kalorie.data.CalorieDatabase/$version.json").use { stream ->
                val array = JSONObject(stream.reader().readText()).getJSONObject("database").getJSONArray("entities")
                (0 until array.length()).map { array.getJSONObject(it) }
            }
        val old = tables(20).map { it.getString("tableName") }.toSet()
        val latest = tables(23)
        val new = latest.filter { it.getString("tableName") !in old }
        val protected = MealReplayFingerprint.tables(23, runtimeIsolated = true)
        assertEquals(new.map { it.getString("tableName") }.toSet(), protected.toSet() - MealReplayFingerprint.tables(20).toSet())
        assertEquals(6, new.size)
        for (table in new) {
            val fields = table.getJSONArray("fields")
            for (index in 0 until fields.length()) {
                val column = fields.getJSONObject(index).getString("columnName")
                for (row in listOf("meal", "operation", "batch", "foreign-row")) {
                    assertEquals("mutated", MealReplayFingerprint.normalize(table.getString("tableName"), row, column,
                        "mutated", "meal", "operation", "batch"))
                }
            }
        }
    }

    @Test fun expiredEvidenceNeverRevivesAfterAdmittedWorkRollbackAndReconstruction() = runBlocking {
        fixture {file,scope->
            val start=1_800_000_000_000L;var instant=start
            val trial=UUID.randomUUID().toString()
            val gate=ReplayRuntimeIsolation(file,scope){instant}.also {it.attach(1)}
            gate.arm(trial,"owner","epoch-1",60_000)
            gate.requireHeld(trial,"owner","epoch-1")
            instant=start+60_001
            var writes=0
            assertEquals(SyncRuntimeEntry.Admitted(1),gate.run {++writes})
            instant=start+50_000
            assertThrows(IllegalStateException::class.java){gate.requireHeld(trial,"owner","epoch-1")}
            assertTrue(runCatching {gate.arm(trial,"owner","epoch-1")}.isFailure)
            val restored=ReplayRuntimeIsolation(file,scope){instant}.also {it.attach(1)}
            assertThrows(IllegalStateException::class.java){restored.requireHeld(trial,"owner","epoch-1")}
            assertTrue(runCatching {restored.arm(trial,"owner","epoch-1")}.isFailure)
            assertEquals(SyncRuntimeEntry.Admitted(2),restored.run {++writes})
            restored.release(trial,"owner","epoch-1")
            val fresh=UUID.randomUUID().toString()
            restored.arm(fresh,"owner","epoch-1",60_000)
            restored.requireHeld(fresh,"owner","epoch-1")
            // A version1 ready record never becomes proof of continuity after an application upgrade.
            val legacy=JSONObject(file.readText()).put("version",1).also {it.remove("terminal")}
            file.writeText(legacy.toString())
            val upgraded=ReplayRuntimeIsolation(file,scope){instant}.also {it.attach(1)}
            assertThrows(IllegalStateException::class.java){upgraded.requireHeld(fresh,"owner","epoch-1")}
            assertTrue(upgraded.run {Unit} is SyncRuntimeEntry.Admitted)
        }
    }
}
