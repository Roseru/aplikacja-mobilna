package pl.roseru.kalorie.energy

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate

/** Immutable wire strings are retained; callers receive fresh JSON objects, never mutable cache objects. */
@ConsistentCopyVisibility
data class EnergyAxisState internal constructor(val epoch:String,val generation:Int,val axisRevision:Int,
    val currentId:String?,val baselineId:String?,val automaticRequested:Boolean,val automaticEffective:Boolean,
    val automaticNotice:String?,val lastAppliedAt:Instant?,val nextApplyAt:Instant?,val wire:String) {
    override fun toString()="EnergyAxisState(redacted)"
}
@ConsistentCopyVisibility
data class EnergyVersion internal constructor(val id:String,val revision:Int,val effectiveFrom:LocalDate,
    val maintenance:BigDecimal,val method:String,val source:String,val sourceId:String,val supersedes:String?,
    val decidedAt:Instant,val audit:String,val wire:String) {
    override fun toString()="EnergyVersion(redacted)"
}
data class EnergyHistoryPage(val items:List<EnergyVersion>,val nextRevision:Int)
@ConsistentCopyVisibility
data class EnergyRuleResult internal constructor(val state:String,val completeDays:Int,val weightDays:Int,
    val firstMedian:BigDecimal?,val secondMedian:BigDecimal?,val proposed:BigDecimal?,val lower:BigDecimal?,val upper:BigDecimal?) {
    override fun toString()="EnergyRuleResult(redacted)"
}
sealed interface EnergyAnalysisResponse
@ConsistentCopyVisibility
data class EnergyUnavailable internal constructor(val state:String,val result:EnergyRuleResult,val wire:String):EnergyAnalysisResponse {
    override fun toString()="EnergyUnavailable(redacted)"
}
@ConsistentCopyVisibility
data class EnergyAnalysis internal constructor(val id:String,val revision:Int,val state:String,val automatic:Boolean,
    val acceptedAt:Instant,val createdAt:Instant?,val expiresAt:Instant?,val dateFrom:LocalDate,val dateTo:LocalDate,
    val result:EnergyRuleResult,val explanation:String?,val uncertainty:String?,val suggestedClass:String?,val errorCode:String?,
    val epoch:String,val generation:Int,val sourceAxisRevision:Int,val sourceEnergyId:String?,val consentRevision:Int,
    val notice:String,val sourceContext:String,val wire:String):EnergyAnalysisResponse {
    fun canAccept(at:Instant)=state=="ready" && result.state=="ready" && result.proposed!=null && expiresAt?.let {at<it}==true
    override fun toString()="EnergyAnalysis(redacted)"
}

/** No local inference of E from a food goal and no model-selected numeric corrections. */
class EnergyProtocol(private val schema:EnergySchema) {
    fun state(bytes:ByteArray):EnergyAxisState {
        val value=schema.read(bytes,"EnergyState")
        val notice=value.optionalObject("automatic_notice")
        if(value.getBoolean("automatic_effective")) {
            require(value.getBoolean("automatic_requested") && !value.isNull("current_id") && !value.isNull("baseline_id") && notice!=null)
            require(notice.getString("scope")=="automatic_energy_adjustment" && notice.isNull("revoked_at"))
            require(notice.getString("sync_epoch")==value.getString("sync_epoch") && notice.getInt("account_generation")==value.getInt("account_generation"))
            require(notice.optionalString("baseline_id")==value.optionalString("baseline_id"))
        }
        return EnergyAxisState(value.getString("sync_epoch"),value.getInt("account_generation"),value.getInt("axis_revision"),
            value.optionalString("current_id"),value.optionalString("baseline_id"),value.getBoolean("automatic_requested"),
            value.getBoolean("automatic_effective"),notice?.let(StrictJson::canonical),value.optionalInstant("last_applied_at"),
            value.optionalInstant("next_apply_at"),StrictJson.canonical(value))
    }
    fun history(bytes:ByteArray,afterRevision:Int):EnergyHistoryPage {
        require(afterRevision>=0)
        val value=schema.read(bytes,"HistoryPage")
        val items=value.getJSONArray("items").let {rows->(0 until rows.length()).map {version(rows.getJSONObject(it))}}
        require(items.map {it.id}.distinct().size==items.size && items.map {it.revision}.distinct().size==items.size)
        var last=afterRevision
        items.forEach {require(it.revision>last);last=it.revision}
        // The API echoes after_revision on an empty terminal page; it never uses a null cursor.
        val next=value.getInt("next_revision")
        require(next==last)
        return EnergyHistoryPage(items,next)
    }
    fun version(value:JSONObject):EnergyVersion {
        schema.validate(value,"EnergyEntity")
        require(!value.getBoolean("deleted"))
        val payload=value.getJSONObject("payload")
        val energy=payload.getString("maintenance_kcal").toBigDecimal();require(energy>BigDecimal.ZERO)
        return EnergyVersion(value.getString("entity_id"),value.getInt("revision"),LocalDate.parse(payload.getString("effective_from")),
            energy,payload.getString("method"),payload.getString("source"),payload.getString("source_id"),payload.optionalString("supersedes"),
            Instant.parse(payload.getString("decided_at")),StrictJson.canonical(payload.getJSONObject("audit")),StrictJson.canonical(value))
    }
    fun analysisResponse(bytes:ByteArray):EnergyAnalysisResponse {
        require(bytes.size in 1..2*1_048_576)
        val raw=StrictJson.read(bytes)
        return if(raw.isNull("id")) {
            val value=schema.read(bytes,"UnavailableRead")
            val rule=rule(value.getJSONObject("result"))
            require(value.getString("state")==rule.state)
            EnergyUnavailable(rule.state,rule,StrictJson.canonical(value))
        } else analysis(schema.read(bytes,"AnalysisRead"))
    }
    fun analyses(bytes:ByteArray):List<EnergyAnalysis> {
        val value=schema.read(bytes,"AnalysisPage").getJSONArray("items")
        val rows=(0 until value.length()).map {analysis(value.getJSONObject(it))}
        require(rows.map {it.id}.distinct().size==rows.size)
        return rows
    }
    private fun analysis(value:JSONObject):EnergyAnalysis {
        val context=value.getJSONObject("source_context");val notice=value.getJSONObject("notice")
        require(context.getString("sync_epoch")==notice.getString("sync_epoch") && context.getInt("account_generation")==notice.getInt("account_generation"))
        require(context.getString("snapshot_hash")==notice.getString("snapshot_hash") && context.getInt("profile_revision")==notice.getInt("profile_revision"))
        require(context.getInt("consent_revision")==notice.getInt("consent_revision"))
        val automatic=value.getBoolean("automatic")
        require(notice.getString("scope")==if(automatic)"automatic_energy_adjustment" else "this_energy_analysis")
        val from=LocalDate.parse(value.getString("date_from"));val to=LocalDate.parse(value.getString("date_to"))
        require(from.plusDays(13)==to)
        val created=value.optionalInstant("created_at");val expires=value.optionalInstant("expires_at")
        require((created==null)==(expires==null))
        if(created!=null)require(expires==created.plusSeconds(24*60*60L))
        val result=rule(value.getJSONObject("result"));val explanation=value.optionalObject("explanation")
        val state=value.getString("state")
        if(state=="ready")require(result.state=="ready" && created!=null && explanation!=null && notice.isNull("revoked_at"))
        return EnergyAnalysis(value.getString("id"),value.getInt("revision"),state,automatic,Instant.parse(value.getString("accepted_at")),
            created,expires,from,to,result,explanation?.getString("explanation"),explanation?.getString("uncertainty"),
            explanation?.optionalString("suggested_class"),value.optionalString("error_code"),context.getString("sync_epoch"),
            context.getInt("account_generation"),context.getInt("energy_axis_revision"),context.optionalString("current_energy_id"),
            context.getInt("consent_revision"),StrictJson.canonical(notice),StrictJson.canonical(context),StrictJson.canonical(value))
    }
    private fun rule(value:JSONObject):EnergyRuleResult {
        val result=EnergyRuleResult(value.getString("state"),value.getInt("complete_days"),value.getInt("weight_days"),
            value.optionalDecimal("first_median"),value.optionalDecimal("second_median"),value.optionalDecimal("proposed"),
            value.optionalDecimal("lower"),value.optionalDecimal("upper"))
        listOfNotNull(result.firstMedian,result.secondMedian,result.proposed,result.lower,result.upper).forEach {require(it>BigDecimal.ZERO)}
        if(result.state=="ready") {
            require(result.completeDays==14 && result.weightDays>=4 && result.firstMedian!=null && result.secondMedian!=null &&
                result.proposed!=null && result.lower!=null && result.upper!=null)
            require(result.lower<=result.proposed && result.proposed<=result.upper)
        }
        return result
    }
    fun analysisRequest(state:EnergyAxisState,provider:String,noticeAccepted:Boolean,qualifiedForV1:Boolean):String =
        body("AnalysisRequest",context(state).put("notice",notice(provider,false,noticeAccepted,qualifiedForV1)))
    fun affirmationRequest(state:EnergyAxisState,consentRevision:Int,provider:String,noticeAccepted:Boolean,qualifiedForV1:Boolean):String {
        require(state.automaticRequested && state.currentId!=null && consentRevision>0)
        return body("AffirmRequest",context(state).put("id",state.currentId).put("consent_revision",consentRevision)
            .put("notice",notice(provider,true,noticeAccepted,qualifiedForV1)))
    }
    fun decisionRequest(state:EnergyAxisState,analysis:EnergyAnalysis,accept:Boolean,at:Instant):String {
        require(state.epoch==analysis.epoch && state.generation==analysis.generation && state.axisRevision==analysis.sourceAxisRevision)
        require(state.currentId==analysis.sourceEnergyId)
        if(accept)require(analysis.canAccept(at))
        else require(analysis.state !in setOf("accepted","rejected","expired","stale"))
        return body("DecisionRequest",JSONObject().put("sync_epoch",analysis.epoch).put("account_generation",analysis.generation)
            .put("axis_revision",analysis.sourceAxisRevision).put("id",analysis.id).put("revision",analysis.revision))
    }
    fun revertRequest(state:EnergyAxisState,target:EnergyVersion,replaceId:String?,replaceApproved:Boolean):String {
        require(target.revision<=state.axisRevision && target.id!=state.currentId)
        require(replaceId==null || replaceApproved)
        return body("RevertRequest",context(state).put("id",target.id).put("replace_id",replaceId?:JSONObject.NULL))
    }
    fun affirmation(bytes:ByteArray):Pair<String,Int> = schema.read(bytes,"AffirmRead").let {it.getString("baseline_id") to it.getInt("axis_revision")}
    private fun context(state:EnergyAxisState)=JSONObject().put("sync_epoch",state.epoch).put("account_generation",state.generation).put("axis_revision",state.axisRevision)
    private fun notice(provider:String,automatic:Boolean,accepted:Boolean,qualified:Boolean):JSONObject {
        require(accepted && qualified && provider in setOf("mock","gemini"))
        return JSONObject().put("accepted",true).put("qualified_for_v1",true).put("notice_version","energy-aggregates-notice-v1")
            .put("aggregate_scope","energy_adjustment_v1_minimal_aggregates").put("provider",provider)
            .put("scope",if(automatic)"automatic_energy_adjustment" else "this_energy_analysis")
    }
    private fun body(definition:String,value:JSONObject)=StrictJson.canonical(schema.validate(value,definition))
}

internal fun JSONObject.optionalString(key:String):String?=if(isNull(key))null else getString(key)
internal fun JSONObject.optionalObject(key:String):JSONObject?=if(isNull(key))null else getJSONObject(key)
internal fun JSONObject.optionalInstant(key:String):Instant?=optionalString(key)?.let(Instant::parse)
internal fun JSONObject.optionalDecimal(key:String):BigDecimal?=optionalString(key)?.toBigDecimal()
