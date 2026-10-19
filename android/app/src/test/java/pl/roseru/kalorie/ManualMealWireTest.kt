package pl.roseru.kalorie

import java.math.BigDecimal
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*

class ManualMealWireTest {
    private val schema=SyncWireSchema(SyncWireSchema.FILES.associateWith {javaClass.getResourceAsStream("/sync/$it")!!.use {s->s.readBytes()}})
    private val item="11111111-1111-4111-8111-111111111111"
    private val nutrition=ExactNutrition(BigDecimal("100.5"),null,BigDecimal.ZERO,BigDecimal("12.345678"))
    private fun wire(amount:String="150.000001",name:String="Własny posiłek",unit:String="g",type:String="lunch",
        nutrients:ExactNutrition=nutrition,time:String="2026-10-19T22:30:00.123456789Z",zone:String="Europe/Warsaw")=
        ManualMealWire.create(name,item,amount,unit,nutrients,time,zone,type,schema)
    private fun first(value:MealWire)=value.json().getJSONArray("items").getJSONObject(0)

    @Test fun manualSnapshotHasNoInventedCatalogueIdentityAndPreservesExactNutrition() {
        val value=wire();val row=first(value)
        assertTrue(row.isNull("product"));assertEquals("manual",row.getString("nutrition_origin"))
        assertEquals(item,row.getString("item_id"));assertEquals("150.000001",row.getJSONObject("quantity").getString("amount"))
        assertTrue(row.getJSONObject("nutrition_per_100").isNull("protein_g"))
        assertEquals("0",row.getJSONObject("nutrition_per_100").getString("fat_g"))
        assertEquals("12.345678",row.getJSONObject("nutrition_per_100").getString("carbs_g"))
        assertTrue(value.json().isNull("ration"));assertTrue(value.json().isNull("goal_id"))
    }
    @Test fun nanoTimeIsTruncatedToContractPrecisionWithoutMovingLocalDate() {
        val value=wire().json()
        assertEquals("2026-10-19T22:30:00.123456Z",value.getString("occurred_at"))
        assertEquals("2026-10-20",value.getString("local_date"))
    }
    @Test fun millilitresAreKeptAsMillilitresWithoutInventedDensity() {
        val row=first(wire(unit="ml",amount="25,5"))
        assertEquals("ml",row.getString("basis_unit"));assertEquals("ml",row.getJSONObject("quantity").getString("unit"))
        assertTrue(row.isNull("density_g_per_ml"));assertTrue(row.isNull("density_source"))
        assertEquals("25.6275",MealWire.consumed(StrictJson.canonical(row)).asExact().energy.canonical)
    }
    @Test fun allExistingMealTypesAndDstFoldsRetainDeclaredMeaning() {
        for(type in MealType.entries)assertEquals(type.name.lowercase(),wire(type=type.name.lowercase()).json().getString("meal_type"))
        assertEquals("2026-10-25",wire(time="2026-10-25T00:30:00Z").json().getString("local_date"))
        assertEquals("2026-10-25",wire(time="2026-10-25T01:30:00Z").json().getString("local_date"))
    }
    @Test fun excessPrecisionIsRejectedRatherThanRoundedForWire() {
        assertThrows(SyncWireException::class.java){wire(amount="1.0000001")}
        assertThrows(SyncWireException::class.java){wire(nutrients=nutrition.copy(energy=BigDecimal("1.0000001")))}
        assertThrows(SyncWireException::class.java){wire(amount="0")}
    }
    @Test fun invalidNamesUnitsOrTypesAreRejectedByTheActualContract() {
        for(name in listOf("", "x".repeat(201), "bad\u0000name"))assertThrows(SyncWireException::class.java){wire(name=name)}
        assertThrows(SyncWireException::class.java){wire(unit="kg")}
        assertThrows(SyncWireException::class.java){wire(type="untrusted")}
        assertThrows(SyncWireException::class.java){wire(zone="invalid-zone")}
    }
    @Test fun ordinaryPayloadCreatesAValidIndependentMealOperation() {
        val value=wire();val text=MealWire.operation("22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333","44444444-4444-4444-8444-444444444444",null,value.canonical,schema)
        val request=StrictJson.read(text.toByteArray())
        assertEquals("upsert",request.getString("action"));assertTrue(request.isNull("base_revision"))
        assertEquals(value.canonical,StrictJson.canonical(request.getJSONObject("payload")))
    }
    @Test fun exactEnergyUsesTheSharedFormulaAndReturnedJsonCannotMutateTheWire() {
        val value=wire(amount="150");val row=first(value)
        assertEquals("150.75",MealWire.consumed(StrictJson.canonical(row)).asExact().energy.canonical)
        row.put("name","changed");assertEquals("Własny posiłek",first(value).getString("name"))
    }
}
