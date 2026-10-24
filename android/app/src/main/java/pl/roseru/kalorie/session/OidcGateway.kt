package pl.roseru.kalorie.session

import android.content.Context
import android.content.Intent
import android.net.Uri
import kotlinx.coroutines.suspendCancellableCoroutine
import net.openid.appauth.*
import net.openid.appauth.connectivity.DefaultConnectionBuilder
import pl.roseru.kalorie.core.requireHttps
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

internal class AppAuthGateway(context: Context) : OidcGateway {
    private val service by lazy { AuthorizationService(context) }
    override suspend fun discover(issuer: String): AuthorizationServiceConfiguration = suspendCancellableCoroutine { continuation ->
        requireHttps(issuer)
        AuthorizationServiceConfiguration.fetchFromIssuer(Uri.parse(issuer), { config, error ->
            if (continuation.isActive) {
                if (config != null && error == null) continuation.resume(config)
                else continuation.resumeWithException(IllegalStateException("OIDC discovery unavailable"))
            }
        }, DefaultConnectionBuilder.INSTANCE)
    }
    override fun browser(request: AuthorizationRequest): Intent = service.getAuthorizationRequestIntent(request)
    override suspend fun tokens(request: TokenRequest): TokenResponse = suspendCancellableCoroutine { continuation ->
        service.performTokenRequest(request) { response, error ->
            if (continuation.isActive) {
                if (response != null && error == null) continuation.resume(response)
                else continuation.resumeWithException(error ?: IllegalStateException("OIDC token request rejected"))
            }
        }
    }
}
