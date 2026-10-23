package pl.roseru.kalorie.catalogupdate

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import pl.roseru.kalorie.core.catalog.CatalogManifest
import pl.roseru.kalorie.core.network.*
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference

enum class CatalogUpdatePhase { IDLE,CHECKING,AVAILABLE,DOWNLOADING,VERIFYING,INSTALLED,CURRENT,NOT_PUBLISHED,
    NOT_CONFIGURED,RETRY_LATER,BLOCKED,CANCELLED,FAILED }
data class CatalogUpdateState(val installed:List<InstalledCatalog> = emptyList(),val localReadFailed:Boolean=false,
    val configured:Boolean=false,val networkAllowed:Boolean=false,val networkUnavailable:Boolean=true,val phase:CatalogUpdatePhase=CatalogUpdatePhase.IDLE,
    val available:CatalogManifest?=null,val received:Long=0,val expected:Long=0,val retryAt:Long=0,
    val checkedAt:Long?=null,val serverOlder:Boolean=false) {
    val busy:Boolean get()=phase in setOf(CatalogUpdatePhase.CHECKING,CatalogUpdatePhase.DOWNLOADING,CatalogUpdatePhase.VERIFYING)
}

class CatalogUpdateViewModel(private val repository:CatalogUpdateRepository,
    private val now:()->Long=System::currentTimeMillis):ViewModel() {
    private val mutable=MutableStateFlow(CatalogUpdateState(configured=repository.configured,
        networkAllowed=repository.networkState.value is NetworkAccessState.Allowed,networkUnavailable=repository.networkState.value==NetworkAccessState.Unavailable))
    val state:StateFlow<CatalogUpdateState> = mutable.asStateFlow()
    private val token=AtomicReference<String?>(null)
    private var operation:Job?=null
    private var operationPolicy:NetworkAccessState?=null
    private val sourceView=MutableStateFlow<CatalogSourcesState>(CatalogSourcesState.Closed)
    val sources:StateFlow<CatalogSourcesState> = sourceView.asStateFlow()
    private var sourceJob:Job?=null
    private val sourceToken=AtomicReference<String?>(null)
    private var localReadJob:Job?=null
    init {
        retryLocalRead()
        viewModelScope.launch {
            repository.networkState.collect {policy->
                val allowed=policy is NetworkAccessState.Allowed
                if(mutable.value.busy && policy!=operationPolicy)stop(if(allowed)CatalogUpdatePhase.CANCELLED else CatalogUpdatePhase.BLOCKED)
                mutable.update { old->old.copy(networkAllowed=allowed,networkUnavailable=policy==NetworkAccessState.Unavailable,phase=if(allowed && old.phase==CatalogUpdatePhase.BLOCKED)
                    if(old.available!=null)CatalogUpdatePhase.AVAILABLE else CatalogUpdatePhase.IDLE else old.phase) }
            }
        }
    }
    fun retryLocalRead() {
        localReadJob?.cancel()
        localReadJob=viewModelScope.launch {
            repository.installed.catch {error->
                if(error is CancellationException)throw error
                mutable.update{it.copy(installed=emptyList(),localReadFailed=true)}
            }.collect {rows->mutable.update{it.copy(installed=rows,localReadFailed=false)}}
        }
    }
    fun check()=begin(CatalogUpdatePhase.CHECKING) { id->
        change(id){it.copy(available=null,received=0,expected=0,serverOlder=false)}
        when(val result=repository.check()) {
            is CatalogCheck.Available->change(id){it.copy(phase=CatalogUpdatePhase.AVAILABLE,available=result.manifest,checkedAt=now(),retryAt=0)}
            is CatalogCheck.Current->change(id){it.copy(phase=CatalogUpdatePhase.CURRENT,checkedAt=now(),retryAt=0,serverOlder=result.serverRelease<result.local.release)}
            CatalogCheck.NotPublished->change(id){it.copy(phase=CatalogUpdatePhase.NOT_PUBLISHED,checkedAt=now())}
            CatalogCheck.NotConfigured->change(id){it.copy(phase=CatalogUpdatePhase.NOT_CONFIGURED)}
            is CatalogCheck.RetryAt->change(id){it.copy(phase=CatalogUpdatePhase.RETRY_LATER,retryAt=result.epochMillis)}
        }
    }
    fun download() {
        val selected=mutable.value.available?:return
        begin(CatalogUpdatePhase.DOWNLOADING) { id->
            change(id){it.copy(received=0,expected=selected.compressedBytes.toLong())}
            when(val result=repository.download(selected,
                progress={read,total->change(id){it.copy(received=read,expected=total)}},
                validating={change(id){it.copy(phase=CatalogUpdatePhase.VERIFYING)}})) {
                is CatalogDownloadResult.Installed->change(id){it.copy(phase=CatalogUpdatePhase.INSTALLED,available=null,received=0,expected=0,retryAt=0)}
                CatalogDownloadResult.Missing->change(id){it.copy(phase=CatalogUpdatePhase.NOT_PUBLISHED,available=null)}
                CatalogDownloadResult.NotConfigured->change(id){it.copy(phase=CatalogUpdatePhase.NOT_CONFIGURED)}
                is CatalogDownloadResult.RetryAt->change(id){it.copy(phase=CatalogUpdatePhase.RETRY_LATER,retryAt=result.epochMillis)}
            }
        }
    }
    fun cancel(){if(mutable.value.busy)stop(CatalogUpdatePhase.CANCELLED)}
    fun showSources(manifest:CatalogManifest,page:Int=0) {
        sourceJob?.cancel()
        val id=UUID.randomUUID().toString();sourceToken.set(id)
        sourceView.value=CatalogSourcesState.Loading(manifest,page)
        sourceJob=viewModelScope.launch {
            try {
                val result=repository.sources(manifest,page)
                if(sourceToken.get()==id)sourceView.value=CatalogSourcesState.Ready(result)
            }catch(error:CancellationException){throw error}
            catch(_:Exception){if(sourceToken.get()==id)sourceView.value=CatalogSourcesState.Failed(manifest,page)}
        }
    }
    fun closeSources(){sourceToken.set(null);sourceJob?.cancel();sourceJob=null;sourceView.value=CatalogSourcesState.Closed}
    private fun stop(phase:CatalogUpdatePhase) {
        token.set(null)
        operation?.cancel();operation=null
        operationPolicy=null
        mutable.update{it.copy(phase=phase,received=0,expected=0)}
    }
    private fun change(id:String,action:(CatalogUpdateState)->CatalogUpdateState) {
        mutable.update{if(token.get()==id)action(it) else it}
    }
    private fun begin(phase:CatalogUpdatePhase,action:suspend(String)->Unit) {
        val current=mutable.value
        if(current.busy)return
        if(!current.configured){mutable.update{it.copy(phase=CatalogUpdatePhase.NOT_CONFIGURED)};return}
        val policy=repository.networkState.value
        if(policy !is NetworkAccessState.Allowed){mutable.update{it.copy(phase=CatalogUpdatePhase.BLOCKED)};return}
        if(current.retryAt>now()){mutable.update{it.copy(phase=CatalogUpdatePhase.RETRY_LATER)};return}
        val id=UUID.randomUUID().toString();token.set(id)
        operationPolicy=policy
        mutable.update{it.copy(phase=phase)}
        val job=viewModelScope.launch(start=CoroutineStart.LAZY) {
            try {action(id)}
            catch(error:CancellationException){throw error}
            catch(_:NetworkAccessDenied){change(id){it.copy(phase=if(repository.networkState.value is NetworkAccessState.Allowed)CatalogUpdatePhase.CANCELLED else CatalogUpdatePhase.BLOCKED)}}
            catch(_:Exception){change(id){it.copy(phase=if(repository.networkState.value is NetworkAccessState.Allowed)CatalogUpdatePhase.FAILED else CatalogUpdatePhase.BLOCKED)}}
            finally {
                if(token.compareAndSet(id,null)) {
                    operation=null
                    operationPolicy=null
                    mutable.update {if(it.busy)it.copy(phase=CatalogUpdatePhase.FAILED) else it}
                }
            }
        }
        operation=job;job.start()
    }
    override fun onCleared(){token.set(null);sourceToken.set(null);operation?.cancel();sourceJob?.cancel();super.onCleared()}
}
