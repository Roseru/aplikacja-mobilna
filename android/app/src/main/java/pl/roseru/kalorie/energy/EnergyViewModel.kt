package pl.roseru.kalorie.energy

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import org.json.JSONObject
import pl.roseru.kalorie.core.RankingConsentState
import pl.roseru.kalorie.core.network.NetworkAccessDenied
import pl.roseru.kalorie.data.OwnerLease
import pl.roseru.kalorie.data.StaleOwnerException

data class EnergyViewState(val local:EnergyLocalState?=null,val loaded:Boolean=false,val busy:Boolean=false,
    val configured:Boolean=false,val selectedAnalysis:String?=null,val externalConsentRevision:Int=0,val externalConsentUncertain:Boolean=false,val message:String?=null) {
    val automaticEffective:Boolean get() {
        val data=local?:return false;val axis=data.axis?:return false;val consent=data.profile?.consents?:return false
        if(data.consentUncertain || externalConsentUncertain || !axis.automaticEffective || !consent.automaticEnergyAdjustment || consent.revision<externalConsentRevision)return false
        return runCatching {JSONObject(checkNotNull(axis.automaticNotice)).getInt("consent_revision")==consent.revision}.getOrDefault(false)
    }
    override fun toString()="EnergyViewState(redacted)"
}
class EnergyViewModel internal constructor(private val repository:EnergyRepository,private val lease:OwnerLease):ViewModel() {
    private val mutable=MutableStateFlow(EnergyViewState(configured=repository.configured))
    val state=mutable.asStateFlow()
    private var operation:Job?=null
    init {
        viewModelScope.launch {
            repository.observeBinding(lease).distinctUntilChanged().collectLatest {
                operation?.cancel()
                mutable.value=EnergyViewState(configured=repository.configured)
                reloadLocal()
            }
        }
        viewModelScope.launch {
            repository.sessionChanges.map {view->
                if(view.binding?.lease!=lease)null else maxOf(view.serverProfile?.consents?.revision?:0,
                    (view.rankingConsent as? RankingConsentState.Ready)?.source?.consents?.revision?:0,
                    (view.rankingConsent as? RankingConsentState.Confirmed)?.consents?.revision?:0) to
                    (view.rankingConsentBusy || view.rankingConsent is RankingConsentState.Pending)
            }.distinctUntilChanged().collect {consent->
                if(consent==null) {
                    operation?.cancel();mutable.value=EnergyViewState(configured=repository.configured)
                }else mutable.value=mutable.value.copy(externalConsentRevision=consent.first,externalConsentUncertain=consent.second)
            }
        }
    }
    fun reload()=perform {reloadLocal()}
    fun refresh()=perform {repository.refresh(lease);mutable.value=mutable.value.copy(message="Pobrano aktualny stan zapotrzebowania.")}
    fun older()=perform {repository.older(lease)}
    fun selectAnalysis(id:String?) {if(!mutable.value.busy)mutable.value=mutable.value.copy(selectedAnalysis=id)}
    fun refreshAnalysis(id:String)=perform {repository.refreshAnalysis(lease,id)}
    fun create(token:String,accepted:Boolean,qualified:Boolean)=mutation {repository.create(lease,token,accepted,qualified)}
    fun decide(id:String,accept:Boolean)=mutation {repository.decide(lease,id,accept)}
    fun revert(id:String,replaceId:String?,approved:Boolean)=mutation {repository.revert(lease,id,replaceId,approved)}
    fun automatic(token:String,enabled:Boolean)=mutation {repository.automatic(lease,token,enabled)}
    fun affirm(token:String,accepted:Boolean,qualified:Boolean)=mutation {repository.affirm(lease,token,accepted,qualified)}
    fun retry(id:String)=mutation {repository.retry(lease,id)}
    fun discardUnsent(id:String)=perform {repository.discardUnsent(lease,id)}
    fun cancel() {operation?.cancel()}
    private fun mutation(action:suspend ()->EnergyAttemptEntity)=perform {
        val row=action()
        mutable.value=mutable.value.copy(message=when(row.state) {
            "succeeded"->"Serwer potwierdził operację. Cel posiłków i makra pozostają bez zmian."
            "rejected"->energyMessage(row.errorCode?:"rejected")
            "needs_reconciliation"->"Wynik wymaga uzgodnienia. Zachowano poprzednią decyzję; nie twórz jej ponownie."
            else->"Wynik nie jest potwierdzony. Poprzednia operacja pozostaje do sprawdzenia."
        })
        if(row.state=="succeeded") {
            try {repository.refresh(lease)}
            catch(error:CancellationException){throw error}
            catch(_:Exception){mutable.value=mutable.value.copy(message="Operacja jest potwierdzona. Nie udało się pobrać nowego podglądu; odśwież go po odzyskaniu połączenia.")}
        }
    }
    private suspend fun reloadLocal() {
        try {
            val local=repository.local(lease)
            val selected=mutable.value.selectedAnalysis?.takeIf {id->local.analyses.any {it.id==id}}
            mutable.value=mutable.value.copy(local=local,loaded=true,selectedAnalysis=selected)
        }catch(error:CancellationException){throw error}
        catch(_:StaleOwnerException){mutable.value=EnergyViewState(configured=repository.configured)}
        catch(_:EnergyAccessFailure){mutable.value=EnergyViewState(configured=repository.configured,message="Stan konta się zmienił. Otwórz ponownie ten ekran.")}
        catch(_:Exception){mutable.value=mutable.value.copy(local=null,loaded=true,message="Nie udało się odczytać zapisanego podglądu zapotrzebowania.")}
    }
    private fun perform(block:suspend ()->Unit) {
        if(operation?.isActive==true)return
        operation=viewModelScope.launch {
            mutable.value=mutable.value.copy(busy=true,message=null)
            try {block()}
            catch(error:CancellationException){mutable.value=mutable.value.copy(message="Przerwano oczekiwanie. Rozpoczęte operacje zachowano do sprawdzenia.");throw error}
            catch(_:StaleOwnerException){mutable.value=EnergyViewState(configured=repository.configured)}
            catch(_:NetworkAccessDenied){mutable.value=mutable.value.copy(message="Połączenie jest zablokowane. Zapisany podgląd pozostaje dostępny.")}
            catch(error:EnergyAccessFailure){mutable.value=mutable.value.copy(message=energyMessage(error.reason))}
            catch(_:Exception){mutable.value=mutable.value.copy(message="Nie udało się potwierdzić odpowiedzi. Sprawdź zapisane operacje przed kolejną decyzją.")}
            finally {
                if(viewModelScope.isActive)withContext(NonCancellable) {
                    try {reloadLocal()}catch(_:Exception){mutable.value=mutable.value.copy(local=null)}
                }
                mutable.value=mutable.value.copy(busy=false)
            }
        }
    }
}

internal fun energyMessage(reason:String):String=when(reason) {
    "account_required","login_required","http_401","unauthorized"->"Zaloguj się i połącz konto, aby korzystać z korekt."
    "not_configured"->"W tym wariancie aplikacji usługa korekt nie jest skonfigurowana."
    "review_changed","refresh_required"->"Dane się zmieniły. Przejrzyj aktualny stan i ponownie potwierdź decyzję."
    "stale_context","recovery_required","sync_epoch_changed","sync_reconciliation_required"->"Najpierw uzgodnij stan konta na ekranie synchronizacji."
    "retry_after","energy_analysis_cooldown","energy_apply_cooldown","ai_user_quota_exhausted"->"Usługa wymaga przerwy. Sprawdź podany termin i spróbuj później."
    "pending_operation","pending_consent"->"Poprzednia decyzja nadal oczekuje na wynik. Najpierw ją sprawdź."
    "reconciliation_required","idempotency_result_expired","idempotency_key_reused"->"Poprzedni wynik wymaga uzgodnienia. Zachowano jego oryginalną operację."
    "analysis_context_changed","version_conflict","revision_conflict","analysis_not_ready"->"Propozycja nie odpowiada już aktualnym danym. Odśwież stan."
    "proposal_expired"->"Propozycja wygasła. Pobierz aktualny stan przed nową analizą."
    "energy_notice_required","energy_notice_provider_mismatch","energy_consent_required"->"Potrzebne jest nowe świadome potwierdzenie zakresu i dostawcy analizy."
    "ai_unavailable","service_unavailable","http_503"->"Usługa analizy jest obecnie niedostępna."
    "energy_next_day_occupied","scheduled_version_conflict"->"Na jutro jest już zaplanowana wersja. Odśwież historię i wskaż plan do zastąpienia."
    "energy_revert_future_version"->"Możesz przywrócić wersję, która już obowiązywała."
    "cache_full"->"Zapisany podgląd zajmuje zbyt dużo miejsca. Dotychczasowe dane i decyzje są zachowane."
    "pending_limit"->"Najpierw uzgodnij wcześniejsze nierozstrzygnięte operacje."
    else->"Serwer nie przyjął tej decyzji. Odśwież stan i sprawdź jej wynik."
}
