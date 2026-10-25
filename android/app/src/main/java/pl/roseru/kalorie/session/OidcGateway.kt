package pl.roseru.kalorie.session

import android.content.Context
import android.content.Intent
import android.net.Uri
import kotlinx.coroutines.suspendCancellableCoroutine
import net.openid.appauth.*
import net.openid.appauth.connectivity.ConnectionBuilder
import pl.roseru.kalorie.core.requireHttps
import pl.roseru.kalorie.core.network.*
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

internal interface OidcGateway {
    suspend fun discover(issuer: String): AuthorizationServiceConfiguration
    fun browser(request: AuthorizationRequest): Intent
    suspend fun tokens(request: TokenRequest): TokenResponse
}

internal fun validateDiscovery(config: AuthorizationServiceConfiguration, issuer: String) {
    val expected = requireHttps(issuer)
    require(config.discoveryDoc?.issuer == issuer)
    for (endpoint in listOf(config.authorizationEndpoint, config.tokenEndpoint)) {
        val actual = requireHttps(endpoint.toString())
        require(actual.scheme == expected.scheme && actual.host == expected.host && actual.port == expected.port)
        require(actual.rawPath.startsWith(expected.rawPath.trimEnd('/') + "/"))
    }
}

internal class AppAuthGateway(context: Context,private val connectionBuilder:ConnectionBuilder=ClosedAppAuthConnectionBuilder,
    private val network:NetworkAccessGate=ClosedNetworkAccessGate) : OidcGateway {
    private val service by lazy { AuthorizationService(context,AppAuthConfiguration.Builder().setConnectionBuilder(connectionBuilder).build()) }
    override suspend fun discover(issuer: String): AuthorizationServiceConfiguration {
        val permit=network.captureAllowed()
        return suspendCancellableCoroutine { continuation ->
        requireHttps(issuer)
        AuthorizationServiceConfiguration.fetchFromIssuer(Uri.parse(issuer), { config, error ->
            if (continuation.isActive) {
                try{network.requireCurrent(permit)}catch(error:NetworkAccessDenied){continuation.resumeWithException(error);return@fetchFromIssuer}
                if (config != null && error == null) continuation.resume(config)
                else continuation.resumeWithException(IllegalStateException("OIDC discovery unavailable"))
            }
        }, connectionBuilder)
        }
    }
    override fun browser(request: AuthorizationRequest): Intent {
        val permit=network.captureAllowed()
        return service.getAuthorizationRequestIntent(request).also{network.requireCurrent(permit)}
    }
    override suspend fun tokens(request: TokenRequest): TokenResponse {
        val permit=network.captureAllowed()
        return suspendCancellableCoroutine { continuation ->
        service.performTokenRequest(request) { response, error ->
            if (continuation.isActive) {
                try{network.requireCurrent(permit)}catch(error:NetworkAccessDenied){continuation.resumeWithException(error);return@performTokenRequest}
                if (response != null && error == null) continuation.resume(response)
                else continuation.resumeWithException(error ?: IllegalStateException("OIDC token request rejected"))
            }
        }
        }
    }
}
