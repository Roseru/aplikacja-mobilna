package pl.roseru.kalorie.core

import java.time.Duration
import java.time.Instant

/** Reconcile only validated reads. The caller still owns the account/session/Room guard. */
internal object PhotoAnalysisProgress {
    fun accept(previous:PhotoAnalysisRead?,incoming:PhotoAnalysisRead):PhotoAnalysisRead {
        if(previous==null) return incoming
        require(previous.analysisId==incoming.analysisId && previous.queueDeadline==incoming.queueDeadline &&
            previous.photoExpiresAt==incoming.photoExpiresAt && profile(previous.profile)==profile(incoming.profile)) {"Niezgodny kontekst analizy"}
        if(incoming.revision<previous.revision) return previous
        if(incoming.revision==previous.revision) {
            require(incoming.wireFingerprint==previous.wireFingerprint) {"Niezgodna rewizja analizy"}
            return previous
        }
        fun unchangedProposal()=previous.proposalFingerprint==incoming.proposalFingerprint
        if(previous.decision!="pending") {
            require(incoming.decision==previous.decision && incoming.state==previous.state &&
                incoming.errorCode==previous.errorCode && unchangedProposal()) {"Rozstrzygnięta analiza nie może się zmienić"}
        } else when(previous.state) {
            "running"->require(incoming.state!="queued") {"Cofnięty stan analizy"}
            "succeeded"->require((incoming.state=="succeeded" && unchangedProposal()) || incoming.decision=="cancelled") {"Zmieniony wynik analizy"}
            "failed"->require(incoming.state=="failed" &&
                (incoming.errorCode==previous.errorCode || incoming.decision=="cancelled")) {"Zmieniony błąd analizy"}
        }
        return incoming
    }
    private fun profile(value:PhotoAnalysisProfile)=listOf(value.provider,value.model,value.prompt,value.schema,
        value.preparation,value.rest,value.mockScenario)
}

internal sealed class PhotoPollStep {
    class Ready(val reserved:PhotoPollBudget,val timeoutMillis:Long):PhotoPollStep() {
        override fun toString()="PhotoPollStep.Ready(redacted)"
    }
    class Wait(val delayMillis:Long):PhotoPollStep() {
        override fun toString()="PhotoPollStep.Wait(redacted)"
    }
    class Stop(val reason:Reason):PhotoPollStep() {
        override fun toString()="PhotoPollStep.Stop(redacted)"
    }
    enum class Reason { TERMINAL, ATTEMPTS, LOCAL_DEADLINE, SERVER_DEADLINE, BACKOFF_OUTSIDE_WINDOW, CLOCK }
}

/** A foreground read budget, never a scheduler or permission to bypass a session guard.
 * Reserve BEFORE each HTTP attempt (including a retry); startup does not construct/start a loop.
 */
internal class PhotoPollBudget private constructor(val attempts:Int,private val startedNanos:Long,private val nextNanos:Long) {
    fun reserve(current:PhotoAnalysisRead,now:Instant,nowNanos:Long,sharedRetryAtMillis:Long=0):PhotoPollStep {
        if(current.state in setOf("succeeded","failed") || current.decision!="pending") return PhotoPollStep.Stop(PhotoPollStep.Reason.TERMINAL)
        return try {
            // A worker may start just before queue_deadline and then run for another120s.
            val deadline=minOf(current.photoExpiresAt,current.queueDeadline.plusSeconds(120))
            reserve(now,nowNanos,sharedRetryAtMillis,Duration.between(now,deadline).toMillis())
        } catch(_:ArithmeticException) {PhotoPollStep.Stop(PhotoPollStep.Reason.CLOCK)}
    }
    /** Before the first valid GET, its current state/expiry is unknown. A completed proposal
     * remains readable after image deletion; never suppress that explicit initial fetch.
     * The same local window, attempts and backoff still apply, including401 retries.
     */
    fun reserveInitial(now:Instant,nowNanos:Long,sharedRetryAtMillis:Long=0):PhotoPollStep =
        reserve(now,nowNanos,sharedRetryAtMillis,Long.MAX_VALUE)

    private fun reserve(now:Instant,nowNanos:Long,sharedRetryAtMillis:Long,serverMillis:Long):PhotoPollStep {
        if(attempts>=MAX_READS) return PhotoPollStep.Stop(PhotoPollStep.Reason.ATTEMPTS)
        try {
            val elapsed=Math.subtractExact(nowNanos,startedNanos)
            if(elapsed<0) return PhotoPollStep.Stop(PhotoPollStep.Reason.CLOCK)
            val remainingNanos=Math.subtractExact(WINDOW_NANOS,elapsed)
            if(remainingNanos<=0) return PhotoPollStep.Stop(PhotoPollStep.Reason.LOCAL_DEADLINE)
            if(serverMillis<=0) return PhotoPollStep.Stop(PhotoPollStep.Reason.SERVER_DEADLINE)
            val remainingMillis=minOf(remainingNanos/1_000_000,serverMillis)
            if(remainingMillis<=0) return PhotoPollStep.Stop(PhotoPollStep.Reason.LOCAL_DEADLINE)
            val untilNext=Math.subtractExact(nextNanos,nowNanos).coerceAtLeast(0)
            val localDelay=untilNext/1_000_000+if(untilNext%1_000_000==0L) 0 else 1
            val sharedDelay=if(sharedRetryAtMillis==0L) 0 else Math.subtractExact(sharedRetryAtMillis,now.toEpochMilli()).coerceAtLeast(0)
            val delay=maxOf(localDelay,sharedDelay)
            if(delay>=remainingMillis) return PhotoPollStep.Stop(PhotoPollStep.Reason.BACKOFF_OUTSIDE_WINDOW)
            if(delay>0) return PhotoPollStep.Wait(delay)
            val pauses=longArrayOf(2_000,4_000,8_000,15_000,30_000)
            val pause=pauses[minOf(attempts,pauses.lastIndex)]
            val reserved=PhotoPollBudget(attempts+1,startedNanos,Math.addExact(nowNanos,pause*1_000_000))
            return PhotoPollStep.Ready(reserved,minOf(45_000,remainingMillis))
        } catch(_:ArithmeticException) {return PhotoPollStep.Stop(PhotoPollStep.Reason.CLOCK)}
    }
    override fun toString()="PhotoPollBudget(redacted)"
    companion object {
        const val MAX_READS=12
        private const val WINDOW_NANOS=120_000_000_000L
        fun start(nowNanos:Long)=PhotoPollBudget(0,nowNanos,nowNanos)
    }
}
