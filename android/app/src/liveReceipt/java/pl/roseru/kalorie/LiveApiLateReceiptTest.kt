package pl.roseru.kalorie

import android.util.Log
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.room.withTransaction
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.MotivationState
import pl.roseru.kalorie.session.ApiReadObservation
import java.time.Instant

/** Opt-in driver only: real existing APK session, no credentials/DTO/transport fixtures. */
@RunWith(AndroidJUnit4::class)
class LiveApiLateReceiptTest {
    private fun mark(event: String) { Log.i("O1ApiReadGate", "event=$event path=/api/v1/me utc=${Instant.now()}") }
    @Test fun actualReceivedGetIsReleasedAfterRealLogout() = runBlocking {
        assumeTrue(InstrumentationRegistry.getArguments().getString("live_api_receipt") == "true")
        val app = ApplicationProvider.getApplicationContext<CalorieApplication>()
        val sessions = app.sessions
        val initial = withTimeout(10_000) { sessions.view.first { it.binding != null } }
        assumeTrue(initial.hasSession && initial.serverLinked && !initial.requiresRecovery && initial.binding?.owner?.kind == "account")
        val tables = listOf("products", "meals", "meal_items", "goals", "outbox", "rations", "ration_components",
            "profiles", "weights", "diary_days", "catalog_generations", "catalog_records", "catalog_members", "catalog_active", "meal_photo_drafts")
        suspend fun snapshot(): Map<String, List<List<String?>>> = app.database.withTransaction {
            tables.associateWith { table ->
                app.database.openHelper.readableDatabase.query("SELECT * FROM \"$table\" ORDER BY rowid").use { cursor ->
                    buildList { while (cursor.moveToNext()) add((0 until cursor.columnCount).map { if (cursor.isNull(it)) null else cursor.getString(it) }) }
                }
            }
        }
        val before = snapshot()
        val ticket = ApiReadObservation.lateRead.arm("/api/v1/me")
        val read = app.sessionScope.async { sessions.readProfile() }
        try {
            withTimeout(20_000) { ticket.held.await() }
            assertFalse("GET returned before hold", read.isCompleted)
            withContext(Dispatchers.Main) { sessions.logout() }
            val guest = sessions.view.value
            assertTrue("Logout did not select guest", guest.binding?.owner?.kind == "guest" && !guest.hasSession)
            mark("logout")
            ticket.release.complete(Unit)
            withTimeout(10_000) { read.await() }
            assertTrue("Response did not leave gateway", ticket.outcome.await() == "released")
            val after = sessions.view.value
            assertTrue("Late response restored a private account", after.binding?.owner?.kind == "guest" && !after.hasSession)
            assertTrue("Late profile became visible", after.serverProfile == null && after.motivation == MotivationState.NotRequested)
            assertTrue("Local data changed; values suppressed", before == snapshot())
            mark("guest_preserved")
        } finally {
            ticket.release.complete(Unit)
            ApiReadObservation.lateRead.disarm(ticket)
            read.cancelAndJoin()
        }
    }
}
