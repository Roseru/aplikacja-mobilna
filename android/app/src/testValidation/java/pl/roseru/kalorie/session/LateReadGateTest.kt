package pl.roseru.kalorie.session

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class LateReadGateTest {
    private val path = "/api/v1/me"
    private fun deadline() = System.nanoTime() + 5_000_000_000
    @Test fun gateIsOneShotAndDoesNotAlterTheReturnedValue() = runBlocking {
        val events = mutableListOf<String>()
        val gate = LateReadGate(event = { name, _ -> events.add(name) })
        val ticket = gate.arm(path)
        val read = async { gate.beforeReturn("GET", path, 200, deadline()); "original result" }
        ticket.held.await(); assertFalse(read.isCompleted)
        ticket.release.complete(Unit)
        assertEquals("original result", read.await()); assertEquals("released", ticket.outcome.await())
        gate.beforeReturn("GET", path, 200, deadline())
        assertEquals(listOf("held", "released"), events)
    }
    @Test fun otherRequestsDoNotConsumeTheArmedRead() = runBlocking {
        val gate = LateReadGate(); val ticket = gate.arm(path)
        gate.beforeReturn("POST", path, 200, deadline())
        gate.beforeReturn("GET", path, 401, deadline())
        gate.beforeReturn("GET", "/api/v1/me/motivation", 200, deadline())
        assertFalse(ticket.held.isCompleted)
        val read = async { gate.beforeReturn("GET", path, 200, deadline()) }
        ticket.held.await(); ticket.release.complete(Unit); read.await()
    }
    @Test fun cancellationCannotDeliverAnOldResponse() = runBlocking {
        val gate = LateReadGate(); val ticket = gate.arm(path)
        val read = async { gate.beforeReturn("GET", path, 200, deadline()); error("Cancelled result delivered") }
        ticket.held.await(); read.cancelAndJoin()
        assertEquals("cancelled", ticket.outcome.await())
        ticket.release.complete(Unit); assertTrue(read.isCancelled)
    }
    @Test fun originalDeadlineBoundsTheHold() = runBlocking {
        val gate = LateReadGate(); val ticket = gate.arm(path)
        val read = async { gate.beforeReturn("GET", path, 200, System.nanoTime() + 50_000_000) }
        ticket.held.await()
        try { read.await(); fail("Expected original deadline expiry") } catch (_: CancellationException) { }
        assertEquals("expired", ticket.outcome.await())
    }
    @Test fun expiredDeadlineNeverReachesTheController() = runBlocking {
        val gate = LateReadGate(); val ticket = gate.arm(path)
        try { gate.beforeReturn("GET", path, 200, System.nanoTime() - 1); fail("Expected expiry") }
        catch (_: CancellationException) { }
        assertFalse(ticket.held.isCompleted); assertEquals("expired", ticket.outcome.await())
    }
    @Test fun gateRejectsUnboundedHoldAndArbitraryPaths() {
        try { LateReadGate(10_001); fail("Unbounded hold accepted") } catch (_: IllegalArgumentException) { }
        val gate = LateReadGate()
        try { gate.arm("/private?token=value"); fail("Path accepted") } catch (_: IllegalArgumentException) { }
        val ticket = gate.arm(path)
        try { gate.arm(path); fail("Second arm accepted") } catch (_: IllegalStateException) { }
        gate.disarm(ticket); gate.arm(path)
    }
}
