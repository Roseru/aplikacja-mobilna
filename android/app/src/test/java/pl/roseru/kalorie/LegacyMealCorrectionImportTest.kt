package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.ImportSource
import pl.roseru.kalorie.data.LegacyImportCorrections
import pl.roseru.kalorie.importing.ImportComparison
import pl.roseru.kalorie.importing.LegacyImportForm

class LegacyMealCorrectionImportTest {
    private val schema = SyncWireSchema(SyncWireSchema.FILES.associateWith { name ->
        javaClass.getResourceAsStream("/sync/$name")!!.use { it.readBytes() }
    })
    private val mealId = "11111111-1111-4111-8111-111111111111"
    private val itemId = "22222222-2222-4222-8222-222222222222"
    private val originalId = "33333333-3333-4333-8333-333333333333"
    private val productId = "44444444-4444-4444-8444-444444444444"
    private val extraId = "55555555-5555-4555-8555-555555555555"
    private fun meal() = JSONObject().put("id", "legacy-meal").put("localDate", "2001-01-02")
        .put("occurredAt", "2001-01-02T12:00:00Z").put("zoneId", "UTC").put("mealType", "LUNCH")
        .put("rationName", "Historical meal").put("deleted", false)
    private fun current() = JSONObject().put("item_id", originalId).put("name", "Corrected drink")
        .put("product", JSONObject.NULL).put("quantity", JSONObject().put("amount", "150").put("unit", "ml"))
        .put("basis_unit", "ml").put("nutrition_per_100", JSONObject().put("energy_kcal", "42.125")
            .put("protein_g", JSONObject.NULL).put("fat_g", "0").put("carbs_g", "10.123456"))
        .put("density_g_per_ml", JSONObject.NULL).put("density_source", JSONObject.NULL)
        .put("nutrition_origin", "manual").put("formula_version", "nutrition_v1")
        .put("ration_component_position", JSONObject.NULL)
    private fun sourceSnapshot() = JSONObject().put("formula_version", "nutrition_v1")
        .put("quantity", JSONObject().put("amount", "100").put("unit", "g"))
        .put("product", JSONObject().put("product_id", productId).put("revision", 3)
            .put("name", "Original catalogue").put("basis_unit", "g")
            .put("density_g_per_ml", JSONObject.NULL).put("nutrition_per_100", JSONObject()
                .put("energy_kcal", "99").put("protein_g", "9").put("fat_g", "1").put("carbs_g", "20")))
        .put("sources", JSONArray())
    private fun item(wire: JSONObject = current()) = JSONObject().put("id", "legacy-item")
        .put("productName", "Original projection").put("grams", "100").put("kcalPer100", "999")
        .put("proteinPer100", "999").put("fatPer100", "999").put("carbsPer100", "999")
        .put("rationComponentPosition", 1).put("snapshotJson", StrictJson.canonical(sourceSnapshot()))
        .put("wirePayload", StrictJson.canonical(wire))
    private fun ids() = LegacyImportIds(mapOf("meal:legacy-meal" to mealId), mapOf("legacy-item" to itemId, "extra" to extraId))
    private fun convert(items: List<JSONObject>, metadata: LegacyImportMetadata = LegacyImportMetadata(), outboxes: List<String> = emptyList()) =
        LegacyImportWire.convert(LegacyImportSource("meal", "legacy-meal", StrictJson.canonical(meal()),
            items.map(StrictJson::canonical), outboxes), ids(), metadata, schema)
    private fun portion(result: LegacyImportConversion) = JSONObject((result as LegacyImportConversion.Ready).payload!!)
        .getJSONArray("items").getJSONObject(0)
    private fun source(items: List<JSONObject>): ImportSource {
        val raw = StrictJson.canonical(JSONObject().put("row", meal()).put("items", JSONArray(items)).put("outboxes", JSONArray()))
        return ImportSource("plan", "meal", "legacy-meal", 0, raw, "digest", "[]", "local", mealId)
    }

    @Test fun currentCorrectionWinsOverHistoricalSnapshotAndProjectionWithoutChangingOriginals() {
        val historical = item(); val before = historical.toString(); val originalOutbox = """{"wireFormat":"legacy","attempted":0,"payload":"original body"}"""
        val first = portion(convert(listOf(historical), outboxes = listOf(originalOutbox)))
        assertEquals(itemId, first.getString("item_id")); assertEquals("Corrected drink", first.getString("name"))
        assertEquals("150", first.getJSONObject("quantity").getString("amount")); assertEquals("ml", first.getString("basis_unit"))
        val values = first.getJSONObject("nutrition_per_100")
        assertEquals("42.125", values.getString("energy_kcal")); assertTrue(values.isNull("protein_g"))
        assertEquals("0", values.getString("fat_g")); assertEquals("10.123456", values.getString("carbs_g"))
        assertEquals(63.1875, MealWire.consumed(StrictJson.canonical(first)).kcal, 0.00000001)
        assertTrue(first.isNull("product")); assertTrue(first.isNull("ration_component_position"))
        assertEquals(before, historical.toString())
    }

    @Test fun formAndComparisonShowCurrentExactValuesThenCorrectionEditsOnlyDerivativeWire() {
        val historical = item(); val original = source(listOf(historical)); val before = original.sourceJson
        val form = LegacyImportForm.from(original)
        fun key(suffix: String) = form.fields.single { it.key.endsWith(":$suffix") }.key
        assertEquals("150", form.fields.single { it.key == key("amount") }.original)
        assertEquals("ml", form.fields.single { it.key == key("basis_unit") }.original)
        assertEquals("", form.fields.single { it.key == key("protein_g") }.original)
        assertEquals("0", form.fields.single { it.key == key("fat_g") }.original)
        val comparison = ImportComparison.local(original)
        assertEquals("42.125 kcal", comparison.values.single { it.label == "Składnik 1: Energia na 100 ml" }.value)
        assertEquals("Brak danych", comparison.values.single { it.label == "Składnik 1: Białko na 100 ml" }.value)
        assertEquals("0 g", comparison.values.single { it.label == "Składnik 1: Tłuszcz na 100 ml" }.value)
        val choice = JSONObject(form.choice(mapOf(key("energy_kcal") to "50,5", key("carbs_g") to "")))
        val (_, changed) = LegacyImportCorrections.apply("meal", meal(), JSONArray().put(historical), choice)
        val copy = changed.getJSONObject(0)
        assertEquals(historical.getString("snapshotJson"), copy.getString("snapshotJson"))
        assertEquals("999", copy.getString("kcalPer100"))
        val corrected = portion(convert(listOf(copy)))
        assertEquals("50.5", corrected.getJSONObject("nutrition_per_100").getString("energy_kcal"))
        assertTrue(corrected.getJSONObject("nutrition_per_100").isNull("carbs_g"))
        assertEquals(before, original.sourceJson)
    }

    private fun ration() = JSONObject().put("ration_id", originalId).put("revision", 2).put("name", "Proven ration")
        .put("components", JSONArray().put(JSONObject().put("position", 1)
            .put("product", JSONObject().put("product_id", productId).put("revision", 3))
            .put("quantity", JSONObject().put("amount", "100").put("unit", "g"))))
    private fun proof() = LegacyImportMetadata(true, provenCatalogProducts = setOf("$productId:3"), provenRationJson = ration().toString())

    @Test fun correctedRationUsesOriginalProvenAssociationAndAllowsAddedManualIngredientWithoutPosition() {
        val corrected = current().put("basis_unit", "g").put("quantity", JSONObject().put("amount", "75").put("unit", "g"))
            .put("ration_component_position", 1)
        val extra = item().put("id", "extra")
        val result = convert(listOf(item(corrected), extra), proof()) as LegacyImportConversion.Ready
        val wire = JSONObject(result.payload!!); val parts = wire.getJSONArray("items")
        assertEquals(originalId, wire.getJSONObject("ration").getString("ration_id"))
        assertEquals(1, parts.getJSONObject(0).getInt("ration_component_position"))
        assertTrue(parts.getJSONObject(0).isNull("product")); assertEquals("manual", parts.getJSONObject(0).getString("nutrition_origin"))
        assertEquals("42.125", parts.getJSONObject(0).getJSONObject("nutrition_per_100").getString("energy_kcal"))
        assertTrue(parts.getJSONObject(1).isNull("ration_component_position")); assertEquals(extraId, parts.getJSONObject(1).getString("item_id"))
        val missingProof = convert(listOf(item(corrected)), proof().copy(provenCatalogProducts = emptySet()))
        assertEquals("ration_proof_review", (missingProof as LegacyImportConversion.NeedsDecision).code)
        val duplicate = item(corrected).put("id", "extra")
        assertTrue(convert(listOf(item(corrected), duplicate), proof()) is LegacyImportConversion.NeedsDecision)
        val tooMuch = item(corrected.put("quantity", JSONObject().put("amount", "100.000001").put("unit", "g")))
        assertTrue(convert(listOf(tooMuch), proof()) is LegacyImportConversion.NeedsDecision)
    }

    @Test fun canonicalAnchorRetainsRationProofAndReplacementClearsAssociation() {
        val original = current().put("product", JSONObject().put("product_id", productId).put("revision", 3))
            .put("basis_unit", "g").put("quantity", JSONObject().put("amount", "75").put("unit", "g"))
            .put("nutrition_origin", "catalog_snapshot").put("ration_component_position", 1)
        val wire = JSONObject(original.toString()).put("product", JSONObject.NULL).put("nutrition_origin", "manual")
        val anchor = JSONObject().put("formula_version", "nutrition_v1").put("quantity", original.getJSONObject("quantity"))
            .put("original_consumption", original)
        val historical = item(wire).put("snapshotJson", StrictJson.canonical(anchor))
        assertEquals(1, portion(convert(listOf(historical), proof())).getInt("ration_component_position"))
        val change = JSONObject().put("choice", "metadata").put("item_overrides", JSONArray()
            .put(JSONObject().put("id", "legacy-item").put("name", "Replacement")))
        val (_, copy) = LegacyImportCorrections.apply("meal", meal(), JSONArray().put(historical), change)
        val first = portion(convert(listOf(copy.getJSONObject(0)), proof()))
        assertEquals("Replacement", first.getString("name")); assertTrue(first.isNull("ration_component_position"))
        assertEquals(StrictJson.canonical(anchor), copy.getJSONObject(0).getString("snapshotJson"))
    }

    @Test fun currentWireCannotBypassIdentityValidationFrozenAttemptOrDecimalRules() {
        val frozen = """{"wireFormat":"legacy","attempted":1,"payload":"frozen"}"""
        assertEquals("existing_wire_review", (convert(listOf(item()), outboxes = listOf(frozen)) as LegacyImportConversion.NeedsDecision).code)
        val bad = item(current().apply { getJSONObject("nutrition_per_100").put("energy_kcal", "1.0000001") })
        assertTrue(convert(listOf(bad)) is LegacyImportConversion.NeedsDecision)
        val collision = LegacyImportIds(mapOf("meal:legacy-meal" to mealId), mapOf("legacy-item" to itemId, "extra" to itemId))
        val result = LegacyImportWire.convert(LegacyImportSource("meal", "legacy-meal", meal().toString(), listOf(item().toString())), collision, LegacyImportMetadata(), schema)
        assertEquals("identity_collision", (result as LegacyImportConversion.NeedsDecision).code)
    }
}
