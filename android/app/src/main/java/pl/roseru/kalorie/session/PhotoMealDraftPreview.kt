package pl.roseru.kalorie.session

import pl.roseru.kalorie.core.*
import java.time.LocalDate
import java.util.Collections

data class PhotoDraftActions(val start:(String,Long,LocalDate)->Unit={_,_,_->},
    val replace:(String,Long,String,PhotoDraftInput)->Unit={_,_,_,_->},
    val add:(String,Long,PhotoDraftInput)->Unit={_,_,_->},val remove:(String,Long,String)->Unit={_,_,_->},
    val rename:(String,Long,String)->Unit={_,_,_->},val discard:(String,Long)->Unit={_,_->},
    val confirm:(String,Long,Long)->Unit={_,_,_->},val retryConfirmation:(String)->Unit={},
    val reopen:(String,Long,Long)->Unit={_,_,_->})

class PhotoDraftItemPreview(val id:String,val manuallyAdded:Boolean,val input:PhotoDraftInput,val energy:PhotoNutrientPreview) {
    override fun toString()="PhotoDraftItemPreview(redacted)"
}
class PhotoMealDraftPreview private constructor(val operationId:String,val editRevision:Long,val title:String,
    val localDate:String,val items:List<PhotoDraftItemPreview>,val nutrition:PhotoNutritionPreview) {
    override fun toString()="PhotoMealDraftPreview(redacted)"
    internal companion object {
        fun from(id:String,snapshot:PhotoAnalysisSnapshot):PhotoMealDraftPreview? {
            val draft=snapshot.mealDraft?:return null
            fun field(value:FieldAggregate)=PhotoNutrientPreview(value.display,value.missingCount)
            val totals=draft.totals
            val items=draft.items.map {item->
                val values=item.portion.per100.values().map {it?.let(ContractDecimal::canonical)?:""}
                PhotoDraftItemPreview(item.id,item.sourceComponentId==null,
                    PhotoDraftInput(item.name,ContractDecimal.canonical(item.portion.amount),item.portion.unit.wire,values[0],values[1],values[2],values[3]),
                    field(NutritionV1.calculate(listOf(item.portion)).energy))
            }
            return PhotoMealDraftPreview(id,draft.editRevision,draft.title,draft.localDate.toString(),Collections.unmodifiableList(ArrayList(items)),
                PhotoNutritionPreview(field(totals.energy),field(totals.protein),field(totals.fat),field(totals.carbs)))
        }
    }
}
