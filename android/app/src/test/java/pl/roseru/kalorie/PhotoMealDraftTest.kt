package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.Instant
import java.time.ZoneId

class PhotoMealDraftTest {
    private val meal="11111111-1111-4111-8111-111111111111"
    private val item="22222222-2222-4222-8222-222222222222"
    private val other="33333333-3333-4333-8333-333333333333"
    private val moment=Instant.parse("2026-10-17T12:00:00Z")
    private val zone=ZoneId.of("Europe/Warsaw")
    private fun fixture(name:String)=checkNotNull(javaClass.getResource("/photo/$name.json")).readText()
    private fun result()=JSONObject(fixture("analysis-read-succeeded"))
    private fun bytes(json:JSONObject)=json.toString().toByteArray(Charsets.UTF_8)
    private fun base()=PhotoAnalysisSnapshot.read(fixture("create-accepted"),"mock").withRead(bytes(result()))
    private fun draft()=PhotoMealDraft.create(base().latest!!,meal,listOf(item),moment,zone)
    private fun saved()=base().withMealDraft(draft(),0)
    private fun restart(value:PhotoAnalysisSnapshot)=PhotoAnalysisSnapshot.read(value.serialized,"mock")
    private fun input(name:String="Poprawiony banan",amount:String="150,5",unit:String="g",energy:String="91,200000",
        protein:String="0",fat:String="",carbs:String="22.8")=PhotoDraftInput(name,amount,unit,energy,protein,fat,carbs)
    private fun bad(action:()->Unit) {
        val error=assertThrows(PhotoMealDraftException::class.java,action)
        assertEquals("Niepoprawne poprawki posiłku",error.message);assertNull(error.cause)
    }

    @Test fun stableIdsSourceAndTimestampSurviveStrictRoundTrip() {
        val original=base();val draft=draft();val saved=restart(original.withMealDraft(draft,0))
        assertEquals("photo-analysis-state-v3",JSONObject(saved.serialized).getString("format"))
        assertEquals(meal,saved.mealDraft!!.mealId);assertEquals(item,saved.mealDraft.items.single().id)
        assertEquals("d7777777-7777-4777-8777-777777777777",saved.mealDraft.items.single().sourceComponentId)
        assertEquals("2026-10-17",saved.mealDraft.localDate.toString());assertEquals(zone,saved.mealDraft.zone)
        assertEquals(StrictJson.canonical(draft.journal()),StrictJson.canonical(saved.mealDraft.journal()))
        assertEquals("Banan",original.latest!!.proposal!!.items.single().name)
        saved.requireSameReceipt(fixture("create-accepted").toByteArray())
    }
    @Test fun correctionsUseExactDecimalsAndMissingDoesNotBecomeZero() {
        val old=draft();val revised=old.replace(item,input())
        assertEquals(2L,revised.editRevision);assertEquals("Banan",old.items.single().name)
        assertEquals("150.5",ContractDecimal.canonical(revised.items.single().portion.amount))
        assertEquals("137.256",revised.totals.energy.canonical);assertEquals("137",revised.totals.energy.display)
        assertEquals("0.0",revised.totals.protein.display);assertTrue(revised.totals.protein.complete)
        assertFalse(revised.totals.fat.complete);assertEquals(1,revised.totals.fat.missingCount)
        assertEquals("34.314",revised.totals.carbs.canonical)
    }
    @Test fun allNutritionMayBeMissingWithoutLosingTheItem() {
        val value=draft().replace(item,input(energy="",protein=" ",fat="",carbs=""))
        assertEquals(1,value.items.size);assertTrue(value.totals.fields().all {!it.complete && it.missingCount==1})
    }
    @Test fun badUserQuantitiesNeverCreateOrMutateACorrection() {
        for(amount in listOf("0","-1","1e3","NaN","01","10000.000001","1.1234567",""))bad {draft().replace(item,input(amount=amount))}
        assertEquals("120",ContractDecimal.canonical(draft().items.single().portion.amount))
    }
    @Test fun invalidNutrientsAndTextAreRejectedWithNeutralErrors() {
        for(value in listOf("-1","1e2","NaN","01","1000000","1.1234567"))bad {draft().replace(item,input(energy=value))}
        for(name in listOf(" ","x\u0000y".replace("\\u0000","\u0000"),"\ud800".replace("\\ud800","\ud800"),"x".repeat(2001)))bad {draft().replace(item,input(name=name))}
    }
    @Test fun addRemoveAndRenameKeepExistingIdsAndDoNotTouchTheOriginalProposal() {
        val revised=draft().add(other,input(name="Woda",amount="250",unit="ml",energy="0",protein="0",fat="0",carbs="0"))
        assertEquals(listOf(item,other),revised.items.map {it.id});assertNull(revised.items.last().sourceComponentId)
        val removed=revised.remove(item).rename(" Obiad ")
        assertEquals(other,removed.items.single().id);assertEquals("Obiad",removed.title)
        assertEquals("Banan",base().latest!!.proposal!!.items.single().name)
        bad {removed.remove(other)};bad {revised.add(item,input())};bad {draft().remove(other)}
    }
    @Test fun thirtyItemsAreAllowedButAThirtyFirstOrDuplicateIdIsNot() {
        var value=draft()
        repeat(29) {index->value=value.add("00000000-0000-4000-8000-${(index+1).toString().padStart(12,'0')}",input())}
        assertEquals(30,value.items.size);bad {value.add(other,input())}
    }
    @Test fun aUnitChoiceDefinesPerHundredOfThatUnitWithoutInventingDensity() {
        val value=draft().replace(item,input(amount="250",unit="ml",energy="46",protein="3.4",fat="1.5",carbs="4.8"))
        assertEquals(QuantityUnit.MILLILITRES,value.items.single().portion.basisUnit)
        assertNull(value.items.single().portion.density);assertEquals("115",value.totals.energy.canonical)
    }
    @Test fun returnedJsonAndListsCannotMutateTheStoredDraft() {
        val value=draft();val copy=value.journal();copy.getJSONArray("items").getJSONObject(0).put("name","Changed")
        assertEquals("Banan",value.items.single().name)
        assertThrows(UnsupportedOperationException::class.java){(value.items as MutableList).clear()}
        assertEquals("PhotoMealDraft(redacted)",value.toString());assertEquals("PhotoDraftInput(redacted)",input().toString())
    }
    @Test fun journalRejectsUnknownFieldsNumbersInsteadOfStringsAndMalformedIds() {
        bad {PhotoMealDraft.restore(draft().journal().put("extra","private"))}
        bad {PhotoMealDraft.restore(draft().journal().put("edit_revision","1"))}
        bad {PhotoMealDraft.restore(draft().journal().put("meal_id","bad"))}
        val value=draft().journal();value.getJSONArray("items").getJSONObject(0).put("amount",120)
        bad {PhotoMealDraft.restore(value)}
    }
    @Test fun sourceBindingRejectsAnotherAnalysisProposalOrFutureRevision() {
        for(change in listOf("analysis_id","source_fingerprint","source_revision")) {
            val value=draft().journal().put(change,when(change){"analysis_id"->other;"source_fingerprint"->"0".repeat(64);else->3})
            bad {PhotoMealDraft.restore(value).matches(base().latest!!)}
        }
        val value=draft().journal();value.getJSONArray("items").getJSONObject(0).put("source_component_id",other)
        bad {PhotoMealDraft.restore(value).matches(base().latest!!)}
    }
    @Test fun longRecognizedNamesArePreservedUntilTheUserCorrectsThemForTheMealContract() {
        val read=base().latest!!;val source=read.proposal!!.items.single()
        val long=PhotoProposalItem(source.componentId,"x".repeat(300),source.portion,source.identity,source.uncertainty,source.notes,source.matches)
        val proposal=PhotoProposal(listOf(long),emptyList(),read.proposal.totals,null)
        val changed=PhotoAnalysisRead(read.analysisId,read.revision,read.state,read.decision,read.queueDeadline,read.photoExpiresAt,
            read.profile,proposal,null,read.wireFingerprint,read.proposalFingerprint)
        val value=PhotoMealDraft.create(changed,meal,listOf(item),moment,zone)
        assertEquals(300,value.items.single().name.length);bad {value.confirmBody(changed)}
        assertTrue(value.replace(item,input(name="Poprawiona nazwa")).confirmBody(changed).isNotEmpty())
    }
    @Test fun strictConfirmTemplateHasIndependentExpectedShapeAndDoesNotPublishProducts() {
        val value=draft().replace(item,input())
        val body=StrictJson.read(value.confirmBody(base().latest!!))
        val expected=StrictJson.read(fixture("corrected-meal-confirm").toByteArray())
        assertEquals(StrictJson.canonical(expected),StrictJson.canonical(body))
        assertEquals(0,body.getJSONArray("drafts").length())
        val row=body.getJSONObject("meal").getJSONObject("payload").getJSONArray("items").getJSONObject(0)
        assertTrue(row.isNull("product"));assertEquals("ai_estimate",row.getString("nutrition_origin"));assertTrue(row.isNull("density_g_per_ml"))
    }
    @Test fun snapshotCasRequiresNextLocalRevisionAndPreservesDraftAcrossARead() {
        val saved=saved();assertTrue(saved.canEditProposal)
        assertThrows(PhotoAnalysisSnapshotException::class.java){saved.withMealDraft(draft().replace(item,input()),0)}
        val next=saved.withMealDraft(draft().replace(item,input()),1)
        assertEquals(2L,restart(next).mealDraft!!.editRevision)
        val newer=restart(next.withRead(bytes(result().put("revision",3))))
        assertEquals(2L,newer.mealDraft!!.sourceRevision);assertEquals(2L,newer.mealDraft.editRevision)
        assertEquals(3,StrictJson.read(newer.mealDraft.confirmBody(newer.latest!!)).getInt("expected_revision"))
    }
    @Test fun discardRequiresTheActualEditRevisionAndLeavesOriginalReadIntact() {
        val saved=saved()
        assertThrows(PhotoAnalysisSnapshotException::class.java){saved.withoutMealDraft(2)}
        val cleared=restart(saved.withoutMealDraft(1));assertNull(cleared.mealDraft)
        assertEquals("Banan",cleared.latest!!.proposal!!.items.single().name);assertTrue(cleared.canEditProposal)
    }
    @Test fun pendingCancelAndConfirmedReadFreezeCorrectionsWithoutLosingTheDraft() {
        val saved=saved();val changed=draft().replace(item,input())
        val pending=saved.prepareCancellation(other,2);assertFalse(pending.canEditProposal)
        assertEquals(meal,restart(pending).mealDraft!!.mealId)
        assertThrows(PhotoAnalysisSnapshotException::class.java){pending.withMealDraft(changed,1)}
        val confirmed=restart(saved.withRead(bytes(result().put("revision",3).put("decision_state","confirmed"))))
        assertFalse(confirmed.canEditProposal);assertNotNull(confirmed.mealDraft)
        bad {confirmed.mealDraft!!.confirmBody(confirmed.latest!!)}
    }
    @Test fun cancelledGetRetainsCorrectionsReadOnlyAndCannotRecreateASubmission() {
        val json=result().put("revision",3).put("state","failed").put("decision_state","cancelled")
            .put("proposal",JSONObject.NULL).put("error_code","analysis_cancelled")
        val closed=restart(saved().withRead(bytes(json)))
        assertTrue(closed.cancelled);assertFalse(closed.canEditProposal);assertEquals(meal,closed.mealDraft!!.mealId)
        bad {closed.mealDraft.confirmBody(closed.latest!!)}
    }
    @Test fun timestampPrecisionAndDayFollowTheChosenIanaZone() {
        val value=PhotoMealDraft.create(base().latest!!,meal,listOf(item),Instant.parse("2026-10-17T22:30:00.123456789Z"),zone)
        assertEquals("2026-10-18",value.localDate.toString());assertEquals(123456000,value.occurredAt.nano)
        assertEquals(value.occurredAt,PhotoMealDraft.restore(value.journal()).occurredAt)
        bad {PhotoMealDraft.restore(draft().journal().put("time_zone","+02:00"))}
    }
}
