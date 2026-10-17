package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.Instant
import java.time.ZoneId

class PhotoConfirmationTest {
    private val key="44444444-4444-4444-8444-444444444444"
    private val epoch="55555555-5555-4555-8555-555555555555"
    private val meal="11111111-1111-4111-8111-111111111111"
    private val item="22222222-2222-4222-8222-222222222222"
    private fun fixture(name:String)=checkNotNull(javaClass.getResource("/photo/$name.json")).readText()
    private fun json(name:String)=JSONObject(fixture(name))
    private fun bytes(value:JSONObject)=value.toString().toByteArray(Charsets.UTF_8)
    private fun base():PhotoAnalysisSnapshot {
        val s=PhotoAnalysisSnapshot.read(fixture("create-accepted"),"mock").withRead(bytes(json("analysis-read-succeeded")))
        val d=PhotoMealDraft.create(s.latest!!,meal,listOf(item),Instant.parse("2026-10-17T12:00:00Z"),ZoneId.of("Europe/Warsaw"))
        return s.withMealDraft(d,0).withMealDraft(d.replace(item,PhotoDraftInput("Poprawiony banan","150,5","g","91.2","0","","22.8")),1)
    }
    private fun frozen()=base().prepareConfirmation(key,2,2)
    private fun attempted()=frozen().markConfirmationAttempted()
    private fun restart(s:PhotoAnalysisSnapshot)=PhotoAnalysisSnapshot.read(s.serialized,"mock")
    private fun receipt()=json("corrected-meal-confirmed")
    private fun mealItem(value:JSONObject)=value.getJSONObject("meal").getJSONObject("payload").getJSONArray("items").getJSONObject(0)
    private fun rejected(action:()->Unit) {val e=assertThrows(IllegalArgumentException::class.java,action);assertNull(e.cause)}
    private fun cancelled()=json("analysis-read-succeeded").put("revision",3).put("state","failed").put("decision_state","cancelled").put("proposal",JSONObject.NULL).put("error_code","analysis_cancelled")

    @Test fun exactIndependentRequestAndVersionFourRoundTrip() {
        val s=restart(frozen());val r=s.confirmation!!.request(epoch)
        assertEquals("photo-analysis-state-v4",JSONObject(s.serialized).getString("format"))
        assertEquals(key,r.key);assertEquals(epoch,r.epoch);assertEquals(2L,r.expectedRevision)
        assertEquals("/ai/food-analyses/${s.receipt.analysisId}/confirm",r.path);assertEquals("POST",r.method)
        assertEquals("application/json; charset=utf-8",r.contentType)
        assertEquals(StrictJson.canonical(json("corrected-meal-confirm")),StrictJson.canonical(StrictJson.read(r.body())))
        assertFalse(s.canEditProposal);assertFalse(s.confirmation.attempted);assertFalse(s.confirmed)
    }
    @Test fun lostAckRestartKeepsExactKeyBodyAndIdsAndReturnedBodyIsDefensive() {
        val s=attempted();val first=s.confirmation!!.request(epoch);val restored=restart(s)
        assertTrue(restored.confirmation!!.attempted);assertSame(restored.confirmation,restored.confirmation.markAttempted())
        val retry=restored.confirmation.request(epoch);assertEquals(first.key,retry.key);assertArrayEquals(first.body(),retry.body())
        val copy=first.body();copy[0]=0;assertArrayEquals(retry.body(),first.body())
    }
    @Test fun independentReceiptBindsTemplateAndProvenanceAndIsIdempotent() {
        val s=attempted().withConfirmationReceipt(bytes(receipt()));val restored=restart(s)
        assertTrue(restored.confirmed);assertTrue(restored.confirmation!!.confirmed)
        assertEquals(s.serialized,restored.withConfirmationReceipt(bytes(receipt())).serialized)
        assertEquals("0",mealItem(JSONObject(restored.confirmation.receiptJson!!)).getJSONObject("nutrition_per_100").getString("protein_g"))
    }
    @Test fun noReceiptBeforeAttemptOrForAnotherAnalysis() {
        rejected{frozen().withConfirmationReceipt(bytes(receipt()))}
        rejected{attempted().withConfirmationReceipt(bytes(receipt().put("analysis_id",key)))}
    }
    @Test fun responseCannotReplaceMealOrItemOrPortionOrMissingNutrition() {
        val edits:List<(JSONObject)->Unit> = listOf({it.getJSONObject("meal").put("meal_id",key)},
            {mealItem(it).put("item_id",key)},{mealItem(it).getJSONObject("quantity").put("amount","150.6")},
            {mealItem(it).getJSONObject("nutrition_per_100").put("fat_g","0")})
        edits.forEach{edit->val v=receipt();edit(v);rejected{attempted().withConfirmationReceipt(bytes(v))}}
    }
    @Test fun responseCannotInventSourceModelProviderOrUncertainty() {
        val edits:List<(JSONObject)->Unit> = listOf({it.put("model_version","invented")},{it.put("provider","gemini")},
            {it.getJSONArray("uncertainty").getJSONObject(0).put("uncertainty","low")},
            {it.getJSONArray("uncertainty").getJSONObject(0).put("component_id",key)})
        edits.forEach{edit->val v=receipt();edit(v.getJSONObject("provenance"));rejected{attempted().withConfirmationReceipt(bytes(v))}}
    }
    @Test fun extraDraftsExtraFieldsNumericDecimalAndMissingNullableAreRejected() {
        val extra=receipt();extra.getJSONArray("drafts").put(JSONObject());rejected{attempted().withConfirmationReceipt(bytes(extra))}
        rejected{attempted().withConfirmationReceipt(bytes(receipt().put("revision",3)))}
        val numeric=receipt();mealItem(numeric).getJSONObject("nutrition_per_100").put("energy_kcal",91.2)
        rejected{attempted().withConfirmationReceipt(bytes(numeric))}
        val missing=receipt();missing.getJSONObject("meal").getJSONObject("payload").remove("ration");rejected{attempted().withConfirmationReceipt(bytes(missing))}
    }
    @Test fun duplicateOversizeDeepJsonAndPrivateDiagnosticAreRejected() {
        val duplicate=receipt().toString().replaceFirst("{","{\"analysis_id\":\"$key\",")
        rejected{attempted().withConfirmationReceipt(duplicate.toByteArray())}
        rejected{attempted().withConfirmationReceipt(ByteArray(PhotoConfirmation.MAX_RECEIPT_BYTES+1))}
        rejected{attempted().withConfirmationReceipt(("{\"x\":"+"[".repeat(50)+"0"+"]".repeat(50)+"}").toByteArray())}
        assertEquals("PhotoConfirmation(redacted)",attempted().confirmation.toString())
        assertEquals("PhotoHttpRequest(redacted)",attempted().confirmation!!.request(epoch).toString())
    }
    @Test fun frozenDecisionRefusesEditDiscardAndCompetingDecisions() {
        val s=frozen();rejected{s.withoutMealDraft(2)};rejected{s.withMealDraft(s.mealDraft!!.rename("Late"),2)}
        rejected{s.prepareCancellation(epoch,2)};rejected{s.prepareConfirmation(epoch,2,2)}
    }
    @Test fun staleProposalEditAndExistingCancellationCannotFreezeAnotherDecision() {
        rejected{base().prepareConfirmation(key,1,2)};rejected{base().prepareConfirmation(key,2,1)}
        rejected{base().prepareCancellation(key,2).prepareConfirmation(epoch,2,2)}
    }
    @Test fun acceptedReceiptFencesOldPendingGetAndRejectsConflictingTerminalState() {
        val s=attempted().withConfirmationReceipt(bytes(receipt()))
        assertSame(s,s.withRead(bytes(json("analysis-read-succeeded"))))
        rejected{s.withRead(bytes(json("analysis-read-succeeded").put("revision",3)))};rejected{s.withRead(bytes(cancelled()))}
        val confirmed=json("analysis-read-succeeded").put("revision",3).put("decision_state","confirmed")
        assertEquals("confirmed",restart(s.withRead(bytes(confirmed))).latest!!.decision)
    }
    @Test fun confirmedGetWithoutAckKeepsUncertainDecisionForExactReplay() {
        val read=json("analysis-read-succeeded").put("revision",3).put("decision_state","confirmed")
        val s=restart(attempted().withRead(bytes(read)));assertTrue(s.confirmed);assertTrue(s.confirmation!!.pending)
        assertArrayEquals(attempted().confirmation!!.request(epoch).body(),s.markConfirmationAttempted().confirmation!!.request(epoch).body())
        assertTrue(restart(s.withConfirmationReceipt(bytes(receipt()))).confirmation!!.confirmed)
    }
    @Test fun cancelledGetWithoutAckRetainsReadOnlyDecisionButRejectsLaterReceipt() {
        val s=restart(attempted().withRead(bytes(cancelled())));assertTrue(s.cancelled);assertFalse(s.canEditProposal)
        assertTrue(s.confirmation!!.pending);rejected{s.markConfirmationAttempted()};rejected{s.withConfirmationReceipt(bytes(receipt()))}
    }
    @Test fun definitiveRejectionCannotBeSilentlyRetriedRekeyedOrEdited() {
        val s=restart(attempted().rejectConfirmation("proposal_revision_conflict"))
        assertEquals("proposal_revision_conflict",s.confirmation!!.rejectedCode);assertFalse(s.canEditProposal)
        rejected{s.markConfirmationAttempted()};rejected{s.prepareConfirmation(epoch,2,2)};rejected{s.withConfirmationReceipt(bytes(receipt()))}
    }
    @Test fun persistedTemplateAndProvenanceAreCheckedAgainstOriginalDraftAndProposal() {
        val s=JSONObject(frozen().serialized);s.getJSONObject("confirmation").getJSONObject("request").getJSONObject("meal").put("meal_id",key)
        rejected{PhotoAnalysisSnapshot.read(s.toString(),"mock")}
        val p=JSONObject(frozen().serialized);p.getJSONObject("confirmation").getJSONObject("expected_provenance").put("model","invented")
        rejected{PhotoAnalysisSnapshot.read(p.toString(),"mock")}
    }
    @Test fun otherConfirmedDecisionAfterGetCanRecordDefinitiveRejectionWithoutAcceptingAMeal() {
        val read=json("analysis-read-succeeded").put("revision",3).put("decision_state","confirmed")
        val uncertain=attempted().withRead(bytes(read))
        val rejected=restart(uncertain.rejectConfirmation("analysis_already_confirmed"))
        assertEquals("analysis_already_confirmed",rejected.confirmation!!.rejectedCode)
        assertNull(rejected.confirmation.receiptJson);assertTrue(rejected.confirmed)
        assertFalse(rejected.canEditProposal)
    }
}