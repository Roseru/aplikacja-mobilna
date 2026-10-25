package pl.roseru.kalorie.core.network

import kotlinx.coroutines.DisposableHandle
import kotlinx.coroutines.InternalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.ThreadContextElement
import kotlin.coroutines.AbstractCoroutineContextElement
import kotlin.coroutines.CoroutineContext

/** Request-local lifecycle only. The operation Job is stable across nested I/O contexts. */
internal class NetworkOperationCancellation(private val operation:Job):ThreadContextElement<Job?>,
    AbstractCoroutineContextElement(Key) {
    companion object Key:CoroutineContext.Key<NetworkOperationCancellation> {
        private val current=ThreadLocal<Job?>()
        /** onCancelling is essential: waiting for completion deadlocks on a blocked I/O child. */
        @OptIn(InternalCoroutinesApi::class)
        internal fun subscribeOnCancelling(close:()->Unit):DisposableHandle?=
            current.get()?.invokeOnCompletion(onCancelling=true,invokeImmediately=true) {cause->
                if(cause!=null)try{close()}catch(_:Exception){/* Best-effort close must not break Job cancellation. */}
            }
    }
    override fun updateThreadContext(context:CoroutineContext):Job?=current.get().also {current.set(operation)}
    override fun restoreThreadContext(context:CoroutineContext,oldState:Job?) {current.set(oldState)}
}
