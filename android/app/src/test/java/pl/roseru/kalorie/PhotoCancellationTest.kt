package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*

class PhotoCancellationTest {
    private val key="10101010-1010-4010-8010-101010101010"
    private val other="20202020-2020-4020-8020-202020202020"
    private val epoch="30303030-3030-4030-8030-303030303030"
    private fun fixture(name:String)=checkNotNull(javaClass.getResource("/photo/$name.json")).readText()
    private fun result()=JSONObject(fixture("analysis-read-succeeded"))
    private fun bytes(json:JSONObject)=json.toString().toByteArray(Charsets.UTF_8)
    private fun base()=PhotoAnalysisSnapshot.read(fixture("create-accepted"),"mock").withRead(bytes(result()))
    private fun pending()=base().prepareCancellation(key,2)
    private fun ack(revision:Int=3)=JSONObject().put("analysis_id",base().receipt.analysisId).put("revision",revision)
        .put("state","failed").put("decision_state","cancelled").put("error_code","analysis_cancelled")
    private fun cancelled(revision:Int=3)=result().put("revision",revision).put("state","failed")
        .put("decision_state","cancelled").put("proposal",JSONObject.NULL).put("error_code","analysis_cancelled")
    private fun restart(value:PhotoAnalysisSnapshot)=PhotoAnalysisSnapshot.read(value.serialized,"mock")
    private fun bad(block:()->Unit) {
        val error=assertThrows(PhotoAnalysisSnapshotException::class.java,block)
        assertNull(error.cause);assertEquals("Niepoprawny zapis analizy zdjęcia",error.message)
    }
    @Test fun exactDecisionAndWireSurviveRestartAndNewerWorkerRead() {
        val saved=pending();assertEquals("photo-analysis-state-v2",JSONObject(saved.serialized).getString("format"))
        assertFalse(saved.cancellation!!.attempted);assertNull(saved.cancellation.confirmedRevision)
        val restored=restart(saved);val first=restored.cancellation!!.request(epoch,restored.receipt.analysisId)
        assertEquals(key,first.key);assertEquals(epoch,first.epoch);assertEquals("{\"expected_revision\":2}",String(first.body()))
        val read=restored.withRead(bytes(result().put("revision",3)))
        val second=restart(read).cancellation!!.request(epoch,read.receipt.analysisId)
        assertEquals(first.key,second.key);assertArrayEquals(first.body(),second.body())
        assertEquals(2L,second.expectedRevision);assertEquals(3L,read.latest!!.revision)
    }
    @Test fun preparedAndAttemptedIntentNeverDisappearOnCreateReplay() {
        val saved=restart(pending().markCancellationAttempted())
        assertTrue(saved.cancellation!!.attempted);assertSame(saved,saved.markCancellationAttempted())
        saved.requireSameReceipt(fixture("create-accepted").toByteArray())
        assertEquals(key,restart(saved).cancellation!!.key);assertEquals("Banan",saved.latest!!.proposal!!.items.single().name)
    }
    @Test fun cancellationRequiresExactDisplayedRevisionAndAnUnresolvedRead() {
        bad {base().prepareCancellation(key,1)};bad {base().prepareCancellation(key,3)}
        bad {PhotoAnalysisSnapshot.read(fixture("create-accepted"),"mock").prepareCancellation(key,1)}
        bad {base().withRead(bytes(result().put("revision",3).put("decision_state","confirmed"))).prepareCancellation(key,3)}
        bad {base().withRead(bytes(cancelled())).prepareCancellation(key,3)}
        bad {pending().prepareCancellation(other,2)}
    }
    @Test fun currentDecisionMayCancelQueuedRunningFailedOrSucceeded() {
        for(state in listOf("queued","running","failed","succeeded")) {
            val json=result().put("state",state)
            if(state!="succeeded")json.put("proposal",JSONObject.NULL)
            if(state=="failed")json.put("error_code","provider_unavailable")
            val read=PhotoAnalysisSnapshot.read(fixture("create-accepted"),"mock").withRead(bytes(json))
            assertTrue(read.prepareCancellation(key,2).cancellation!!.pending)
        }
    }
    @Test fun ackIsBoundToAttemptIdentityStateAndRevisionThenRemainsStable() {
        bad {pending().withCancellationReceipt(bytes(ack()))}
        val sent=pending().markCancellationAttempted()
        for(change in listOf(ack().put("analysis_id",other),ack().put("revision",1),ack().put("state","succeeded"),
            ack().put("decision_state","confirmed"),ack().put("error_code","other"),ack().put("extra",true),ack(2)))
            bad {sent.withCancellationReceipt(bytes(change))}
        val accepted=restart(sent.withCancellationReceipt(bytes(ack())))
        assertTrue(accepted.cancelled);assertEquals(3L,accepted.cancellation!!.confirmedRevision)
        assertSame(accepted,accepted.withCancellationReceipt(bytes(ack())))
        bad {accepted.withCancellationReceipt(bytes(ack(4)))}
        bad {accepted.prepareCancellation(other,2)};bad {accepted.markCancellationAttempted()}
    }
    @Test fun cancelAckCannotBeOverwrittenByStalePendingOrContradictoryGet() {
        val accepted=restart(pending().markCancellationAttempted().withCancellationReceipt(bytes(ack())))
        assertSame(accepted,accepted.withRead(bytes(result())))
        bad {accepted.withRead(bytes(result().put("revision",3)))}
        bad {accepted.withRead(bytes(result().put("revision",4).put("decision_state","confirmed")))}
        val final=restart(accepted.withRead(bytes(cancelled())))
        assertEquals("cancelled",final.latest!!.decision);assertTrue(final.cancelled)
        assertNull(final.latest.proposal);assertEquals(3L,final.cancellation!!.confirmedRevision)
    }
    @Test fun readCanProveCancellationWithoutInventingAMutationReceipt() {
        val sent=restart(pending().markCancellationAttempted()).withRead(bytes(cancelled()))
        assertTrue(sent.cancelled);assertNull(sent.cancellation!!.receiptJson)
        assertEquals(key,restart(sent).cancellation!!.key)
        val withoutIntent=base().withRead(bytes(cancelled()));assertTrue(withoutIntent.cancelled);assertNull(withoutIntent.cancellation)
    }
    @Test fun oldAckMayReplayAfterANewerCancelledReadWithoutRegressingIt() {
        val saved=pending().markCancellationAttempted().withRead(bytes(cancelled(4)))
        val restored=restart(saved.withCancellationReceipt(bytes(ack())))
        assertEquals(4L,restored.latest!!.revision);assertEquals(3L,restored.cancellation!!.confirmedRevision)
    }
    @Test fun revisionRejectionRequiresANewerGetAndNewExplicitKey() {
        val rejected=restart(pending().markCancellationAttempted().rejectCancellation("proposal_revision_conflict"))
        assertEquals("proposal_revision_conflict",rejected.cancellation!!.rejectedCode)
        bad {rejected.prepareCancellation(other,2)};bad {rejected.markCancellationAttempted()}
        val newer=restart(rejected.withRead(bytes(result().put("revision",3))))
        bad {newer.prepareCancellation(key,3)}
        val fresh=restart(newer.prepareCancellation(other,3))
        assertEquals(other,fresh.cancellation!!.key);assertEquals(3L,fresh.cancellation.expectedRevision)
        assertFalse(fresh.cancellation.attempted);assertNull(fresh.cancellation.rejectedCode)
    }
    @Test fun definitiveRejectionCannotSilentlyRotateKeyOrBeTurnedIntoSuccess() {
        for(code in listOf("idempotency_key_reused","photo_cancel_rejected","analysis_already_confirmed")) {
            val saved=restart(pending().markCancellationAttempted().rejectCancellation(code))
            bad {saved.withCancellationReceipt(bytes(ack()))}
            bad {saved.withRead(bytes(result().put("revision",3))).prepareCancellation(other,3)}
        }
        bad {pending().rejectCancellation("proposal_revision_conflict")}
        bad {pending().markCancellationAttempted().rejectCancellation("private-invalid-code")}
    }
    @Test fun invalidEnvelopeTypesAndReceiptsAreRejectedWithoutPrivateCauses() {
        val saved=pending().markCancellationAttempted()
        val changes=listOf("key" to "private-key","expected_revision" to "2","expected_revision" to 0,
            "attempted" to "true","receipt" to "private-reply","rejected_code" to "private-code")
        for((key,value) in changes) {
            val json=JSONObject(saved.serialized);json.getJSONObject("cancellation").put(key,value)
            bad {PhotoAnalysisSnapshot.read(json.toString(),"mock")}
        }
        // JSONObject serializes Double2.0 as2; retain the decimal spelling in the actual wire.
        val decimal=saved.serialized.replace("\"expected_revision\":2","\"expected_revision\":2.0")
        assertNotEquals(saved.serialized,decimal)
        bad {PhotoAnalysisSnapshot.read(decimal,"mock")}
        val missing=JSONObject(saved.serialized).put("latest",JSONObject.NULL)
        bad {PhotoAnalysisSnapshot.read(missing.toString(),"mock")}
        val unknown=JSONObject(saved.serialized);unknown.getJSONObject("cancellation").put("extra",true)
        bad {PhotoAnalysisSnapshot.read(unknown.toString(),"mock")}
        val wrong=JSONObject(saved.withCancellationReceipt(bytes(ack())).serialized)
        wrong.getJSONObject("cancellation").getJSONObject("receipt").put("analysis_id",other)
        bad {PhotoAnalysisSnapshot.read(wrong.toString(),"mock")}
    }
    @Test fun legacyAndV1KeepTheirFormatUntilUserActuallyPreparesCancellation() {
        val ack=PhotoAnalysisSnapshot.read(fixture("create-accepted"),"mock")
        assertFalse(JSONObject(ack.serialized).has("format"))
        val read=ack.withRead(bytes(result()));assertEquals("photo-analysis-state-v1",JSONObject(read.serialized).getString("format"))
        assertNull(restart(read).cancellation)
        val intent=restart(read.prepareCancellation(key,2));assertNotNull(intent.cancellation)
        assertFalse(intent.toString().contains("Banan"));assertEquals("PhotoCancellation(redacted)",intent.cancellation.toString())
    }
}
