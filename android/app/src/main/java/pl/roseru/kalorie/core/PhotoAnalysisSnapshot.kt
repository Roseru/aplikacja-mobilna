package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson

internal class PhotoAnalysisSnapshotException : IllegalArgumentException("Niepoprawny zapis analizy zdjęcia")

/** Versioned value for the existing receiptJson column. No IO or authority to write a diary.
 * Decode/merge outside Room/session guards; commit the serialized value with a source-row CAS.
 */
internal class PhotoAnalysisSnapshot private constructor(val serialized:String,
    val receipt:PhotoCreateReceipt,val latest:PhotoAnalysisRead?,private val originalAck:String,
    private val originalRead:String?=null,val cancellation:PhotoCancellation?=null,val mealDraft:PhotoMealDraft?=null,val confirmation:PhotoConfirmation?=null) {

    val cancelled get()=cancellation?.confirmedRevision!=null || latest?.decision=="cancelled"

    val confirmed get()=confirmation?.confirmed==true || latest?.decision=="confirmed"

    val canEditProposal get()=confirmation==null && !confirmed && !cancelled && latest?.state=="succeeded" && latest.decision=="pending" &&
        (cancellation==null || (cancellation.rejectedCode=="proposal_revision_conflict" && latest.revision>cancellation.expectedRevision))

    fun withMealDraft(value:PhotoMealDraft,expectedEditRevision:Long):PhotoAnalysisSnapshot = safe {
        require(canEditProposal)
        val current=mealDraft
        require((current?.editRevision?:0)==expectedEditRevision)
        require(value.editRevision==Math.addExact(expectedEditRevision,1))
        value.matches(checkNotNull(latest))
        if(current!=null)require(value.mealId==current.mealId && value.sourceRevision==current.sourceRevision && value.sourceFingerprint==current.sourceFingerprint)
        else require(value.sourceRevision==latest.revision)
        rebuild(latest,originalRead,cancellation,value)
    }
    fun withoutMealDraft(expectedEditRevision:Long):PhotoAnalysisSnapshot = safe {
        require(canEditProposal && mealDraft?.editRevision==expectedEditRevision)
        rebuild(latest,originalRead,cancellation,null)
    }

    /** A repeated POST ACK may never erase an already saved GET or replace the original ACK. */
    fun requireSameReceipt(bytes:ByteArray) = safe {
        require(bytes.size in 1..65_536)
        val exact=bytes.copyOf()
        PhotoAnalysisProtocol.storedCreate(exact,receipt.profile.provider)
        require(canonical(exact)==originalAck)
    }

    fun withRead(bytes:ByteArray):PhotoAnalysisSnapshot = safe {
        require(bytes.size in 1..PhotoAnalysisReadProtocol.MAX_BYTES)
        val exact=bytes.copyOf()
        val incoming=PhotoAnalysisReadProtocol.read(exact,receipt)
        confirmation?.takeIf {it.confirmed}?.let { decision->
            if(incoming.revision<=decision.expectedRevision)return@safe this
            require(incoming.state=="succeeded" && incoming.decision=="confirmed")
        }
        cancellation?.confirmedRevision?.let { revision->
            if(incoming.revision<revision)return@safe this
            require(incoming.decision=="cancelled" && incoming.state=="failed" && incoming.errorCode=="analysis_cancelled")
        }
        if(latest==null) {
            when(receipt.state) {
                "running"->require(incoming.state!="queued")
                "succeeded"->require(incoming.state=="succeeded" || incoming.decision=="cancelled")
                "failed"->require(incoming.state=="failed")
            }
        }
        val accepted=PhotoAnalysisProgress.accept(latest,incoming)
        if(accepted===latest) return@safe this
        rebuild(accepted,canonical(exact),cancellation)
    }

    fun prepareCancellation(key:String,expectedRevision:Long):PhotoAnalysisSnapshot = safe {
        val current=checkNotNull(latest)
        require(confirmation==null && !cancelled && current.decision=="pending" && current.revision==expectedRevision)
        cancellation?.let { previous->
            require(previous.rejectedCode=="proposal_revision_conflict" && current.revision>previous.expectedRevision && key!=previous.key)
        }
        rebuild(latest,originalRead,PhotoCancellation.prepare(key,expectedRevision))
    }
    fun markCancellationAttempted():PhotoAnalysisSnapshot = safe {
        require(!cancelled && latest?.decision=="pending")
        val previous=checkNotNull(cancellation);val next=previous.markAttempted()
        if(next===previous)this else rebuild(latest,originalRead,next)
    }
    fun withCancellationReceipt(bytes:ByteArray):PhotoAnalysisSnapshot = safe {
        val previous=checkNotNull(cancellation)
        val next=previous.accept(bytes,receipt.analysisId)
        require(latest?.decision!="confirmed")
        require(checkNotNull(next.confirmedRevision)>checkNotNull(latest).revision || latest.decision=="cancelled")
        if(next===previous)this else rebuild(latest,originalRead,next)
    }
    fun rejectCancellation(code:String):PhotoAnalysisSnapshot = safe {
        require(!cancelled)
        rebuild(latest,originalRead,checkNotNull(cancellation).reject(code))
    }
    fun prepareConfirmation(key:String,revision:Long,editRevision:Long):PhotoAnalysisSnapshot = safe {
        val read=checkNotNull(latest);val draft=checkNotNull(mealDraft)
        require(canEditProposal && read.revision==revision && draft.editRevision==editRevision)
        require(key!=cancellation?.key && key!=receipt.analysisId)
        rebuild(read,originalRead,cancellation,draft,PhotoConfirmation.prepare(key,draft,read))
    }
    fun markConfirmationAttempted():PhotoAnalysisSnapshot = safe {
        val previous=checkNotNull(confirmation)
        require(!cancelled && (latest?.decision=="pending" || (latest?.decision=="confirmed" && previous.attempted)))
        rebuild(latest,originalRead,cancellation,mealDraft,previous.markAttempted())
    }
    fun withConfirmationReceipt(bytes:ByteArray):PhotoAnalysisSnapshot = safe {
        require(!cancelled)
        rebuild(latest,originalRead,cancellation,mealDraft,checkNotNull(confirmation).accept(bytes))
    }
    fun rejectConfirmation(code:String):PhotoAnalysisSnapshot = safe {
        require(!cancelled && confirmation?.confirmed!=true)
        rebuild(latest,originalRead,cancellation,mealDraft,checkNotNull(confirmation).reject(code))
    }
    private fun rebuild(read:PhotoAnalysisRead?,wire:String?,cancel:PhotoCancellation?,draft:PhotoMealDraft?=mealDraft,
        confirm:PhotoConfirmation?=confirmation):PhotoAnalysisSnapshot {
        val json=JSONObject().put("format",if(confirm!=null)CONFIRM_FORMAT else if(draft!=null)EDIT_FORMAT else if(cancel==null)FORMAT else CANCEL_FORMAT)
            .put("create",StrictJson.read(originalAck.toByteArray(Charsets.UTF_8)))
            .put("latest",wire?.let {StrictJson.read(it.toByteArray(Charsets.UTF_8))}?:JSONObject.NULL)
        if(cancel!=null || draft!=null || confirm!=null)json.put("cancellation",cancel?.journal()?:JSONObject.NULL)
        if(draft!=null || confirm!=null)json.put("meal_draft",draft?.journal()?:JSONObject.NULL)
        if(confirm!=null)json.put("confirmation",confirm.journal())
        val encoded=StrictJson.canonical(json)
        require(encoded.toByteArray(Charsets.UTF_8).size<=MAX_STORED_BYTES)
        return PhotoAnalysisSnapshot(encoded,receipt,read,originalAck,wire,cancel,draft,confirm)
    }

    override fun toString()="PhotoAnalysisSnapshot(redacted)"

    companion object {
        private const val FORMAT="photo-analysis-state-v1"
        private const val CANCEL_FORMAT="photo-analysis-state-v2"
        private const val EDIT_FORMAT="photo-analysis-state-v3"
        private const val CONFIRM_FORMAT="photo-analysis-state-v4"
        const val MAX_STORED_BYTES=PhotoAnalysisReadProtocol.MAX_BYTES+65_536+PhotoMealDraft.MAX_BYTES+PhotoConfirmation.MAX_BODY_BYTES+PhotoConfirmation.MAX_PROVENANCE_BYTES+PhotoConfirmation.MAX_RECEIPT_BYTES+4096

        /** Legacy raw ACKs remain readable; they are upgraded only when a GET is committed. */
        fun read(serialized:String,expectedProvider:String):PhotoAnalysisSnapshot = safe {
            require(serialized.length in 1..MAX_STORED_BYTES)
            val bytes=serialized.toByteArray(Charsets.UTF_8)
            require(bytes.size<=MAX_STORED_BYTES && bytes.toString(Charsets.UTF_8)==serialized)
            val json=StrictJson.read(bytes)
            if(!json.has("format")) {
                val receipt=PhotoAnalysisProtocol.storedCreate(bytes,expectedProvider)
                return@safe PhotoAnalysisSnapshot(serialized,receipt,null,StrictJson.canonical(json))
            }
            val version=json.get("format")
            require(version==FORMAT || version==CANCEL_FORMAT || version==EDIT_FORMAT || version==CONFIRM_FORMAT)
            require(json.keys().asSequence().toSet()==if(version==FORMAT)setOf("format","create","latest") else if(version==CANCEL_FORMAT)setOf("format","create","latest","cancellation") else if(version==EDIT_FORMAT)setOf("format","create","latest","cancellation","meal_draft") else setOf("format","create","latest","cancellation","meal_draft","confirmation"))
            val ack=StrictJson.canonical(json.getJSONObject("create"))
            val receipt=PhotoAnalysisProtocol.storedCreate(ack.toByteArray(Charsets.UTF_8),expectedProvider)
            val base=PhotoAnalysisSnapshot(serialized,receipt,null,ack)
            val merged=if(json.get("latest")===JSONObject.NULL)base else
                base.withRead(StrictJson.canonical(json.getJSONObject("latest")).toByteArray(Charsets.UTF_8))
            val cancel=if(version!=FORMAT && json.get("cancellation")!==JSONObject.NULL)PhotoCancellation.restore(json.getJSONObject("cancellation"),receipt.analysisId) else null
            if(version==CANCEL_FORMAT)require(cancel!=null)
            val draft=if(version==EDIT_FORMAT || version==CONFIRM_FORMAT)PhotoMealDraft.restore(json.getJSONObject("meal_draft")) else null
            draft?.matches(checkNotNull(merged.latest))
            if(cancel!=null) {
                val latest=checkNotNull(merged.latest)
                require(cancel.expectedRevision>=receipt.revision && cancel.expectedRevision<=latest.revision)
                if(cancel.confirmedRevision!=null) {
                    require(latest.decision!="confirmed")
                    if(latest.revision>=cancel.confirmedRevision)require(latest.decision=="cancelled")
                }
            }
            val confirmation=if(version==CONFIRM_FORMAT)PhotoConfirmation.restore(json.getJSONObject("confirmation"),checkNotNull(draft),checkNotNull(merged.latest)) else null
            if(confirmation!=null) {
                require(cancel==null || cancel.rejectedCode=="proposal_revision_conflict")
                require(!cancelledBy(cancel))
                if(confirmation.confirmed)require(merged.latest?.decision!="cancelled")
                require(confirmation.key!=cancel?.key)
            }
            PhotoAnalysisSnapshot(serialized,receipt,merged.latest,ack,merged.originalRead,cancel,draft,confirmation)
        }

        private fun cancelledBy(value:PhotoCancellation?)=value?.confirmedRevision!=null
        private fun canonical(bytes:ByteArray)=StrictJson.canonical(StrictJson.read(bytes))
        private inline fun <T> safe(block:()->T):T = try {block()} catch(_:Exception) {
            // JSON/numeric exceptions can contain private data. Do not retain their causes.
            throw PhotoAnalysisSnapshotException()
        }
    }
}
