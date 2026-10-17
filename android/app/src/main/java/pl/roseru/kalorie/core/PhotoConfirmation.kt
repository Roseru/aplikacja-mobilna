package pl.roseru.kalorie.core

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson

internal class PhotoConfirmationException:IllegalArgumentException("Niepoprawne potwierdzenie posiłku")

/** One frozen, explicit correction decision. It grants no authority to write a diary/outbox.
 * An ACK must later be materialized atomically with canonical E4 operations and provenance.
 */
internal class PhotoConfirmation private constructor(val key:String,val analysisId:String,val expectedRevision:Long,
    val editRevision:Long,private val requestJson:String,private val provenanceJson:String,
    val attempted:Boolean,val receiptJson:String?,val rejectedCode:String?) {
    val pending get()=receiptJson==null && rejectedCode==null
    val confirmed get()=receiptJson!=null
    init {
        PhotoHttpRequest.uuid(key);PhotoHttpRequest.uuid(analysisId);require(key!=analysisId)
        require(expectedRevision in 1..Int.MAX_VALUE.toLong() && editRevision in 1..Int.MAX_VALUE.toLong())
        require(requestJson.toByteArray(Charsets.UTF_8).size in 1..MAX_BODY_BYTES)
        require(provenanceJson.toByteArray(Charsets.UTF_8).size in 1..MAX_PROVENANCE_BYTES)
        require(receiptJson==null || (attempted && rejectedCode==null))
        require(rejectedCode==null || (attempted && rejectedCode in REJECTIONS))
    }
    fun request(epoch:String)=PhotoHttpRequest.Confirm(key,epoch,analysisId,expectedRevision,requestJson.toByteArray(Charsets.UTF_8))
    fun markAttempted():PhotoConfirmation = safe {
        require(pending)
        if(attempted)this else copy(attempted=true)
    }
    fun reject(code:String):PhotoConfirmation = safe {
        require(pending && attempted && code in REJECTIONS);copy(rejection=code)
    }
    /** Exact submitted template and original provider provenance, never a replacement chosen by a response. */
    fun accept(bytes:ByteArray):PhotoConfirmation = safe {
        require(attempted && rejectedCode==null && bytes.size in 1..MAX_RECEIPT_BYTES)
        val exact=bytes.copyOf();depth(exact);val value=StrictJson.read(exact);exact(value,setOf("analysis_id","meal","drafts","provenance"))
        require(value.get("analysis_id")==analysisId)
        val request=StrictJson.read(requestJson.toByteArray(Charsets.UTF_8))
        require(StrictJson.canonical(value.get("meal"))==StrictJson.canonical(request.get("meal")))
        require(StrictJson.canonical(value.get("drafts"))==StrictJson.canonical(request.get("drafts")))
        require(StrictJson.canonical(value.getJSONObject("provenance"))==provenanceJson)
        val canonical=StrictJson.canonical(value)
        if(receiptJson!=null){require(receiptJson==canonical);this}else copy(receipt=canonical)
    }
    private fun copy(attempted:Boolean=this.attempted,receipt:String?=receiptJson,rejection:String?=rejectedCode)=
        PhotoConfirmation(key,analysisId,expectedRevision,editRevision,requestJson,provenanceJson,attempted,receipt,rejection)
    fun journal():JSONObject=JSONObject().put("format","photo-confirmation-v1").put("key",key)
        .put("analysis_id",analysisId).put("expected_revision",expectedRevision).put("edit_revision",editRevision)
        .put("request",StrictJson.read(requestJson.toByteArray(Charsets.UTF_8)))
        .put("expected_provenance",StrictJson.read(provenanceJson.toByteArray(Charsets.UTF_8)))
        .put("attempted",attempted).put("receipt",receiptJson?.let {StrictJson.read(it.toByteArray(Charsets.UTF_8))}?:JSONObject.NULL)
        .put("rejected_code",rejectedCode?:JSONObject.NULL)
    override fun toString()="PhotoConfirmation(redacted)"
    companion object {
        const val MAX_BODY_BYTES=PhotoMealDraft.MAX_BYTES
        const val MAX_PROVENANCE_BYTES=65_536
        const val MAX_RECEIPT_BYTES=MAX_BODY_BYTES+MAX_PROVENANCE_BYTES+1024
        private val REJECTIONS=setOf("proposal_revision_conflict","photo_catalog_choice_changed","idempotency_key_reused",
            "analysis_already_confirmed","photo_confirm_rejected")
        fun prepare(key:String,draft:PhotoMealDraft,read:PhotoAnalysisRead):PhotoConfirmation = safe {
            PhotoConfirmation(key,read.analysisId,read.revision,draft.editRevision,
                canonical(draft.confirmBody(read)),provenance(read),false,null,null)
        }
        fun restore(value:JSONObject,draft:PhotoMealDraft,read:PhotoAnalysisRead):PhotoConfirmation = safe {
            require(StrictJson.canonical(value).toByteArray(Charsets.UTF_8).size<=MAX_BODY_BYTES+MAX_PROVENANCE_BYTES+MAX_RECEIPT_BYTES+2048)
            exact(value,setOf("format","key","analysis_id","expected_revision","edit_revision","request","expected_provenance","attempted","receipt","rejected_code"))
            require(value.get("format")=="photo-confirmation-v1" && value.get("analysis_id")==read.analysisId)
            draft.matches(read)
            val expected=integer(value,"expected_revision");require(expected in draft.sourceRevision..read.revision)
            val edit=integer(value,"edit_revision");require(edit==draft.editRevision)
            val request=StrictJson.canonical(value.getJSONObject("request"))
            require(request==canonical(draft.confirmationTemplate(expected)))
            val provenanceValue=value.getJSONObject("expected_provenance")
            validateProvenance(provenanceValue,read,draft)
            val provenance=StrictJson.canonical(provenanceValue)
            val attempted=value.get("attempted");require(attempted is Boolean)
            val code=if(value.get("rejected_code")===JSONObject.NULL)null else value.get("rejected_code") as String
            val saved=PhotoConfirmation(value.get("key") as String,read.analysisId,expected,edit,request,provenance,attempted,null,code)
            if(value.get("receipt")===JSONObject.NULL)saved else {
                require(read.decision!="cancelled")
                saved.accept(StrictJson.canonical(value.getJSONObject("receipt")).toByteArray(Charsets.UTF_8))
            }
        }
        private fun validateProvenance(value:JSONObject,read:PhotoAnalysisRead,draft:PhotoMealDraft) {
            if(read.proposal!=null){require(StrictJson.canonical(value)==provenance(read));return}
            require(read.decision=="cancelled") // frozen proof retained read-only; no ACK/diary can be accepted
            exact(value,setOf("analysis_id","provider","model","prompt_version","schema_version","preparation_version",
                "rest_profile_version","mock_scenario","model_version","uncertainty"))
            val p=read.profile
            val fields=mapOf("analysis_id" to read.analysisId,"provider" to p.provider,"model" to p.model,"prompt_version" to p.prompt,
                "schema_version" to p.schema,"preparation_version" to p.preparation,"rest_profile_version" to p.rest,"mock_scenario" to p.mockScenario)
            fields.forEach {(key,expected)->require(value.get(key)==(expected?:JSONObject.NULL))}
            val model=value.get("model_version");require(model===JSONObject.NULL || (model is String && model.codePointCount(0,model.length)<=200 && '\u0000' !in model))
            val rows=value.getJSONArray("uncertainty");require(rows.length() in 1..30)
            val ids=(0 until rows.length()).map {index->
                val row=rows.getJSONObject(index);exact(row,setOf("component_id","uncertainty"))
                require(row.get("uncertainty") in setOf("low","medium","high"));PhotoHttpRequest.uuid(row.get("component_id") as String)
            }
            require(ids.toSet().size==ids.size && draft.items.mapNotNull {it.sourceComponentId}.all {it in ids})
        }
        private fun depth(bytes:ByteArray) {
            var level=0;var quoted=false;var escaped=false
            for(byte in bytes) {
                val c=byte.toInt().toChar()
                if(quoted) {if(escaped)escaped=false else if(c=='\\')escaped=true else if(c=='"')quoted=false}
                else when(c) {'"'->quoted=true;'[','{'->{level++;require(level<=20)};']','}'->{level--;require(level>=0)}}
            }
        }
        private fun provenance(read:PhotoAnalysisRead):String {
            val profile=read.profile;val proposal=checkNotNull(read.proposal)
            return StrictJson.canonical(JSONObject().put("analysis_id",read.analysisId)
                .put("provider",profile.provider).put("model",profile.model).put("prompt_version",profile.prompt)
                .put("schema_version",profile.schema).put("preparation_version",profile.preparation)
                .put("rest_profile_version",profile.rest).put("mock_scenario",profile.mockScenario?:JSONObject.NULL)
                .put("model_version",proposal.modelVersion?:JSONObject.NULL)
                .put("uncertainty",JSONArray(proposal.items.map {JSONObject().put("component_id",it.componentId).put("uncertainty",it.uncertainty)})))
        }
        private fun canonical(bytes:ByteArray)=StrictJson.canonical(StrictJson.read(bytes))
        private fun integer(value:JSONObject,name:String):Long {
            val n=value.get(name);require(n is Int || n is Long);return (n as Number).toLong()
        }
        private fun exact(value:JSONObject,fields:Set<String>){require(value.keys().asSequence().toSet()==fields)}
        private inline fun <T> safe(action:()->T):T=try{action()}catch(_:Exception){throw PhotoConfirmationException()}
    }
}
