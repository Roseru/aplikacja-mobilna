package pl.roseru.kalorie.session

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference

/** Holds one actual HTTP200 after bounded IO. Telemetry never changes delivery/guard decisions. */
internal class LateReadGate(
    private val maxHoldMillis: Long = 10_000,
    private val event: (String, String, String) -> Unit = { _, _, _ -> }
) {
    init { require(maxHoldMillis in 1..10_000) }
    internal class Ticket(val path: String, private val event: (String, String, String) -> Unit) : ApiReadProof {
        val run = UUID.randomUUID().toString()
        val held = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val outcome = CompletableDeferred<String>()
        val parsed = CompletableDeferred<Unit>()
        val rejected = CompletableDeferred<Unit>()
        private val sequence = mutableListOf<String>()
        @Synchronized fun events(): List<String> = sequence.toList()
        @Synchronized private fun record(name: String) {
            sequence.add(name)
            try { event(name, path, run) } catch (_: RuntimeException) { }
        }
        @Synchronized private fun advance(name: String, prefix: List<String>): Boolean {
            if (sequence != prefix) return false
            record(name); return true
        }
        internal fun transportEvent(name: String) { record(name) }
        fun logoutCompleted() { advance("logout", listOf("held")) }
        override fun dtoParsed() {
            if (advance("dto_parsed", listOf("held", "logout", "released"))) parsed.complete(Unit)
        }
        override fun staleOwnerRejected() {
            if (advance("stale_owner_rejected", listOf("held", "logout", "released", "dto_parsed"))) rejected.complete(Unit)
        }
        fun guestPreserved() { advance("guest_preserved", listOf("held", "logout", "released", "dto_parsed", "stale_owner_rejected")) }
    }
    private val armed = AtomicReference<Ticket?>()
    fun arm(path: String): Ticket {
        require(path in setOf("/api/v1/me", "/api/v1/me/motivation"))
        val ticket = Ticket(path, event)
        check(armed.compareAndSet(null, ticket)) { "A live read is already armed" }
        return ticket
    }
    fun proof(path: String): ApiReadProof? = armed.get()?.takeIf { it.path == path }
    fun disarm(ticket: Ticket) { armed.compareAndSet(ticket, null) }
    suspend fun beforeReturn(method: String, path: String, status: Int, deadlineNanos: Long) {
        val ticket = armed.get() ?: return
        if (method != "GET" || status != 200 || path != ticket.path || !armed.compareAndSet(ticket, null)) return
        val remainingMillis = (deadlineNanos - System.nanoTime()) / 1_000_000
        if (remainingMillis <= 0) {
            ticket.transportEvent("expired"); ticket.outcome.complete("expired")
            throw CancellationException("Original HTTP deadline expired before hold")
        }
        ticket.transportEvent("held"); ticket.held.complete(Unit)
        try {
            withTimeout(minOf(maxHoldMillis, remainingMillis)) { ticket.release.await() }
            ticket.transportEvent("released"); ticket.outcome.complete("released")
        } catch (error: TimeoutCancellationException) {
            ticket.transportEvent("expired"); ticket.outcome.complete("expired"); throw error
        } catch (error: CancellationException) {
            ticket.transportEvent("cancelled"); ticket.outcome.complete("cancelled"); throw error
        }
    }
}
