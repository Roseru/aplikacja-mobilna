package pl.roseru.kalorie.core

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.Instant
import java.time.LocalDateTime
import java.util.Collections
import java.security.MessageDigest

internal class PhotoAnalysisReadException : IllegalArgumentException("Niepoprawny wynik analizy zdjęcia")

/** Read-only proposals. Nothing in these objects authorizes a diary or product write. */
internal class PhotoAnalysisRead(val analysisId:String,val revision:Long,val state:String,val decision:String,
    val queueDeadline:Instant,val photoExpiresAt:Instant,val profile:PhotoAnalysisProfile,
    val proposal:PhotoProposal?,val errorCode:String?,internal val wireFingerprint:String,internal val proposalFingerprint:String?) {
    override fun toString()="PhotoAnalysisRead(redacted)"
}
internal class PhotoProposal(val items:List<PhotoProposalItem>,val notes:List<String>,val totals:ExactTotals,val modelVersion:String?) {
    override fun toString()="PhotoProposal(redacted)"
}
internal class PhotoProposalItem(val componentId:String,val name:String,val portion:ExactPortion,
    val identity:PhotoItemIdentity,val uncertainty:String,val notes:List<String>,val matches:PhotoItemMatches) {
    override fun toString()="PhotoProposalItem(redacted)"
}
internal class PhotoIdentityValue(val state:String,val value:String?) {
    override fun toString()="PhotoIdentityValue(redacted)"
}
internal class PhotoComposition(val state:String,val recipe:String?,val ingredients:List<String>?) {
    override fun toString()="PhotoComposition(redacted)"
}
internal class PhotoItemIdentity(val brand:PhotoIdentityValue,val variant:PhotoIdentityValue,val composition:PhotoComposition) {
    override fun toString()="PhotoItemIdentity(redacted)"
}
internal class PhotoProductReference(val productId:String,val revision:Long) {
    override fun toString()="PhotoProductReference(redacted)"
}
internal class PhotoMatchCandidate(val product:PhotoProductReference,val provenance:String,
    val reasons:List<String>,val highConfidence:Boolean) {
    override fun toString()="PhotoMatchCandidate(redacted)"
}
internal class PhotoItemMatches(val decision:String,val existing:PhotoProductReference?,
    val candidates:List<PhotoMatchCandidate>,val missingIdentityFields:List<String>,val truncated:Boolean) {
    override fun toString()="PhotoItemMatches(redacted)"
}

/** Bounded strict GET decoder, bound to the immutable create receipt. No IO or scheduling. */
internal object PhotoAnalysisReadProtocol {
    // The server permits a 1 MiB proposal; the GET envelope/profile adds bytes around it.
    const val MAX_BYTES=2*1_048_576
    fun read(bytes:ByteArray,expected:PhotoCreateReceipt):PhotoAnalysisRead {
        try {
            require(bytes.size in 1..MAX_BYTES)
            depth(bytes)
            val value=StrictJson.read(bytes)
            exact(value,setOf("analysis_id","revision","state","decision_state","queue_deadline","photo_expires_at","profile","proposal","error_code"))
            val id=PhotoHttpRequest.uuid(text(value.get("analysis_id"),36))
            require(id==expected.analysisId)
            val revision=revision(value.get("revision"));require(revision>=expected.revision)
            val state=enum(value.get("state"),setOf("queued","running","succeeded","failed"))
            val decision=enum(value.get("decision_state"),setOf("pending","confirmed","cancelled"))
            val deadline=time(value.get("queue_deadline"));require(deadline==expected.queueDeadline)
            val expires=time(value.get("photo_expires_at"))
            profile(value.getJSONObject("profile"),expected.profile)
            val proposal=if(value.get("proposal")===JSONObject.NULL) null else proposal(value.getJSONObject("proposal"))
            val error=if(value.get("error_code")===JSONObject.NULL) null else text(value.get("error_code"),100)
                .also {require(Regex("[a-z][a-z0-9_]{0,99}").matches(it))}
            when(state) {
                "succeeded"->require(proposal!=null && error==null && decision!="cancelled")
                "failed"->require(proposal==null && error!=null && decision!="confirmed")
                else->require(proposal==null && error==null && decision=="pending")
            }
            if(decision=="cancelled") require(error=="analysis_cancelled")
            if(error=="analysis_cancelled") require(decision=="cancelled")
            return PhotoAnalysisRead(id,revision,state,decision,deadline,expires,expected.profile,proposal,error,
                fingerprint(value),if(proposal==null) null else fingerprint(value.getJSONObject("proposal")))
        } catch(_:Exception) {
            // JSONObject and numeric errors can include the rejected private value: do not retain their cause.
            throw PhotoAnalysisReadException()
        }
    }
    private fun profile(json:JSONObject,expected:PhotoAnalysisProfile) {
        val fields=mapOf("provider" to expected.provider,"model" to expected.model,"prompt_version" to expected.prompt,
            "schema_version" to expected.schema,"preparation_version" to expected.preparation,
            "rest_profile_version" to expected.rest,"mock_scenario" to expected.mockScenario)
        exact(json,fields.keys)
        fields.forEach { (key,value)->require(json.get(key)==(value?:JSONObject.NULL)) }
    }
    private fun proposal(json:JSONObject):PhotoProposal {
        require(StrictJson.canonical(json).toByteArray(Charsets.UTF_8).size<=1_048_576)
        exact(json,setOf("items","notes","totals","model_version","formula_version"))
        require(json.get("formula_version")==NutritionV1.FORMULA)
        val items=objects(json.getJSONArray("items"),1,30).map(::item)
        require(items.map {it.componentId}.toSet().size==items.size)
        val totals=NutritionV1.calculate(items.map {it.portion})
        val wire=json.getJSONObject("totals");exact(wire,ExactNutrition.fields.toSet())
        ExactNutrition.fields.zip(totals.fields()).forEach { (name,calculated)->
            val field=wire.getJSONObject(name);exact(field,setOf("known_sum","missing_count","complete","display"))
            val sum=text(field.get("known_sum"),27)
            require(Regex("(0|[1-9][0-9]{0,12})(\\.[0-9]{1,12})?").matches(sum))
            require(sum.toBigDecimal().compareTo(calculated.knownSum)==0)
            require(integer(field.get("missing_count"),0,30)==calculated.missingCount.toLong())
            require(boolean(field.get("complete"))==calculated.complete)
            require(field.get("display")==calculated.display)
        }
        val version=if(json.get("model_version")===JSONObject.NULL) null else text(json.get("model_version"),200,0,false)
        return PhotoProposal(immutable(items),strings(json.getJSONArray("notes"),0,10,2000),totals,version)
    }
    private fun item(json:JSONObject):PhotoProposalItem {
        exact(json,setOf("component_id","name","quantity","basis_unit","nutrition_per_100","identity","density","uncertainty","notes","matches"))
        val id=PhotoHttpRequest.uuid(text(json.get("component_id"),36))
        val quantity=json.getJSONObject("quantity");exact(quantity,setOf("amount","unit"))
        val amount=ContractDecimal.read(text(quantity.get("amount"),13))
        val unit=QuantityUnit.read(text(quantity.get("unit"),2))
        val basis=QuantityUnit.read(text(json.get("basis_unit"),2));require(unit==basis)
        require(json.get("density")===JSONObject.NULL)
        val nutrition=json.getJSONObject("nutrition_per_100");exact(nutrition,ExactNutrition.fields.toSet())
        val per100=ExactNutrition.read(ExactNutrition.fields.associateWith { field->
            if(nutrition.get(field)===JSONObject.NULL) null else text(nutrition.get(field),13)
        })
        val portion=ExactPortion(amount,unit,basis,per100)
        // Enforce quantity/nutrition ranges before exposing an individual item, even with all-null values.
        NutritionV1.calculate(listOf(portion))
        val identity=identity(json.getJSONObject("identity"))
        val matches=matches(json.getJSONObject("matches"),identity,per100)
        return PhotoProposalItem(id,text(json.get("name"),2000),portion,identity,
            enum(json.get("uncertainty"),setOf("low","medium","high")),strings(json.getJSONArray("notes"),0,5,2000),matches)
    }
    private fun identity(json:JSONObject):PhotoItemIdentity {
        exact(json,setOf("brand","variant","composition"))
        fun field(key:String):PhotoIdentityValue {
            val obj=json.getJSONObject(key);exact(obj,setOf("state","value"))
            val state=enum(obj.get("state"),setOf("known","unknown","not_applicable"))
            val value=if(obj.get("value")===JSONObject.NULL) null else text(obj.get("value"),2000)
            require((state=="known")== (value!=null))
            return PhotoIdentityValue(state,value)
        }
        val composition=json.getJSONObject("composition");exact(composition,setOf("state","value"))
        val state=enum(composition.get("state"),setOf("known","unknown"))
        val value=composition.get("value")
        val result=if(state=="unknown") {
            require(value===JSONObject.NULL);PhotoComposition(state,null,null)
        } else if(value is JSONArray) PhotoComposition(state,null,strings(value,1,100,2000))
        else PhotoComposition(state,text(value,4000),null)
        return PhotoItemIdentity(field("brand"),field("variant"),result)
    }
    private fun matches(json:JSONObject,identity:PhotoItemIdentity,nutrition:ExactNutrition):PhotoItemMatches {
        exact(json,setOf("decision","existing_product","candidates","missing_identity_fields","truncated"))
        val decision=enum(json.get("decision"),setOf("existing_variant","manual_candidates","new_product"))
        val existing=if(json.get("existing_product")===JSONObject.NULL) null else reference(json.getJSONObject("existing_product"))
        require((decision=="existing_variant")== (existing!=null))
        val candidates=objects(json.getJSONArray("candidates"),0,20).map {candidate->
            exact(candidate,setOf("product","provenance","reasons","high_confidence"))
            PhotoMatchCandidate(reference(candidate.getJSONObject("product")),
                enum(candidate.get("provenance"),setOf("official","community")),
                strings(candidate.getJSONArray("reasons"),1,20,2000),boolean(candidate.get("high_confidence")))
        }
        val missing=strings(json.getJSONArray("missing_identity_fields"),0,4,20)
        val expected=buildList {
            if(identity.brand.state=="unknown") add("brand")
            if(identity.variant.state=="unknown") add("variant")
            if(identity.composition.state=="unknown") add("composition")
            if(nutrition.energy==null) add("energy_kcal")
        }
        if(decision=="manual_candidates") require(missing==expected) else require(missing.isEmpty() && expected.isEmpty())
        return PhotoItemMatches(decision,existing,immutable(candidates),missing,boolean(json.get("truncated")))
    }
    private fun reference(json:JSONObject):PhotoProductReference {
        exact(json,setOf("product_id","revision"))
        return PhotoProductReference(PhotoHttpRequest.uuid(text(json.get("product_id"),36)),revision(json.get("revision")))
    }
    private fun exact(json:JSONObject,names:Set<String>) {require(json.keys().asSequence().toSet()==names)}
    private fun fingerprint(json:JSONObject)=MessageDigest.getInstance("SHA-256")
        .digest(StrictJson.canonical(json).toByteArray(Charsets.UTF_8)).joinToString(""){"%02x".format(it)}
    private fun text(value:Any,max:Int,min:Int=1,nonblank:Boolean=true):String {
        require(value is String && '\u0000' !in value)
        require(value.codePointCount(0,value.length) in min..max && (!nonblank || value.isNotBlank()))
        return value
    }
    private fun enum(value:Any,values:Set<String>)=text(value,100).also {require(it in values)}
    private fun integer(value:Any,min:Long,max:Long):Long {
        require(value is Int || value is Long)
        return (value as Number).toLong().also {require(it in min..max)}
    }
    private fun revision(value:Any)=integer(value,1,2_147_483_647)
    private fun boolean(value:Any):Boolean {require(value is Boolean);return value}
    private fun time(value:Any):Instant {
        val text=text(value,32)
        require(Regex("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.[0-9]{1,6})?Z").matches(text))
        require(LocalDateTime.parse(text.dropLast(1)).year in 1..9999)
        return Instant.parse(text)
    }
    private fun objects(array:JSONArray,min:Int,max:Int):List<JSONObject> {
        require(array.length() in min..max)
        return (0 until array.length()).map {array.getJSONObject(it)}
    }
    private fun strings(array:JSONArray,min:Int,max:Int,length:Int):List<String> {
        require(array.length() in min..max)
        return immutable((0 until array.length()).map {text(array.get(it),length)})
    }
    private fun <T> immutable(values:List<T>):List<T> = Collections.unmodifiableList(ArrayList(values))
    private fun depth(bytes:ByteArray) {
        var depth=0;var quoted=false;var escaped=false
        for(byte in bytes) {
            val c=byte.toInt().toChar()
            if(quoted) {
                if(escaped) escaped=false else if(c=='\\') escaped=true else if(c=='"') quoted=false
            } else when(c) {
                '"'->quoted=true
                '{','['->{depth++;require(depth<=20)}
                '}',']'->{depth--;require(depth>=0)}
            }
        }
    }
}
