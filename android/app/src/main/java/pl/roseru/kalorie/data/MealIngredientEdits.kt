package pl.roseru.kalorie.data

import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.MealWire
import java.math.BigDecimal

/** The current exact value and the retained source are deliberately different snapshots. */
fun MealItemEntity.ingredientInput(): MealIngredientInput {
    val exact = wirePayload?.let { MealWire.portion(StrictJson.read(it.toByteArray())) }
        ?: snapshotJson?.let { snapshot ->
            val row=JSONObject(snapshot); val product=row.optJSONObject("private_product")?:row.getJSONObject("product")
            val nutrition=product.getJSONObject("nutrition_per_100")
            val density=product.optJSONObject("density_g_per_ml")?.let {
                ExactDensity(BigDecimal(it.getString("amount")),it.getString("source_id"))
            } ?: if(product.isNull("density_g_per_ml"))null else ExactDensity(
                BigDecimal(product.getString("density_g_per_ml")),product.getString("density_source"))
            ExactPortion(BigDecimal(amountText),QuantityUnit.read(unit),QuantityUnit.read(product.getString("basis_unit")),
                ExactNutrition.read(ExactNutrition.fields.associateWith {field->if(nutrition.isNull(field))null else nutrition.getString(field)}),density)
        } ?: ExactPortion(BigDecimal(amountText),QuantityUnit.GRAMS,QuantityUnit.GRAMS,
            ExactNutrition(kcalPer100?.let(BigDecimal::valueOf),proteinPer100?.let(BigDecimal::valueOf),
                fatPer100?.let(BigDecimal::valueOf),carbsPer100?.let(BigDecimal::valueOf)))
    return MealIngredientInput(productName,ContractDecimal.canonical(exact.amount),exact.unit,exact.basisUnit,exact.per100,exact.density)
}

/** First pre-correction consumption, only when no product/source snapshot already exists. */
internal fun MealItemEntity.sourceSnapshot(): String = snapshotJson ?: StrictJson.canonical(JSONObject()
    .put("formula_version",NutritionV1.FORMULA).put("quantity",JSONObject().put("amount",amountText).put("unit",unit))
    .put("original_consumption",wirePayload?.let(::JSONObject) ?: JSONObject()
        .put("name",productName).put("quantity",JSONObject().put("amount",amountText).put("unit",unit))
        .put("nutrition_per_100",JSONObject().apply {
            ExactNutrition.fields.zip(listOf(kcalPer100,proteinPer100,fatPer100,carbsPer100)).forEach {(field,value)->
                put(field,value?.let {ContractDecimal.canonical(BigDecimal.valueOf(it))}?:JSONObject.NULL)
            }
        })))
