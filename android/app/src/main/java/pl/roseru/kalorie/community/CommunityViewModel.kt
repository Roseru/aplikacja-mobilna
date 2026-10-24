package pl.roseru.kalorie.community

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import pl.roseru.kalorie.core.network.NetworkAccessDenied
import pl.roseru.kalorie.data.*

data class CommunityViewState(val scope:CommunityScope?=null,val query:String="",val products:List<CommunityProduct> = emptyList(),
    val drafts:List<PublicationDraft> = emptyList(),val attempts:List<CommunityAttemptEntity> = emptyList(),
    val selected:CommunityProduct?=null,val feedback:CommunityFeedback?=null,val publication:PublicationDraft?=null,
    val matchBody:String?=null,val matches:CommunityMatches?=null,val previews:Map<PublicProductRef,CandidatePreview> = emptyMap(),
    val next:String?=null,val remote:Boolean=false,val loaded:Boolean=false,val busy:Boolean=false,
    val configured:Boolean=false,val retryAt:Long=0,val message:String?=null) {
    override fun toString()="CommunityViewState(redacted)"
}

class CommunityViewModel internal constructor(private val repository:CommunityRepository,private val lease:OwnerLease):ViewModel() {
    private val mutable=MutableStateFlow(CommunityViewState(configured=repository.configured))
    val state=mutable.asStateFlow()
    init {reload()}
    fun query(value:String) {
        if(mutable.value.busy)return
        if(value.codePointCount(0,value.length)<=100)mutable.value=mutable.value.copy(query=value,next=null,remote=false)
    }
    fun reload()=run {
        val local=repository.local(lease,mutable.value.query)
        mutable.value=mutable.value.copy(scope=local.scope,products=local.products,drafts=local.drafts,attempts=local.attempts,
            next=null,remote=false,loaded=true,retryAt=local.retryAt)
    }
    fun search(more:Boolean=false)=run {
        val before=mutable.value;val scope=requireNotNull(before.scope)
        val next=if(more)checkNotNull(before.next) else null
        val page=repository.search(scope,before.query.trim(),next)
        check(page.next==null || page.next!=next)
        // One bounded page in memory; restarting search returns to the first page.
        mutable.value=mutable.value.copy(products=page.items,next=page.next,remote=true,loaded=true)
    }
    fun select(product:CommunityProduct)=run {
        val scope=checkNotNull(mutable.value.scope)
        mutable.value=mutable.value.copy(selected=product,publication=null,feedback=repository.cachedFeedback(scope,product))
    }
    fun close() {
        if(mutable.value.busy)return
        mutable.value=mutable.value.copy(selected=null,feedback=null,publication=null,matches=null,matchBody=null,previews=emptyMap())
    }
    fun refreshDetail()=run {
        val before=mutable.value;val scope=checkNotNull(before.scope);val product=repository.detail(scope,checkNotNull(before.selected).ref)
        mutable.value=mutable.value.copy(selected=product,feedback=repository.feedback(scope,product))
    }
    fun openDraft(draft:PublicationDraft) {
        if(mutable.value.busy)return
        mutable.value=mutable.value.copy(publication=draft,selected=null,feedback=null,matches=null,matchBody=null,previews=emptyMap(),message=null)
    }
    fun matches(body:String)=run {
        val before=mutable.value
        val result=repository.matches(checkNotNull(before.scope),checkNotNull(before.publication),body)
        mutable.value=mutable.value.copy(matchBody=body,matches=result,previews=emptyMap())
    }
    fun preview(candidate:CommunityCandidate)=run {
        val preview=repository.preview(checkNotNull(mutable.value.scope),candidate)
        mutable.value=mutable.value.copy(previews=mutable.value.previews+(candidate.product to preview))
    }
    fun publish(selected:PublicProductRef?=null,confirmNew:Boolean=false)=run {
        val before=mutable.value
        val result=repository.publish(checkNotNull(before.scope),checkNotNull(before.publication),checkNotNull(before.matchBody),selected,confirmNew)
        refreshOperations(result)
    }
    fun vote(value:Int?)=run {
        val before=mutable.value;val scope=checkNotNull(before.scope);val product=checkNotNull(before.selected)
        val result=repository.vote(scope,product,checkNotNull(before.feedback),value)
        refreshOperations(result)
        if(result.state=="succeeded")mutable.value=mutable.value.copy(feedback=repository.feedback(scope,product))
    }
    fun report(reason:String,description:String)=run {
        val before=mutable.value
        refreshOperations(repository.report(checkNotNull(before.scope),checkNotNull(before.selected),reason,description))
    }
    fun retry(id:String)=run {refreshOperations(repository.retry(checkNotNull(mutable.value.scope),id))}
    fun discardUnsent(id:String)=run {
        repository.discardUnsent(checkNotNull(mutable.value.scope),id);refreshOperations(null)
    }
    private suspend fun refreshOperations(result:CommunityAttemptEntity?) {
        val local=repository.local(lease,mutable.value.query)
        val message=when(result?.state) {
            "succeeded"->when(result.kind){"publish"->"Serwer potwierdził publikację lub wybór istniejącego produktu.";"report"->"Zgłoszenie zostało przyjęte.";else->"Serwer potwierdził zmianę oceny."}
            "needs_reconciliation"->"Wynik wymaga wyjaśnienia. Zachowano identyfikator i treść wcześniejszego żądania."
            "rejected"->failure(result.errorCode?:"request_rejected")
            "unknown"->"Wynik nie jest potwierdzony. Ponowienie użyje tego samego zapisanego żądania."
            else->mutable.value.message
        }
        mutable.value=mutable.value.copy(drafts=local.drafts,attempts=local.attempts,retryAt=local.retryAt,message=message)
    }
    private fun run(action:suspend ()->Unit) {
        if(mutable.value.busy)return
        mutable.value=mutable.value.copy(busy=true,message=null)
        viewModelScope.launch {
            try {action()}
            catch(error:CancellationException){throw error}
            catch(_:StaleOwnerException){mutable.value=mutable.value.copy(message="Profil zmienił się. Otwórz katalog ponownie.")}
            catch(_:NetworkAccessDenied){mutable.value=mutable.value.copy(message="Ruch sieciowy jest zablokowany. Zapisany katalog i dziennik pozostają dostępne.")}
            catch(error:CommunityUnavailable){mutable.value=mutable.value.copy(message=failure(error.reason))}
            catch(_:Exception){mutable.value=mutable.value.copy(message="Nie udało się potwierdzić działania. Zapisane dane zachowano; sprawdź listę operacji przed ponowieniem.")}
            finally {
                // Reload durable outcomes even when a socket failed after sending.
                try {refreshOperations(null)}catch(error:CancellationException){throw error}catch(_:Exception){}
                mutable.value=mutable.value.copy(busy=false)
            }
        }
    }
    private fun failure(code:String)=when(code) {
        "not_configured"->"Ten wariant aplikacji nie ma skonfigurowanego API. Możesz korzystać z zapisanej bazy."
        "retry_after","http_429"->"Obowiązuje zapisana przerwa od serwera. Spróbuj po jej zakończeniu."
        "recovery_required","reconciliation_required"->"Najpierw uzgodnij konto i dane serwera w ekranie konta."
        "login_required","http_401"->"Zaloguj się ponownie. Dane zapisane na telefonie są zachowane."
        "vote_revision_conflict","revision_conflict"->"Ocena zmieniła się na innym urządzeniu. Odśwież szczegóły przed nowym wyborem."
        "own_product_vote","cannot_vote_own_product","own_product_vote_forbidden"->"Własnego produktu nie można oceniać."
        "product_not_found","http_404"->"Produkt jest niedostępny. Wcześniejsze posiłki zachowują swój zapis."
        "catalog_changed","page_token_expired","invalid_page_token"->"Katalog lub strona zmieniły się. Rozpocznij wyszukiwanie od początku."
        else->"Serwer nie potwierdził działania. Odśwież dane przed przygotowaniem nowej operacji."
    }
}
