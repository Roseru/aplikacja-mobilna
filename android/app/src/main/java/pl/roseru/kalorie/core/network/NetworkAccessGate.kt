package pl.roseru.kalorie.core.network

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.UUID

sealed interface NetworkAccessState {
    data object Unavailable:NetworkAccessState
    data object Blocked:NetworkAccessState
    data class Allowed(val revision:Long):NetworkAccessState {init{require(revision>0)}}
}

enum class NetworkDenial { UNAVAILABLE,BLOCKED,STALE_PERMIT }
class NetworkAccessDenied(val reason:NetworkDenial):java.io.IOException("network_access_${reason.name.lowercase()}")

/** Public identity fence, not a credential. A new provider/process cannot reuse an old issuance. */
data class NetworkIssuance(val instanceId:String,val generation:Long) {
    init {require(UUID.fromString(instanceId).toString()==instanceId && generation>=0)}
    override fun toString()="NetworkIssuance(redacted)"
}
/** Unlike state alone, this frame differs after even a fully conflated same-revision ABA. */
data class NetworkAccessSnapshot(val state:NetworkAccessState,val issuance:NetworkIssuance)

/** A permit belongs to one provider instance and one uninterrupted allowed generation. */
class NetworkPermit internal constructor(internal val issuer:Any,val issuance:NetworkIssuance,val revision:Long) {
    override fun toString()="NetworkPermit(redacted)"
}
interface NetworkAccessGate {
    val state:StateFlow<NetworkAccessState>
    val changes:StateFlow<NetworkAccessSnapshot>
    fun captureAllowed():NetworkPermit
    fun requireCurrent(permit:NetworkPermit)
}

abstract class ObservableNetworkAccessGate:NetworkAccessGate {
    private val monitor=Any()
    private val issuer=Any()
    private val instanceId=UUID.randomUUID().toString()
    private var generation=0L
    private val mutable=MutableStateFlow<NetworkAccessState>(NetworkAccessState.Unavailable)
    private val frames=MutableStateFlow(NetworkAccessSnapshot(mutable.value,NetworkIssuance(instanceId,generation)))
    final override val state:StateFlow<NetworkAccessState> = mutable.asStateFlow()
    final override val changes:StateFlow<NetworkAccessSnapshot> = frames.asStateFlow()
    protected fun publish(value:NetworkAccessState)=synchronized(monitor) {
        if(mutable.value!=value) {
            generation=Math.addExact(generation,1)
            mutable.value=value
            frames.value=NetworkAccessSnapshot(value,NetworkIssuance(instanceId,generation))
        }
    }
    final override fun captureAllowed():NetworkPermit=synchronized(monitor) {
        when(val value=mutable.value) {
            NetworkAccessState.Unavailable->throw NetworkAccessDenied(NetworkDenial.UNAVAILABLE)
            NetworkAccessState.Blocked->throw NetworkAccessDenied(NetworkDenial.BLOCKED)
            is NetworkAccessState.Allowed->NetworkPermit(issuer,frames.value.issuance,value.revision)
        }
    }
    final override fun requireCurrent(permit:NetworkPermit):Unit=synchronized(monitor) {
        val value=mutable.value
        if(permit.issuer!==issuer || permit.issuance!=frames.value.issuance || value !is NetworkAccessState.Allowed || value.revision!=permit.revision)
            throw NetworkAccessDenied(NetworkDenial.STALE_PERMIT)
    }
}
object ClosedNetworkAccessGate:ObservableNetworkAccessGate()
