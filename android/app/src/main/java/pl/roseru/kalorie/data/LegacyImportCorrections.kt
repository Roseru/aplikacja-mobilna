package pl.roseru.kalorie.data

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.LegacyImportWire

/** Explicit form values create a derivative. Neither the archived source nor frozen outbox is edited. */
internal object LegacyImportCorrections {
    fun apply(type:String,original:JSONObject,originalItems:JSONArray,choice:JSONObject):Pair<JSONObject,JSONArray> {
        val row=JSONObject(original.toString());val items=JSONArray(originalItems.toString())
        if(choice.optString("choice")!="metadata")return row to items
        val allowed=when(type) {
            "weight"->setOf("kg","occurredAt","zoneId","localDate")
            "profile"->setOf("nickname","heightCm","zoneId","activityClass","dietAim")
            "goal"->setOf("kcal","protein","fat","carbs","validFrom","decidedAt","zoneId","reason","correctionOf")
            "diary_day"->setOf("localDate","declaredComplete","zoneId")
            "meal"->setOf("localDate","occurredAt","zoneId","mealType","rationName")
            "product_draft"->setOf("name","kcal","protein","fat","carbs","source","basisUnit","density","densitySource")
            else->error("Unsupported import source")
        }
        val overrides=choice.optJSONObject("row_overrides") ?: JSONObject()
        require(overrides.keys().asSequence().all {it in allowed})
        overrides.keys().asSequence().toList().forEach {row.put(it,overrides.get(it))}
        if(type=="goal" && choice.optBoolean("standalone_goal",false))row.put("correctionOf",JSONObject.NULL)
        if(type=="product_draft") {
            val product=if(!original.isNull("wirePayload"))LegacyImportWire.readSource(original.getString("wirePayload")) else JSONObject()
                .put("name",original.getString("name")).put("brand",JSONObject.NULL).put("variant",JSONObject.NULL)
                .put("basis_unit","g").put("package_quantity",JSONObject.NULL).put("density_g_per_ml",JSONObject.NULL)
                .put("density_source",JSONObject.NULL).put("source_description",original.getString("source"))
                .put("nutrition_per_100",JSONObject().put("energy_kcal",original.get("kcal")).put("protein_g",original.get("protein"))
                    .put("fat_g",original.get("fat")).put("carbs_g",original.get("carbs")))
            for((local,wire) in mapOf("name" to "name","source" to "source_description","basisUnit" to "basis_unit","density" to "density_g_per_ml","densitySource" to "density_source"))
                if(overrides.has(local))product.put(wire,overrides.get(local))
            for((local,wire) in NUTRIENTS)if(overrides.has(local))product.getJSONObject("nutrition_per_100").put(wire,overrides.get(local))
            row.put("wirePayload",StrictJson.canonical(product))
        }
        val changes=choice.optJSONArray("item_overrides") ?: JSONArray()
        val seen=mutableSetOf<String>()
        for(i in 0 until changes.length()) {
            val change=changes.getJSONObject(i);val id=change.getString("id");require(seen.add(id))
            require(change.keys().asSequence().all {it in setOf("id","amount","unit","name","basis_unit","energy_kcal","protein_g","fat_g","carbs_g","density","density_source")})
            val item=(0 until items.length()).map {items.getJSONObject(it)}.single {it.getString("id")==id}
            val existing=item.optString("snapshotJson").takeIf {it.isNotEmpty() && !item.isNull("snapshotJson")}
                ?.let(LegacyImportWire::readSource)
            val snap=existing ?: JSONObject().put("quantity",JSONObject().put("amount",item.get("grams")).put("unit","g"))
            val catalog=snap.optJSONObject("product")
            val product=snap.optJSONObject("private_product") ?: catalog?.let {
                JSONObject().put("name",it.getString("name")).put("basis_unit",it.getString("basis_unit"))
                    .put("nutrition_per_100",JSONObject(it.getJSONObject("nutrition_per_100").toString()))
                    .put("density_g_per_ml",it.optJSONObject("density_g_per_ml")?.get("amount") ?: JSONObject.NULL)
                    .put("density_source",it.optJSONObject("density_g_per_ml")?.get("source_id") ?: JSONObject.NULL)
            } ?: JSONObject().put("name",item.getString("productName")).put("basis_unit","g")
                .put("nutrition_per_100",JSONObject().put("energy_kcal",item.get("kcalPer100")).put("protein_g",item.get("proteinPer100"))
                    .put("fat_g",item.get("fatPer100")).put("carbs_g",item.get("carbsPer100")))
                .put("density_g_per_ml",JSONObject.NULL).put("density_source",JSONObject.NULL)
            if(change.has("amount"))snap.getJSONObject("quantity").put("amount",change.get("amount"))
            if(change.has("unit")) {require(change.getString("unit") in setOf("g","ml"));snap.getJSONObject("quantity").put("unit",change.getString("unit"))}
            if(change.has("name"))product.put("name",change.getString("name"))
            if(change.has("basis_unit")) {require(change.getString("basis_unit") in setOf("g","ml"));product.put("basis_unit",change.getString("basis_unit"))}
            for(wire in NUTRIENTS.values)if(change.has(wire))product.getJSONObject("nutrition_per_100").put(wire,change.get(wire))
            if(change.has("density"))product.put("density_g_per_ml",change.get("density"))
            if(change.has("density_source"))product.put("density_source",change.get("density_source"))
            // An explicit correction is a manual historical snapshot, not a claim about a catalogue revision.
            snap.remove("product");snap.put("private_product",product)
            item.put("snapshotJson",StrictJson.canonical(snap))
        }
        return row to items
    }
    private val NUTRIENTS=mapOf("kcal" to "energy_kcal","protein" to "protein_g","fat" to "fat_g","carbs" to "carbs_g")
}
