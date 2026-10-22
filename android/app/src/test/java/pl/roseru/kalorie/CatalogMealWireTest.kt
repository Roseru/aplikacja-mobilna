package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*

class CatalogMealWireTest {
    private val schema = SyncWireSchema(SyncWireSchema.FILES.associateWith {
        javaClass.getResourceAsStream("/sync/$it")!!.use { stream -> stream.readBytes() }
    })
    private val productId = "11111111-1111-4111-8111-111111111111"
    private val itemId = "22222222-2222-4222-8222-222222222222"
    private val rationId = "33333333-3333-4333-8333-333333333333"
    private val sourceId = "44444444-4444-4444-8444-444444444444"
    private fun snapshot(amount: String = "150.5", unit: String = "g", density: Boolean = false): String {
        val product = JSONObject().put("product_id", productId).put("revision", 7).put("name", "Produkt katalogowy")
            .put("basis_unit", "g").put("nutrition_per_100", JSONObject().put("energy_kcal", "100.5")
                .put("protein_g", JSONObject.NULL).put("fat_g", "0").put("carbs_g", "12.25"))
            .put("density_g_per_ml", if (density) JSONObject().put("amount", "1.25").put("source_id", sourceId) else JSONObject.NULL)
        return StrictJson.canonical(JSONObject().put("formula_version", "nutrition_v1").put("product", product)
            .put("quantity", JSONObject().put("amount", amount).put("unit", unit))
            .put("sources", JSONArray().put(JSONObject().put("source_id", sourceId))))
    }
    private fun ration() = JSONObject().put("ration_id", rationId).put("revision", 2).put("name", "Racja katalogowa")
        .put("components", JSONArray().put(JSONObject().put("position", 9)
            .put("product", JSONObject().put("product_id", productId).put("revision", 7))
            .put("quantity", JSONObject().put("amount", "300").put("unit", "g")))).toString()
    private fun wire(snapshot: String = snapshot(), ration: String? = null, position: Int? = null) = CatalogMealWire.create(
        "Spożycie", listOf(CatalogMealWire.Part(itemId, snapshot, position)), ration,
        "2026-10-20T22:30:00.123456789Z", "Europe/Warsaw", "lunch", schema)

    @Test fun catalogueIdentityNullZeroAndExactQuantitySurviveTheSnapshot() {
        val value = wire().json(); val item = value.getJSONArray("items").getJSONObject(0)
        assertEquals(productId, item.getJSONObject("product").getString("product_id"))
        assertEquals(7, item.getJSONObject("product").getInt("revision"))
        assertEquals("catalog_snapshot", item.getString("nutrition_origin"))
        assertEquals("150.5", item.getJSONObject("quantity").getString("amount"))
        assertTrue(item.getJSONObject("nutrition_per_100").isNull("protein_g"))
        assertEquals("0", item.getJSONObject("nutrition_per_100").getString("fat_g"))
        assertEquals("2026-10-21", value.getString("local_date"))
        assertEquals("2026-10-20T22:30:00.123456Z", value.getString("occurred_at"))
        assertTrue(value.isNull("ration")); assertTrue(item.isNull("ration_component_position"))
        val unknownEnergy = JSONObject(snapshot()).apply {
            getJSONObject("product").getJSONObject("nutrition_per_100").put("energy_kcal", JSONObject.NULL)
        }
        assertTrue(wire(unknownEnergy.toString()).json().getJSONArray("items").getJSONObject(0)
            .getJSONObject("nutrition_per_100").isNull("energy_kcal"))
    }
    @Test fun selectedRationPositionMustMatchItsOriginalProductRevisionAndPackageLimit() {
        val value = wire(ration = ration(), position = 9).json()
        assertEquals(rationId, value.getJSONObject("ration").getString("ration_id"))
        assertEquals(9, value.getJSONArray("items").getJSONObject(0).getInt("ration_component_position"))
        assertEquals(1, value.getJSONArray("items").length())
        assertThrows(SyncWireException::class.java) { wire(ration = ration(), position = 8) }
        val differentRevision = JSONObject(ration()).apply {
            getJSONArray("components").getJSONObject(0).getJSONObject("product").put("revision", 8)
        }
        assertThrows(SyncWireException::class.java) { wire(ration = differentRevision.toString(), position = 9) }
        assertThrows(SyncWireException::class.java) { wire(snapshot("300.000001"), ration(), 9) }
        assertThrows(SyncWireException::class.java) { wire(snapshot("1.0000001")) }
    }
    @Test fun crossUnitConsumptionUsesOnlyTheRecordedDensityAndSource() {
        val item = wire(snapshot("20", "ml", true)).json().getJSONArray("items").getJSONObject(0)
        assertEquals("ml", item.getJSONObject("quantity").getString("unit"))
        assertEquals("g", item.getString("basis_unit")); assertEquals("1.25", item.getString("density_g_per_ml"))
        assertEquals(sourceId, item.getString("density_source"))
        assertEquals("25.125", MealWire.consumed(StrictJson.canonical(item)).asExact().energy.canonical)
        assertThrows(SyncWireException::class.java) { wire(snapshot("20", "ml", false)) }
        val missingSource = JSONObject(snapshot("20", "ml", true)).put("sources", JSONArray()).toString()
        assertThrows(SyncWireException::class.java) { wire(missingSource) }
    }
}
