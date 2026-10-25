package pl.roseru.kalorie.sync

import android.util.AtomicFile
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.io.File
import java.security.MessageDigest
import java.util.UUID

/** Private validation-only fence. It survives process death; it never rewrites a diary row. */
class ReplayRuntimeIsolation(
    private val file: File,
    private val scope: CoroutineScope,
    private val now: () -> Long = System::currentTimeMillis
) : SyncRuntimeAdmission {
    companion object {
        const val CONTRACT_VERSION = 1
        const val MAX_DURATION_MILLIS = 30 * 60_000L
    }
    private val lock = Any()
    private val active = mutableSetOf<Deferred<*>>()
    private var attached = false
    private val notifications = MutableStateFlow(0L)
    override val changes: StateFlow<Long> get() = notifications
    private var expiryJob: Job? = null
    private val atomic = AtomicFile(file)

    private data class Fence(val trial: String, val ownerHash: String, val contextHash: String,
        val created: Long, val expires: Long, val ready: Boolean, val terminal: Boolean = false) {
        override fun toString() = "Fence(redacted)"
    }
    private sealed interface Stored {
        data object Empty : Stored
        data object Invalid : Stored
        data class Present(val fence: Fence) : Stored
    }

    init { synchronized(lock) { scheduleExpiry(observed()) } }

    override fun attach(contractVersion: Int) = synchronized(lock) {
        require(contractVersion == CONTRACT_VERSION) { "Unsupported runtime admission contract" }
        attached = true
    }

    override suspend fun <T> run(block: suspend () -> T): SyncRuntimeEntry<T> = coroutineScope {
        val work = async(start = CoroutineStart.LAZY) { block() }
        val allowed = try {
            synchronized(lock) {
                if (paused(observed())) false else { active.add(work); true }
            }
        } catch (failure: Throwable) { work.cancel(); throw failure }
        if (!allowed) { work.cancel(); return@coroutineScope SyncRuntimeEntry.Paused }
        try { work.start(); SyncRuntimeEntry.Admitted(work.await()) }
        finally { synchronized(lock) { active.remove(work) } }
    }

    /** Persist first, cancel admitted work, wait for its finally blocks, then mark quiescence. */
    suspend fun arm(trial: String, owner: String, wireContext: String, durationMillis: Long = 20 * 60_000L) {
        require(UUID.fromString(trial).toString() == trial && owner.isNotBlank() && wireContext.isNotBlank())
        require(durationMillis in 60_000L..MAX_DURATION_MILLIS)
        val (fence, running) = synchronized(lock) {
            check(attached) { "Runtime admission is not connected; trial remains unsupported" }
            val old = observed()
            val instant = now()
            val next = when (old) {
                Stored.Invalid -> error("Invalid private runtime fence; explicit abort required")
                is Stored.Present -> if (old.fence.trial == trial) {
                    check(matches(old.fence, trial, owner, wireContext) && current(old.fence)) {
                        "A trial cannot change account, renew its deadline or reuse expired evidence"
                    }
                    old.fence.copy(ready = false)
                } else {
                    check(!paused(old)) { "Another private trial is still active" }
                    Fence(trial, hash(owner), hash(wireContext), instant, Math.addExact(instant, durationMillis), false)
                }
                Stored.Empty -> Fence(trial, hash(owner), hash(wireContext), instant, Math.addExact(instant, durationMillis), false)
            }
            write(next)
            next to active.toList()
        }
        // Timeout preserves the durable block and never permits preparation of a baseline.
        running.forEach { it.cancel(CancellationException("Private replay trial isolation")) }
        withTimeout(45_000) { running.joinAll() }
        synchronized(lock) {
            val saved = (observed() as? Stored.Present)?.fence
            check(saved == fence && current(fence) && active.none { !it.isCompleted }) {
                "Runtime did not become quiescent within the private trial"
            }
            write(fence.copy(ready = true))
        }
    }

    /** Must hold before every protected observation, including after the external process kill. */
    fun requireHeld(trial: String, owner: String, wireContext: String): Long = synchronized(lock) {
        check(attached) { "Runtime admission is not connected" }
        val fence = (observed() as? Stored.Present)?.fence ?: error("Missing private runtime fence")
        check(fence.ready && current(fence) && matches(fence, trial, owner, wireContext) && active.none { !it.isCompleted }) {
            "Trial isolation expired, changed account or failed to quiesce"
        }
        fence.expires
    }

    /** Release is a separate operator phase, after local and server observations are collected. */
    fun release(trial: String, owner: String, wireContext: String) = synchronized(lock) {
        val fence = (read() as? Stored.Present)?.fence ?: error("Missing private runtime fence")
        check(matches(fence, trial, owner, wireContext)) { "Cannot release another trial" }
        atomic.delete()
        check(!file.exists() && !File(file.path + ".bak").exists()) { "Runtime fence removal failed" }
        expiryJob?.cancel(); expiryJob = null
        changed()
    }

    private fun matches(fence: Fence, trial: String, owner: String, context: String) =
        fence.trial == trial && fence.ownerHash == hash(owner) && fence.contextHash == hash(context)
    private fun current(fence: Fence) = !fence.terminal && now() in fence.created until fence.expires
    private fun paused(stored: Stored) = when (stored) {
        Stored.Empty -> false
        Stored.Invalid -> true
        // Only observed() may retire an existing fence after persisting its terminal state.
        // A second clock read here could cross expiry and admit work while ready remains on disk.
        is Stored.Present -> !stored.fence.terminal
    }
    private fun changed() { notifications.value = Math.addExact(notifications.value, 1L) }

    /** Persist the terminal state BEFORE admitting any work, even when the clock later rolls back. */
    private fun observed(): Stored {
        val stored=read()
        if(stored !is Stored.Present || stored.fence.terminal || now()<stored.fence.expires)return stored
        val terminal=stored.fence.copy(ready=false,terminal=true)
        write(terminal) // A failed durable write throws; it never permits the mutation.
        return Stored.Present(terminal)
    }

    private fun read(): Stored {
        if (!file.exists() && !File(file.path + ".bak").exists()) return Stored.Empty
        return try {
            val bytes = atomic.openRead().use { stream ->
                val result = stream.readBytesUpTo(2049)
                check(result.size in 1..2048)
                result
            }
            val value = StrictJson.read(bytes)
            val version=value.get("version")
            check(version==1 || version==2)
            val keys=setOf("version", "trial", "owner_hash", "context_hash", "created", "expires", "ready")
            check(value.keys().asSequence().toSet() == if(version==1)keys else keys+"terminal")
            check(value.get("ready") is Boolean)
            if(version==2)check(value.get("terminal") is Boolean && (!value.getBoolean("terminal") || !value.getBoolean("ready")))
            val trial = value.getString("trial")
            check(UUID.fromString(trial).toString() == trial)
            val owner = value.getString("owner_hash"); val context = value.getString("context_hash")
            check(owner.matches(Regex("[0-9a-f]{64}")) && context.matches(Regex("[0-9a-f]{64}")))
            val created = value.get("created").toString().takeIf { it.matches(Regex("[1-9][0-9]*")) }?.toLongOrNull()
                ?: error("Invalid fence creation time")
            val expires = value.get("expires").toString().takeIf { it.matches(Regex("[1-9][0-9]*")) }?.toLongOrNull()
                ?: error("Invalid fence deadline")
            check(created > 0 && expires > created && Math.subtractExact(expires, created) in 60_000L..MAX_DURATION_MILLIS)
            // Version1 did not prove uninterrupted isolation; it is always retired, never upgraded to ready.
            val terminal=version==1 || value.getBoolean("terminal")
            Stored.Present(Fence(trial, owner, context, created, expires, !terminal && value.getBoolean("ready"), terminal))
        } catch (_: Exception) { Stored.Invalid }
    }

    private fun write(fence: Fence) {
        check(file.parentFile!!.isDirectory || file.parentFile!!.mkdirs())
        val bytes = JSONObject().put("version", 2).put("trial", fence.trial).put("owner_hash", fence.ownerHash)
            .put("context_hash", fence.contextHash).put("created", fence.created).put("expires", fence.expires)
            .put("ready", fence.ready).put("terminal",fence.terminal).toString().toByteArray(Charsets.UTF_8)
        val stream = atomic.startWrite()
        try { stream.write(bytes); stream.fd.sync(); atomic.finishWrite(stream) }
        catch (failure: Throwable) { atomic.failWrite(stream); throw failure }
        check((read() as? Stored.Present)?.fence == fence) { "Private runtime fence was not persisted" }
        changed(); scheduleExpiry(Stored.Present(fence))
    }

    private fun scheduleExpiry(stored: Stored) {
        expiryJob?.cancel(); expiryJob = null
        if (stored !is Stored.Present || stored.fence.terminal) return
        val remaining = (stored.fence.expires - now()).coerceAtLeast(0L).coerceAtMost(MAX_DURATION_MILLIS)
        expiryJob = scope.launch {
            delay(remaining)
            synchronized(lock) {
                val current=(read() as? Stored.Present)?.fence
                if(current!=null && current==stored.fence && !current.terminal)write(current.copy(ready=false,terminal=true))
            }
        }
    }

    private fun hash(value: String) = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

    private fun java.io.InputStream.readBytesUpTo(limit: Int): ByteArray {
        val output = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(512)
        while (output.size() < limit) {
            val count = read(buffer, 0, minOf(buffer.size, limit - output.size()))
            if (count < 0) break
            output.write(buffer, 0, count)
        }
        return output.toByteArray()
    }
}
