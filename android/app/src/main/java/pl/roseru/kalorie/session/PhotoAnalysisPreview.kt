package pl.roseru.kalorie.session

import pl.roseru.kalorie.core.*
import java.util.Collections

/** Read-only presentation. All values originate in the strict decoder, never in a server write. */
class PhotoNutrientPreview(val display:String,val missingCount:Int) {
    override fun toString()="PhotoNutrientPreview(redacted)"
}
class PhotoNutritionPreview(val energy:PhotoNutrientPreview,val protein:PhotoNutrientPreview,
    val fat:PhotoNutrientPreview,val carbs:PhotoNutrientPreview) {
    override fun toString()="PhotoNutritionPreview(redacted)"
}
class PhotoItemPreview(val name:String,val amount:String,val unit:String,val nutrition:PhotoNutritionPreview,
    val uncertainty:String,val notes:List<String>) {
    override fun toString()="PhotoItemPreview(redacted)"
}
class PhotoAnalysisPreview private constructor(val revision:Long,val state:String,val decision:String,
    val provider:String,val model:String,val items:List<PhotoItemPreview>,val nutrition:PhotoNutritionPreview?,
    val notes:List<String>,val errorCode:String?) {
    override fun toString()="PhotoAnalysisPreview(redacted)"
    internal companion object {
        /** Projection must run outside SessionController's Room/mutex guard. */
        fun from(read:PhotoAnalysisRead):PhotoAnalysisPreview {
            val proposal=read.proposal
            val items=proposal?.items?.map { item->PhotoItemPreview(item.name,item.portion.amount.toPlainString(),
                item.portion.unit.wire,nutrition(NutritionV1.calculate(listOf(item.portion))),item.uncertainty,immutable(item.notes)) }?:emptyList()
            return PhotoAnalysisPreview(read.revision,read.state,read.decision,read.profile.provider,read.profile.model,
                immutable(items),proposal?.let {nutrition(it.totals)},immutable(proposal?.notes?:emptyList()),read.errorCode)
        }
        private fun nutrition(totals:ExactTotals):PhotoNutritionPreview {
            fun field(value:FieldAggregate)=PhotoNutrientPreview(value.display,value.missingCount)
            return PhotoNutritionPreview(field(totals.energy),field(totals.protein),field(totals.fat),field(totals.carbs))
        }
        private fun <T> immutable(values:List<T>):List<T> = Collections.unmodifiableList(ArrayList(values))
    }
}
