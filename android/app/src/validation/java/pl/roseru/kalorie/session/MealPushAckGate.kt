package pl.roseru.kalorie.session

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withTimeout
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Validation only: hold a parsed ACK outside the session mutex and Room transaction.
 * A timeout/cancellation never delivers the prepared ACK. No request/response is rewritten.
 */
internal class MealPushAckGate(
    private val maxHoldMillis: Long = 45_000,
    private val nanoTime: () -> Long = System::nanoTime,
    private val event: (String, String) -> Unit = { _, _ -> }
) {
    init { require(maxHoldMillis in 1..45_000) }

    internal class Ticket internal constructor(
        internal val batchId: String,
        internal val requestHash: String,
        internal val armedAtNanos: Long,
        private val event: (String, String) -> Unit
    ) {
        val run: String = UUID.randomUUID().toString()
        val held = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val outcome = CompletableDeferred<String>()
        internal val claimed = AtomicBoolean(false)
        private val sequence = mutableListOf<String>()

        @Synchronized fun events(): List<String> = sequence.toList()
        @Synchronized internal fun record(name: String) {
            sequence.add(name)
            // Diagnostics contain only the generated run ID and fixed event name.
            try { event(name, run) } catch (_: RuntimeException) { }
        }
        override fun toString() = "MealPushAckTicket(redacted)"
    }

    private val active = AtomicReference<Ticket?>()

    fun arm(batchId: String, requestHash: String): Ticket {
        require(UUID_PATTERN.matches(batchId))
        require(HASH_PATTERN.matches(requestHash))
        val ticket = Ticket(batchId, requestHash, nanoTime(), event)
        check(active.compareAndSet(null, ticket)) { "An ACK trial is already armed" }
        return ticket
    }

    /** Removing a held ticket also cancels its wait; it cannot release an ACK by accident. */
    fun disarm(ticket: Ticket) {
        if (active.compareAndSet(ticket, null)) {
            ticket.release.cancel(CancellationException("ACK trial disarmed"))
        }
    }

    suspend fun beforeApplyAck(batchId: String, requestHash: String) {
        val ticket = active.get() ?: return
        if (ticket.batchId != batchId || ticket.requestHash != requestHash) return
        check(ticket.claimed.compareAndSet(false, true)) { "Selected ACK is already held" }
        try {
            val remaining = ARM_TTL_MILLIS - (nanoTime() - ticket.armedAtNanos) / 1_000_000
            if (remaining <= 0) {
                ticket.record("expired"); ticket.outcome.complete("expired")
                throw CancellationException("ACK trial expired before hold")
            }
            ticket.record("held"); ticket.held.complete(Unit)
            try {
                withTimeout(minOf(maxHoldMillis, remaining)) { ticket.release.await() }
                currentCoroutineContext().ensureActive()
                ticket.record("released"); ticket.outcome.complete("released")
            } catch (error: TimeoutCancellationException) {
                ticket.record("expired"); ticket.outcome.complete("expired"); throw error
            } catch (error: CancellationException) {
                ticket.record("cancelled"); ticket.outcome.complete("cancelled"); throw error
            }
        } finally {
            active.compareAndSet(ticket, null)
        }
    }

    private companion object {
        const val ARM_TTL_MILLIS = 120_000L
        val UUID_PATTERN = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        val HASH_PATTERN = Regex("[0-9a-f]{64}")
    }
}
