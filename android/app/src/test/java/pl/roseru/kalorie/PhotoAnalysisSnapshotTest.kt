package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*

class PhotoAnalysisSnapshotTest {
    private fun fixture(name:String)=checkNotNull(javaClass.getResource("/photo/$name.json")).readText()
    private fun ack()=fixture("create-accepted")
    private fun result()=JSONObject(fixture("analysis-read-succeeded"))
    private fun encoded(value:JSONObject)=value.toString().toByteArray(Charsets.UTF_8)
    private fun base()=PhotoAnalysisSnapshot.read(ack(),"mock")
    private fun working(revision:Int=2)=result().put("state","running").put("revision",revision).put("proposal",JSONObject.NULL)
    private fun bad(action:()->Unit) {
        val error=assertThrows(PhotoAnalysisSnapshotException::class.java,action)
        assertEquals("Niepoprawny zapis analizy zdjęcia",error.message);assertNull(error.cause)
    }

    @Test fun legacyAckDoesNotNeedAnImageAndIsNotRewrittenUntilAReadArrives() {
        val saved=base();assertEquals(ack(),saved.serialized);assertNull(saved.latest)
        assertEquals("c7777777-7777-4777-8777-777777777777",saved.receipt.analysisId)
        saved.requireSameReceipt(encoded(JSONObject(ack())))
        assertEquals("PhotoAnalysisSnapshot(redacted)",saved.toString())
    }
    @Test fun restartRestoresOriginalAckAndTheCompleteProposal() {
        val saved=base().withRead(encoded(result()))
        val restored=PhotoAnalysisSnapshot.read(saved.serialized,"mock")
        assertEquals(saved.serialized,restored.serialized);assertEquals(1L,restored.receipt.revision)
        assertEquals(2L,restored.latest!!.revision);assertEquals("Banan",restored.latest.proposal!!.items.single().name)
        assertEquals("106.8",restored.latest.proposal.totals.energy.canonical)
        restored.requireSameReceipt(ack().toByteArray(Charsets.UTF_8))
        assertFalse(restored.toString().contains("Banan"))
    }
    @Test fun staleAndIdenticalReadsKeepTheSameSerializedSnapshotAfterRestart() {
        val saved=PhotoAnalysisSnapshot.read(base().withRead(encoded(working(4))).serialized,"mock")
        assertSame(saved,saved.withRead(encoded(working(3))))
        assertSame(saved,saved.withRead(encoded(working(4))))
    }
    @Test fun conflictingSameRevisionCannotReplaceSavedProposal() {
        val saved=base().withRead(encoded(result()));val changed=result()
        changed.getJSONObject("proposal").getJSONArray("notes").put("private-proposal-change")
        bad {saved.withRead(encoded(changed))};assertEquals("Banan",saved.latest!!.proposal!!.items.single().name)
    }
    @Test fun repeatedCreateCannotReplaceTheAckOrEraseTheLatestRead() {
        val saved=base().withRead(encoded(result()));val before=saved.serialized
        for(field in listOf("analysis_id","revision","state","queue_deadline")) {
            val changed=JSONObject(ack()).put(field,when(field) {
                "analysis_id"->"12345678-1234-5678-9234-123456789abc"
                "revision"->2;"state"->"running";else->"2026-10-11T18:00:00Z"
            })
            bad {saved.requireSameReceipt(encoded(changed))}
        }
        saved.requireSameReceipt(ack().toByteArray());assertEquals(before,saved.serialized)
    }
    @Test fun firstReadCannotRegressAStateAlreadyPresentInCreateAck() {
        for(state in listOf("running","succeeded","failed")) {
            val saved=PhotoAnalysisSnapshot.read(JSONObject(ack()).put("state",state).toString(),"mock")
            bad {saved.withRead(encoded(working().put("state","queued")))}
            if(state!="running") bad {saved.withRead(encoded(working()))}
        }
    }
    @Test fun cancellationAndConfirmationRemainFinalAcrossRestarts() {
        val succeeded=base().withRead(encoded(result()))
        val confirmed=succeeded.withRead(encoded(result().put("revision",3).put("decision_state","confirmed")))
        val restored=PhotoAnalysisSnapshot.read(confirmed.serialized,"mock")
        bad {restored.withRead(encoded(result().put("revision",4)))}
        val cancelled=succeeded.withRead(encoded(result().put("revision",3).put("state","failed")
            .put("decision_state","cancelled").put("proposal",JSONObject.NULL).put("error_code","analysis_cancelled")))
        assertNull(PhotoAnalysisSnapshot.read(cancelled.serialized,"mock").latest!!.proposal)
        bad {cancelled.withRead(encoded(result().put("revision",4)))}
    }
    @Test fun envelopeRejectsUnknownVersionFieldsAndNonObjects() {
        val saved=JSONObject(base().withRead(encoded(result())).serialized)
        for(value in listOf("v2",1,JSONObject.NULL)) bad {PhotoAnalysisSnapshot.read(JSONObject(saved.toString()).put("format",value).toString(),"mock")}
        bad {PhotoAnalysisSnapshot.read(JSONObject(saved.toString()).put("extra",true).toString(),"mock")}
        bad {PhotoAnalysisSnapshot.read(JSONObject(saved.toString()).put("create",JSONObject.NULL).toString(),"mock")}
        bad {PhotoAnalysisSnapshot.read(JSONObject(saved.toString()).put("latest","private").toString(),"mock")}
    }
    @Test fun envelopeWithoutLatestReadKeepsTheImmutableAck() {
        val saved=JSONObject(base().withRead(encoded(result())).serialized).put("latest",JSONObject.NULL)
        val restored=PhotoAnalysisSnapshot.read(saved.toString(),"mock")
        assertNull(restored.latest);restored.requireSameReceipt(ack().toByteArray())
    }
    @Test fun providerIdentityAndAckBindingAreRevalidatedAfterRestart() {
        val saved=base().withRead(encoded(result()))
        bad {PhotoAnalysisSnapshot.read(saved.serialized,"gemini")}
        bad {PhotoAnalysisSnapshot.read(saved.serialized,"other")}
        val changed=JSONObject(saved.serialized);changed.getJSONObject("latest").put("analysis_id","12345678-1234-5678-9234-123456789abc")
        bad {PhotoAnalysisSnapshot.read(changed.toString(),"mock")}
        changed.getJSONObject("latest").put("analysis_id",saved.receipt.analysisId)
        changed.getJSONObject("create").put("state","failed")
        bad {PhotoAnalysisSnapshot.read(changed.toString(),"mock")}
    }
    @Test fun duplicateKeysMalformedUtf8AndUnpairedSurrogatesAreRejectedWithoutPrivateCause() {
        val duplicate=ack().replaceFirst("{","{\"revision\":1,")
        bad {PhotoAnalysisSnapshot.read(duplicate,"mock")}
        bad {base().withRead(byteArrayOf(0xc3.toByte(),0x28))}
        bad {PhotoAnalysisSnapshot.read(ack()+"\uD800","mock")}
        bad {base().requireSameReceipt("{\"private\":\"secret\"}".toByteArray())}
    }
    @Test fun sizeLimitsAreAppliedBeforeParsingAndDoNotModifyTheSnapshot() {
        val saved=base()
        bad {PhotoAnalysisSnapshot.read(" ".repeat(PhotoAnalysisSnapshot.MAX_STORED_BYTES+1),"mock")}
        bad {saved.withRead(ByteArray(PhotoAnalysisReadProtocol.MAX_BYTES+1))}
        bad {saved.requireSameReceipt(ByteArray(65_537))}
        assertEquals(ack(),saved.serialized)
    }
}
