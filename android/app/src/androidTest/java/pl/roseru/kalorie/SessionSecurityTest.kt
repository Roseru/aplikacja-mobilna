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
    private fun client(db: CalorieDatabase, vault: SessionVault, fixture: FixtureGateway, api: BootstrapGateway? = null,
        profiles: ProfileGateway? = null) = SessionController(
        db, vault, fixture, issuer, context.packageName, now = { fixture.time }, bootstrapGateway = api, profileGateway = profiles)
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

    private val accountId = "a1111111-1111-4111-8111-111111111111"
    private val epoch = "e1111111-1111-4111-8111-111111111111"
    private val newEpoch = "f1111111-1111-4111-8111-111111111111"
    private fun accepted(syncEpoch: String = epoch, generation: Int = 1, id: String = accountId) = BootstrapHttpResult(200,
        BootstrapResponse(id, syncEpoch, generation, "2026-10-11T10:00:00Z").canonical().toByteArray())
    private fun denied(status: Int, code: String, retry: String? = null) = BootstrapHttpResult(status,
        JSONObject().put("code", code).put("message", "fixture text never displayed").put("details", JSONArray())
            .put("request_id", "b1111111-1111-4111-8111-111111111111").toString().toByteArray(), retry)
    private fun profileAnswer(change: (JSONObject) -> Unit = {}) = BootstrapHttpResult(200,
        JSONObject(androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context.assets
            .open("contracts/profile-read.json").bufferedReader().use { it.readText() })
            .also(change).toString().toByteArray())
    private inner class ProfileFixture(var answer: suspend (Int) -> BootstrapHttpResult = { profileAnswer() }) : ProfileGateway {
        val calls = mutableListOf<ApiSession>()
        val started = CompletableDeferred<Unit>()
        var hold: CompletableDeferred<Unit>? = null
        override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit): BootstrapHttpResult {
            beforeSend(); calls.add(session)
            val index = calls.size
            started.complete(Unit); hold?.await()
            return answer(index)
        }
    }
    @Test fun profilePreviewRequiresBootstrapAndNeverChangesLocalProfileGoalOrQueue() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture(); val profiles = ProfileFixture()
        try {
            val controller = client(db, vault, fixture, api, profiles); controller.start()
            controller.readProfile(); assertTrue(profiles.calls.isEmpty())
            login(controller, fixture, "fixture-A")
            controller.readProfile(); assertTrue(profiles.calls.isEmpty())
            controller.bootstrap()
            val lease = controller.view.value.binding!!.lease
            val repo = DiaryRepository(db, context, lease).apply { initialize() }
            repo.setProfile("Lokalny profil", 170.0, ActivityClass.GARRISON, DietAim.REDUCE)
            repo.setGoal(2400.0, 140.0, 70.0, 250.0)
            val local = db.dao().currentProfile(lease.storageScope)
            val goals = db.dao().goalsThrough(lease.storageScope, LocalDate.now().toString()).first()
            val queue = db.dao().operationCount(lease.storageScope)
            controller.readProfile()
            assertEquals("Użytkownik demo", controller.view.value.serverProfile!!.profile!!.pseudonym)
            assertEquals(local, db.dao().currentProfile(lease.storageScope))
            assertEquals(goals, db.dao().goalsThrough(lease.storageScope, LocalDate.now().toString()).first())
            assertEquals(queue, db.dao().operationCount(lease.storageScope))
            profiles.answer = { profileAnswer { it.put("profile", JSONObject.NULL) } }
            controller.readProfile(); assertNotNull(controller.view.value.serverProfile)
            assertNull(controller.view.value.serverProfile!!.profile)
            val restarted = client(db, vault, fixture, api, profiles); restarted.start()
            assertNull(restarted.view.value.serverProfile)
            assertEquals(local, db.dao().currentProfile(lease.storageScope))
        } finally { vault.clear(); db.close() }
    }
    @Test fun delayedProfileCannotLeakAcrossLogoutAToBToAAndDuplicateTapSendsOnce() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture(); val profiles = ProfileFixture().apply { hold = CompletableDeferred() }
        try {
            val controller = client(db, vault, fixture, api, profiles); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            val original = controller.view.value.binding!!.lease
            val request = async { controller.readProfile() }
            withTimeout(10_000) { profiles.started.await() }
            controller.readProfile(); controller.bootstrap(); assertEquals(1, profiles.calls.size); assertEquals(1, api.calls.size)
            controller.logout(); login(controller, fixture, "fixture-B")
            assertNull(controller.view.value.serverProfile); assertFalse(controller.view.value.profileBusy)
            controller.logout(); login(controller, fixture, "fixture-A")
            assertNotEquals(original, controller.view.value.binding!!.lease)
            profiles.hold!!.complete(Unit); request.await()
            assertNull(controller.view.value.serverProfile)
            assertEquals(original, profiles.calls.single().lease)
        } finally { profiles.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun manualRefreshInvalidatesHeldProfileAndClearsDisplayedPreview() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture(); val profiles = ProfileFixture()
        try {
            val controller = client(db, vault, fixture, api, profiles); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            controller.readProfile(); assertNotNull(controller.view.value.serverProfile)
            profiles.hold = CompletableDeferred()
            val request = async { controller.readProfile() }
            withTimeout(10_000) { while (profiles.calls.size < 2) yield() }
            controller.refresh(); assertNull(controller.view.value.serverProfile)
            profiles.hold!!.complete(Unit); request.await()
            assertNull(controller.view.value.serverProfile); assertFalse(controller.view.value.profileBusy)
            profiles.hold = null; controller.readProfile(); assertNotNull(controller.view.value.serverProfile)
        } finally { profiles.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun profileUnauthorizedRenewsOnceAndFailedRenewalNeverResendsOldToken() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture(); val profiles = ProfileFixture { if (it == 1) denied(401, "unauthorized") else profileAnswer() }
        try {
            val controller = client(db, vault, fixture, api, profiles); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            controller.readProfile()
            assertEquals(2, profiles.calls.size); assertEquals(2, fixture.calls)
            assertNotEquals(profiles.calls[0].accessToken, profiles.calls[1].accessToken)
            assertEquals(profiles.calls[0].lease, profiles.calls[1].lease)
            assertNotNull(controller.view.value.serverProfile)
            profiles.calls.clear(); profiles.answer = { denied(401, "unauthorized") }
            controller.readProfile(); assertEquals(2, profiles.calls.size); assertNull(controller.view.value.serverProfile)
            profiles.calls.clear(); fixture.subject = "fixture-B"
            controller.readProfile(); assertEquals(1, profiles.calls.size)
            assertEquals("fixture-A", controller.view.value.binding!!.owner.subject)
            assertNull(db.ownerDao().byIdentity(issuer, "fixture-B"))
            assertFalse(controller.view.value.profileBusy)
        } finally { vault.clear(); db.close() }
    }
    @Test fun expiringProfileSessionRefreshesButForbiddenAndInvalidResponseNeverBecomePreview() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture(); val profiles = ProfileFixture()
        try {
            val controller = client(db, vault, fixture, api, profiles); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            fixture.time += 400_000
            controller.readProfile(); assertEquals(2, fixture.calls); assertNotNull(controller.view.value.serverProfile)
            val original = db.bootstrapDao().binding(controller.view.value.binding!!.lease.storageScope)
            for (response in listOf(denied(403, "account_bootstrap_required"), BootstrapHttpResult(200, "{}".toByteArray()),
                profileAnswer { it.put("account_id", "c1111111-1111-4111-8111-111111111111") })) {
                profiles.answer = { response }; controller.readProfile()
                assertNull(controller.view.value.serverProfile); assertFalse(controller.view.value.profileBusy)
                assertEquals(2, fixture.calls)
                assertEquals(original, db.bootstrapDao().binding(controller.view.value.binding!!.lease.storageScope))
            }
        } finally { vault.clear(); db.close() }
    }
    @Test fun profileRetryAfterPersistsAcrossRestartAndAlsoBlocksBootstrap() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture(); val profiles = ProfileFixture { denied(503, "service_unavailable", "60") }
        try {
            val controller = client(db, vault, fixture, api, profiles); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            controller.readProfile(); assertEquals(1, profiles.calls.size)
            val restarted = client(db, vault, fixture, api, profiles); restarted.start()
            restarted.readProfile(); restarted.bootstrap()
            assertEquals(1, profiles.calls.size); assertEquals(1, api.calls.size)
            fixture.time += 59_000; restarted.readProfile(); assertEquals(1, profiles.calls.size)
            fixture.time += 1000; profiles.answer = { profileAnswer() }; restarted.readProfile()
            assertEquals(2, profiles.calls.size); assertNotNull(restarted.view.value.serverProfile)
        } finally { vault.clear(); db.close() }
    }
    @Test fun changedProfileEpochMarksRecoveryWithoutReplacingMappingOrClearingOnRestart() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture(); val profiles = ProfileFixture { profileAnswer { it.put("sync_epoch", newEpoch) } }
        try {
            val controller = client(db, vault, fixture, api, profiles); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            val lease = controller.view.value.binding!!.lease
            val original = db.bootstrapDao().binding(lease.storageScope)!!
            controller.readProfile(); assertNull(controller.view.value.serverProfile)
            assertEquals(original.copy(requiresRecovery = true, contextRevision = original.contextRevision + 1), db.bootstrapDao().binding(lease.storageScope))
            assertTrue(controller.view.value.requiresRecovery)
            val restarted = client(db, vault, fixture, api, profiles); restarted.start(); restarted.readProfile()
            assertEquals(1, profiles.calls.size); assertTrue(restarted.view.value.requiresRecovery)
            restarted.bootstrap(); assertTrue(restarted.view.value.requiresRecovery)
        } finally { vault.clear(); db.close() }
    }
    @Test fun cancelledProfileRequestReleasesBusyStateAndKeepsMappingForRetry() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture(); val profiles = ProfileFixture().apply { hold = CompletableDeferred() }
        try {
            val controller = client(db, vault, fixture, api, profiles); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            val original = db.bootstrapDao().binding(controller.view.value.binding!!.lease.storageScope)
            val task = async { controller.readProfile() }; withTimeout(10_000) { profiles.started.await() }
            task.cancelAndJoin(); assertFalse(controller.view.value.profileBusy); assertNull(controller.view.value.serverProfile)
            assertEquals(original, db.bootstrapDao().binding(controller.view.value.binding!!.lease.storageScope))
            profiles.hold = null; controller.readProfile(); assertNotNull(controller.view.value.serverProfile)
        } finally { profiles.hold?.complete(Unit); vault.clear(); db.close() }
    }
    private class ApiCall(val ticket: ApiSession, val key: String)
    private inner class ApiFixture(var answer: suspend (Int) -> BootstrapHttpResult = { accepted() }) : BootstrapGateway {
        val calls = mutableListOf<ApiCall>()
        val started = CompletableDeferred<Unit>()
        var hold: CompletableDeferred<Unit>? = null
        override suspend fun post(session: ApiSession, operationId: String, beforeSend: suspend () -> Unit): BootstrapHttpResult {
            beforeSend()
            calls.add(ApiCall(session, operationId))
            val index = calls.size
            started.complete(Unit)
            hold?.await()
            return answer(index)
        }
    }
    @Test fun bootstrapLostAckReusesDurableKeyAfterControllerRestartWithoutImportingGuest() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture { if (it == 1) throw java.io.IOException("fixture lost ACK") else accepted() }
        try {
            val first = client(db, vault, fixture, api); first.start()
            val guest = DiaryRepository(db, context).apply { initialize() }
            guest.add("basic-banana", 100.0, MealType.LUNCH, LocalDate.now(), "bootstrap-guest-preserved")
            first.bootstrap(); assertTrue(api.calls.isEmpty())
            login(first, fixture, "fixture-A")
            val lease = first.view.value.binding!!.lease
            first.bootstrap()
            assertNull(db.bootstrapDao().binding(lease.storageScope))
            val key = db.bootstrapDao().attempt(lease.storageScope)!!.operationId
            assertEquals(key, api.calls.single().key)
            val restarted = client(db, vault, fixture, api); restarted.start(); restarted.bootstrap()
            assertEquals(listOf(key, key), api.calls.map { it.key })
            assertTrue(restarted.view.value.serverLinked)
            assertEquals(SessionIdentity(issuer, "fixture-A"), api.calls.last().ticket.identity)
            assertEquals(lease, api.calls.last().ticket.lease)
            assertEquals(accountId, db.bootstrapDao().binding(lease.storageScope)!!.accountId)
            assertEquals(1, db.dao().operationCount("guest")); assertEquals(0, db.dao().operationCount(lease.storageScope))
            assertNull(db.dao().currentProfile(lease.storageScope))
            assertTrue(db.dao().goalsThrough(lease.storageScope, LocalDate.now().toString()).first().isEmpty())
            assertTrue(db.dao().day(lease.storageScope, LocalDate.now().toString()).first().isEmpty())
            assertEquals("bootstrap-guest-preserved", db.dao().day("guest", LocalDate.now().toString()).first().single().meal.id)
        } finally { vault.clear(); db.close() }
    }
    @Test fun delayedBootstrapAndCapturedTicketCannotApplyAfterLogoutAToBToA() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture().apply { hold = CompletableDeferred() }
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            val old = controller.view.value.binding!!
            val ticket = controller.apiSession(old.lease)
            val task = async { controller.bootstrap() }
            withTimeout(10_000) { api.started.await() }
            controller.bootstrap(); assertEquals(1, api.calls.size)
            controller.logout(); login(controller, fixture, "fixture-B")
            controller.logout(); login(controller, fixture, "fixture-A")
            assertNotEquals(old.lease, controller.view.value.binding!!.lease)
            api.hold!!.complete(Unit); task.await()
            assertNull(db.bootstrapDao().binding(old.owner.storageScope))
            assertFalse(controller.view.value.serverLinked)
            assertThrows(StaleOwnerException::class.java) { runBlocking { controller.withApiSession(ticket) { fail("stale block ran") } } }
            assertEquals("fixture-A", api.calls.single().ticket.identity.subject)
        } finally { api.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun unauthorizedRenewsOnceWithSameLeaseKeyAndNewToken() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture { if (it == 1) denied(401, "unauthorized") else accepted() }
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            val lease = controller.view.value.binding!!.lease
            controller.bootstrap()
            assertEquals(2, api.calls.size); assertEquals(2, fixture.calls)
            assertEquals(lease, api.calls[0].ticket.lease); assertEquals(lease, api.calls[1].ticket.lease)
            assertEquals(api.calls[0].key, api.calls[1].key)
            assertNotEquals(api.calls[0].ticket.accessToken, api.calls[1].ticket.accessToken)
            assertTrue(controller.view.value.serverLinked)
            assertThrows(Exception::class.java) { runBlocking { controller.withApiSession(api.calls[0].ticket) { fail("old token block ran") } } }
            api.calls.clear(); api.answer = { denied(401, "unauthorized") }
            controller.bootstrap()
            assertEquals(2, api.calls.size); assertFalse(controller.view.value.bootstrapBusy)
            assertTrue(controller.view.value.message!!.contains("logowania"))
        } finally { vault.clear(); db.close() }
    }
    @Test fun epochAndGenerationRenewKeyOnceAndKeepRecoveryFlagAndOriginals() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            val lease = controller.view.value.binding!!.lease
            val repo = DiaryRepository(db, context, lease).apply { initialize() }
            repo.add("basic-banana", 120.0, MealType.LUNCH, LocalDate.now(), "bootstrap-account-preserved")
            controller.bootstrap()
            api.answer = { if (it == 2) denied(409, "sync_epoch_changed") else accepted(newEpoch) }
            controller.bootstrap()
            assertEquals(3, api.calls.size); assertNotEquals(api.calls[1].key, api.calls[2].key)
            val binding = db.bootstrapDao().binding(lease.storageScope)!!
            assertEquals(newEpoch, binding.syncEpoch); assertEquals(2L, binding.contextRevision)
            assertTrue(binding.requiresRecovery); assertTrue(controller.view.value.requiresRecovery)
            controller.bootstrap(); assertTrue(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            api.answer = { if (it == 5) denied(409, "account_generation_changed") else accepted(newEpoch, 2) }
            controller.bootstrap()
            assertNotEquals(api.calls[4].key, api.calls[5].key)
            assertEquals(2, db.bootstrapDao().binding(lease.storageScope)!!.accountGeneration)
            val preserved = db.bootstrapDao().binding(lease.storageScope)!!
            api.answer = { accepted(newEpoch, 1) }; controller.bootstrap()
            assertEquals(preserved, db.bootstrapDao().binding(lease.storageScope))
            api.answer = { accepted(newEpoch, 2, "b1111111-1111-4111-8111-111111111111") }; controller.bootstrap()
            assertEquals(preserved, db.bootstrapDao().binding(lease.storageScope))
            assertEquals("bootstrap-account-preserved", db.dao().day(lease.storageScope, LocalDate.now().toString()).first().single().meal.id)
            assertEquals(1, db.dao().operationCount(lease.storageScope))
        } finally { vault.clear(); db.close() }
    }
    @Test fun unavailableRespectsRetryAfterAcrossRestartAndReusesKey() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture { if (it == 1) BootstrapHttpResult(503, "<html>fixture proxy</html>".toByteArray(), "60") else accepted() }
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            controller.bootstrap(); assertEquals(1, api.calls.size)
            val restarted = client(db, vault, fixture, api); restarted.start()
            restarted.bootstrap(); assertEquals(1, api.calls.size)
            fixture.time += 59_000; restarted.bootstrap(); assertEquals(1, api.calls.size)
            fixture.time += 1000; restarted.bootstrap(); assertEquals(2, api.calls.size)
            assertEquals(api.calls[0].key, api.calls[1].key); assertTrue(restarted.view.value.serverLinked)
        } finally { vault.clear(); db.close() }
    }
    @Test fun malformedResponseForbiddenAndRepeatedEpochConflictNeverDiscardPendingKey() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture { BootstrapHttpResult(200, accepted().body + "x".toByteArray()) }
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            val lease = controller.view.value.binding!!.lease
            controller.bootstrap(); val key = api.calls.single().key
            api.answer = { denied(403, "forbidden") }; controller.bootstrap()
            assertEquals(key, api.calls.last().key); assertEquals(1, fixture.calls)
            api.answer = { denied(409, "sync_epoch_changed") }; controller.bootstrap()
            assertEquals(4, api.calls.size); assertEquals(key, api.calls[2].key); assertNotEquals(key, api.calls[3].key)
            val renewed = db.bootstrapDao().attempt(lease.storageScope)!!.operationId
            assertEquals(renewed, api.calls.last().key); assertNull(db.bootstrapDao().binding(lease.storageScope))
            api.answer = { accepted() }; controller.bootstrap()
            assertEquals(renewed, api.calls.last().key); assertTrue(controller.view.value.serverLinked)
        } finally { vault.clear(); db.close() }
    }
    @Test fun expiryRenewsBeforeHttpAndLocalIdentityWithoutSessionNeverSends() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            val lease = controller.view.value.binding!!.lease
            fixture.time += 400_000; controller.bootstrap()
            assertEquals(2, fixture.calls); assertEquals(lease, api.calls.single().ticket.lease)
            assertTrue(controller.view.value.serverLinked)
            controller.logout()
            val owners = LocalOwnerStore(db)
            val local = owners.registerIdentity(issuer, "fixture-only-local")
            owners.select(local.id)
            val noSession = client(db, vault, fixture, api); noSession.start(); noSession.bootstrap()
            assertEquals(1, api.calls.size); assertFalse(noSession.view.value.serverLinked)
        } finally { vault.clear(); db.close() }
    }
    @Test fun refreshWhileBootstrapWaitsInvalidatesItsResponseWithoutDeletingAttempt() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture().apply { hold = CompletableDeferred() }
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            val lease = controller.view.value.binding!!.lease
            val task = async { controller.bootstrap() }; withTimeout(10_000) { api.started.await() }
            controller.refresh(); api.hold!!.complete(Unit); task.await()
            assertNull(db.bootstrapDao().binding(lease.storageScope))
            assertNull(db.bootstrapDao().attempt(lease.storageScope)!!.responseJson)
            val key = api.calls.single().key
            api.hold = null; controller.bootstrap()
            assertEquals(key, api.calls.last().key); assertTrue(controller.view.value.serverLinked)
        } finally { api.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun cancelledBootstrapReleasesBusyStateAndKeepsKeyForRetry() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture().apply { hold = CompletableDeferred() }
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            val lease = controller.view.value.binding!!.lease
            val task = async { controller.bootstrap() }; withTimeout(10_000) { api.started.await() }
            task.cancelAndJoin()
            assertFalse(controller.view.value.bootstrapBusy)
            assertNull(db.bootstrapDao().binding(lease.storageScope))
            val key = db.bootstrapDao().attempt(lease.storageScope)!!.operationId
            api.hold = null; controller.bootstrap()
            assertEquals(listOf(key, key), api.calls.map { it.key }); assertTrue(controller.view.value.serverLinked)
        } finally { api.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun cancelledAutomaticRenewalReleasesSessionAndBootstrapForRetry() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            val lease = controller.view.value.binding!!.lease
            fixture.time += 400_000; fixture.hold = CompletableDeferred()
            val task = async { controller.bootstrap() }; withTimeout(10_000) { fixture.refreshStarted.await() }
            task.cancelAndJoin()
            assertFalse(controller.view.value.busy); assertFalse(controller.view.value.bootstrapBusy)
            assertEquals(lease, controller.view.value.binding!!.lease); assertTrue(api.calls.isEmpty())
            fixture.hold = null; controller.bootstrap()
            assertEquals(1, api.calls.size); assertTrue(controller.view.value.serverLinked)
        } finally { fixture.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun failedUnauthorizedRenewalNeverResendsTheUnconfirmedOrOldToken() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture { denied(401, "unauthorized") }
        try {
            val controller = client(db, vault, fixture, api); controller.start(); login(controller, fixture, "fixture-A")
            val lease = controller.view.value.binding!!.lease
            fixture.subject = "fixture-B" // Token renewal must not change the confirmed subject.
            controller.bootstrap()
            assertEquals(1, api.calls.size); assertEquals(2, fixture.calls)
            assertEquals("fixture-A", api.calls.single().ticket.identity.subject)
            assertEquals(lease, controller.view.value.binding!!.lease)
            assertNull(db.bootstrapDao().binding(lease.storageScope))
            assertFalse(controller.view.value.bootstrapBusy)
            assertNull(db.ownerDao().byIdentity(issuer, "fixture-B"))
        } finally { vault.clear(); db.close() }
    }
}
