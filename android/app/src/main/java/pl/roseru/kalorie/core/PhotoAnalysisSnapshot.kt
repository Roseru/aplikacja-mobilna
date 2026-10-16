package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson

internal class PhotoAnalysisSnapshotException : IllegalArgumentException("Niepoprawny zapis analizy zdjęcia")

/** Versioned value for the existing receiptJson column. No IO or authority to write a diary.
 * Decode/merge outside Room/session guards; commit the serialized value with a source-row CAS.
 */
internal class PhotoAnalysisSnapshot private constructor(val serialized:String,
    val receipt:PhotoCreateReceipt,val latest:PhotoAnalysisRead?,private val originalAck:String) {

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
        if(latest==null) {
            when(receipt.state) {
                "running"->require(incoming.state!="queued")
                "succeeded"->require(incoming.state=="succeeded" || incoming.decision=="cancelled")
                "failed"->require(incoming.state=="failed")
            }
        }
        val accepted=PhotoAnalysisProgress.accept(latest,incoming)
        if(accepted===latest) return@safe this
        val encoded=StrictJson.canonical(JSONObject().put("format",FORMAT)
            .put("create",StrictJson.read(originalAck.toByteArray(Charsets.UTF_8)))
            .put("latest",StrictJson.read(exact)))
        require(encoded.toByteArray(Charsets.UTF_8).size<=MAX_STORED_BYTES)
        PhotoAnalysisSnapshot(encoded,receipt,accepted,originalAck)
    }

    override fun toString()="PhotoAnalysisSnapshot(redacted)"

    companion object {
        private const val FORMAT="photo-analysis-state-v1"
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
            require(json.keys().asSequence().toSet()==setOf("format","create","latest"))
            require(json.get("format")==FORMAT)
            val ack=StrictJson.canonical(json.getJSONObject("create"))
            val receipt=PhotoAnalysisProtocol.storedCreate(ack.toByteArray(Charsets.UTF_8),expectedProvider)
            val base=PhotoAnalysisSnapshot(serialized,receipt,null,ack)
            if(json.get("latest")===JSONObject.NULL) base else {
                // Reuse every first-read invariant, including ACK state, on process restart.
                val merged=base.withRead(StrictJson.canonical(json.getJSONObject("latest")).toByteArray(Charsets.UTF_8))
                PhotoAnalysisSnapshot(serialized,receipt,merged.latest,ack)
            }
        }

        private fun canonical(bytes:ByteArray)=StrictJson.canonical(StrictJson.read(bytes))
        private inline fun <T> safe(block:()->T):T = try {block()} catch(_:Exception) {
            // JSON/numeric exceptions can contain private data. Do not retain their causes.
            throw PhotoAnalysisSnapshotException()
        }
    }
}
