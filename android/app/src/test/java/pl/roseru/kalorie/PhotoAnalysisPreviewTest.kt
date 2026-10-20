package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.session.*

class PhotoAnalysisPreviewTest {
    private fun json()=JSONObject(checkNotNull(javaClass.getResource("/photo/analysis-read-succeeded.json")).readText())
    private fun preview(json:JSONObject):PhotoAnalysisPreview {
        val ack=checkNotNull(javaClass.getResource("/photo/create-accepted.json")).readText()
        val snapshot=PhotoAnalysisSnapshot.read(ack,"mock").withRead(json.toString().toByteArray())
        return PhotoAnalysisPreview.from(snapshot.latest!!)
    }
    @Test fun projectsExactPortionAndRoundedNutritionWithoutLosingUncertainty() {
        val view=preview(json());val item=view.items.single()
        assertEquals("succeeded",view.state);assertEquals("pending",view.decision);assertEquals(2L,view.revision)
        assertEquals("Banan",item.name);assertEquals("120",item.amount);assertEquals("g",item.unit)
        assertEquals("107",item.nutrition.energy.display);assertEquals("1.3",item.nutrition.protein.display)
        assertEquals(0,item.nutrition.energy.missingCount);assertEquals("medium",item.uncertainty)
        assertEquals("107",view.nutrition!!.energy.display);assertEquals("mock",view.provider)
    }
    @Test fun missingNutrientRemainsExplicitlyIncompleteInBothItemAndTotal() {
        val value=json();val proposal=value.getJSONObject("proposal")
        proposal.getJSONArray("items").getJSONObject(0).getJSONObject("nutrition_per_100").put("energy_kcal",JSONObject.NULL)
        proposal.getJSONArray("items").getJSONObject(0).getJSONObject("matches").getJSONArray("missing_identity_fields").put("energy_kcal")
        proposal.getJSONObject("totals").getJSONObject("energy_kcal").put("known_sum","0").put("missing_count",1)
            .put("complete",false).put("display","0")
        val view=preview(value)
        assertEquals(1,view.items.single().nutrition.energy.missingCount);assertEquals(1,view.nutrition!!.energy.missingCount)
        assertEquals(0,view.nutrition.protein.missingCount)
    }
    @Test fun workingFailureAndCancellationCannotInventAProposal() {
        val running=preview(json().put("state","running").put("proposal",JSONObject.NULL))
        assertNull(running.nutrition);assertTrue(running.items.isEmpty())
        val cancelled=preview(json().put("state","failed").put("decision_state","cancelled")
            .put("proposal",JSONObject.NULL).put("error_code","analysis_cancelled"))
        assertEquals("cancelled",cancelled.decision);assertTrue(cancelled.items.isEmpty());assertNull(cancelled.nutrition)
    }
    @Test fun collectionsAreImmutableAndObjectStringsNeverContainMealData() {
        val view=preview(json());val item=view.items.single()
        assertThrows(UnsupportedOperationException::class.java){(view.items as MutableList).clear()}
        assertThrows(UnsupportedOperationException::class.java){(view.notes as MutableList).add("changed")}
        assertThrows(UnsupportedOperationException::class.java){(item.notes as MutableList).add("changed")}
        for(value in listOf(view,item,item.nutrition,item.nutrition.energy)) {
            assertFalse(value.toString().contains("Banan"));assertTrue(value.toString().contains("redacted"))
        }
    }
}
