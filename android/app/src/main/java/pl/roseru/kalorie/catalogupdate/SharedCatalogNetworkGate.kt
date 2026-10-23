package pl.roseru.kalorie.catalogupdate

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.*

/** Maps the shared sync policy, without owning or writing any policy preference. */
class SharedCatalogNetworkGate(scope:CoroutineScope,permission:Flow<Boolean>):CatalogNetworkGate {
    override val allowed:StateFlow<Boolean> = permission.distinctUntilChanged().catch {error->
        if(error is CancellationException)throw error
        emit(false)
    }.stateIn(scope,SharingStarted.Eagerly,false)
}
