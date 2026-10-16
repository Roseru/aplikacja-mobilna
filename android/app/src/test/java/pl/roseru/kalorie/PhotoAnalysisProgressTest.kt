package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import java.time.Instant

class PhotoAnalysisProgressTest {
    private val key="12345678-1234-5678-9234-123456789abc"
    private val epoch="22345678-1234-5678-9234-123456789abc"
    private val start=Instant.parse("2026-10-11T16:59:00Z")
    private fun json()=JSONObject(checkNotNull(javaClass.getResource("/photo/analysis-read-succeeded.json")).readText())
    private fun read(value:JSONObject):PhotoAnalysisRead {
        val ack=JSONObject(checkNotNull(javaClass.getResource("/photo/create-accepted.json")).readText()).put("analysis_id",value.get("analysis_id"))
        val request=PhotoHttpRequest.Create.prepare(key,epoch,PhotoCapabilitiesRead("mock","mock-food-v1","food-photo-notice-v1",true,null,5_242_880,10),
            true,byteArrayOf(0xff.toByte(),0xd8.toByte(),0xff.toByte()),"image/jpeg")
        return PhotoAnalysisReadProtocol.read(value.toString().toByteArray(),PhotoAnalysisProtocol.create(ack.toString().toByteArray(),request))
    }
    private fun working(state:String="running",revision:Int=2)=read(json().put("state",state).put("revision",revision).put("proposal",JSONObject.NULL))
    private fun failure(cancelled:Boolean=false,revision:Int=3)=read(json().put("state","failed").put("revision",revision)
        .put("proposal",JSONObject.NULL).put("decision_state",if(cancelled)"cancelled" else "pending")
        .put("error_code",if(cancelled)"analysis_cancelled" else "provider_result_unknown"))
    private fun stopped(step:PhotoPollStep,reason:PhotoPollStep.Reason) {
        assertTrue(step is PhotoPollStep.Stop);assertEquals(reason,(step as PhotoPollStep.Stop).reason)
    }

    @Test fun initialReadLateRevisionAndIdenticalReplayKeepTheCorrectSnapshot() {
        val current=working(revision=4)
        assertSame(current,PhotoAnalysisProgress.accept(null,current))
        assertSame(current,PhotoAnalysisProgress.accept(current,working("queued",3)))
        assertSame(current,PhotoAnalysisProgress.accept(current,working(revision=4)))
    }
    @Test fun sameRevisionCannotChangeAStateOrPrivateProposal() {
        assertThrows(IllegalArgumentException::class.java){PhotoAnalysisProgress.accept(working(),read(json()))}
        val current=read(json());val changed=json();changed.getJSONObject("proposal").getJSONArray("notes").put("changed")
        val error=assertThrows(IllegalArgumentException::class.java){PhotoAnalysisProgress.accept(current,read(changed))}
        assertNull(error.cause);assertFalse(error.toString().contains("changed"))
    }
    @Test fun aNewerResponseCannotChangeTheAnalysisOrExpiry() {
        val current=working()
        val expiry=json().put("revision",4).put("photo_expires_at","2026-10-13T16:55:00Z")
        assertThrows(IllegalArgumentException::class.java){PhotoAnalysisProgress.accept(current,read(expiry))}
        val another=json().put("revision",4).put("analysis_id",key)
        assertThrows(IllegalArgumentException::class.java){PhotoAnalysisProgress.accept(current,read(another))}
    }
    @Test fun missedServerTransitionsMayJumpToSuccessOrConfirmationButRunningCannotGoBackToQueued() {
        val queued=working("queued",1)
        val confirmed=read(json().put("revision",5).put("decision_state","confirmed"))
        assertSame(confirmed,PhotoAnalysisProgress.accept(queued,confirmed))
        assertSame(confirmed,PhotoAnalysisProgress.accept(working(),confirmed))
        assertThrows(IllegalArgumentException::class.java){PhotoAnalysisProgress.accept(working(),working("queued",3))}
    }
    @Test fun successfulProposalCannotBeReplacedEvenUnderANewerRevision() {
        val current=read(json());val altered=json().put("revision",3)
        altered.getJSONObject("proposal").getJSONArray("notes").put("different proposal")
        assertThrows(IllegalArgumentException::class.java){PhotoAnalysisProgress.accept(current,read(altered))}
        val confirmed=read(json().put("revision",3).put("decision_state","confirmed"))
        assertSame(confirmed,PhotoAnalysisProgress.accept(current,confirmed))
    }
    @Test fun pendingSuccessOrFailureMayBeCancelledButFinalDecisionsCannotBeReversed() {
        val cancelled=failure(true,5)
        assertSame(cancelled,PhotoAnalysisProgress.accept(read(json()),cancelled))
        assertSame(cancelled,PhotoAnalysisProgress.accept(failure(),cancelled))
        assertThrows(IllegalArgumentException::class.java){PhotoAnalysisProgress.accept(cancelled,failure(false,6))}
        val confirmed=read(json().put("revision",4).put("decision_state","confirmed"))
        assertThrows(IllegalArgumentException::class.java){PhotoAnalysisProgress.accept(confirmed,cancelled)}
        assertThrows(IllegalArgumentException::class.java){PhotoAnalysisProgress.accept(failure(),read(json().put("revision",5)))}
    }
    @Test fun higherRevisionWithAnUnchangedFinalDecisionIsHarmless() {
        val previous=read(json().put("revision",4).put("decision_state","confirmed"))
        val current=read(json().put("revision",5).put("decision_state","confirmed"))
        assertSame(current,PhotoAnalysisProgress.accept(previous,current))
    }
    @Test fun pollReservationCountsBeforeIoAndWaitDoesNotConsumeAnotherAttempt() {
        val initial=PhotoPollBudget.start(0)
        val first=initial.reserve(working(),start,0) as PhotoPollStep.Ready
        assertEquals(0,initial.attempts);assertEquals(1,first.reserved.attempts);assertEquals(45_000L,first.timeoutMillis)
        val waiting=first.reserved.reserve(working(),start,0) as PhotoPollStep.Wait
        assertEquals(2_000L,waiting.delayMillis);assertEquals(1,first.reserved.attempts)
        val second=first.reserved.reserve(working(),start.plusSeconds(2),2_000_000_000) as PhotoPollStep.Ready
        assertEquals(2,second.reserved.attempts)
    }
    @Test fun workerMayStillRunAfterQueueDeadlineButAutomaticReadsHaveAnAbsoluteServerEnd() {
        val running=working();val afterQueue=running.queueDeadline.plusSeconds(10)
        assertTrue(PhotoPollBudget.start(0).reserve(running,afterQueue,0) is PhotoPollStep.Ready)
        stopped(PhotoPollBudget.start(0).reserve(running,running.queueDeadline.plusSeconds(120),0),PhotoPollStep.Reason.SERVER_DEADLINE)
        val nearEnd=PhotoPollBudget.start(0).reserve(running,running.queueDeadline.plusSeconds(119).plusMillis(500),0) as PhotoPollStep.Ready
        assertEquals(500L,nearEnd.timeoutMillis)
    }
    @Test fun localMonotonicDeadlineStopsPollingEvenWhenWallClockMovesBackwards() {
        val budget=PhotoPollBudget.start(0)
        stopped(budget.reserve(working(),start.minusSeconds(3600),120_000_000_000),PhotoPollStep.Reason.LOCAL_DEADLINE)
        stopped(budget.reserve(working(),start,-1),PhotoPollStep.Reason.CLOCK)
        assertTrue(PhotoPollBudget.start(-100).reserve(working(),start,-100) is PhotoPollStep.Ready)
    }
    @Test fun sharedRetryAfterIsNeverShortenedOrAllowedToExtendThePollWindow() {
        val budget=PhotoPollBudget.start(0)
        val wait=budget.reserve(working(),start,0,start.plusSeconds(30).toEpochMilli()) as PhotoPollStep.Wait
        assertEquals(30_000L,wait.delayMillis);assertEquals(0,budget.attempts)
        stopped(budget.reserve(working(),start,0,start.plusSeconds(120).toEpochMilli()),PhotoPollStep.Reason.BACKOFF_OUTSIDE_WINDOW)
        stopped(budget.reserve(working(),start,0,Long.MIN_VALUE),PhotoPollStep.Reason.CLOCK)
    }
    @Test fun terminalReadsNeverAuthorizeMoreAutomaticRequestsAndExpiryAlsoStopsWork() {
        val budget=PhotoPollBudget.start(0)
        for(read in listOf(read(json()),failure(),failure(true))) stopped(budget.reserve(read,start,0),PhotoPollStep.Reason.TERMINAL)
        val expired=json().put("state","running").put("proposal",JSONObject.NULL).put("photo_expires_at",start.toString())
        stopped(budget.reserve(read(expired),start,0),PhotoPollStep.Reason.SERVER_DEADLINE)
    }
    @Test fun readBudgetAndBackoffCannotCreateAnUnboundedLoop() {
        var budget=PhotoPollBudget.start(0);var elapsed=0L;var reads=0;var stop=false
        repeat(40) {
            if(!stop) when(val step=budget.reserve(working(),start.plusMillis(elapsed),elapsed*1_000_000)) {
                is PhotoPollStep.Ready->{reads++;budget=step.reserved;assertTrue(step.timeoutMillis in 1..45_000)}
                is PhotoPollStep.Wait->elapsed+=step.delayMillis
                is PhotoPollStep.Stop->stop=true
            }
        }
        assertTrue(stop);assertTrue(reads in 1..PhotoPollBudget.MAX_READS);assertTrue(elapsed<=120_000)
        assertEquals(reads,budget.attempts);assertEquals("PhotoPollBudget(redacted)",budget.toString())
    }
}
