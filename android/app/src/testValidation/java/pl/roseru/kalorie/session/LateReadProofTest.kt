package pl.roseru.kalorie.session

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class LateReadProofTest {
    private val path = "/api/v1/me"
    private fun deadline() = System.nanoTime() + 5_000_000_000
    @Test fun proofIsCapturedOnlyForTheArmedPathAndTicket() {
        val gate = LateReadGate(); val first = gate.arm(path)
        assertSame(first, gate.proof(path)); assertNull(gate.proof("/api/v1/me/motivation"))
        gate.disarm(first); val next = gate.arm(path)
        assertNotEquals(first.run, next.run); assertSame(next, gate.proof(path))
    }
    @Test fun parsedAndRejectedCannotBeAssertedBeforeDelivery() {
        val ticket = LateReadGate().arm(path)
        ticket.dtoParsed(); ticket.staleOwnerRejected(); ticket.guestPreserved()
        assertFalse(ticket.parsed.isCompleted); assertFalse(ticket.rejected.isCompleted)
        assertTrue(ticket.events().isEmpty())
    }
    @Test fun releaseWithoutCompletedLogoutCannotProveRejection() = runBlocking {
        val gate = LateReadGate(); val ticket = gate.arm(path)
        val read = async { gate.beforeReturn("GET", path, 200, deadline()) }
        ticket.held.await(); ticket.release.complete(Unit); read.await()
        ticket.dtoParsed(); ticket.staleOwnerRejected()
        assertEquals(listOf("held", "released"), ticket.events())
        assertFalse(ticket.parsed.isCompleted); assertFalse(ticket.rejected.isCompleted)
    }
    @Test fun completeTraceIsOrderedAndCannotBeRecordedTwice() = runBlocking {
        val gate = LateReadGate(); val ticket = gate.arm(path); val proof = checkNotNull(gate.proof(path))
        val read = async { gate.beforeReturn("GET", path, 200, deadline()); proof.dtoParsed(); proof.staleOwnerRejected() }
        ticket.held.await(); assertNull(gate.proof(path))
        ticket.logoutCompleted(); ticket.release.complete(Unit); read.await()
        assertTrue(ticket.parsed.isCompleted); assertTrue(ticket.rejected.isCompleted)
        ticket.guestPreserved(); proof.dtoParsed(); proof.staleOwnerRejected()
        assertEquals(listOf("held", "logout", "released", "dto_parsed", "stale_owner_rejected", "guest_preserved"), ticket.events())
    }
    @Test fun cancellationCannotCompleteDeliveryProof() = runBlocking {
        val gate = LateReadGate(); val ticket = gate.arm(path)
        val read = async { gate.beforeReturn("GET", path, 200, deadline()) }
        ticket.held.await(); ticket.logoutCompleted(); read.cancelAndJoin()
        ticket.dtoParsed(); ticket.staleOwnerRejected()
        assertEquals("cancelled", ticket.outcome.await())
        assertFalse(ticket.parsed.isCompleted); assertFalse(ticket.rejected.isCompleted)
    }
    @Test fun optionalLoggingFailureDoesNotInterruptDelivery() = runBlocking {
        val gate = LateReadGate(event = { _, _, _ -> throw IllegalStateException("logger unavailable") })
        val ticket = gate.arm(path)
        val read = async { gate.beforeReturn("GET", path, 200, deadline()); "unchanged" }
        ticket.held.await(); ticket.release.complete(Unit)
        assertEquals("unchanged", read.await()); assertEquals("released", ticket.outcome.await())
    }
}
