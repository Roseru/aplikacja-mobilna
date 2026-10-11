package pl.roseru.kalorie.core

import org.json.JSONArray
import pl.roseru.kalorie.core.catalog.StrictJson
import java.net.URI
import java.net.URLDecoder
import java.util.Base64

/** Exact issuer: never rewrite a host for an emulator, or normalize a trailing slash. */
data class SessionIdentity(val issuer: String, val subject: String) {
    init {
        requireHttps(issuer)
        require(subject.isNotBlank() && subject == subject.trim() && subject.length <= 255 && subject.none { it.isISOControl() })
    }
}

fun requireHttps(value: String): URI = URI(value).also {
    require(it.scheme == "https" && it.host != null && it.userInfo == null && it.rawQuery == null && it.rawFragment == null)
    require(it.port == -1 || it.port in 1..65535)
}

fun validateAuthCallback(value: String, applicationId: String, issuer: String) {
    require(value.length in 1..16_384 && issuer.isNotEmpty())
    requireHttps(issuer)
    val uri = URI(value)
    require(!uri.isOpaque && uri.scheme == applicationId && uri.rawAuthority == null && uri.rawFragment == null)
    require(uri.rawPath == "/oauth2redirect" && value.substringBefore('?') == AuthReturn.redirect(applicationId))
    val params = linkedMapOf<String, String>()
    for (item in checkNotNull(uri.rawQuery).split('&')) {
        require(item.contains('='))
        val key = URLDecoder.decode(item.substringBefore('='), "UTF-8")
        val content = URLDecoder.decode(item.substringAfter('='), "UTF-8")
        require(key !in params)
        params[key] = content
    }
    require(!params["state"].isNullOrEmpty())
    require(params.containsKey("code") xor params.containsKey("error"))
    require(!(params["code"] ?: params["error"]).isNullOrEmpty())
    params["iss"]?.let { require(it == issuer) }
}

/** Additional strict claims checks, ONLY for an ID token returned by the TLS token endpoint.
 * AppAuth validates code-flow ID tokens first. Parsing a caller-supplied JWT is not authentication.
 * Code flow permits TLS endpoint authentication in place of a local signature check (OIDC 3.1.3.7).
 */
object SessionClaims {
    const val CLIENT_ID = "calorie-android"
    fun identity(idToken: String, issuer: String, nonce: String?, nowSeconds: Long, previous: SessionIdentity? = null): SessionIdentity {
        require(idToken.length in 1..65_536)
        val sections = idToken.split('.')
        require(sections.size == 3 && sections.all { it.isNotEmpty() && it.matches(Regex("[A-Za-z0-9_-]+")) })
        val header = StrictJson.read(Base64.getUrlDecoder().decode(sections[0]))
        require(header.getString("alg") == "RS256")
        val claims = StrictJson.read(Base64.getUrlDecoder().decode(sections[1]))
        val result = SessionIdentity(claims.get("iss") as String, claims.get("sub") as String)
        require(result.issuer == issuer && (previous == null || previous == result))
        val rawAudience = claims.get("aud")
        val audiences = when (rawAudience) {
            is String -> listOf(rawAudience)
            is JSONArray -> (0 until rawAudience.length()).map { rawAudience.get(it) as String }
            else -> throw IllegalArgumentException("Invalid audience")
        }
        require(CLIENT_ID in audiences)
        val azp = if (claims.has("azp")) claims.get("azp") as String else null
        require((azp == null || azp == CLIENT_ID) && (audiences.size == 1 || azp == CLIENT_ID))
        fun integer(key: String): Long = (claims.get(key) as Number).toString().toBigDecimal().longValueExact()
        require(integer("exp") > nowSeconds)
        val issued = integer("iat")
        require(issued >= nowSeconds - 600 && issued <= nowSeconds + 600)
        if (nonce != null) require(claims.get("nonce") == nonce)
        return result
    }
}
