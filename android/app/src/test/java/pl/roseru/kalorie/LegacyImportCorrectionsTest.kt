package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.NutritionV1
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.LegacyImportCorrections

class LegacyImportCorrectionsTest {
    private val schema=SyncWireSchema(SyncWireSchema.FILES.associateWith {javaClass.getResourceAsStream("/sync/$it")!!.use {s->s.readBytes()}})
    private val target="11111111-1111-4111-8111-111111111111"
    private val itemId="22222222-2222-4222-8222-222222222222"
    private fun meal()=JSONObject().put("id","old").put("localDate","2001-01-02").put("occurredAt","2001-01-02T12:00:00Z")
        .put("zoneId","UTC").put("mealType","UNSPECIFIED").put("rationName",JSONObject.NULL).put("deleted",0)
    private fun product()=JSONObject().put("name","Historical").put("brand",JSONObject.NULL).put("variant",JSONObject.NULL).put("basis_unit","g")
        .put("nutrition_per_100",JSONObject().put("energy_kcal",JSONObject.NULL).put("protein_g",JSONObject.NULL).put("fat_g","0").put("carbs_g","12.5"))
        .put("package_quantity",JSONObject.NULL).put("density_g_per_ml",JSONObject.NULL).put("density_source",JSONObject.NULL).put("source_description","Historical label")
    private fun item(amount:String):JSONObject {
        val snap=JSONObject().put("formula_version",NutritionV1.FORMULA).put("private_product",product())
            .put("quantity",JSONObject().put("amount",amount).put("unit","g"))
        return JSONObject().put("id","old-item").put("productName","Historical").put("grams",amount)
            .put("kcalPer100",JSONObject.NULL).put("proteinPer100",JSONObject.NULL).put("fatPer100","0").put("carbsPer100","12.5")
            .put("snapshotJson",StrictJson.canonical(snap))
    }
    private fun convert(row:JSONObject,items:JSONArray)=LegacyImportWire.convert(LegacyImportSource("meal","old",StrictJson.canonical(row),
        (0 until items.length()).map {StrictJson.canonical(items.getJSONObject(it))}),
        LegacyImportIds(mapOf("meal:old" to target),mapOf("old-item" to itemId)),LegacyImportMetadata(confirmed=true),schema)
    @Test fun explicitSixPlaceQuantityIsDerivativeAndOriginalTwelvePlacesNullsAndUnspecifiedTypeSurvive() {
        val row=meal();val items=JSONArray().put(item("1.234567890123"));val original=items.toString();val originalRow=row.toString()
        assertEquals("precision_review",(convert(row,items) as LegacyImportConversion.NeedsDecision).code)
        val choice=JSONObject().put("choice","metadata").put("item_overrides",JSONArray().put(JSONObject().put("id","old-item").put("amount","1.234567")))
        val (corrected,copy)=LegacyImportCorrections.apply("meal",row,items,choice)
        val result=convert(corrected,copy) as LegacyImportConversion.Ready;val wire=JSONObject(result.payload!!)
        assertTrue(wire.isNull("meal_type"));val portion=wire.getJSONArray("items").getJSONObject(0)
        assertEquals("1.234567",portion.getJSONObject("quantity").getString("amount"))
        assertTrue(portion.getJSONObject("nutrition_per_100").isNull("energy_kcal"));assertEquals("0",portion.getJSONObject("nutrition_per_100").getString("fat_g"))
        assertEquals(original,items.toString());assertEquals(originalRow,row.toString())
        assertEquals("1.234567890123",JSONObject(items.getJSONObject(0).getString("snapshotJson")).getJSONObject("quantity").getString("amount"))
    }
    @Test fun selectingMetadataWithoutExplicitQuantityCorrectionDoesNotRound() {
        val row=meal();val items=JSONArray().put(item("0.000000000001"));val original=items.toString()
        val (copy,parts)=LegacyImportCorrections.apply("meal",row,items,JSONObject().put("choice","metadata"))
        assertEquals("precision_review",(convert(copy,parts) as LegacyImportConversion.NeedsDecision).code)
        assertEquals(original,items.toString())
    }
    @Test fun productCorrectionUsesExactUnknownEnergyInsteadOfRealZeroProjection() {
        val exact=product();val row=JSONObject().put("id","old").put("name","Historical").put("kcal","0.0")
            .put("protein",JSONObject.NULL).put("fat","0.0").put("carbs","12.5").put("source","Historical label")
            .put("wirePayload",StrictJson.canonical(exact));val before=row.toString()
        val (copy,_)=LegacyImportCorrections.apply("product_draft",row,JSONArray(),JSONObject().put("choice","metadata")
            .put("row_overrides",JSONObject().put("carbs","15.123456")))
        val result=LegacyImportWire.convert(LegacyImportSource("product_draft","old",StrictJson.canonical(copy)),
            LegacyImportIds(mapOf("product_draft:old" to target)),LegacyImportMetadata(confirmed=true),schema) as LegacyImportConversion.Ready
        val nutrition=JSONObject(result.payload!!).getJSONObject("nutrition_per_100")
        assertTrue(nutrition.isNull("energy_kcal"));assertTrue(nutrition.isNull("protein_g"));assertEquals("0",nutrition.getString("fat_g"))
        assertEquals("15.123456",nutrition.getString("carbs_g"));assertEquals(before,row.toString())
    }
    @Test fun correctionCannotChangeOwnerIdentityOrAnUnlistedItem() {
        val row=meal();val items=JSONArray().put(item("1"));val before=row.toString()+items.toString()
        assertThrows(IllegalArgumentException::class.java) {LegacyImportCorrections.apply("meal",row,items,
            JSONObject().put("choice","metadata").put("row_overrides",JSONObject().put("ownerScope","another")))}
        assertThrows(NoSuchElementException::class.java) {LegacyImportCorrections.apply("meal",row,items,
            JSONObject().put("choice","metadata").put("item_overrides",JSONArray().put(JSONObject().put("id","missing").put("amount","1"))))}
        assertEquals(before,row.toString()+items.toString())
    }
    @Test fun correctedCatalogueSnapshotRetainsHistoricalNutritionAndSourceWithoutClaimingProductRef() {
        val catalog=JSONObject().put("product_id","33333333-3333-4333-8333-333333333333").put("revision",2)
            .put("name","Catalog history").put("basis_unit","g").put("nutrition_per_100",JSONObject()
                .put("energy_kcal","99.125").put("protein_g",JSONObject.NULL).put("fat_g","0").put("carbs_g","12.5"))
            .put("density_g_per_ml",JSONObject().put("amount","1.1").put("source_id","historical-density"))
        val snapshot=JSONObject().put("formula_version",NutritionV1.FORMULA).put("product",catalog)
            .put("sources",JSONArray().put(JSONObject().put("source_id","historical-density").put("description","Historical measured density")))
            .put("quantity",JSONObject().put("amount","20.123456789123").put("unit","ml"))
        val item=item("20.123456789123").put("snapshotJson",StrictJson.canonical(snapshot));val items=JSONArray().put(item);val before=items.toString()
        val (row,copy)=LegacyImportCorrections.apply("meal",meal(),items,JSONObject().put("choice","metadata")
            .put("item_overrides",JSONArray().put(JSONObject().put("id","old-item").put("amount","20"))))
        val result=convert(row,copy) as LegacyImportConversion.Ready
        val part=JSONObject(result.payload!!).getJSONArray("items").getJSONObject(0)
        assertTrue(part.isNull("product"));assertEquals("manual",part.getString("nutrition_origin"))
        assertEquals("99.125",part.getJSONObject("nutrition_per_100").getString("energy_kcal"))
        assertEquals("historical-density",part.getString("density_source"));assertEquals("1.1",part.getString("density_g_per_ml"))
        assertEquals(21.8075,MealWire.consumed(StrictJson.canonical(part)).kcal,0.000000001)
        assertEquals(before,items.toString())
    }
}
