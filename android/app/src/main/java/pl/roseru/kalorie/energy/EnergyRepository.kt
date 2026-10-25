package pl.roseru.kalorie.energy

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.network.NetworkAccessGate
import pl.roseru.kalorie.core.network.NetworkPermit
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.session.*
import java.security.MessageDigest
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

data class EnergyLocalState(val scope:EnergyScope?,val axis:EnergyAxisState?,val versions:List<EnergyVersion>,val analyses:List<EnergyAnalysis>,
    val profile:ProfileRead?,val capabilities:PhotoCapabilitiesRead?,val unavailable:EnergyUnavailable?,val attempts:List<EnergyAttemptEntity>,
    val fetchedAt:Long,val reviewToken:String?,val retryAt:Long,val consentUncertain:Boolean=false) {
    fun matchesAnalysis(value:EnergyAnalysis,at:Instant):Boolean=runCatching {
        val state=checkNotNull(axis);val ownerProfile=checkNotNull(profile);val payload=checkNotNull(ownerProfile.profile)
        val source=StrictJson.read(value.sourceContext.toByteArray())
        state.epoch==value.epoch && state.generation==value.generation && state.axisRevision==value.sourceAxisRevision &&
            state.currentId==value.sourceEnergyId && payload.revision==source.getInt("profile_revision") &&
            ownerProfile.consents.revision==value.consentRevision && ownerProfile.goalTimelineRevision==source.getInt("goal_timeline_revision") &&
            value.dateTo==at.atZone(ZoneId.of(payload.timeZone)).toLocalDate().minusDays(1)
    }.getOrDefault(false)
    override fun toString()="EnergyLocalState(redacted)"
}
internal class EnergyRepository(private val store:EnergyStore,private val protocol:EnergyProtocol,private val sessions:EnergySessionAccess,
    private val gate:NetworkAccessGate,private val gateway:EnergyGateway?,private val now:()->Long=System::currentTimeMillis) {
    private val operations=Mutex()
    private val activeConsentChanges=java.util.concurrent.ConcurrentHashMap.newKeySet<String>()
    internal class ConsentChange(val marker:String)
    val configured get()=gateway!=null
    val sessionChanges get()=sessions.view
    fun observeBinding(lease:OwnerLease)=store.observeBinding(lease)
    suspend fun local(lease:OwnerLease):EnergyLocalState {
        val scope=store.scope(lease)?:return EnergyLocalState(null,null,emptyList(),emptyList(),null,null,null,emptyList(),0,null,0)
        val rows=store.cached(scope)
        fun row(kind:String)=rows.singleOrNull {it.kind==kind}
        fun <T> decode(kind:String,read:(ByteArray)->T):T?=row(kind)?.let {runCatching {read(it.wire.toByteArray(Charsets.UTF_8))}.getOrNull()}
        val axis=decode("state",protocol::state)
        val profile=decode("profile",ProfileReadProtocol::parse)
        val capabilities=decode("capabilities",PhotoCapabilitiesProtocol::parse)
        if(axis!=null)require(axis.epoch==scope.binding.syncEpoch && axis.generation==scope.binding.accountGeneration)
        if(profile!=null)require(profile.accountId==scope.binding.accountId && profile.syncEpoch==scope.binding.syncEpoch)
        val versions=rows.filter {it.kind=="version"}.mapNotNull {runCatching {protocol.version(StrictJson.read(it.wire.toByteArray()))}.getOrNull()}
        val analyses=rows.filter {it.kind=="analysis"}.mapNotNull {runCatching {protocol.analysisResponse(it.wire.toByteArray()) as EnergyAnalysis}.getOrNull()}
        val unavailable=decode("unavailable",protocol::analysisResponse) as? EnergyUnavailable
        val complete=listOfNotNull(row("state"),row("profile"),row("capabilities"))
        val attempts=store.attempts(scope)
        val consentUncertain=rows.any {it.kind=="consent_uncertain"} || attempts.any {it.wireContext==scope.wireContext && it.kind=="consent" && it.state in EnergyStore.pendingStates}
        val review=if(!consentUncertain && axis!=null && profile!=null && capabilities!=null && complete.size==3)token(complete.map {it.kind to it.wire})else null
        val shared=sessions.view.value.takeIf {it.binding?.lease==lease}?.mealPushRetryAt?:0
        return EnergyLocalState(scope,axis,versions.sortedByDescending {it.revision},analyses.sortedByDescending {it.acceptedAt},
            profile,capabilities,unavailable,attempts,complete.minOfOrNull {it.fetchedAt}?:0,review,maxOf(shared,store.retryAt(scope)),consentUncertain)
    }
    /** Called before the shared ranking PUT/retry; a GET overlapping that mutation cannot clear it. */
    suspend fun beginConsentChange(lease:OwnerLease):ConsentChange? {
        val scope=store.scope(lease)?:return null
        val marker=StrictJson.canonical(JSONObject().put("nonce",java.util.UUID.randomUUID().toString()))
        activeConsentChanges.add(marker)
        try {store.cache(scope,"consent_uncertain","consent",0,marker,now())}
        catch(error:Throwable){activeConsentChanges.remove(marker);throw error}
        return ConsentChange(marker)
    }
    fun finishConsentChange(change:ConsentChange?) {change?.let {activeConsentChanges.remove(it.marker)}}
    suspend fun refresh(lease:OwnerLease)=operations.withLock {
        val scope=store.scope(lease)?:throw EnergyAccessFailure("account_required")
        val permit=gate.captureAllowed()
        val fresh=fresh(scope,permit)
        history(scope,maxOf(0,fresh.axis.axisRevision-100),permit)
        var local=local(lease)
        while(fresh.axis.currentId!=null && local.versions.none {it.id==fresh.axis.currentId} && (local.versions.minOfOrNull {it.revision}?:0)>1) {
            history(scope,maxOf(0,local.versions.minOf {it.revision}-101),permit)
            local=local(lease)
        }
        val response=read(scope,"GET","/me/energy/analyses?limit=100",permit=permit)
        val rows=protocol.analyses(response.result.bytes)
        guard(response,scope){rows.forEach {store.cache(scope,"analysis",it.id,it.revision,it.wire,now())}}
    }
    suspend fun older(lease:OwnerLease)=operations.withLock {
        val snapshot=local(lease);val scope=snapshot.scope?:throw EnergyAccessFailure("account_required")
        val smallest=snapshot.versions.minOfOrNull {it.revision}?:return@withLock
        if(smallest>1)history(scope,maxOf(0,smallest-101),gate.captureAllowed())
    }
    suspend fun refreshAnalysis(lease:OwnerLease,id:String)=operations.withLock {
        require(java.util.UUID.fromString(id).toString()==id)
        val scope=store.scope(lease)?:throw EnergyAccessFailure("account_required")
        val response=read(scope,"GET","/me/energy/analyses/$id")
        val analysis=protocol.analysisResponse(response.result.bytes) as EnergyAnalysis
        require(analysis.id==id)
        guard(response,scope){store.cache(scope,"analysis",id,analysis.revision,analysis.wire,now())}
    }
    private class Fresh(val axis:EnergyAxisState,val profile:ProfileRead,val capabilities:PhotoCapabilitiesRead,val token:String)
    private suspend fun fresh(scope:EnergyScope,permit:NetworkPermit):Fresh {
        val marker=store.consentMarker(scope)
        val wasActive=marker!=null && activeConsentChanges.contains(marker)
        val state=read(scope,"GET","/me/energy/state",permit=permit)
        val axis=protocol.state(state.result.bytes)
        require(axis.epoch==scope.binding.syncEpoch && axis.generation==scope.binding.accountGeneration)
        val me=read(scope,"GET","/me",permit=permit)
        val profile=ProfileReadProtocol.parse(me.result.bytes)
        require(profile.accountId==scope.binding.accountId && profile.syncEpoch==scope.binding.syncEpoch)
        val caps=read(scope,"GET","/ai/capabilities",permit=permit)
        val capabilities=PhotoCapabilitiesProtocol.parse(caps.result.bytes)
        val meWire=StrictJson.canonical(StrictJson.read(me.result.bytes));val capWire=StrictJson.canonical(StrictJson.read(caps.result.bytes))
        val readAt=now()
        guard(caps,scope){
            store.cache(scope,"state","state",axis.axisRevision,axis.wire,readAt)
            store.cache(scope,"profile","profile",profile.consents.revision,meWire,readAt)
            store.cache(scope,"capabilities","capabilities",0,capWire,readAt)
            val consentPending=sessions.view.value.rankingConsentBusy || sessions.view.value.rankingConsent is RankingConsentState.Pending
            if(!wasActive && !consentPending && (marker==null || !activeConsentChanges.contains(marker)))store.clearConsentMarker(scope,marker)
        }
        return Fresh(axis,profile,capabilities,token(listOf("state" to axis.wire,"profile" to meWire,"capabilities" to capWire)))
    }
    private suspend fun history(scope:EnergyScope,after:Int,permit:NetworkPermit) {
        val response=read(scope,"GET","/me/energy/history?after_revision=$after&limit=100",permit=permit)
        val page=protocol.history(response.result.bytes,after)
        guard(response,scope){page.items.forEach {store.cache(scope,"version",it.id,it.revision,it.wire,now())}}
    }
    private suspend fun reviewed(lease:OwnerLease,expected:String,permit:NetworkPermit):Pair<EnergyScope,Fresh> {
        val scope=store.scope(lease)?:throw EnergyAccessFailure("account_required")
        val value=fresh(scope,permit)
        if(value.token!=expected)throw EnergyAccessFailure("review_changed")
        return scope to value
    }
    suspend fun create(lease:OwnerLease,reviewToken:String,accepted:Boolean,qualified:Boolean):EnergyAttemptEntity=operations.withLock {
        require(accepted && qualified)
        val permit=gate.captureAllowed();val (scope,value)=reviewed(lease,reviewToken,permit)
        if(!value.capabilities.available)throw EnergyAccessFailure("ai_unavailable")
        val body=protocol.analysisRequest(value.axis,value.capabilities.provider,accepted,qualified)
        send(scope,store.prepare(scope,"analysis-create","create","POST","/me/energy/analyses",body,null,now()).id,permit)
    }
    suspend fun decide(lease:OwnerLease,id:String,accept:Boolean):EnergyAttemptEntity=operations.withLock {
        val permit=gate.captureAllowed()
        val local=local(lease);val scope=local.scope?:throw EnergyAccessFailure("account_required")
        val analysis=local.analyses.single {it.id==id};val axis=local.axis?:throw EnergyAccessFailure("refresh_required")
        if(accept && !local.matchesAnalysis(analysis,Instant.ofEpochMilli(now())))throw EnergyAccessFailure("analysis_context_changed")
        val body=protocol.decisionRequest(axis,analysis,accept,Instant.ofEpochMilli(now()))
        send(scope,store.prepare(scope,"analysis:$id",if(accept)"accept" else "reject","POST",
            "/me/energy/analyses/"+if(accept)"accept" else "reject",body,null,now()).id,permit)
    }
    suspend fun revert(lease:OwnerLease,id:String,replaceId:String?,replaceApproved:Boolean):EnergyAttemptEntity=operations.withLock {
        val permit=gate.captureAllowed()
        val local=local(lease);val scope=local.scope?:throw EnergyAccessFailure("account_required")
        val axis=local.axis?:throw EnergyAccessFailure("refresh_required");val target=local.versions.single {it.id==id}
        val body=protocol.revertRequest(axis,target,replaceId,replaceApproved)
        send(scope,store.prepare(scope,"axis","revert","POST","/me/energy/revert",body,null,now()).id,permit)
    }
    suspend fun affirm(lease:OwnerLease,reviewToken:String,accepted:Boolean,qualified:Boolean):EnergyAttemptEntity=operations.withLock {
        require(accepted && qualified)
        val permit=gate.captureAllowed();val (scope,value)=reviewed(lease,reviewToken,permit)
        if(!value.capabilities.available)throw EnergyAccessFailure("ai_unavailable")
        require(value.profile.consents.automaticEnergyAdjustment)
        val body=protocol.affirmationRequest(value.axis,value.profile.consents.revision,value.capabilities.provider,accepted,qualified)
        send(scope,store.prepare(scope,"axis","affirm","POST","/me/energy/affirm",body,null,now()).id,permit)
    }
    suspend fun automatic(lease:OwnerLease,reviewToken:String,enabled:Boolean):EnergyAttemptEntity=operations.withLock {
        val permit=gate.captureAllowed();val (scope,value)=reviewed(lease,reviewToken,permit)
        if(sessions.view.value.rankingConsentBusy || sessions.view.value.rankingConsent is RankingConsentState.Pending)throw EnergyAccessFailure("pending_consent")
        val consent=value.profile.consents
        require(consent.automaticEnergyAdjustment!=enabled)
        val body=StrictJson.canonical(JSONObject().put("ranking",consent.ranking).put("automatic_energy_adjustment",enabled))
        send(scope,store.prepare(scope,"consents","consent","PUT","/me/consents",body,"\"${consent.revision}\"",now()).id,permit)
    }
    suspend fun retry(lease:OwnerLease,id:String):EnergyAttemptEntity=operations.withLock {
        val scope=store.scope(lease)?:throw EnergyAccessFailure("account_required")
        send(scope,id,gate.captureAllowed())
    }
    suspend fun discardUnsent(lease:OwnerLease,id:String)=operations.withLock {
        store.discardUnsent(store.scope(lease)?:throw EnergyAccessFailure("account_required"),id)
    }
    private class Response(val result:EnergyHttpResult,val ticket:ApiSession,val permit:NetworkPermit)
    private suspend fun <T> guard(response:Response,scope:EnergyScope,block:suspend ()->T):T {
        gate.requireCurrent(response.permit)
        return sessions.withSession(response.ticket,scope) {
            gate.requireCurrent(response.permit);store.transaction(scope,block)
        }
    }
    private suspend fun read(scope:EnergyScope,method:String,path:String,body:String?=null,attemptId:String?=null,
        permit:NetworkPermit=gate.captureAllowed()):Response {
        val transport=gateway?:throw EnergyAccessFailure("not_configured")
        gate.requireCurrent(permit);store.requireScope(scope)
        if(scope.binding.requiresRecovery)throw EnergyAccessFailure("recovery_required")
        val shared=sessions.view.value.mealPushRetryAt
        if(maxOf(shared,store.retryAt(scope))>now())throw EnergyAccessFailure("retry_after")
        var ticket=sessions.session(scope)
        repeat(2) {index->
            gate.requireCurrent(permit)
            val attempt=attemptId?.let {store.open(scope,it)}
            if(attempt?.state=="needs_reconciliation")throw EnergyAccessFailure("reconciliation_required")
            if((attempt?.retryAt?:0)>now())throw EnergyAccessFailure("retry_after")
            val captured=ticket
            val result=transport.request(captured,scope.binding.syncEpoch,method,path,body,attempt?.id,attempt?.ifMatch) {
                gate.requireCurrent(permit)
                sessions.withSession(captured,scope) {
                    gate.requireCurrent(permit);store.requireScope(scope)
                    if(attempt!=null)store.attempted(scope,attempt)
                }
            }
            val response=Response(result,captured,permit);guard(response,scope){}
            if(result.status==401 && index==0){ticket=sessions.session(scope,true);return@repeat}
            if(result.status in setOf(429,503)) {
                val seconds=BootstrapHttpProtocol.retrySeconds(result.retryAfter,now()).coerceAtLeast(1)
                val deadline=Math.addExact(now(),Math.multiplyExact(seconds,1000))
                guard(response,scope){store.defer(scope,deadline)}
                sessions.defer(captured,scope,deadline)
            }
            if(attemptId==null && result.status !in 200..299)throw EnergyAccessFailure(errorCode(result))
            return response
        }
        throw EnergyAccessFailure("login_required")
    }
    private suspend fun send(scope:EnergyScope,id:String,permit:NetworkPermit):EnergyAttemptEntity {
        val row=store.open(scope,id)
        val response=read(scope,row.method,row.path,row.body,id,permit)
        val result=response.result
        if(result.status in 200..299) {
            require(result.status==200)
            val wire=StrictJson.canonical(StrictJson.read(result.bytes))
            when(row.kind) {
                "create"->{
                    val value=protocol.analysisResponse(result.bytes)
                    if(value is EnergyAnalysis)require(value.epoch==scope.binding.syncEpoch && value.generation==scope.binding.accountGeneration)
                    guard(response,scope){
                        when(value) {
                            is EnergyAnalysis->store.cache(scope,"analysis",value.id,value.revision,value.wire,now())
                            is EnergyUnavailable->store.cache(scope,"unavailable","last",0,value.wire,now())
                        }
                        store.finish(scope,id,"succeeded",wire,null)
                    }
                }
                "accept","revert"->{
                    val version=protocol.version(StrictJson.read(result.bytes))
                    val request=StrictJson.read(row.body.toByteArray())
                    require(version.revision==Math.addExact(request.getInt("axis_revision"),1))
                    require(version.source==if(row.kind=="accept")"manual" else "revert")
                    require(version.sourceId==if(row.kind=="accept")request.getString("id")else row.id)
                    if(row.kind=="revert")require(StrictJson.read(version.audit.toByteArray()).getString("restored_id")==request.getString("id"))
                    guard(response,scope){store.cache(scope,"version",version.id,version.revision,version.wire,now());store.invalidateState(scope);store.finish(scope,id,"succeeded",wire,null)}
                }
                "reject"->{
                    val value=protocol.analysisResponse(result.bytes) as EnergyAnalysis
                    val request=StrictJson.read(row.body.toByteArray())
                    require(value.id==request.getString("id") && value.state=="rejected")
                    guard(response,scope){store.cache(scope,"analysis",value.id,value.revision,value.wire,now());store.finish(scope,id,"succeeded",wire,null)}
                }
                "affirm"->{
                    val (baseline,axis)=protocol.affirmation(result.bytes);val request=StrictJson.read(row.body.toByteArray())
                    require(baseline==request.getString("id") && axis==request.getInt("axis_revision"))
                    guard(response,scope){store.invalidateState(scope);store.finish(scope,id,"succeeded",wire,null)}
                }
                "consent"->{
                    val consent=ProfileReadProtocol.parseConsents(result.bytes);val request=StrictJson.read(row.body.toByteArray())
                    val revision=checkNotNull(row.ifMatch).removeSurrounding("\"").toInt()
                    require(consent.revision==Math.addExact(revision,1) && consent.ranking==request.getBoolean("ranking") && consent.automaticEnergyAdjustment==request.getBoolean("automatic_energy_adjustment"))
                    guard(response,scope){store.invalidateState(scope);store.invalidateProfile(scope);store.finish(scope,id,"succeeded",wire,null)}
                }
                else->error("Unsupported energy operation")
            }
        } else {
            val code=BootstrapHttpProtocol.errorCode(result.bytes)
            val state=when {
                code in setOf("idempotency_result_expired","idempotency_key_reused")->"needs_reconciliation"
                result.status in setOf(400,403,404,409,410,422,429)->"rejected"
                else->"unknown"
            }
            guard(response,scope){store.finish(scope,id,state,StrictJson.canonical(StrictJson.read(result.bytes)),code,store.retryAt(scope))}
        }
        return store.attempts(scope).single {it.id==id}
    }
    private fun errorCode(result:EnergyHttpResult)=try {BootstrapHttpProtocol.errorCode(result.bytes)}catch(_:Exception){"http_${result.status}"}
    companion object {
        private fun token(values:List<Pair<String,String>>)=MessageDigest.getInstance("SHA-256")
            .digest(values.sortedBy {it.first}.joinToString("\u0000"){it.first+"\u0000"+it.second}.toByteArray(Charsets.UTF_8)).joinToString(""){"%02x".format(it)}
    }
}
