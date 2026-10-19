package pl.roseru.kalorie.session

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class MealPushAckGateTest {
    private val batch = "00000000-0000-4000-8000-000000000001"
    private val other = "00000000-0000-4000-8000-000000000002"
    private val hash = "a".repeat(64)

    @Test fun selectedEnvelopeHoldsBeforeAckAndReleasesWithoutChangingResult() = runBlocking<Unit> {
        val gate = MealPushAckGate(); val ticket = gate.arm(batch, hash)
        var applied = false
        val operation = async { gate.beforeApplyAck(batch, hash); applied = true; "original ACK" }
        ticket.held.await(); assertFalse(applied)
        ticket.release.complete(Unit)
        assertEquals("original ACK", operation.await()); assertTrue(applied)
        assertEquals(listOf("held", "released"), ticket.events())
        assertEquals("released", ticket.outcome.await())
        gate.beforeApplyAck(batch, hash) // One-shot: no second hold.
        assertEquals(2, ticket.events().size)
    }

    @Test fun anotherBatchOrHashCannotConsumeSelectedEnvelope() = runBlocking<Unit> {
        val gate = MealPushAckGate(); val ticket = gate.arm(batch, hash)
        gate.beforeApplyAck(other, hash); gate.beforeApplyAck(batch, "b".repeat(64))
        assertFalse(ticket.held.isCompleted)
        val operation = async { gate.beforeApplyAck(batch, hash) }
        ticket.held.await(); ticket.release.complete(Unit); operation.await()
    }

    @Test fun timeoutNeverReachesDurableAckAndCanBeArmedAgain() = runBlocking<Unit> {
        val gate = MealPushAckGate(maxHoldMillis = 20); val ticket = gate.arm(batch, hash)
        var applied = false
        val operation = async { gate.beforeApplyAck(batch, hash); applied = true }
        ticket.held.await()
        try { operation.await(); fail("Timed out ACK delivered") } catch (_: CancellationException) { }
        assertFalse(applied); assertEquals("expired", ticket.outcome.await())
        assertEquals(listOf("held", "expired"), ticket.events())
        gate.disarm(gate.arm(batch, hash))
    }

    @Test fun cancellationNeverDeliversAckEvenAfterLateRelease() = runBlocking<Unit> {
        val gate = MealPushAckGate(); val ticket = gate.arm(batch, hash)
        var applied = false
        val operation = launch { gate.beforeApplyAck(batch, hash); applied = true }
        ticket.held.await(); operation.cancelAndJoin(); ticket.release.complete(Unit)
        assertFalse(applied); assertEquals("cancelled", ticket.outcome.await())
    }

    @Test fun disarmingHeldTrialCancelsWaitAndDoesNotReleaseAck() = runBlocking<Unit> {
        val gate = MealPushAckGate(); val ticket = gate.arm(batch, hash)
        var applied = false
        val operation = async { gate.beforeApplyAck(batch, hash); applied = true }
        ticket.held.await(); gate.disarm(ticket)
        try { operation.await(); fail("Disarmed ACK delivered") } catch (_: CancellationException) { }
        assertFalse(applied); assertEquals("cancelled", ticket.outcome.await())
    }

    @Test fun staleDisarmCannotRemoveAnotherTrial() = runBlocking<Unit> {
        val gate = MealPushAckGate(); val old = gate.arm(batch, hash); gate.disarm(old)
        val current = gate.arm(other, hash); gate.disarm(old)
        val operation = async { gate.beforeApplyAck(other, hash) }
        current.held.await(); current.release.complete(Unit); operation.await()
        assertEquals("released", current.outcome.await())
    }

    @Test fun secondArmIsRejectedWhileResponseIsHeld() = runBlocking<Unit> {
        val gate = MealPushAckGate(); val ticket = gate.arm(batch, hash)
        val operation = async { gate.beforeApplyAck(batch, hash) }
        ticket.held.await()
        try { gate.arm(other, hash); fail("Concurrent arm") } catch (_: IllegalStateException) { }
        ticket.release.complete(Unit); operation.await()
    }

    @Test fun concurrentMatchingResponseCannotBypassAnActiveHold() = runBlocking<Unit> {
        val gate = MealPushAckGate(); val ticket = gate.arm(batch, hash)
        val operation = async { gate.beforeApplyAck(batch, hash) }
        ticket.held.await()
        try { gate.beforeApplyAck(batch, hash); fail("Concurrent ACK bypassed hold") }
        catch (_: IllegalStateException) { }
        assertEquals(listOf("held"), ticket.events())
        ticket.release.complete(Unit); operation.await()
    }

    @Test fun expiredArmNeverDeliversAnAckOrEntersHold() = runBlocking<Unit> {
        var nanos = 0L
        val gate = MealPushAckGate(nanoTime = { nanos }); val ticket = gate.arm(batch, hash)
        nanos = 120_000_000_000L
        try { gate.beforeApplyAck(batch, hash); fail("Expired trial delivered") } catch (_: CancellationException) { }
        assertFalse(ticket.held.isCompleted); assertEquals(listOf("expired"), ticket.events())
        assertEquals("expired", ticket.outcome.await())
    }

    @Test fun armDeadlineAlsoBoundsTheRemainingHold() = runBlocking<Unit> {
        var nanos = 0L
        val gate = MealPushAckGate(nanoTime = { nanos }); val ticket = gate.arm(batch, hash)
        nanos = 119_980_000_000L
        val operation = async { gate.beforeApplyAck(batch, hash) }
        ticket.held.await()
        try { withTimeout(2_000) { operation.await() }; fail("Expired hold delivered") }
        catch (_: CancellationException) { }
        assertEquals("expired", ticket.outcome.await())
    }

    @Test fun observerFailureDoesNotChangeDeliveryAndReceivesNoEnvelopeData() = runBlocking<Unit> {
        val observed = mutableListOf<Pair<String,String>>()
        val gate = MealPushAckGate(event = { name, run -> observed.add(name to run); error("synthetic logger") })
        val ticket = gate.arm(batch, hash)
        val operation = async { gate.beforeApplyAck(batch, hash) }
        ticket.held.await(); ticket.release.complete(Unit); operation.await()
        assertEquals(listOf("held", "released"), observed.map { it.first })
        assertTrue(observed.all { it.second == ticket.run && it.second != batch && it.second != hash })
        assertFalse(ticket.toString().contains(batch)); assertFalse(ticket.toString().contains(hash))
    }

    @Test fun limitsAndInvalidEnvelopeReferencesAreRejected() {
        for (limit in listOf(0L, 45_001L)) {
            try { MealPushAckGate(maxHoldMillis = limit); fail("Unbounded hold") } catch (_: IllegalArgumentException) { }
        }
        val gate = MealPushAckGate()
        for ((id,digest) in listOf("arbitrary" to hash, batch to "token", batch to "A".repeat(64))) {
            try { gate.arm(id,digest); fail("Invalid envelope") } catch (_: IllegalArgumentException) { }
        }
        val ticket = gate.arm(batch, hash)
        try { gate.arm(other, hash); fail("Second arm") } catch (_: IllegalStateException) { }
        gate.disarm(ticket)
    }
}
