package pl.roseru.kalorie.session

import pl.roseru.kalorie.core.PhotoAnalysisSnapshot

/** Own decision summary; mutation keys, bodies and identities never reach the UI. */
class PhotoCancellationStatus(val operationId:String,val revision:Long,val canStart:Boolean,
    val canRetry:Boolean,val cancelled:Boolean,val revisionConflict:Boolean) {
    override fun toString()="PhotoCancellationStatus(redacted)"
    internal companion object {
        fun from(id:String,snapshot:PhotoAnalysisSnapshot):PhotoCancellationStatus {
            val read=snapshot.latest
            val intent=snapshot.cancellation
            val pending=!snapshot.cancelled && read?.decision=="pending"
            val conflict=intent?.rejectedCode=="proposal_revision_conflict"
            return PhotoCancellationStatus(id,read?.revision?:snapshot.receipt.revision,
                pending && (intent==null || (conflict && checkNotNull(read).revision>intent.expectedRevision)),
                pending && intent?.pending==true,snapshot.cancelled,conflict)
        }
    }
}
