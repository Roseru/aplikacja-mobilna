package pl.roseru.kalorie

import android.content.Context
import android.content.Intent
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import net.openid.appauth.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import java.io.File
import java.security.KeyStore
import java.security.MessageDigest
import java.time.LocalDate
import java.util.Base64
import java.util.UUID

/** Deterministic transport fixtures, NOT an end-to-end Keycloak/TLS/signature acceptance test. */
@RunWith(AndroidJUnit4::class)
class SessionSecurityTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val issuer = "https://identity.example/realms/calorie-dev"
    private fun memory() = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
    private fun name() = "session-test-${UUID.randomUUID()}"
    private fun encode(text: String) = Base64.getUrlEncoder().withoutPadding().encodeToString(text.toByteArray())
    private inner class FixtureGateway : OidcGateway {
        var time = System.currentTimeMillis()
        var subject = "fixture-A"
        var request: AuthorizationRequest? = null
        var calls = 0
        var hold: CompletableDeferred<Unit>? = null
        var codeHold: CompletableDeferred<Unit>? = null
        val codeStarted = CompletableDeferred<Unit>()
        val refreshStarted = CompletableDeferred<Unit>()
        val config = AuthorizationServiceConfiguration(AuthorizationServiceDiscovery(JSONObject()
            .put("issuer", issuer).put("authorization_endpoint", "$issuer/protocol/openid-connect/auth")
            .put("token_endpoint", "$issuer/protocol/openid-connect/token").put("jwks_uri", "$issuer/protocol/openid-connect/certs")
            .put("response_types_supported", JSONArray(listOf("code"))).put("subject_types_supported", JSONArray(listOf("public")))
            .put("id_token_signing_alg_values_supported", JSONArray(listOf("RS256")))))
        override suspend fun discover(issuer: String) = config
        override fun browser(request: AuthorizationRequest): Intent {
            this.request = request
            return Intent("fixture.browser")
        }
        override suspend fun tokens(request: TokenRequest): TokenResponse {
            calls++
            val captured = subject
            if (request.grantType == GrantTypeValues.AUTHORIZATION_CODE) {
                codeStarted.complete(Unit)
                codeHold?.await()
            }
            if (request.grantType == GrantTypeValues.REFRESH_TOKEN) {
                refreshStarted.complete(Unit)
                hold?.await()
            }
            val claims = JSONObject().put("iss", issuer).put("sub", captured).put("aud", SessionClaims.CLIENT_ID)
                .put("iat", time / 1000).put("exp", time / 1000 + 300)
            request.nonce?.let { claims.put("nonce", it) }
            val token = "${encode("{\"alg\":\"RS256\"}")}.${encode(claims.toString())}.fixture"
            return TokenResponse.Builder(request).setTokenType("Bearer").setAccessToken("fixture-access-$captured-$calls")
                .setRefreshToken("fixture-refresh-$captured-$calls").setAccessTokenExpirationTime(time + 300_000).setIdToken(token).build()
        }
        fun response(state: String? = request!!.state) = AuthorizationResponse.Builder(request!!)
            .setState(state).setAuthorizationCode("fixture-code").build().toIntent()
    }
    private fun client(db: CalorieDatabase, vault: SessionVault, fixture: FixtureGateway) = SessionController(
        db, vault, fixture, issuer, context.packageName) { fixture.time }
    private suspend fun login(client: SessionController, fixture: FixtureGateway, subject: String) {
        fixture.subject = subject
        assertNotNull(client.beginLogin())
        client.completeLogin(fixture.response())
        assertEquals(subject, client.view.value.binding!!.owner.subject)
    }

    @Test fun pendingPkceSurvivesRestartAndCallbacksAreSingleUse() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        try {
            val first = client(db, vault, fixture); first.start()
            val guestLease = first.view.value.binding!!.lease
            val guest = DiaryRepository(db, context, guestLease).apply { initialize() }
            guest.add("basic-banana", 100.0, MealType.LUNCH, LocalDate.now(), "fixture-guest-meal")
            assertNotNull(first.beginLogin())
            val request = fixture.request!!
            assertEquals("S256", request.codeVerifierChallengeMethod)
            val expected = Base64.getUrlEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256").digest(request.codeVerifier!!.toByteArray(Charsets.US_ASCII)))
            assertEquals(expected, request.codeVerifierChallenge)
            assertEquals(AuthReturn.redirect(context.packageName), request.redirectUri.toString())
            val restarted = client(db, vault, fixture); restarted.start()
            assertTrue(restarted.view.value.pendingLogin)
            restarted.completeLogin(fixture.response("wrong-state"))
            assertEquals(0, fixture.calls)
            assertTrue(restarted.view.value.pendingLogin)
            assertEquals(guestLease, restarted.view.value.binding!!.lease)
            val wrongRequest = AuthorizationRequest.Builder(fixture.config, SessionClaims.CLIENT_ID, ResponseTypeValues.CODE,
                request.redirectUri).setScope("openid profile").setState(request.state).build()
            restarted.completeLogin(AuthorizationResponse.Builder(wrongRequest).setState(request.state).setAuthorizationCode("fixture-code").build().toIntent())
            assertEquals(0, fixture.calls)
            restarted.completeLogin(fixture.response())
            val account = restarted.view.value.binding!!
            assertEquals("fixture-A", account.owner.subject)
            assertTrue(restarted.view.value.hasSession)
            assertTrue(db.dao().day(account.owner.storageScope, LocalDate.now().toString()).first().isEmpty())
            assertEquals("fixture-guest-meal", db.dao().day("guest", LocalDate.now().toString()).first().single().meal.id)
            assertNull(db.dao().goal(account.owner.storageScope, LocalDate.now().toString()).first())
            restarted.completeLogin(fixture.response())
            assertEquals(1, fixture.calls)
            assertEquals(account.lease, restarted.view.value.binding!!.lease)
            assertThrows(StaleOwnerException::class.java) { runBlocking { guest.add("basic-banana", 50.0, MealType.LUNCH, LocalDate.now(), "stale-guest") } }
        } finally { vault.clear(); db.close() }
    }

    @Test fun expiryRefreshLogoutAndRestartKeepOfflineDiary() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        try {
            val controller = client(db, vault, fixture); controller.start(); login(controller, fixture, "fixture-A")
            val a = controller.view.value.binding!!
            val repo = DiaryRepository(db, context, a.lease).apply { initialize() }
            repo.add("basic-banana", 120.0, MealType.LUNCH, LocalDate.now(), "fixture-A-meal")
            fixture.time += 400_000
            val restarted = client(db, vault, fixture); restarted.start()
            assertEquals(a.lease, restarted.view.value.binding!!.lease)
            assertFalse(restarted.view.value.hasSession)
            repo.addWeight(80.0, LocalDate.now(), "fixture-A-weight")
            restarted.refresh()
            assertTrue(restarted.view.value.hasSession)
            assertEquals(a.lease, restarted.view.value.binding!!.lease)
            val before = vault.read().getJSONObject("session").getString("authState")
            fixture.subject = "fixture-B"
            restarted.refresh()
            assertEquals(a.lease, restarted.view.value.binding!!.lease)
            assertEquals(before, vault.read().getJSONObject("session").getString("authState"))
            assertNull(db.ownerDao().byIdentity(issuer, "fixture-B"))
            restarted.logout()
            assertEquals("guest", restarted.view.value.binding!!.owner.kind)
            assertEquals(0, vault.read().length())
            assertEquals("fixture-A-meal", db.dao().day(a.owner.storageScope, LocalDate.now().toString()).first().single().meal.id)
            assertEquals(80.0, db.dao().weights(a.owner.storageScope).first().single().kg, 0.0)
            login(restarted, fixture, "fixture-A")
            assertEquals(a.owner.id, restarted.view.value.binding!!.owner.id)
            assertNotEquals(a.lease, restarted.view.value.binding!!.lease)
        } finally { vault.clear(); db.close() }
    }

    @Test fun delayedRefreshCannotApplyAfterAToBToA() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        try {
            val controller = client(db, vault, fixture); controller.start(); login(controller, fixture, "fixture-A")
            val old = controller.view.value.binding!!
            fixture.hold = CompletableDeferred()
            val refresh = async { controller.refresh() }
            withTimeout(10_000) { fixture.refreshStarted.await() }
            controller.logout(); login(controller, fixture, "fixture-B")
            controller.logout(); login(controller, fixture, "fixture-A")
            val current = controller.view.value.binding!!
            val state = vault.read().getJSONObject("session").getString("authState")
            assertEquals(old.owner, current.owner)
            assertNotEquals(old.lease, current.lease)
            fixture.hold!!.complete(Unit); refresh.await()
            assertEquals(state, vault.read().getJSONObject("session").getString("authState"))
            assertEquals(current.lease, controller.view.value.binding!!.lease)
        } finally { fixture.hold?.complete(Unit); vault.clear(); db.close() }
    }

    @Test fun oldCallbackAndExpiredAttemptCannotSelectOwner() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        try {
            val controller = client(db, vault, fixture); controller.start()
            controller.beginLogin(); val old = fixture.response()
            controller.cancelLogin(); controller.beginLogin()
            controller.completeLogin(old)
            assertEquals(0, fixture.calls)
            assertEquals("guest", controller.view.value.binding!!.owner.kind)
            fixture.time += 600_001
            val restarted = client(db, vault, fixture); restarted.start()
            assertFalse(restarted.view.value.pendingLogin)
            restarted.completeLogin(fixture.response())
            assertEquals(0, fixture.calls)
            assertEquals("guest", restarted.view.value.binding!!.owner.kind)
        } finally { vault.clear(); db.close() }
    }

    @Test fun cancellationDuringExchangeAndDuplicateLoginCannotActivateOldResponse() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        try {
            val controller = client(db, vault, fixture); controller.start()
            controller.beginLogin()
            assertNull(controller.beginLogin())
            fixture.codeHold = CompletableDeferred()
            val exchange = async { controller.completeLogin(fixture.response()) }
            withTimeout(10_000) { fixture.codeStarted.await() }
            assertTrue(controller.view.value.busy)
            assertNull(controller.beginLogin())
            controller.logout()
            val guest = controller.view.value.binding!!
            fixture.codeHold!!.complete(Unit); exchange.await()
            assertEquals(guest.lease, controller.view.value.binding!!.lease)
            assertNull(db.ownerDao().byIdentity(issuer, "fixture-A"))
            assertEquals(0, vault.read().length())
        } finally { fixture.codeHold?.complete(Unit); vault.clear(); db.close() }
    }

    @Test fun ciphertextTamperOrLostKeyDoesNotDeleteOrBlockAccountData() = runBlocking<Unit> {
        val db = memory(); val vaultName = name(); val vault = SessionVault(context, vaultName); val fixture = FixtureGateway()
        try {
            val controller = client(db, vault, fixture); controller.start(); login(controller, fixture, "fixture-A")
            val account = controller.view.value.binding!!
            val repo = DiaryRepository(db, context, account.lease).apply { initialize() }
            repo.add("basic-banana", 100.0, MealType.LUNCH, LocalDate.now(), "fixture-preserved")
            val file = File(context.noBackupFilesDir, vaultName)
            val firstBytes = file.readBytes()
            assertFalse(String(firstBytes, Charsets.ISO_8859_1).contains("fixture-access"))
            vault.write(vault.read())
            assertFalse(firstBytes.contentEquals(file.readBytes()))
            file.writeBytes(file.readBytes().also { it[it.lastIndex] = (it.last().toInt() xor 1).toByte() })
            assertThrows(Exception::class.java) { vault.read() }
            val tampered = client(db, vault, fixture); tampered.start()
            assertEquals(account.lease, tampered.view.value.binding!!.lease)
            assertFalse(tampered.view.value.hasSession)
            repo.addWeight(81.0, LocalDate.now(), "fixture-weight-after-tamper")
            login(tampered, fixture, "fixture-A")
            val latest = tampered.view.value.binding!!
            KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry("${context.packageName}.$vaultName") }
            val lostKey = client(db, vault, fixture); lostKey.start()
            assertEquals(latest.lease, lostKey.view.value.binding!!.lease)
            assertFalse(lostKey.view.value.hasSession)
            assertEquals("fixture-preserved", db.dao().day(account.owner.storageScope, LocalDate.now().toString()).first().single().meal.id)
            assertEquals(81.0, db.dao().weights(account.owner.storageScope).first().single().kg, 0.0)
        } finally { vault.clear(); db.close() }
    }

    @Test fun discoveryCannotChangeIssuerOrSendVerifierToAnotherHost() {
        val fixture = FixtureGateway()
        validateDiscovery(fixture.config, issuer)
        assertThrows(IllegalArgumentException::class.java) { validateDiscovery(fixture.config, "$issuer/") }
        val json = fixture.config.discoveryDoc!!.docJson
        val malicious = AuthorizationServiceConfiguration(AuthorizationServiceDiscovery(JSONObject(json.toString())
            .put("token_endpoint", "https://other.example/token")))
        assertThrows(IllegalArgumentException::class.java) { validateDiscovery(malicious, issuer) }
    }
}
