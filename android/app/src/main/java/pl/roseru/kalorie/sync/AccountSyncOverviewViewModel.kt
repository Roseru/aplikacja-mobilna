package pl.roseru.kalorie.sync

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.*
import pl.roseru.kalorie.data.*

data class AccountSyncOverviewState(val loading:Boolean=true,val overview:AccountSyncOverview?=null,val message:String?=null)

class AccountSyncOverviewViewModel(val lease:OwnerLease,private val store:AccountSyncOverviewStore):ViewModel() {
    val state:StateFlow<AccountSyncOverviewState> = store.changes().conflate().map {
        try {AccountSyncOverviewState(loading=false,overview=store.read(lease))}
        catch(error:CancellationException){throw error}
        catch(_:StaleOwnerException){AccountSyncOverviewState(loading=false,message="Wybrany profil się zmienił. Otwórz ponownie synchronizację.")}
        catch(_:Exception){AccountSyncOverviewState(loading=false,message="Nie udało się odczytać lokalnego stanu synchronizacji. Dane pozostają zapisane.")}
    }.catch {error->
        if(error is CancellationException)throw error
        emit(AccountSyncOverviewState(loading=false,message="Odczyt lokalnego stanu został przerwany. Otwórz ponownie ten ekran."))
    }.stateIn(viewModelScope,SharingStarted.WhileSubscribed(5_000,replayExpirationMillis=0),AccountSyncOverviewState())
}
