package pl.roseru.kalorie.session

import pl.roseru.kalorie.core.PhotoAnalysisSnapshot

/** A display-only decision summary. It exposes neither mutation keys nor frozen wire data. */
class PhotoConfirmationStatus(val operationId:String,val revision:Long,val editRevision:Long,
    val canStart:Boolean,val canRetry:Boolean,val rejected:Boolean,val canReopen:Boolean=false) {
    override fun toString()="PhotoConfirmationStatus(redacted)"
    internal companion object {
        fun from(id:String,snapshot:PhotoAnalysisSnapshot,readProof:Boolean=false):PhotoConfirmationStatus? {
            val draft=snapshot.mealDraft?:return null
            val intent=snapshot.confirmation
            val read=snapshot.latest?:return null
            return PhotoConfirmationStatus(id,read.revision,draft.editRevision,snapshot.canEditProposal,
                !snapshot.cancelled && intent?.pending==true &&
                    (read.decision=="pending" || (read.decision=="confirmed" && intent.attempted)),
                intent?.rejectedCode!=null,readProof && snapshot.canReopenConfirmation)
        }
    }
}
