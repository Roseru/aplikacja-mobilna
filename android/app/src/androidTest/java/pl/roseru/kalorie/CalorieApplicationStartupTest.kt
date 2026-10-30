package pl.roseru.kalorie

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

/** Cold process only: no Activity, runtime getter, worker, manual sync or diary writes. */
@RunWith(AndroidJUnit4::class)
class CalorieApplicationStartupTest {
    @Test fun coldProcessSubscribesBothRealRuntimeCollectors() = runBlocking {
        val app = ApplicationProvider.getApplicationContext<CalorieApplication>()
        // This getter creates only admission, never the lazy runtime that consumes it.
        val changes = app.syncRuntimeAdmission.changes as? MutableStateFlow<Long>
            ?: error("The pinned admission flow must expose its real subscription count")
        // observe() has two independent combine collectors of admission.changes.
        // Merely constructing/attaching runtime, signal() or execute() cannot satisfy this.
        val count = changes.subscriptionCount
        try {
            withTimeout(10_000) { count.first { it == 2 } }
        } catch (error: TimeoutCancellationException) {
            throw AssertionError("Expected two real runtime collectors; observed ${count.value}", error)
        }
        assertEquals(2, count.value)
    }
}
