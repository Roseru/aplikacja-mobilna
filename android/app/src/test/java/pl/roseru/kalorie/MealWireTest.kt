package pl.roseru.kalorie

import org.json.JSONObject
import org.json.JSONArray
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.core.catalog.StrictJson

class MealWireTest {
    private fun bytes(path:String)=javaClass.getResourceAsStream(path)!!.use {it.readBytes()}
    private val schema=SyncWireSchema(SyncWireSchema.FILES.associateWith {bytes("/sync/$it")})
    private val id="11111111-1111-4111-8111-111111111111"
    private val item="22222222-2222-4222-8222-222222222222"
    private val operation="44444444-4444-4444-8444-444444444444"
    private val epoch="55555555-5555-4555-8555-555555555555"
    private fun payload()=JSONObject(String(bytes("/photo/corrected-meal-confirm.json"))).getJSONObject("meal").getJSONObject("payload")
    private fun read(value:JSONObject=payload())=MealWire.read(value.toString(),schema)
    private fun first(value:JSONObject)=value.getJSONArray("items").getJSONObject(0)
    @Test fun exactIndependentOperationHasNullBaseAndNoProvenanceInPayload() {
        val actual=MealWire.operation(operation,id,epoch,null,read().canonical,schema)
        val expected=StrictJson.canonical(StrictJson.read(bytes("/photo/materialized-meal-operation.json")))
        assertEquals(expected,actual);assertEquals("MealWire(redacted)",read().toString())
    }
    @Test fun missingEnergyAndProductRemainNullAndMissingWhileExplicitProteinZeroIsComplete() {
        val value=payload();first(value).getJSONObject("nutrition_per_100").put("energy_kcal",JSONObject.NULL)
        val exact=MealWire.consumed(StrictJson.canonical(first(read(value).json()))).asExact()
        assertFalse(exact.energy.complete);assertEquals(1,exact.energy.missingCount)
        assertTrue(exact.protein.complete);assertEquals(0,exact.protein.knownSum.signum());assertTrue(first(read(value).json()).isNull("product"))
    }
    @Test fun mlIsNotGuessedAsGramsAndDeclaredDensityConvertsOnlyWhenRequired() {
        val value=payload();first(value).getJSONObject("quantity").put("unit","ml");first(value).put("basis_unit","ml")
        assertEquals("ml",read(value).json().getJSONArray("items").getJSONObject(0).getJSONObject("quantity").getString("unit"))
        first(value).put("basis_unit","g");assertThrows(Exception::class.java){read(value)}
        first(value).put("density_g_per_ml","2").put("density_source","Etykieta")
        assertEquals("274.512",MealWire.consumed(StrictJson.canonical(first(read(value).json()))).asExact().energy.canonical)
    }
    @Test fun quantityEditPreservesNutritionReferencesAndExactDecimal() {
        val original=read();val edited=original.withAmount(item,"123,000001",schema)
        val expected=original.json();first(expected).getJSONObject("quantity").put("amount","123.000001")
        assertEquals(StrictJson.canonical(expected),edited.canonical)
        assertThrows(Exception::class.java){original.withAmount(item,"0",schema)}
        assertThrows(Exception::class.java){original.withAmount(item,"1.0000001",schema)}
    }
    @Test fun removingLastItemRepresentsDeletionAndNeverEmitsEmptyMeal() {
        assertNull(read().without(item,schema));assertThrows(Exception::class.java){read().without(operation,schema)}
    }
    @Test fun itemIdsAreUniqueAndDateMustMatchItsInstantAndZone() {
        val duplicate=payload();duplicate.getJSONArray("items").put(first(payload()));assertThrows(Exception::class.java){read(duplicate)}
        assertThrows(Exception::class.java){read(payload().put("local_date","2026-10-18"))}
    }
    @Test fun missingNullableNumericNutritionAndAdditionalProvenanceAreRejected() {
        val missing=payload();first(missing).remove("density_source");assertThrows(Exception::class.java){read(missing)}
        val numeric=payload();first(numeric).getJSONObject("nutrition_per_100").put("energy_kcal",91)
        assertThrows(Exception::class.java){read(numeric)};assertThrows(Exception::class.java){read(payload().put("provenance",JSONObject()))}
    }
    @Test fun catalogOriginWithoutReferenceOrRationPositionWithoutRationIsInvalid() {
        val value=payload();first(value).put("nutrition_origin","catalog_snapshot");assertThrows(Exception::class.java){read(value)}
        val ration=payload();first(ration).put("ration_component_position",1);assertThrows(Exception::class.java){read(ration)}
    }
    @Test fun deleteRequiresRealServerRevisionAndPayloadIsNull() {
        assertThrows(Exception::class.java){MealWire.operation(operation,id,epoch,null,null,schema)}
        val delete=JSONObject(MealWire.operation(operation,id,epoch,3,null,schema));assertEquals(3,delete.getInt("base_revision"))
        assertEquals("delete",delete.getString("action"));assertTrue(delete.isNull("payload"))
    }
    @Test fun staleOrMutatedJsonInputCannotChangeTheImmutableParsedValue() {
        val value=payload();val wire=read(value);first(value).put("name","Mutated");assertEquals("Poprawiony banan",first(wire.json()).getString("name"))
        val copy=wire.json();copy.put("title","Mutated");assertEquals("Posiłek ze zdjęcia",wire.json().getString("title"))
    }
    @Test fun timestampSpellingComparisonPreservesWireAndRejectsOtherContentChanges() {
        for((localTime,serverTime) in listOf("12:00:00.630Z" to "12:00:00.630000Z",
            "12:00:00.1Z" to "12:00:00.100000Z","12:00:00Z" to "12:00:00.000000Z")) {
            val local=read(payload().put("occurred_at","2026-10-17T$localTime"))
            val server=read(local.json().put("occurred_at","2026-10-17T$serverTime"))
            val before=local.canonical;val operationBefore=MealWire.operation(operation,id,epoch,null,before,schema)
            assertNotEquals(local.canonical,server.canonical)
            assertTrue(local.hasSameContent(server));assertTrue(server.hasSameContent(local))
            assertEquals(before,local.canonical)
            assertEquals(operationBefore,MealWire.operation(operation,id,epoch,null,local.canonical,schema))
            assertFalse(local.hasSameContent(read(server.json().put("occurred_at","2026-10-17T12:00:00.630001Z"))))
            assertFalse(local.hasSameContent(read(server.json().put("title","Changed title"))))
            val changed=server.json();first(changed).getJSONObject("quantity").put("amount","151")
            assertFalse(local.hasSameContent(read(changed)))
            val missing=server.json();first(missing).getJSONObject("nutrition_per_100").put("protein_g",JSONObject.NULL)
            assertFalse(local.hasSameContent(read(missing)))
        }
    }
}
