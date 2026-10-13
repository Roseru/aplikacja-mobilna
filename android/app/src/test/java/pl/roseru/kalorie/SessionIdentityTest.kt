package pl.roseru.kalorie

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import java.util.Base64

class SessionIdentityTest {
    private val issuer = "https://identity.example/realms/calorie-dev"
    private val now = 1_800_000_000L
    private fun claims() = JSONObject().put("iss", issuer).put("sub", "A").put("aud", "calorie-android")
        .put("iat", now).put("exp", now + 300).put("nonce", "expected-nonce")
    private fun encode(value: String) = Base64.getUrlEncoder().withoutPadding().encodeToString(value.toByteArray())
    private fun token(body: String, alg: String = "RS256") = "${encode("{\"alg\":\"$alg\"}")}.${encode(body)}.fixture"
    private fun accepts(value: JSONObject) = SessionClaims.identity(token(value.toString()), issuer, "expected-nonce", now)
    private fun rejects(value: JSONObject) = assertThrows(Exception::class.java) { accepts(value) }

    @Test fun exactIssuerSubjectAndStrictAudience() {
        assertEquals(SessionIdentity(issuer, "A"), accepts(claims()))
        accepts(claims().put("aud", JSONArray(listOf("calorie-android", "extra"))).put("azp", "calorie-android"))
        rejects(claims().put("iss", "$issuer/"))
        rejects(claims().put("aud", "other").put("azp", "calorie-android"))
        rejects(claims().put("aud", JSONArray(listOf("calorie-android", "extra"))))
        rejects(claims().put("azp", "other"))
        for (subject in listOf("", " padded", "a\nb", "x".repeat(256))) rejects(claims().put("sub", subject))
    }
    @Test fun nonceExpiryAndIssuedAtBoundaries() {
        rejects(claims().put("nonce", "other"))
        rejects(claims().put("exp", now))
        rejects(claims().put("iat", now + 601))
        rejects(claims().put("iat", now - 601))
        rejects(claims().put("exp", "$now"))
        rejects(claims().put("exp", now + 0.5))
        accepts(claims().put("iat", now - 600))
    }
    @Test fun refreshCannotChangeConfirmedIdentity() {
        val previous = SessionIdentity(issuer, "A")
        assertEquals(previous, SessionClaims.identity(token(claims().toString()), issuer, null, now, previous))
        assertThrows(IllegalArgumentException::class.java) {
            SessionClaims.identity(token(claims().put("sub", "B").toString()), issuer, null, now, previous)
        }
    }
    @Test fun ambiguousOrUnsignedTokenRejected() {
        assertThrows(IllegalArgumentException::class.java) { SessionClaims.identity(token(claims().toString(), "none"), issuer, "expected-nonce", now) }
        val body = claims().toString().dropLast(1) + ",\"sub\":\"B\"}"
        assertThrows(IllegalArgumentException::class.java) { SessionClaims.identity(token(body), issuer, "expected-nonce", now) }
        for (bad in listOf("", "header.body", "a.b.c.d", "a.b.", "a.b=.c")) {
            assertThrows(Exception::class.java) { SessionClaims.identity(bad, issuer, "expected-nonce", now) }
        }
    }
    @Test fun httpsConfigurationRejectsAmbiguousOrInsecureUris() {
        requireHttps(issuer)
        for (bad in listOf("http://localhost", "http://identity.example", "https://user:pass@identity.example",
            "https://identity.example?x=1", "https://identity.example#x", "https://identity.example:0", "not-a-url")) {
            assertThrows(Exception::class.java) { requireHttps(bad) }
        }
    }
    @Test fun callbackIsExactAndRejectsDuplicateOrMixedParameters() {
        val callback = AuthReturn.redirect("pl.roseru.kalorie")
        validateAuthCallback("$callback?code=fixture&state=fixture", "pl.roseru.kalorie", issuer)
        validateAuthCallback("$callback?error=access_denied&state=fixture", "pl.roseru.kalorie", issuer)
        for (bad in listOf("pl.roseru.kalorie:/other?code=x&state=x", "pl.roseru.kalorie://host/oauth2redirect?code=x&state=x",
            "$callback?code=x&state=x#fragment", "$callback?code=x&code=y&state=x", "$callback?code=x&%73tate=x&state=x",
            "$callback?code=x&error=x&state=x", "$callback?code=x", "$callback?code=x&state=x&iss=https%3A%2F%2Fother.example",
            "pl.roseru.kalorie.validation:/oauth2redirect?code=x&state=x")) {
            assertThrows(Exception::class.java) { validateAuthCallback(bad, "pl.roseru.kalorie", issuer) }
        }
    }
}
