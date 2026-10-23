package pl.roseru.kalorie.core.network

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

sealed interface NetworkAccessState {
    data object Unavailable:NetworkAccessState
    data object Blocked:NetworkAccessState
    data class Allowed(val revision:Long):NetworkAccessState {init{require(revision>0)}}
}
enum class NetworkDenial { UNAVAILABLE,BLOCKED,STALE_PERMIT }
// Java networking clients (including AppAuth) report connection failures through IOException.
class NetworkAccessDenied(val reason:NetworkDenial):java.io.IOException("network_access_${reason.name.lowercase()}")

/** A permit belongs to one provider instance and one uninterrupted allowed generation. */
class NetworkPermit internal constructor(internal val issuer:Any,internal val generation:Long,val revision:Long) {
    override fun toString()="NetworkPermit(redacted)"
}
interface NetworkAccessGate {
    val state:StateFlow<NetworkAccessState>
    fun captureAllowed():NetworkPermit
    fun requireCurrent(permit:NetworkPermit)
}

/** The local generation also revokes permits across an I/O failure, even if a revision is re-read. */
abstract class ObservableNetworkAccessGate:NetworkAccessGate {
    private val monitor=Any()
    private val issuer=Any()
    private var generation=0L
    private val mutable=MutableStateFlow<NetworkAccessState>(NetworkAccessState.Unavailable)
    final override val state:StateFlow<NetworkAccessState> = mutable.asStateFlow()
    protected fun publish(value:NetworkAccessState)=synchronized(monitor) {
        if(mutable.value!=value) {
            generation=Math.addExact(generation,1)
            mutable.value=value
        }
    }
    final override fun captureAllowed():NetworkPermit=synchronized(monitor) {
        when(val value=mutable.value) {
            NetworkAccessState.Unavailable->throw NetworkAccessDenied(NetworkDenial.UNAVAILABLE)
            NetworkAccessState.Blocked->throw NetworkAccessDenied(NetworkDenial.BLOCKED)
            is NetworkAccessState.Allowed->NetworkPermit(issuer,generation,value.revision)
        }
    }
    final override fun requireCurrent(permit:NetworkPermit):Unit=synchronized(monitor) {
        val value=mutable.value
        if(permit.issuer!==issuer || permit.generation!=generation || value !is NetworkAccessState.Allowed || value.revision!=permit.revision)
            throw NetworkAccessDenied(NetworkDenial.STALE_PERMIT)
    }
}
object ClosedNetworkAccessGate:ObservableNetworkAccessGate()
