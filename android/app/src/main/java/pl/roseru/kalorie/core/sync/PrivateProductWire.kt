package pl.roseru.kalorie.core.sync

import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson

/** A private draft retains its exact source, missing nutrients, unit and density. */
internal object PrivateProductWire {
    fun portion(text: String, amount: String, unit: String): Nutrients {
        val value = StrictJson.read(text.toByteArray(Charsets.UTF_8))
        // Local quantities retain twelve places; the separate wire producer still enforces six.
        val quantity = ContractDecimal.userQuantity(amount, 12) ?: throw NutritionError("quantity_range")
        val nutrition = value.getJSONObject("nutrition_per_100")
        val values = ExactNutrition.read(ExactNutrition.fields.associateWith {
            if (nutrition.isNull(it)) null else nutrition.getString(it)
        })
        require(value.isNull("density_g_per_ml") == value.isNull("density_source"))
        val density = if (value.isNull("density_g_per_ml")) null else
            ExactDensity(ContractDecimal.read(value.getString("density_g_per_ml")), value.getString("density_source"))
        return Nutrients.fromExact(NutritionV1.calculate(listOf(ExactPortion(quantity, QuantityUnit.read(unit),
            QuantityUnit.read(value.getString("basis_unit")), values, density))))
    }

    fun meal(text: String, itemId: String, amount: String, unit: String, occurredAt: String,
        zone: String, type: String, schema: SyncWireSchema): MealWire {
        val product = StrictJson.read(text.toByteArray(Charsets.UTF_8))
        val nutrition = product.getJSONObject("nutrition_per_100")
        val values = ExactNutrition.read(ExactNutrition.fields.associateWith {
            if (nutrition.isNull(it)) null else nutrition.getString(it)
        })
        val wire = ManualMealWire.create(product.getString("name"), itemId, amount, unit, values,
            occurredAt, zone, type, schema).json()
        val item = wire.getJSONArray("items").getJSONObject(0)
        item.put("basis_unit", product.getString("basis_unit"))
            .put("density_g_per_ml", product.get("density_g_per_ml"))
            .put("density_source", product.get("density_source"))
        // Private consumption has no official ProductRef and does not publish the draft.
        return MealWire.read(StrictJson.canonical(wire), schema)
    }
}
