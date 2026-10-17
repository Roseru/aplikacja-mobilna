package pl.roseru.kalorie.core

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.time.Instant
import java.time.ZoneId
import java.time.temporal.ChronoUnit
import java.util.Collections

/** Form input only. Empty nutrition means missing, never zero. No action authorizes HTTP. */
class PhotoDraftInput(val name:String,val amount:String,val unit:String,val energy:String,
    val protein:String,val fat:String,val carbs:String) {
    override fun toString()="PhotoDraftInput(redacted)"
}
internal class PhotoMealDraftException:IllegalArgumentException("Niepoprawne poprawki posiłku")

internal class PhotoDraftItem internal constructor(val id:String,val sourceComponentId:String?,val name:String,val portion:ExactPortion) {
    override fun toString()="PhotoDraftItem(redacted)"
}

/** Unsubmitted, immutable corrections. Stable IDs are allocated once; the source proposal is untouched. */
internal class PhotoMealDraft private constructor(val analysisId:String,val sourceRevision:Long,val sourceFingerprint:String,
    val mealId:String,val editRevision:Long,val title:String,val occurredAt:Instant,val zone:ZoneId,val mealType:String?,
    items:List<PhotoDraftItem>) {
    val items:List<PhotoDraftItem> = Collections.unmodifiableList(ArrayList(items))
    val localDate get()=occurredAt.atZone(zone).toLocalDate()
    init {
        PhotoHttpRequest.uuid(analysisId);PhotoHttpRequest.uuid(mealId);require(analysisId!=mealId)
        require(sourceRevision in 1..Int.MAX_VALUE.toLong() && editRevision in 1..Int.MAX_VALUE.toLong())
        require(Regex("[0-9a-f]{64}").matches(sourceFingerprint));text(title,200)
        require(zone.id in ZoneId.getAvailableZoneIds() && zone.id.length<=100)
        require(localDate.year in 1..9999 && occurredAt.nano%1000==0)
        require(mealType==null || mealType in setOf("breakfast","lunch","dinner","snack"))
        require(this.items.size in 1..30 && this.items.map {it.id}.toSet().size==this.items.size)
        val sources=this.items.mapNotNull {it.sourceComponentId};require(sources.toSet().size==sources.size)
        this.items.forEach {item->
            PhotoHttpRequest.uuid(item.id);require(item.id!=analysisId && item.id!=mealId)
            item.sourceComponentId?.let(PhotoHttpRequest::uuid);text(item.name,2000)
            require(item.portion.unit==item.portion.basisUnit && item.portion.density==null)
            ContractDecimal.read(ContractDecimal.canonical(item.portion.amount))
            item.portion.per100.values().filterNotNull().forEach {ContractDecimal.read(ContractDecimal.canonical(it))}
        }
        NutritionV1.calculate(this.items.map {it.portion})
    }
    val totals get()=NutritionV1.calculate(items.map {it.portion})
    private fun changed(values:List<PhotoDraftItem>,newTitle:String=title)=PhotoMealDraft(analysisId,sourceRevision,sourceFingerprint,
        mealId,Math.addExact(editRevision,1),newTitle,occurredAt,zone,mealType,values)
    fun replace(id:String,input:PhotoDraftInput):PhotoMealDraft = safe {
        val old=items.single {it.id==id};val next=item(id,old.sourceComponentId,input)
        changed(items.map {if(it.id==id)next else it})
    }
    fun add(id:String,input:PhotoDraftInput):PhotoMealDraft = safe {
        require(items.none {it.id==id});changed(items+item(id,null,input))
    }
    fun remove(id:String):PhotoMealDraft = safe {
        require(items.any {it.id==id});changed(items.filterNot {it.id==id})
    }
    fun rename(value:String):PhotoMealDraft = safe {changed(items,value.trim())}
    fun matches(read:PhotoAnalysisRead) = safe {
        require(analysisId==read.analysisId && sourceRevision<=read.revision)
        val proposal=read.proposal
        if(proposal!=null) {
            require(sourceFingerprint==read.proposalFingerprint)
            val sourceIds=proposal.items.map {it.componentId}.toSet()
            require(items.mapNotNull {it.sourceComponentId}.all {it in sourceIds})
        } else require(read.decision=="cancelled") // retained read-only after terminal GET; never confirmable
    }
    /** Strict sync-v1 template only; not a request, a mutation key, a diary write or a product publication. */
    fun confirmBody(read:PhotoAnalysisRead):ByteArray = safe {
        matches(read);require(read.state=="succeeded" && read.decision=="pending" && read.proposal!=null)
        val rows=items.map {item->
            text(item.name,200)
            JSONObject().put("item_id",item.id).put("name",item.name).put("product",JSONObject.NULL)
                .put("quantity",JSONObject().put("amount",ContractDecimal.canonical(item.portion.amount)).put("unit",item.portion.unit.wire))
                .put("basis_unit",item.portion.basisUnit.wire).put("nutrition_per_100",nutrition(item.portion.per100))
                .put("density_g_per_ml",JSONObject.NULL).put("density_source",JSONObject.NULL)
                .put("nutrition_origin","ai_estimate").put("formula_version",NutritionV1.FORMULA).put("ration_component_position",JSONObject.NULL)
        }
        val meal=JSONObject().put("title",title).put("occurred_at",occurredAt.toString()).put("time_zone",zone.id)
            .put("local_date",localDate.toString()).put("meal_type",mealType?:JSONObject.NULL).put("goal_id",JSONObject.NULL)
            .put("ration",JSONObject.NULL).put("items",JSONArray(rows))
        StrictJson.canonical(JSONObject().put("expected_revision",read.revision)
            .put("meal",JSONObject().put("meal_id",mealId).put("payload",meal)).put("drafts",JSONArray())).toByteArray(Charsets.UTF_8)
    }
    fun journal():JSONObject = safe {
        val rows=items.map {item->JSONObject().put("id",item.id).put("source_component_id",item.sourceComponentId?:JSONObject.NULL)
            .put("name",item.name).put("amount",ContractDecimal.canonical(item.portion.amount)).put("unit",item.portion.unit.wire)
            .put("nutrition",nutrition(item.portion.per100))}
        JSONObject().put("format","photo-meal-draft-v1").put("analysis_id",analysisId).put("source_revision",sourceRevision)
            .put("source_fingerprint",sourceFingerprint).put("meal_id",mealId).put("edit_revision",editRevision)
            .put("title",title).put("occurred_at",occurredAt.toString()).put("time_zone",zone.id)
            .put("meal_type",mealType?:JSONObject.NULL).put("items",JSONArray(rows)).also {
                require(StrictJson.canonical(it).toByteArray(Charsets.UTF_8).size<=MAX_BYTES)
            }
    }
    override fun toString()="PhotoMealDraft(redacted)"
    companion object {
        const val MAX_BYTES=262_144
        fun create(read:PhotoAnalysisRead,mealId:String,itemIds:List<String>,occurredAt:Instant,zone:ZoneId):PhotoMealDraft = safe {
            require(read.state=="succeeded" && read.decision=="pending")
            val proposal=checkNotNull(read.proposal);require(itemIds.size==proposal.items.size)
            PhotoMealDraft(read.analysisId,read.revision,checkNotNull(read.proposalFingerprint),mealId,1,"Posiłek ze zdjęcia",
                occurredAt.truncatedTo(ChronoUnit.MICROS),zone,null,proposal.items.zip(itemIds).map {(source,id)->
                    PhotoDraftItem(id,source.componentId,source.name,source.portion)})
        }
        fun restore(value:JSONObject):PhotoMealDraft = safe {
            require(StrictJson.canonical(value).toByteArray(Charsets.UTF_8).size<=MAX_BYTES)
            exact(value,setOf("format","analysis_id","source_revision","source_fingerprint","meal_id","edit_revision","title","occurred_at","time_zone","meal_type","items"))
            require(value.get("format")=="photo-meal-draft-v1")
            val rows=value.getJSONArray("items");require(rows.length() in 1..30)
            val items=(0 until rows.length()).map {index->
                val row=rows.getJSONObject(index);exact(row,setOf("id","source_component_id","name","amount","unit","nutrition"))
                val fields=row.getJSONObject("nutrition");exact(fields,ExactNutrition.fields.toSet())
                val values=ExactNutrition.read(ExactNutrition.fields.associateWith {field->nullable(fields,field)})
                val amount=ContractDecimal.read(row.get("amount") as String);val unit=QuantityUnit.read(row.get("unit") as String)
                PhotoDraftItem(row.get("id") as String,nullable(row,"source_component_id"),row.get("name") as String,ExactPortion(amount,unit,unit,values))
            }
            val time=value.get("occurred_at") as String;val instant=Instant.parse(time)
            require(instant.toString()==time)
            PhotoMealDraft(value.get("analysis_id") as String,integer(value,"source_revision"),value.get("source_fingerprint") as String,
                value.get("meal_id") as String,integer(value,"edit_revision"),value.get("title") as String,instant,
                ZoneId.of(value.get("time_zone") as String),nullable(value,"meal_type"),items)
        }
        private fun integer(value:JSONObject,name:String):Long {
            val number=value.get(name);require(number is Int || number is Long);return (number as Number).toLong()
        }
        private fun nullable(value:JSONObject,name:String):String? = if(value.get(name)===JSONObject.NULL)null else value.get(name) as String
        private fun exact(value:JSONObject,fields:Set<String>){require(value.keys().asSequence().toSet()==fields)}
        private fun nutrition(value:ExactNutrition)=JSONObject().also {json->ExactNutrition.fields.zip(value.values()).forEach {(key,number)->json.put(key,number?.let(ContractDecimal::canonical)?:JSONObject.NULL)}}
        fun validateInput(input:PhotoDraftInput) = safe {
            val value=item("00000000-0000-4000-8000-000000000001",null,input)
            text(value.name,2000);NutritionV1.calculate(listOf(value.portion));Unit
        }
        private fun item(id:String,component:String?,input:PhotoDraftInput):PhotoDraftItem {
            fun number(value:String):BigDecimal? {
                if(value.isBlank())return null
                val normalized=value.trim().replace(',','.')
                require(Regex("(0|[1-9][0-9]{0,5})([.][0-9]{1,6})?").matches(normalized))
                return ContractDecimal.read(ContractDecimal.canonical(BigDecimal(normalized)))
            }
            val amount=checkNotNull(ContractDecimal.userQuantity(input.amount));val unit=QuantityUnit.read(input.unit)
            return PhotoDraftItem(id,component,input.name.trim(),ExactPortion(amount,unit,unit,
                ExactNutrition(number(input.energy),number(input.protein),number(input.fat),number(input.carbs))))
        }
        private fun text(value:String,max:Int) {
            require(value.isNotBlank() && '\u0000' !in value && value.codePointCount(0,value.length) in 1..max)
            value.forEachIndexed {index,char->
                require(!char.isHighSurrogate() || value.getOrNull(index+1)?.isLowSurrogate()==true)
                require(!char.isLowSurrogate() || value.getOrNull(index-1)?.isHighSurrogate()==true)
            }
        }
        private inline fun <T> safe(action:()->T):T=try{action()}catch(_:Exception){throw PhotoMealDraftException()}
    }
}
