package pl.roseru.kalorie.sync

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import pl.roseru.kalorie.data.*

data class SnapshotMaintenanceState(val busy:Boolean=false,val review:SnapshotRestartReview?=null,val message:String?=null)

/** Scoped to one selected local owner/lease, never the device-wide network model. */
class SnapshotMaintenanceViewModel(private val store:SnapshotMaintenanceStore,private val lease:OwnerLease):ViewModel() {
    private val mutable=MutableStateFlow(SnapshotMaintenanceState())
    val state=mutable.asStateFlow()
    private var operation:Job?=null

    fun prepare()=perform {
        val review=store.review(lease)
        mutable.value=mutable.value.copy(review=review?.takeIf {it.count>0},message=when {
            review==null->"Najpierw połącz ten profil z kontem na ekranie konta."
            review.count==0->"Nie ma wcześniejszych pobierań, które można bezpiecznie przerwać."
            else->null
        })
    }
    fun dismiss() {if(!mutable.value.busy)mutable.value=mutable.value.copy(review=null)}
    fun confirm(review:SnapshotRestartReview) {
        if(mutable.value.review!==review)return
        perform {
            store.confirm(review)
            mutable.value=mutable.value.copy(review=null,message="Poprzednie pobierania zostały przerwane. Na ekranie konta możesz teraz ponowić synchronizację.")
        }
    }
    private fun perform(block:suspend ()->Unit) {
        if(operation?.isActive==true)return
        operation=viewModelScope.launch {
            mutable.value=mutable.value.copy(busy=true,message=null)
            try {block()}
            catch(error:CancellationException){throw error}
            catch(_:StaleOwnerException){mutable.value=SnapshotMaintenanceState(message="Wybrany profil się zmienił. Otwórz ponownie ustawienia.")}
            catch(_:SnapshotMaintenanceChangedException){mutable.value=SnapshotMaintenanceState(message="Stan pobierania się zmienił. Sprawdź ponownie przed podjęciem decyzji.")}
            catch(_:Exception){mutable.value=SnapshotMaintenanceState(message="Nie udało się sprawdzić wcześniejszych pobierań. Spróbuj ponownie.")}
            finally {mutable.value=mutable.value.copy(busy=false)}
        }
    }
}
