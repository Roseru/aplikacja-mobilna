package pl.roseru.kalorie.core.sync

import org.json.JSONObject
import org.json.JSONArray
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.*

/** Exact domain data, never an invented catalogue product or a provider payload. */
class MealWire private constructor(val canonical:String) {
    fun json()=StrictJson.read(canonical.toByteArray(Charsets.UTF_8))
    fun withAmount(itemId:String,text:String,schema:SyncWireSchema):MealWire {
        val amount=ContractDecimal.userQuantity(text)?:throw NutritionError("quantity_range")
        val value=json();val items=value.getJSONArray("items");var found=false
        for(i in 0 until items.length())if(items.getJSONObject(i).getString("item_id")==itemId) {
            require(!found);found=true;items.getJSONObject(i).getJSONObject("quantity").put("amount",ContractDecimal.canonical(amount))
        }
        require(found);return read(StrictJson.canonical(value),schema)
    }
    fun without(itemId:String,schema:SyncWireSchema):MealWire? {
        val value=json();val items=value.getJSONArray("items")
        val kept=(0 until items.length()).map {items.getJSONObject(it)}.filter {it.getString("item_id")!=itemId}
        require(kept.size==items.length()-1)
        return if(kept.isEmpty())null else read(StrictJson.canonical(value.put("items",JSONArray(kept))),schema)
    }
    override fun toString()="MealWire(redacted)"
    companion object {
        fun read(text:String,schema:SyncWireSchema):MealWire = safe {
            val bytes=text.toByteArray(Charsets.UTF_8);schema.validateMeal(bytes)
            val value=StrictJson.read(bytes);val date=LocalDate.parse(value.getString("local_date"))
            require(Instant.parse(value.getString("occurred_at")).atZone(ZoneId.of(value.getString("time_zone"))).toLocalDate()==date)
            val items=value.getJSONArray("items");val ids=mutableSetOf<String>()
            for(i in 0 until items.length()) {
                val item=items.getJSONObject(i);require(ids.add(item.getString("item_id")))
                if(item.getString("nutrition_origin")=="catalog_snapshot")require(!item.isNull("product"))
                if(value.isNull("ration"))require(item.isNull("ration_component_position"))
                NutritionV1.calculate(listOf(portion(item)))
            }
            MealWire(StrictJson.canonical(value))
        }
        fun portion(item:JSONObject):ExactPortion = safe {
            val quantity=item.getJSONObject("quantity");val nutrition=item.getJSONObject("nutrition_per_100")
            val density=if(item.isNull("density_g_per_ml")){require(item.isNull("density_source"));null}
                else {require(!item.isNull("density_source"));ExactDensity(ContractDecimal.read(item.getString("density_g_per_ml")),item.getString("density_source"))}
            ExactPortion(ContractDecimal.read(quantity.getString("amount")),QuantityUnit.read(quantity.getString("unit")),
                QuantityUnit.read(item.getString("basis_unit")),ExactNutrition.read(ExactNutrition.fields.associateWith {
                    field->if(nutrition.isNull(field))null else nutrition.getString(field)}),density)
        }
        fun consumed(text:String)=safe {Nutrients.fromExact(NutritionV1.calculate(listOf(portion(StrictJson.read(text.toByteArray(Charsets.UTF_8))))))}
        private inline fun <T> safe(action:()->T):T=try{action()}catch(_:Exception){throw SyncWireException()}
        fun operation(id:String,mealId:String,epoch:String,base:Int?,payload:String?,schema:SyncWireSchema):String {
            val value=JSONObject().put("operation_id",id).put("entity_type","meal").put("entity_id",mealId)
                .put("action",if(payload==null)"delete" else "upsert").put("base_revision",base?:JSONObject.NULL)
                .put("sync_epoch",epoch).put("payload",payload?.let {StrictJson.read(it.toByteArray(Charsets.UTF_8))}?:JSONObject.NULL)
            val text=StrictJson.canonical(value);schema.validate(text.toByteArray(Charsets.UTF_8),"Operation");return text
        }
    }
}
