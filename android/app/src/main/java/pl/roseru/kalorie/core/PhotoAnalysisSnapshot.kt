package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson

internal class PhotoAnalysisSnapshotException : IllegalArgumentException("Niepoprawny zapis analizy zdjęcia")

/** Versioned value for the existing receiptJson column. No IO or authority to write a diary.
 * Decode/merge outside Room/session guards; commit the serialized value with a source-row CAS.
 */
internal class PhotoAnalysisSnapshot private constructor(val serialized:String,
    val receipt:PhotoCreateReceipt,val latest:PhotoAnalysisRead?,private val originalAck:String,
    private val originalRead:String?=null,val cancellation:PhotoCancellation?=null) {

    val cancelled get()=cancellation?.confirmedRevision!=null || latest?.decision=="cancelled"

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
        require(!cancelled && current.decision=="pending" && current.revision==expectedRevision)
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
    private fun rebuild(read:PhotoAnalysisRead?,wire:String?,cancel:PhotoCancellation?):PhotoAnalysisSnapshot {
        val json=JSONObject().put("format",if(cancel==null)FORMAT else CANCEL_FORMAT)
            .put("create",StrictJson.read(originalAck.toByteArray(Charsets.UTF_8)))
            .put("latest",wire?.let {StrictJson.read(it.toByteArray(Charsets.UTF_8))}?:JSONObject.NULL)
        if(cancel!=null)json.put("cancellation",cancel.journal())
        val encoded=StrictJson.canonical(json)
        require(encoded.toByteArray(Charsets.UTF_8).size<=MAX_STORED_BYTES)
        return PhotoAnalysisSnapshot(encoded,receipt,read,originalAck,wire,cancel)
    }

    override fun toString()="PhotoAnalysisSnapshot(redacted)"

    companion object {
        private const val FORMAT="photo-analysis-state-v1"
        private const val CANCEL_FORMAT="photo-analysis-state-v2"
        const val MAX_STORED_BYTES=PhotoAnalysisReadProtocol.MAX_BYTES+65_536+1024

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
            require(version==FORMAT || version==CANCEL_FORMAT)
            require(json.keys().asSequence().toSet()==if(version==FORMAT)setOf("format","create","latest") else setOf("format","create","latest","cancellation"))
            val ack=StrictJson.canonical(json.getJSONObject("create"))
            val receipt=PhotoAnalysisProtocol.storedCreate(ack.toByteArray(Charsets.UTF_8),expectedProvider)
            val base=PhotoAnalysisSnapshot(serialized,receipt,null,ack)
            val merged=if(json.get("latest")===JSONObject.NULL)base else
                base.withRead(StrictJson.canonical(json.getJSONObject("latest")).toByteArray(Charsets.UTF_8))
            val cancel=if(version==CANCEL_FORMAT)PhotoCancellation.restore(json.getJSONObject("cancellation"),receipt.analysisId) else null
            if(cancel!=null) {
                val latest=checkNotNull(merged.latest)
                require(cancel.expectedRevision>=receipt.revision && cancel.expectedRevision<=latest.revision)
                if(cancel.confirmedRevision!=null) {
                    require(latest.decision!="confirmed")
                    if(latest.revision>=cancel.confirmedRevision)require(latest.decision=="cancelled")
                }
            }
            PhotoAnalysisSnapshot(serialized,receipt,merged.latest,ack,merged.originalRead,cancel)
        }

        private fun canonical(bytes:ByteArray)=StrictJson.canonical(StrictJson.read(bytes))
        private inline fun <T> safe(block:()->T):T = try {block()} catch(_:Exception) {
            // JSON/numeric exceptions can contain private data. Do not retain their causes.
            throw PhotoAnalysisSnapshotException()
        }
    }
}
