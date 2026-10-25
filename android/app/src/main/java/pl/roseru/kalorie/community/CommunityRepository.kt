package pl.roseru.kalorie.community

import android.content.Context
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.CatalogSchema
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.network.NetworkAccessGate
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*

class CommunityUnavailable(val reason:String):IllegalStateException(reason)
data class CommunityLocalState(val scope:CommunityScope?,val products:List<CommunityProduct>,
    val drafts:List<PublicationDraft>,val attempts:List<CommunityAttemptEntity>,val retryAt:Long)
data class CandidatePreview(val ref:PublicProductRef,val name:String,val unit:String,val energy:String?,val source:String)

internal class CommunityRepository(private val context:Context,private val store:CommunityStore,
    private val sessions:SessionController,private val gate:NetworkAccessGate,private val gateway:CommunityGateway?,
    private val now:()->Long=System::currentTimeMillis) {
    private val writes=Mutex()
    val configured get()=gateway!=null
    suspend fun local(lease:OwnerLease,query:String=""):CommunityLocalState {
        val scope=store.scope(lease)?:return CommunityLocalState(null,emptyList(),emptyList(),emptyList(),0)
        val shared=sessions.view.value.takeIf {it.binding?.lease==lease}?.mealPushRetryAt?:0
        return CommunityLocalState(scope,store.cached(scope,query),store.drafts(scope),store.attempts(scope),maxOf(shared,store.retryAt(scope)))
    }
    suspend fun search(scope:CommunityScope,query:String,next:String?):CommunityPage {
        require(query.codePointCount(0,query.length)<=100 && (query.isEmpty() || query.isNotBlank()))
        next?.let {CommunityProtocol.text(it,4096)}
        val path=buildString {
            append("/community/products?limit=10")
            if(query.isNotEmpty())append("&query=").append(HttpsCommunityGateway.encode(query))
            if(next!=null)append("&page_token=").append(HttpsCommunityGateway.encode(next))
        }
        val response=read(scope,"GET",path)
        val page=CommunityProtocol.page(response.result.bytes)
        guard(response,scope){store.cache(scope,page.items,now())}
        return page
    }
    suspend fun detail(scope:CommunityScope,ref:PublicProductRef):CommunityProduct {
        val response=read(scope,"GET","/community/products/${ref.id}?revision=${ref.revision}")
        val product=CommunityProtocol.product(response.result.bytes)
        require(product.ref==ref && product.visible)
        guard(response,scope){store.cache(scope,listOf(product),now())}
        return product
    }
    suspend fun feedback(scope:CommunityScope,product:CommunityProduct):CommunityFeedback {
        val response=read(scope,"GET","/products/${product.canonicalRef.id}/feedback")
        val value=CommunityProtocol.feedback(response.result.bytes)
        require(value.product.id==product.canonicalRef.id)
        guard(response,scope){store.saveFeedback(scope,product.ref,response.result.bytes)}
        return value
    }
    suspend fun cachedFeedback(scope:CommunityScope,product:CommunityProduct)=store.feedback(scope,product.ref)
    suspend fun matches(scope:CommunityScope,draft:PublicationDraft,body:String):CommunityMatches {
        requireDraft(scope,draft,body)
        val response=read(scope,"POST","/products/matches",body)
        val result=CommunityProtocol.matches(response.result.bytes)
        guard(response,scope){};return result
    }
    suspend fun preview(scope:CommunityScope,candidate:CommunityCandidate):CandidatePreview {
        if(candidate.provenance=="community") {
            val product=detail(scope,candidate.product)
            return CandidatePreview(product.ref,product.name,product.basisUnit,
                product.json().getJSONObject("nutrition_per_100").let {if(it.isNull("energy_kcal"))null else it.getString("energy_kcal")},product.sourceDescription)
        }
        val ref=candidate.product
        val response=read(scope,"GET","/products/${ref.id}?revision=${ref.revision}")
        val value=CommunityProtocol.read(response.result.bytes)
        val schema=CatalogSchema(context.assets.open("catalog/e2/common.schema.json").use {StrictJson.read(it.readBytes())},
            context.assets.open("catalog/e2/catalog.schema.json").use {StrictJson.read(it.readBytes())})
        schema.validate(value,"Product")
        require(value.getString("product_id")==ref.id && value.getInt("revision")==ref.revision)
        val nutrition=value.getJSONObject("nutrition_per_100")
        val result=CandidatePreview(ref,value.getString("name"),value.getString("basis_unit"),
            if(nutrition.isNull("energy_kcal"))null else nutrition.getString("energy_kcal"),value.getString("source_locator"))
        guard(response,scope){};return result
    }
    suspend fun publish(scope:CommunityScope,draft:PublicationDraft,matchBody:String,selected:PublicProductRef?,confirmNew:Boolean):CommunityAttemptEntity=writes.withLock {
        requireDraft(scope,draft,matchBody)
        val row=store.prepare(scope,"publish:${draft.id}","publish","POST","/products",
            CommunityProtocol.publishBody(matchBody,selected,confirmNew),null,now())
        send(scope,row.id)
    }
    suspend fun vote(scope:CommunityScope,product:CommunityProduct,feedback:CommunityFeedback,value:Int?):CommunityAttemptEntity=writes.withLock {
        require(value==null || value in listOf(-1,1))
        require(feedback.product.id==product.canonicalRef.id && !feedback.isMine && !product.isMine)
        val row=store.prepare(scope,"vote:${product.canonicalRef.id}",if(value==null)"withdraw" else "vote",
            if(value==null)"DELETE" else "PUT","/products/${product.canonicalRef.id}/vote",
            value?.let {StrictJson.canonical(JSONObject().put("value",it))},"\"${feedback.revision}\"",now())
        send(scope,row.id)
    }
    suspend fun report(scope:CommunityScope,product:CommunityProduct,reason:String,description:String):CommunityAttemptEntity=writes.withLock {
        val row=store.prepare(scope,"report:${product.ref.id}","report","POST","/products/${product.ref.id}/reports",
            CommunityProtocol.reportBody(product.ref,reason,description),null,now())
        send(scope,row.id)
    }
    suspend fun retry(scope:CommunityScope,id:String):CommunityAttemptEntity=writes.withLock {send(scope,id)}
    suspend fun discardUnsent(scope:CommunityScope,id:String)=writes.withLock {store.discardUnsent(scope,id)}
    private suspend fun requireDraft(scope:CommunityScope,draft:PublicationDraft,body:String) {
        val value=CommunityProtocol.read(body.toByteArray())
        require(value.getString("draft_id")==draft.id && value.getInt("draft_revision")==draft.revision)
        check(store.drafts(scope).any {it==draft})
    }
    private class ReadResponse(val result:CommunityHttpResult,val ticket:ApiSession,val permit:pl.roseru.kalorie.core.network.NetworkPermit)
    private suspend fun <T> guard(response:ReadResponse,scope:CommunityScope,block:suspend ()->T):T {
        gate.requireCurrent(response.permit)
        return sessions.withCommunitySession(response.ticket,scope){gate.requireCurrent(response.permit);store.requireScope(scope);block()}
    }
    private suspend fun read(scope:CommunityScope,method:String,path:String,body:String?=null,attemptId:String?=null):ReadResponse {
        val transport=gateway?:throw CommunityUnavailable("not_configured")
        val permit=gate.captureAllowed();store.requireScope(scope)
        if(scope.binding.requiresRecovery)throw CommunityUnavailable("recovery_required")
        if(store.retryAt(scope)>now())throw CommunityUnavailable("retry_after")
        var ticket=sessions.communitySession(scope)
        repeat(2) {index ->
            gate.requireCurrent(permit)
            val attempt=attemptId?.let {store.open(scope,it).also {row->
                if(row.state=="needs_reconciliation")throw CommunityUnavailable("reconciliation_required")
                if(row.retryAt>now())throw CommunityUnavailable("retry_after")
            }}
            val captured=ticket
            val result=transport.request(captured,scope.binding.syncEpoch,method,path,body,attempt?.id,attempt?.ifMatch) {
                gate.requireCurrent(permit)
                sessions.withCommunitySession(captured,scope) {
                    gate.requireCurrent(permit);store.requireScope(scope)
                    if(attempt!=null)store.attempted(scope,attempt)
                }
            }
            val response=ReadResponse(result,captured,permit)
            guard(response,scope){}
            if(result.status==401 && index==0) {ticket=sessions.communitySession(scope,true);return@repeat}
            if(result.status in setOf(429,503)) {
                val seconds=BootstrapHttpProtocol.retrySeconds(result.retryAfter,now()).coerceAtLeast(1)
                val deadline=Math.addExact(now(),Math.multiplyExact(seconds,1000))
                guard(response,scope){store.defer(scope,deadline)}
                sessions.deferCommunity(captured,scope,deadline)
            }
            if(attemptId==null && result.status !in 200..299)throw CommunityUnavailable(errorCode(result))
            return response
        }
        throw CommunityUnavailable("login_required")
    }
    private suspend fun send(scope:CommunityScope,id:String):CommunityAttemptEntity {
        val row=store.open(scope,id)
        val response=read(scope,row.method,row.path,row.body,id)
        val result=response.result
        if(result.status in 200..299) {
            require(result.status==if(row.kind=="report")201 else 200)
            // Parse before durable success; an invalid/lost response keeps the exact unknown request.
            when(row.kind) {
                "publish"->{
                    val (decision,ref)=CommunityProtocol.publishResult(result.bytes)
                    val sent=CommunityProtocol.read(checkNotNull(row.body).toByteArray())
                    val selected=sent.optJSONObject("selected_product")?.let(CommunityProtocol::ref)
                    require((decision=="selected_existing")== (selected!=null))
                    if(selected!=null)require(ref==selected)
                }
                "vote","withdraw"->{
                    val (revision,value)=CommunityProtocol.voteResult(result.bytes)
                    val previous=checkNotNull(row.ifMatch).removeSurrounding("\"").toLong()
                    require(revision==Math.addExact(previous,1) && revision<=Int.MAX_VALUE.toLong())
                    val expected=row.body?.let {CommunityProtocol.read(it.toByteArray()).getInt("value")}
                    require(value==expected)
                }
                "report"->CommunityProtocol.reportResult(result.bytes)
                else->error("kind")
            }
            guard(response,scope){store.finish(scope,id,"succeeded",StrictJson.canonical(CommunityProtocol.read(result.bytes)),null)}
        } else {
            // An invalid error body could hide an expired executed receipt. Keep it unknown.
            val code=BootstrapHttpProtocol.errorCode(result.bytes)
            val state=when {
                code in setOf("idempotency_result_expired","idempotency_key_reused") -> "needs_reconciliation"
                result.status in setOf(400,403,404,409,422,429) -> "rejected"
                else -> "unknown"
            }
            guard(response,scope){store.finish(scope,id,state,StrictJson.canonical(CommunityProtocol.read(result.bytes)),code,store.retryAt(scope))}
        }
        return store.attempts(scope).single {it.id==id}
    }
    private fun errorCode(result:CommunityHttpResult):String=try{BootstrapHttpProtocol.errorCode(result.bytes)}catch(_:Exception){"http_${result.status}"}
}
