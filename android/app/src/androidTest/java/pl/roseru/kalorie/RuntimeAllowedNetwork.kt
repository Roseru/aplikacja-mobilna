package pl.roseru.kalorie

import pl.roseru.kalorie.core.network.NetworkAccessState
import pl.roseru.kalorie.core.network.ObservableNetworkAccessGate

/** The old C tests exercise healthy networking; production defaults remain closed. */
internal object RuntimeAllowedNetwork:ObservableNetworkAccessGate() {
    init {publish(NetworkAccessState.Allowed(1))}
}
