package pl.roseru.kalorie.core.network

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

data class NetworkPolicyViewState(val access:NetworkAccessState=NetworkAccessState.Unavailable,
    val saving:Boolean=false,val requestedBlocked:Boolean?=null,val saveFailed:Boolean=false,
    val lastKnownBlocked:Boolean?=null) {
    val checked:Boolean get()=requestedBlocked?:lastKnownBlocked?:false
}
class NetworkPolicyViewModel(private val policy:DeviceNetworkPolicy):ViewModel() {
    private val mutable=MutableStateFlow(NetworkPolicyViewState(access=policy.state.value,
        lastKnownBlocked=when(policy.state.value){is NetworkAccessState.Allowed->false;NetworkAccessState.Blocked->true;else->null}))
    val state:StateFlow<NetworkPolicyViewState> = mutable.asStateFlow()
    init {
        viewModelScope.launch {
            policy.state.collect {access->mutable.update {
                it.copy(access=access,lastKnownBlocked=when(access) {
                    is NetworkAccessState.Allowed->false
                    NetworkAccessState.Blocked->true
                    NetworkAccessState.Unavailable->it.lastKnownBlocked
                })
            }}
        }
    }
    fun setBlocked(blocked:Boolean) {
        if(mutable.value.saving)return
        mutable.update{it.copy(saving=true,requestedBlocked=blocked,saveFailed=false)}
        viewModelScope.launch {
            try {policy.setBlocked(blocked)}
            catch(error:CancellationException){throw error}
            catch(_:Exception){mutable.update{it.copy(saveFailed=true)}}
            finally {mutable.update{it.copy(saving=false,requestedBlocked=null)}}
        }
    }
}
