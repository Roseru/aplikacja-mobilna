package pl.roseru.kalorie.session

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import java.util.concurrent.atomic.AtomicReference

/** One actual successful read, after bounded body IO; no DTO or session is supplied to this gate. */
internal class LateReadGate(
    private val maxHoldMillis: Long = 10_000,
    private val event: (String, String) -> Unit = { _, _ -> }
) {
    init { require(maxHoldMillis in 1..10_000) }
    internal class Ticket(val path: String) {
        val held = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val outcome = CompletableDeferred<String>()
    }
    private val armed = AtomicReference<Ticket?>()
    fun arm(path: String): Ticket {
        require(path in setOf("/api/v1/me", "/api/v1/me/motivation"))
        val ticket = Ticket(path)
        check(armed.compareAndSet(null, ticket)) { "A live read is already armed" }
        return ticket
    }
    fun disarm(ticket: Ticket) { armed.compareAndSet(ticket, null) }
    suspend fun beforeReturn(method: String, path: String, status: Int, deadlineNanos: Long) {
        val ticket = armed.get() ?: return
        if (method != "GET" || status != 200 || path != ticket.path || !armed.compareAndSet(ticket, null)) return
        val remainingMillis = (deadlineNanos - System.nanoTime()) / 1_000_000
        if (remainingMillis <= 0) {
            event("expired", path); ticket.outcome.complete("expired")
            throw CancellationException("Original HTTP deadline expired before hold")
        }
        event("held", path)
        ticket.held.complete(Unit)
        try {
            withTimeout(minOf(maxHoldMillis, remainingMillis)) { ticket.release.await() }
            event("released", path); ticket.outcome.complete("released")
        } catch (error: TimeoutCancellationException) {
            event("expired", path); ticket.outcome.complete("expired"); throw error
        } catch (error: CancellationException) {
            event("cancelled", path); ticket.outcome.complete("cancelled"); throw error
        }
    }
}
