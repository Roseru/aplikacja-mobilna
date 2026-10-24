package pl.roseru.kalorie.community

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.NutritionV1
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.MealWire
import pl.roseru.kalorie.core.sync.SyncWireSchema
import java.time.Instant
import java.time.ZoneId
import java.time.temporal.ChronoUnit

internal object CommunityMeal {
    fun create(product:CommunityProduct,amount:String,unit:String,itemId:String,occurredAt:Instant,zone:ZoneId,
        mealType:String,schema:SyncWireSchema):MealWire {
        require(product.visible)
        val exact=checkNotNull(ContractDecimal.userQuantity(amount))
        val quantity=ContractDecimal.canonical(exact)
        product.consumed(quantity,unit)
        val density=product.density
        val name=product.name.let {if(it.codePointCount(0,it.length)>200)it.substring(0,it.offsetByCodePoints(0,200)) else it}
        val item=JSONObject().put("item_id",itemId).put("name",name)
            // A merged alias keeps its original version/nutrients in the diary snapshot.
            .put("product",product.ref.json()).put("quantity",JSONObject().put("amount",quantity).put("unit",unit))
            .put("basis_unit",product.basisUnit).put("nutrition_per_100",product.json().getJSONObject("nutrition_per_100"))
            .put("density_g_per_ml",density?.gramsPerMl?.let(ContractDecimal::canonical)?:JSONObject.NULL)
            .put("density_source",density?.sourceId?:JSONObject.NULL).put("nutrition_origin","catalog_snapshot")
            .put("formula_version",NutritionV1.FORMULA).put("ration_component_position",JSONObject.NULL)
        val time=occurredAt.truncatedTo(ChronoUnit.MICROS)
        return MealWire.read(StrictJson.canonical(JSONObject().put("title",name).put("occurred_at",time.toString())
            .put("time_zone",zone.id).put("local_date",time.atZone(zone).toLocalDate().toString())
            .put("meal_type",mealType).put("goal_id",JSONObject.NULL).put("ration",JSONObject.NULL)
            .put("items",JSONArray().put(item))),schema)
    }
}
