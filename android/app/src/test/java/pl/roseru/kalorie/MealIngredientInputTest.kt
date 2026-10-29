package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import java.math.BigDecimal

class MealIngredientInputTest {
    private val schema=SyncWireSchema(SyncWireSchema.FILES.associateWith {javaClass.getResourceAsStream("/sync/$it")!!.use {s->s.readBytes()}})
    private val item="11111111-1111-4111-8111-111111111111"
    private fun input(amount:String="250",fields:List<String> = listOf("42","","0","10,123456"),unit:String="ml",basis:String="ml")=
        MealIngredientInput.parse("Napój",amount,unit,basis,fields)
    private fun wire()=ManualMealWire.create("Original",item,"100","g",ExactNutrition(BigDecimal("100"),null,null,null),
        "2026-10-25T01:30:00Z","Europe/Warsaw","lunch",schema)

    @Test fun independentFieldsKeepUnknownAndKnownZeroWithExactSumAndHalfUp() {
        val edit=requireNotNull(input());val result=NutritionV1.calculate(listOf(edit.portion()))
        assertEquals("105",result.energy.canonical);assertEquals("105",result.energy.display)
        assertFalse(result.protein.complete);assertTrue(result.fat.complete);assertEquals("0",result.fat.canonical)
        assertEquals("25.30864",result.carbs.canonical);assertEquals("25.3",result.carbs.display)
        val rounding=NutritionV1.calculate(listOf(requireNotNull(input("150",listOf("1","0.1","0",""))).portion()))
        assertEquals("2",rounding.energy.display);assertEquals("0.2",rounding.protein.display)
    }
    @Test fun blanksAreNullableButMalformedNegativeNonfiniteAndExcessPrecisionAreRejected() {
        assertNotNull(input(fields=List(4){""}))
        for(bad in listOf("-1","NaN","Infinity","1e2","1.0000001","1000000","1,2.3","00.5")) {
            assertNull("nutrient $bad",input(fields=listOf(bad,"","","")))
            assertNull("amount $bad",input(amount=bad))
        }
        for(amount in listOf("0","10000.000001",""))assertNull(input(amount))
        assertNotNull(input("10000",listOf("999999.999999","0.000000","0","")))
        assertNull(MealIngredientInput.parse("", "100","g","g",List(4){""}))
        assertNull(MealIngredientInput.parse("bad\uD800", "100","g","g",List(4){""}))
    }
    @Test fun changingUnitsNeverInventsDensityOrAutomaticallyChangesEnteredNutrition() {
        assertNull(input(unit="g",basis="ml"))
        val edit=MealIngredientInput.parse("Drink","125","g","ml",listOf("42","","0",""),ExactDensity(BigDecimal("1.25"),"label"))!!
        assertEquals("42",ContractDecimal.canonical(edit.nutrition.energy!!))
        assertEquals("42",NutritionV1.calculate(listOf(edit.portion())).energy.canonical)
    }
    @Test fun correctedWirePreservesTimeIdentityOtherIngredientsAndTheOriginalObject() {
        val original=wire();val bytes=original.canonical
        val add="22222222-2222-4222-8222-222222222222"
        val withOther=original.withIngredient(add,requireNotNull(input("100",listOf("10","1","2","3"))),schema,true)
        val other=StrictJson.canonical(withOther.json().getJSONArray("items").getJSONObject(1))
        val corrected=withOther.withIngredient(item,requireNotNull(input()),schema)
        assertEquals(bytes,original.canonical)
        for(field in listOf("occurred_at","time_zone","local_date","meal_type","title","goal_id","ration"))
            assertEquals(withOther.json().get(field).toString(),corrected.json().get(field).toString())
        val rows=corrected.json().getJSONArray("items")
        assertEquals(other,StrictJson.canonical(rows.getJSONObject(1)));assertEquals(item,rows.getJSONObject(0).getString("item_id"))
        assertEquals("manual",rows.getJSONObject(0).getString("nutrition_origin"));assertTrue(rows.getJSONObject(0).isNull("product"))
        assertEquals("105",MealWire.consumed(StrictJson.canonical(rows.getJSONObject(0))).asExact().energy.canonical)
        assertThrows(IllegalArgumentException::class.java){corrected.withIngredient(item,requireNotNull(input()),schema,true)}
    }
    @Test fun substitutionDropsRationMarkerButNutrientCorrectionKeepsIt() {
        val value=wire().json().put("ration",JSONObject().put("ration_id","33333333-3333-4333-8333-333333333333").put("revision",1).put("name","Ration"))
        value.getJSONArray("items").getJSONObject(0).put("ration_component_position",2)
        val original=MealWire.read(StrictJson.canonical(value),schema)
        val edit=requireNotNull(input()).copy(name="Original")
        assertEquals(2,original.withIngredient(item,edit,schema).json().getJSONArray("items").getJSONObject(0).getInt("ration_component_position"))
        assertTrue(original.withIngredient(item,edit.copy(name="Replacement"),schema).json().getJSONArray("items").getJSONObject(0).isNull("ration_component_position"))
    }
}
