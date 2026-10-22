package pl.roseru.kalorie.core.sync

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.NutritionV1
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.time.Instant
import java.time.ZoneId
import java.time.temporal.ChronoUnit

/** Consumption of immutable catalogue revisions; never publishes a product or fabricates its identity. */
internal object CatalogMealWire {
    class Part(val itemId: String, val snapshotJson: String, val rationPosition: Int?) {
        override fun toString() = "CatalogMealPart(redacted)"
    }

    fun create(title: String, parts: List<Part>, rationJson: String?, occurredAt: String,
        zoneId: String, mealType: String, schema: SyncWireSchema): MealWire = try {
        val ration = rationJson?.let { StrictJson.read(it.toByteArray(Charsets.UTF_8)) }
        val positions = mutableSetOf<Int>()
        val items = parts.map { part ->
            val snapshot = StrictJson.read(part.snapshotJson.toByteArray(Charsets.UTF_8))
            require(snapshot.getString("formula_version") == NutritionV1.FORMULA)
            val product = snapshot.getJSONObject("product")
            val quantity = snapshot.getJSONObject("quantity")
            val amount = checkNotNull(ContractDecimal.userQuantity(quantity.getString("amount")))
            val reference = JSONObject().put("product_id", product.getString("product_id"))
                .put("revision", product.getInt("revision"))
            if (ration == null) require(part.rationPosition == null) else {
                val position = checkNotNull(part.rationPosition)
                require(positions.add(position))
                val components = ration.getJSONArray("components")
                val component = (0 until components.length()).map { components.getJSONObject(it) }
                    .single { it.getInt("position") == position }
                val expected = component.getJSONObject("product")
                require(expected.getString("product_id") == reference.getString("product_id") &&
                    expected.getInt("revision") == reference.getInt("revision"))
                val packageQuantity = component.getJSONObject("quantity")
                require(quantity.getString("unit") == packageQuantity.getString("unit") &&
                    amount <= BigDecimal(packageQuantity.getString("amount")))
            }
            val density = product.optJSONObject("density_g_per_ml")
            // Keep the same source identity used by the exact catalogue calculator.
            val densitySource = density?.getString("source_id")
            if (densitySource != null) {
                val sources = snapshot.getJSONArray("sources")
                require((0 until sources.length()).any { sources.getJSONObject(it).getString("source_id") == densitySource })
            }
            JSONObject().put("item_id", part.itemId).put("name", product.getString("name"))
                .put("product", reference)
                .put("quantity", JSONObject().put("amount", ContractDecimal.canonical(amount)).put("unit", quantity.getString("unit")))
                .put("basis_unit", product.getString("basis_unit"))
                .put("nutrition_per_100", product.getJSONObject("nutrition_per_100"))
                .put("density_g_per_ml", density?.getString("amount") ?: JSONObject.NULL)
                .put("density_source", densitySource ?: JSONObject.NULL)
                .put("nutrition_origin", "catalog_snapshot").put("formula_version", NutritionV1.FORMULA)
                .put("ration_component_position", part.rationPosition ?: JSONObject.NULL)
        }
        val time = Instant.parse(occurredAt).truncatedTo(ChronoUnit.MICROS)
        val zone = ZoneId.of(zoneId)
        val rationRef = ration?.let { JSONObject().put("ration_id", it.getString("ration_id"))
            .put("revision", it.getInt("revision")).put("name", it.getString("name")) }
        MealWire.read(StrictJson.canonical(JSONObject().put("title", title).put("occurred_at", time.toString())
            .put("time_zone", zone.id).put("local_date", time.atZone(zone).toLocalDate().toString())
            .put("meal_type", mealType).put("goal_id", JSONObject.NULL).put("ration", rationRef ?: JSONObject.NULL)
            .put("items", JSONArray(items))), schema)
    } catch (_: Exception) { throw SyncWireException() }
}
