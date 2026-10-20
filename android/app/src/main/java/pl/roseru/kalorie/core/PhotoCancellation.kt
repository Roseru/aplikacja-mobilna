package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson

/** One explicit decision. Its key and revision stay fixed during an uncertain retry. */
internal class PhotoCancellation private constructor(val key:String,val expectedRevision:Long,
    val attempted:Boolean,val receiptJson:String?,val rejectedCode:String?,val confirmedRevision:Long?) {
    init {
        PhotoHttpRequest.uuid(key)
        require(expectedRevision in 1..Int.MAX_VALUE.toLong())
        require(receiptJson==null || attempted)
        require(rejectedCode==null || (attempted && rejectedCode in REJECTIONS))
        require(receiptJson==null || rejectedCode==null)
    }
    val pending get()=receiptJson==null && rejectedCode==null
    fun request(epoch:String,analysisId:String)=PhotoHttpRequest.Cancel(key,epoch,analysisId,expectedRevision)
    fun markAttempted():PhotoCancellation {
        require(pending)
        return if(attempted)this else PhotoCancellation(key,expectedRevision,true,null,null,null)
    }
    fun accept(bytes:ByteArray,analysisId:String):PhotoCancellation {
        require(attempted && rejectedCode==null)
        require(bytes.size in 1..65_536)
        val exact=bytes.copyOf()
        val revision=PhotoAnalysisProtocol.cancelled(exact,analysisId,expectedRevision)
        val canonical=StrictJson.canonical(StrictJson.read(exact))
        if(receiptJson!=null){require(receiptJson==canonical);return this}
        return PhotoCancellation(key,expectedRevision,true,canonical,null,revision)
    }
    fun reject(code:String):PhotoCancellation {
        require(attempted && pending && code in REJECTIONS)
        return PhotoCancellation(key,expectedRevision,true,null,code,null)
    }
    fun journal():JSONObject=JSONObject().put("key",key).put("expected_revision",expectedRevision)
        .put("attempted",attempted).put("receipt",receiptJson?.let {StrictJson.read(it.toByteArray(Charsets.UTF_8))}?:JSONObject.NULL)
        .put("rejected_code",rejectedCode?:JSONObject.NULL)
    override fun toString()="PhotoCancellation(redacted)"
    companion object {
        private val REJECTIONS=setOf("proposal_revision_conflict","idempotency_key_reused","analysis_already_confirmed","photo_cancel_rejected")
        fun prepare(key:String,revision:Long)=PhotoCancellation(key,revision,false,null,null,null)
        fun restore(value:JSONObject,analysisId:String):PhotoCancellation {
            require(value.keys().asSequence().toSet()==setOf("key","expected_revision","attempted","receipt","rejected_code"))
            val revision=value.get("expected_revision");require(revision is Int || revision is Long)
            val attempted=value.get("attempted");require(attempted is Boolean)
            val code=if(value.get("rejected_code")===JSONObject.NULL)null else value.get("rejected_code") as String
            val saved=PhotoCancellation(value.get("key") as String,(revision as Number).toLong(),attempted,null,code,null)
            return if(value.get("receipt")===JSONObject.NULL)saved else {
                require(code==null)
                saved.accept(StrictJson.canonical(value.getJSONObject("receipt")).toByteArray(Charsets.UTF_8),analysisId)
            }
        }
    }
}
