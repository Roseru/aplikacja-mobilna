package pl.roseru.kalorie.core.sync

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.ExactNutrition
import pl.roseru.kalorie.core.NutritionV1
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.Instant
import java.time.ZoneId
import java.time.temporal.ChronoUnit

/** Manual consumption snapshot only: never publishes or invents a catalogue ProductRef. */
internal object ManualMealWire {
    fun create(name: String, itemId: String, amount: String, unit: String, nutrition: ExactNutrition,
        occurredAt: String, zoneId: String, mealType: String, schema: SyncWireSchema): MealWire = try {
        val quantity = checkNotNull(ContractDecimal.userQuantity(amount))
        val values = JSONObject()
        ExactNutrition.fields.zip(nutrition.values()).forEach { (field, value) ->
            values.put(field, value?.let(ContractDecimal::canonical) ?: JSONObject.NULL)
        }
        val time = Instant.parse(occurredAt).truncatedTo(ChronoUnit.MICROS)
        val zone = ZoneId.of(zoneId)
        val item = JSONObject().put("item_id", itemId).put("name", name).put("product", JSONObject.NULL)
            .put("quantity", JSONObject().put("amount", ContractDecimal.canonical(quantity)).put("unit", unit))
            .put("basis_unit", unit).put("nutrition_per_100", values)
            .put("density_g_per_ml", JSONObject.NULL).put("density_source", JSONObject.NULL)
            .put("nutrition_origin", "manual").put("formula_version", NutritionV1.FORMULA)
            .put("ration_component_position", JSONObject.NULL)
        val meal = JSONObject().put("title", name).put("occurred_at", time.toString()).put("time_zone", zone.id)
            .put("local_date", time.atZone(zone).toLocalDate().toString()).put("meal_type", mealType)
            .put("goal_id", JSONObject.NULL).put("ration", JSONObject.NULL).put("items", JSONArray().put(item))
        MealWire.read(StrictJson.canonical(meal), schema)
    } catch (_: Exception) { throw SyncWireException() }
}
