package pl.roseru.kalorie.core.network

import android.content.Context
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import androidx.datastore.core.DataStore
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

private val Context.networkPolicyStore by preferencesDataStore("device-network-policy")

/** One application-scoped policy for guest/account, catalog, session and background synchronization. */
class DeviceNetworkPolicy internal constructor(private val storage:DataStore<Preferences>,private val scope:CoroutineScope):ObservableNetworkAccessGate() {
    constructor(context:Context,scope:CoroutineScope):this(context.applicationContext.networkPolicyStore,scope)
    private val formatKey=intPreferencesKey("format")
    private val blockedKey=booleanPreferencesKey("blocked")
    private val revisionKey=longPreferencesKey("revision")
    private val mutex=Mutex()
    private var lastRevision=0L
    private var faulted=false
    private var observer:Job?=null
    private data class Snapshot(val blocked:Boolean,val revision:Long)
    init{observe()}
    private fun read(values:Preferences):Snapshot {
        if(values[formatKey]==null && values[blockedKey]==null && values[revisionKey]==null)return Snapshot(false,1)
        check(values[formatKey]==1)
        return Snapshot(checkNotNull(values[blockedKey]),checkNotNull(values[revisionKey]).also{check(it>0)})
    }
    private fun accept(value:Snapshot) {
        if(value.revision<lastRevision)return
        lastRevision=value.revision
        publish(if(value.blocked)NetworkAccessState.Blocked else NetworkAccessState.Allowed(value.revision))
    }
    private fun observe() {
        observer?.cancel()
        observer=scope.launch(Dispatchers.IO) {
            storage.data.catch {error->
                if(error is CancellationException)throw error
                mutex.withLock {faulted=true;publish(NetworkAccessState.Unavailable)}
            }.collect {values->
                mutex.withLock {
                    if(!faulted) {
                        try{accept(read(values))}
                        catch(_:Exception){faulted=true;publish(NetworkAccessState.Unavailable)}
                    }
                }
            }
        }
    }
    suspend fun setBlocked(blocked:Boolean)=mutex.withLock {
        if(!faulted && (state.value==NetworkAccessState.Blocked && blocked || state.value is NetworkAccessState.Allowed && !blocked))return@withLock
        // Invalidate existing permits before disk I/O; a failed save never reopens the gate.
        publish(NetworkAccessState.Unavailable)
        try {
            val saved=storage.edit {values->
                val current=read(values)
                val revision=Math.addExact(maxOf(current.revision,lastRevision),1)
                values[formatKey]=1;values[blockedKey]=blocked;values[revisionKey]=revision
            }
            val value=read(saved)
            faulted=false;accept(value)
            observe()
        }catch(error:CancellationException){faulted=true;publish(NetworkAccessState.Unavailable);throw error}
        catch(error:Exception){faulted=true;publish(NetworkAccessState.Unavailable);throw error}
    }
}
