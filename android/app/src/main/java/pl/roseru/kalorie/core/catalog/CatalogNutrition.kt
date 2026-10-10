package pl.roseru.kalorie.core.catalog

import org.json.JSONObject
import pl.roseru.kalorie.core.*
import java.math.BigDecimal

fun JSONObject.exactPortion(amount: BigDecimal, unit: String): ExactPortion {
    val values = getJSONObject("nutrition_per_100")
    val nutrition = ExactNutrition.read(ExactNutrition.fields.associateWith { if (values.isNull(it)) null else values.getString(it) })
    val density = optJSONObject("density_g_per_ml")?.let { ExactDensity(ContractDecimal.read(it.getString("amount")), it.getString("source_id")) }
    return ExactPortion(amount, QuantityUnit.read(unit), QuantityUnit.read(getString("basis_unit")), nutrition, density)
}

fun exactProductNutrients(productJson: String, amount: String, unit: String): Nutrients = Nutrients.fromExact(
    NutritionV1.calculate(listOf(JSONObject(productJson).exactPortion(BigDecimal(amount), unit))))
