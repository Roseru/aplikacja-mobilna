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
import pl.roseru.kalorie.core.sync.*
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
        profiles: ProfileGateway? = null, snapshots: SnapshotGateway? = null, motivation: MotivationGateway? = null,
        consents: RankingConsentGateway? = null, ranking: RankingGateway? = null, nemesis: NemesisGateway? = null, nemesisWrites: NemesisWriteGateway? = null, photos: PhotoCapabilitiesGateway? = null) = SessionController(
        db, vault, fixture, issuer, context.packageName, now = { fixture.time }, bootstrapGateway = api, profileGateway = profiles, snapshotGateway = snapshots,
        snapshotProtocol = snapshots?.let { snapshotProtocol() }, motivationGateway = motivation, rankingConsentGateway = consents, rankingGateway = ranking, nemesisGateway = nemesis, nemesisWriteGateway = nemesisWrites, photoCapabilitiesGateway = photos)
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

    private fun snapshotProtocol() = SnapshotProtocol(SyncWireSchema(SyncWireSchema.FILES.associateWith { file ->
        context.assets.open("sync/$file").use { it.readBytes() }
    }))
    private fun snapshotAnswer(next: String? = null) = BootstrapHttpResult(200,
        JSONObject().put("sync_epoch", epoch).put("mode", "snapshot").put("snapshot_token", "fixture-snapshot")
            .put("page_token", next ?: JSONObject.NULL).put("checkpoint", if (next == null) "fixture-checkpoint" else JSONObject.NULL)
            .put("server_time", "2026-10-11T10:00:00Z").put("entities", JSONArray()).put("goal_timeline_revision", 0)
            .put("recovery_mappings", JSONArray()).put("operation_receipts", JSONArray()).toString().toByteArray())
    private fun syncDenied(status: Int, code: String, retry: String? = null) = BootstrapHttpResult(status,
        JSONObject().put("code", code).put("message", "fixture").put("details", JSONObject().apply {
            if (code == "sync_epoch_changed") {
                put("current_sync_epoch", newEpoch); put("requested_sync_epoch", epoch); put("recovery_required", "epoch_recovery")
            }
            if (code in setOf("sync_cursor_expired", "sync_reconciliation_required")) {
                put("current_sync_epoch", epoch); put("recovery_required", "full_snapshot")
            }
        })
            .put("request_id", "b1111111-1111-4111-8111-111111111111").toString().toByteArray(), retry)
    private inner class SnapshotFixture(var answer: suspend (Int) -> BootstrapHttpResult = { snapshotAnswer() }) : SnapshotGateway {
        val calls = mutableListOf<Pair<ApiSession, String>>()
        val started = CompletableDeferred<Unit>()
        var hold: CompletableDeferred<Unit>? = null
        override suspend fun get(session: ApiSession, query: SnapshotQuery, beforeSend: suspend () -> Unit): BootstrapHttpResult {
            beforeSend(); calls.add(session to query.encoded()); val index = calls.size
            started.complete(Unit); hold?.await(); return answer(index)
        }
    }
    @Test fun snapshotNeedsConfirmedSessionAndBootstrapAndKeepsGuestAndLocalQueue() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val copies = SnapshotFixture { if (it == 1) snapshotAnswer("fixture-next") else snapshotAnswer() }
        try {
            val controller = client(db, vault, fixture, api, snapshots = copies); controller.start()
            val guest = DiaryRepository(db, context).apply { initialize(); add("basic-banana", 100.0, MealType.LUNCH, LocalDate.now(), "copy-guest") }
            controller.downloadSnapshot(); assertTrue(copies.calls.isEmpty())
            login(controller, fixture, "fixture-A"); controller.downloadSnapshot(); assertTrue(copies.calls.isEmpty())
            val lease = controller.view.value.binding!!.lease
            val repo = DiaryRepository(db, context, lease).apply { initialize(); add("basic-banana", 150.0, MealType.LUNCH, LocalDate.now(), "copy-account") }
            controller.bootstrap(); controller.downloadSnapshot()
            assertEquals(2, copies.calls.size); assertTrue(copies.calls[1].second.contains("page_token=fixture-next"))
            assertEquals(2, controller.view.value.snapshot!!.completedPages); assertFalse(controller.view.value.snapshotBusy)
            assertEquals(1, db.dao().operationCount(guest.owner)); assertEquals(1, db.dao().operationCount(repo.owner))
            assertEquals("copy-account", db.dao().day(repo.owner, LocalDate.now().toString()).first().single().meal.id)
        } finally { vault.clear(); db.close() }
    }
    @Test fun snapshotControllerRestartResumesSavedPageAfterNetworkLoss() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val copies = SnapshotFixture { if (it == 1) snapshotAnswer("next") else error("fixture network loss") }
        try {
            val first = client(db, vault, fixture, api, snapshots = copies); first.start(); login(first, fixture, "fixture-A"); first.bootstrap()
            first.downloadSnapshot(); assertEquals(1, first.view.value.snapshot!!.pendingPages)
            assertNull(first.view.value.snapshot!!.completedTime); assertFalse(first.view.value.snapshotBusy)
            val retryQuery = copies.calls[1].second
            copies.answer = { snapshotAnswer() }
            val restarted = client(db, vault, fixture, api, snapshots = copies); restarted.start()
            assertEquals(1, restarted.view.value.snapshot!!.pendingPages)
            restarted.downloadSnapshot(); assertEquals(retryQuery, copies.calls[2].second)
            assertEquals(2, restarted.view.value.snapshot!!.completedPages)
        } finally { vault.clear(); db.close() }
    }
    @Test fun snapshotLogoutAbaAndLateResponseCannotPublishIntoNewSession() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val copies = SnapshotFixture().apply { hold = CompletableDeferred() }
        try {
            val controller = client(db, vault, fixture, api, snapshots = copies); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            val lease = controller.view.value.binding!!.lease
            val pending = async { controller.downloadSnapshot() }; withTimeout(10_000) { copies.started.await() }
            controller.logout(); assertNull(controller.view.value.snapshot)
            login(controller, fixture, "fixture-A"); assertNotEquals(lease, controller.view.value.binding!!.lease)
            copies.hold!!.complete(Unit); pending.await()
            assertNull(controller.view.value.snapshot!!.completedTime)
            assertTrue(db.snapshotDao().runs(lease.storageScope).all { it.pageCount == 0 })
            copies.hold = null; controller.downloadSnapshot()
            assertEquals(2, db.snapshotDao().runs(lease.storageScope).size)
            assertEquals(1, controller.view.value.snapshot!!.completedPages)
        } finally { copies.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun snapshotCancellationDoubleTapAndRefreshDoNotCommitStaleResponse() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val copies = SnapshotFixture().apply { hold = CompletableDeferred() }
        try {
            val controller = client(db, vault, fixture, api, snapshots = copies); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            val pending = async { controller.downloadSnapshot() }; withTimeout(10_000) { copies.started.await() }
            controller.downloadSnapshot(); assertEquals(1, copies.calls.size)
            pending.cancelAndJoin(); assertFalse(controller.view.value.snapshotBusy)
            val old = async { controller.downloadSnapshot() }
            withTimeout(10_000) { while (copies.calls.size < 2) yield() }
            controller.refresh(); copies.hold!!.complete(Unit); old.await()
            assertNull(controller.view.value.snapshot!!.completedTime)
            copies.hold = null; controller.downloadSnapshot()
            assertEquals(copies.calls[0].second, copies.calls[2].second)
            assertEquals(1, controller.view.value.snapshot!!.completedPages)
        } finally { copies.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun snapshot401RefreshesOnceAnd503DelaySurvivesControllerRestart() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val copies = SnapshotFixture { if (it == 1) syncDenied(401, "unauthorized") else syncDenied(503, "service_unavailable", "60") }
        try {
            val controller = client(db, vault, fixture, api, snapshots = copies); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            controller.downloadSnapshot(); assertEquals(2, copies.calls.size); assertEquals(2, fixture.calls)
            assertEquals(copies.calls[0].second, copies.calls[1].second)
            assertNotEquals(copies.calls[0].first.accessToken, copies.calls[1].first.accessToken)
            val restarted = client(db, vault, fixture, api, snapshots = copies); restarted.start(); restarted.downloadSnapshot()
            assertEquals(2, copies.calls.size); fixture.time += 60_000
            copies.answer = { snapshotAnswer() }; restarted.downloadSnapshot()
            assertEquals(3, copies.calls.size); assertEquals(1, restarted.view.value.snapshot!!.completedPages)
        } finally { vault.clear(); db.close() }
    }
    @Test fun snapshotExpiryAndEpochConflictKeepArchivesAndRecoveryFlag() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val copies = SnapshotFixture { if (it == 1) snapshotAnswer("next") else syncDenied(410, "snapshot_expired") }
        try {
            val controller = client(db, vault, fixture, api, snapshots = copies); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            val lease = controller.view.value.binding!!.lease
            controller.downloadSnapshot(); assertEquals("expired", db.snapshotDao().runs(lease.storageScope).single().state)
            copies.answer = { syncDenied(409, "sync_epoch_changed") }; controller.downloadSnapshot()
            assertTrue(controller.view.value.requiresRecovery); assertNull(controller.view.value.snapshot!!.completedTime)
            assertTrue(controller.view.value.snapshot!!.needsBootstrap)
            val calls = copies.calls.size; controller.downloadSnapshot(); assertEquals(calls, copies.calls.size)
            controller.bootstrap(); assertFalse(controller.view.value.snapshot!!.needsBootstrap)
            copies.answer = { snapshotAnswer() }; controller.downloadSnapshot()
            assertTrue(controller.view.value.requiresRecovery); assertEquals(1, controller.view.value.snapshot!!.completedPages)
            assertEquals(3, db.snapshotDao().runs(lease.storageScope).size)
            assertEquals(1, db.snapshotDao().pages(db.snapshotDao().runs(lease.storageScope).last().id).size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun snapshotAccountDeletingIsDurablyBlockedWithoutLosingLocalSession() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val copies = SnapshotFixture { syncDenied(403, "account_deleting") }
        try {
            val controller = client(db, vault, fixture, api, snapshots = copies); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            controller.downloadSnapshot(); assertTrue(controller.view.value.snapshot!!.blocked); assertTrue(controller.view.value.hasSession)
            val restarted = client(db, vault, fixture, api, snapshots = copies); restarted.start(); restarted.downloadSnapshot()
            assertEquals(1, copies.calls.size); assertTrue(restarted.view.value.snapshot!!.blocked)
        } finally { vault.clear(); db.close() }
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
    private fun motivationAnswer(name: String = "final", change: (JSONObject) -> Unit = {}) = BootstrapHttpResult(200,
        JSONObject(androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context.assets
            .open("motivation/motivation-$name.json").bufferedReader().use { it.readText() })
            .put("sync_epoch", epoch).also(change).toString().toByteArray())
    private inner class MotivationFixture(var answer: suspend (Int) -> BootstrapHttpResult = { motivationAnswer() }) : MotivationGateway {
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
    @Test fun motivationReadRequiresBootstrapPreservesDiaryQueueAndDoesNotPersistConfirmation() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        try {
            val controller = client(db, vault, fixture, api, motivation = motivation); controller.start()
            controller.readMotivation(); assertTrue(motivation.calls.isEmpty())
            login(controller, fixture, "fixture-A"); controller.readMotivation(); assertTrue(motivation.calls.isEmpty())
            controller.bootstrap()
            val lease = controller.view.value.binding!!.lease
            val repo = DiaryRepository(db, context, lease).apply { initialize() }
            repo.setProfile("Lokalny profil", 170.0, ActivityClass.GARRISON, DietAim.REDUCE)
            repo.setGoal(2400.0, 140.0, 70.0, 250.0)
            repo.add("basic-banana", 100.0, MealType.LUNCH, LocalDate.now(), "motivation-preserved")
            val local = db.dao().currentProfile(lease.storageScope)
            val goals = db.dao().goalsThrough(lease.storageScope, LocalDate.now().toString()).first()
            val meals = db.dao().day(lease.storageScope, LocalDate.now().toString()).first()
            val queue = db.dao().operationCount(lease.storageScope)
            controller.readMotivation()
            val read = (controller.view.value.motivation as MotivationState.Ready).read
            assertEquals(20L, read.points); assertTrue(read.ranking.pendingConsentRefresh); assertFalse(read.ranking.effective)
            assertEquals(local, db.dao().currentProfile(lease.storageScope)); assertEquals(goals, db.dao().goalsThrough(lease.storageScope, LocalDate.now().toString()).first())
            assertEquals(meals, db.dao().day(lease.storageScope, LocalDate.now().toString()).first()); assertEquals(queue, db.dao().operationCount(lease.storageScope))
            assertEquals(1, api.calls.size)
            val restarted = client(db, vault, fixture, api, motivation = motivation); restarted.start()
            assertEquals(MotivationState.NotRequested, restarted.view.value.motivation)
            assertEquals(1, motivation.calls.size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun heldMotivationIsSingleFlightAndCannotLeakAcrossLogoutAToBToA() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture(); val motivation = MotivationFixture().apply { hold = CompletableDeferred() }
        try {
            val controller = client(db, vault, fixture, api, profiles, motivation = motivation); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            val original = controller.view.value.binding!!.lease
            val request = async { controller.readMotivation() }; withTimeout(10_000) { motivation.started.await() }
            assertTrue(controller.view.value.motivationBusy); assertFalse(controller.view.value.profileBusy)
            controller.readMotivation(); controller.readProfile(); controller.bootstrap()
            assertEquals(1, motivation.calls.size); assertTrue(profiles.calls.isEmpty()); assertEquals(1, api.calls.size)
            controller.logout(); assertEquals(MotivationState.NotRequested, controller.view.value.motivation)
            login(controller, fixture, "fixture-B"); controller.logout(); login(controller, fixture, "fixture-A")
            assertNotEquals(original, controller.view.value.binding!!.lease)
            motivation.hold!!.complete(Unit); request.await()
            assertEquals(MotivationState.NotRequested, controller.view.value.motivation); assertFalse(controller.view.value.motivationBusy)
        } finally { motivation.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun manualRefreshClearsConfirmedAndRejectsHeldMotivation() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        val held = CompletableDeferred<Unit>()
        try {
            val controller = client(db, vault, fixture, api, motivation = motivation); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            controller.readMotivation(); assertTrue(controller.view.value.motivation is MotivationState.Ready)
            motivation.hold = held
            val request = async { controller.readMotivation() }; withTimeout(10_000) { while (motivation.calls.size < 2) yield() }
            controller.refresh(); assertEquals(MotivationState.NotRequested, controller.view.value.motivation)
            motivation.hold = null; controller.readMotivation()
            val fresh = controller.view.value.motivation
            assertTrue(fresh is MotivationState.Ready)
            held.complete(Unit); request.await()
            assertSame(fresh, controller.view.value.motivation); assertFalse(controller.view.value.motivationBusy)
        } finally { held.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun motivationUnauthorizedRefreshesOnceAndFailedIdentityNeverResendsOldToken() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val motivation = MotivationFixture { if (it == 1) denied(401, "unauthorized") else motivationAnswer() }
        try {
            val controller = client(db, vault, fixture, api, motivation = motivation); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            controller.readMotivation(); assertEquals(2, motivation.calls.size); assertEquals(2, fixture.calls)
            assertNotEquals(motivation.calls[0].accessToken, motivation.calls[1].accessToken); assertTrue(controller.view.value.motivation is MotivationState.Ready)
            motivation.calls.clear(); motivation.answer = { denied(401, "unauthorized") }
            controller.readMotivation(); assertEquals(2, motivation.calls.size); assertTrue(controller.view.value.motivation is MotivationState.Failed)
            motivation.calls.clear(); fixture.subject = "fixture-B"
            controller.readMotivation(); assertEquals(1, motivation.calls.size); assertEquals("fixture-A", controller.view.value.binding!!.owner.subject)
            assertNull(db.ownerDao().byIdentity(issuer, "fixture-B")); assertFalse(controller.view.value.motivationBusy)
        } finally { vault.clear(); db.close() }
    }
    @Test fun motivationUnknownEpochOrGenerationMarksRecoveryWithoutReplacingBootstrap() = runBlocking<Unit> {
        for (field in listOf("sync_epoch", "account_generation")) {
            val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
            val motivation = MotivationFixture { motivationAnswer { it.put(field, if (field == "sync_epoch") newEpoch else 2) } }
            try {
                val controller = client(db, vault, fixture, api, motivation = motivation); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
                val lease = controller.view.value.binding!!.lease; val original = db.bootstrapDao().binding(lease.storageScope)!!
                controller.readMotivation(); assertTrue(controller.view.value.requiresRecovery); assertFalse(controller.view.value.motivationBusy)
                assertTrue(controller.view.value.motivation is MotivationState.Failed)
                assertEquals(original.copy(requiresRecovery = true, contextRevision = original.contextRevision + 1), db.bootstrapDao().binding(lease.storageScope))
                controller.readMotivation(); assertEquals(1, motivation.calls.size)
                val restarted = client(db, vault, fixture, api, motivation = motivation); restarted.start()
                assertTrue(restarted.view.value.requiresRecovery); assertEquals(MotivationState.NotRequested, restarted.view.value.motivation)
            } finally { vault.clear(); db.close() }
        }
    }
    @Test fun motivationBackoffSurvivesRestartAndBlocksProfileAndBootstrapUntilDeadline() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val profiles = ProfileFixture()
        val motivation = MotivationFixture { denied(503, "service_unavailable", "60") }
        try {
            val controller = client(db, vault, fixture, api, profiles, motivation = motivation); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            controller.readMotivation(); assertTrue(controller.view.value.motivation is MotivationState.Failed)
            val restarted = client(db, vault, fixture, api, profiles, motivation = motivation); restarted.start()
            restarted.readMotivation(); restarted.readProfile(); restarted.bootstrap()
            assertEquals(1, motivation.calls.size); assertTrue(profiles.calls.isEmpty()); assertEquals(1, api.calls.size)
            assertTrue(restarted.view.value.motivation is MotivationState.Failed)
            fixture.time += 59_000; restarted.readMotivation(); assertEquals(1, motivation.calls.size)
            fixture.time += 1000; motivation.answer = { motivationAnswer("pending-backfill") }; restarted.readMotivation()
            assertEquals(2, motivation.calls.size); assertNull((restarted.view.value.motivation as MotivationState.Ready).read.points)
        } finally { vault.clear(); db.close() }
    }
    @Test fun cancelledInvalidOrForbiddenMotivationReleasesBusyAndAllowsExplicitRetry() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val motivation = MotivationFixture().apply { hold = CompletableDeferred() }
        try {
            val controller = client(db, vault, fixture, api, motivation = motivation); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            val original = db.bootstrapDao().binding(controller.view.value.binding!!.lease.storageScope)
            val task = async { controller.readMotivation() }; withTimeout(10_000) { motivation.started.await() }
            task.cancelAndJoin(); assertFalse(controller.view.value.motivationBusy); assertTrue(controller.view.value.motivation is MotivationState.Failed)
            motivation.hold = null
            for (response in listOf(denied(403, "forbidden"), BootstrapHttpResult(200, "{}".toByteArray()))) {
                motivation.answer = { response }; controller.readMotivation()
                assertTrue(controller.view.value.motivation is MotivationState.Failed); assertFalse(controller.view.value.motivationBusy)
                assertEquals(original, db.bootstrapDao().binding(controller.view.value.binding!!.lease.storageScope))
            }
            fixture.time += 400_000; motivation.answer = { motivationAnswer() }; controller.readMotivation()
            assertEquals(2, fixture.calls); assertTrue(controller.view.value.motivation is MotivationState.Ready)
        } finally { motivation.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun roomContextChangeClearsDisplayedMotivationAndHeldOldRevisionCannotApply() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        var observer: Job? = null
        try {
            val controller = client(db, vault, fixture, api, motivation = motivation); controller.start(); login(controller, fixture, "fixture-A"); controller.bootstrap()
            controller.readMotivation(); observer = launch(start = CoroutineStart.UNDISPATCHED) { controller.observeMotivationContext() }
            val lease = controller.view.value.binding!!.lease; val old = db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(old.copy(contextRevision = old.contextRevision + 1))
            withTimeout(10_000) { controller.view.first { it.motivation == MotivationState.NotRequested } }
            motivation.hold = CompletableDeferred()
            val task = async { controller.readMotivation() }; withTimeout(10_000) { while (motivation.calls.size < 2) yield() }
            db.bootstrapDao().update(old.copy(contextRevision = old.contextRevision + 2))
            motivation.hold!!.complete(Unit); task.await()
            assertTrue(controller.view.value.motivation is MotivationState.Failed); assertFalse(controller.view.value.motivationBusy)
        } finally { observer?.cancelAndJoin(); motivation.hold?.complete(Unit); vault.clear(); db.close() }
    }
    private fun rankingProfileAnswer(ranking: Boolean = true, energy: Boolean = true, revision: Int = 1) = profileAnswer {
        it.getJSONObject("consents").put("ranking", ranking).put("automatic_energy_adjustment", energy).put("revision", revision)
    }
    private fun rankingMotivationAnswer(ranking: Boolean = true) = motivationAnswer {
        it.getJSONObject("ranking").put("requested", ranking).put("effective", false).put("pending_consent_refresh", ranking).put("consent_epoch", epoch)
    }
    private fun consentReceipt(request: RankingConsentAttempt) = BootstrapHttpResult(200,
        JSONObject().put("ranking", request.ranking).put("automatic_energy_adjustment", request.automaticEnergyAdjustment)
            .put("revision", request.baseRevision + 1).put("updated_at", "2026-10-12T12:00:00Z").toString().toByteArray(), etag = "\"${request.baseRevision + 1}\"")
    private inner class ConsentFixture(var answer: suspend (Int, RankingConsentAttempt) -> BootstrapHttpResult = { _, request -> consentReceipt(request) }) : RankingConsentGateway {
        val calls = mutableListOf<Pair<ApiSession, RankingConsentAttempt>>()
        val preparing = CompletableDeferred<Unit>()
        val started = CompletableDeferred<Unit>()
        var hold: CompletableDeferred<Unit>? = null
        var beforeHold: CompletableDeferred<Unit>? = null
        var durableCheck: (() -> Unit)? = null
        override suspend fun put(session: ApiSession, request: RankingConsentAttempt, beforeSend: suspend () -> Unit): BootstrapHttpResult {
            preparing.complete(Unit); beforeHold?.await(); beforeSend(); durableCheck?.invoke()
            calls.add(session to request); val index = calls.size
            started.complete(Unit); hold?.await()
            return answer(index, request)
        }
    }
    private fun consentSource(controller: SessionController) = (controller.view.value.rankingConsent as RankingConsentState.Ready).source

    @Test fun rankingConsentRequiresFreshReadsAndExplicitDecisionPreservingEnergyAndDiary() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway()
        val api = ApiFixture(); val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }; val writes = ConsentFixture()
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start()
            c.readRankingConsents(); c.confirmRankingConsent("stale", true); assertTrue(profiles.calls.isEmpty()); assertTrue(writes.calls.isEmpty())
            login(c, fixture, "fixture-A"); c.readRankingConsents(); assertTrue(profiles.calls.isEmpty()); c.bootstrap()
            val lease = c.view.value.binding!!.lease
            val repo = DiaryRepository(db, context, lease).apply { initialize() }; repo.setGoal(2400.0, 140.0, 70.0, 250.0)
            val queue = db.dao().operationCount(lease.storageScope); val goals = db.dao().goalsThrough(lease.storageScope, LocalDate.now().toString()).first()
            val binding = db.bootstrapDao().binding(lease.storageScope)
            c.readRankingConsents(); val source = consentSource(c)
            assertEquals(1, profiles.calls.size); assertEquals(1, motivation.calls.size); assertTrue(writes.calls.isEmpty()); assertFalse(vault.read().has("rankingConsentAttempt"))
            assertTrue(source.consents.automaticEnergyAdjustment); assertTrue(source.ranking.pendingConsentRefresh)
            writes.durableCheck = { assertTrue(vault.read().has("rankingConsentAttempt")) }
            c.confirmRankingConsent(source.id, true)
            val sent = writes.calls.single().second
            assertTrue(sent.ranking); assertTrue(sent.automaticEnergyAdjustment); assertEquals(epoch, sent.consentEpoch); assertNotEquals(source.id, sent.key)
            assertTrue(c.view.value.rankingConsent is RankingConsentState.Confirmed); assertFalse(vault.read().has("rankingConsentAttempt"))
            assertEquals(MotivationState.NotRequested, c.view.value.motivation); assertNull(c.view.value.serverProfile)
            assertEquals(queue, db.dao().operationCount(lease.storageScope)); assertEquals(goals, db.dao().goalsThrough(lease.storageScope, LocalDate.now().toString()).first())
            assertEquals(binding, db.bootstrapDao().binding(lease.storageScope))
        } finally { vault.clear(); db.close() }
    }
    @Test fun lostConsentAckRestartsWithoutSendingAndRetryKeepsExactKeyThenOptOutGetsNewKey() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }
        val writes = ConsentFixture { index, request -> if (index == 1) error("fixture lost ACK") else consentReceipt(request) }
        try {
            val first = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); first.start(); login(first, fixture, "fixture-A"); first.bootstrap()
            first.readRankingConsents(); first.confirmRankingConsent(consentSource(first).id, true)
            assertEquals(RankingConsentState.Pending(true), first.view.value.rankingConsent)
            val exact = writes.calls.single().second.journal().toString()
            val restarted = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); restarted.start()
            assertEquals(1, writes.calls.size); assertEquals(RankingConsentState.Pending(true), restarted.view.value.rankingConsent)
            restarted.confirmRankingConsent("stale", false); restarted.readRankingConsents(); assertEquals(1, writes.calls.size); assertEquals(1, profiles.calls.size)
            restarted.retryRankingConsent(); assertEquals(exact, writes.calls[1].second.journal().toString()); assertTrue(restarted.view.value.rankingConsent is RankingConsentState.Confirmed)
            profiles.answer = { rankingProfileAnswer(energy = false, revision = 2) }
            restarted.readRankingConsents(); restarted.confirmRankingConsent(consentSource(restarted).id, false)
            val optOut = writes.calls[2].second
            assertNotEquals(writes.calls[0].second.key, optOut.key); assertFalse(optOut.ranking); assertFalse(optOut.automaticEnergyAdjustment); assertNull(optOut.consentEpoch); assertEquals(2, optOut.baseRevision)
        } finally { vault.clear(); db.close() }
    }
    @Test fun consentConflictRequiresNewReadAndDecisionAndNeverReplaysDifferentEnergy() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }
        val writes = ConsentFixture { index, request -> if (index == 1) denied(409, "version_conflict") else consentReceipt(request) }
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readRankingConsents(); val original = consentSource(c); c.confirmRankingConsent(original.id, true)
            assertTrue(c.view.value.rankingConsent is RankingConsentState.Failed); assertFalse(vault.read().has("rankingConsentAttempt"))
            c.retryRankingConsent(); c.confirmRankingConsent(original.id, true); assertEquals(1, writes.calls.size)
            profiles.answer = { rankingProfileAnswer(energy = false, revision = 2) }; c.readRankingConsents(); val fresh = consentSource(c)
            assertNotEquals(original.id, fresh.id); assertFalse(fresh.consents.automaticEnergyAdjustment)
            c.confirmRankingConsent(fresh.id, true)
            assertEquals(2, writes.calls.size); assertNotEquals(writes.calls[0].second.key, writes.calls[1].second.key)
            assertEquals(2, writes.calls[1].second.baseRevision); assertFalse(writes.calls[1].second.automaticEnergyAdjustment)
        } finally { vault.clear(); db.close() }
    }
    @Test fun consentRetryAfterSurvivesRestartAndBlocksOtherApiWithoutLosingDecision() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }
        val writes = ConsentFixture { index, request -> if (index == 1) denied(503, "service_unavailable", "60") else consentReceipt(request) }
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readRankingConsents(); c.confirmRankingConsent(consentSource(c).id, true)
            val restarted = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); restarted.start()
            restarted.retryRankingConsent(); restarted.readProfile(); restarted.bootstrap(); restarted.readRankingConsents()
            assertEquals(1, writes.calls.size); assertEquals(1, api.calls.size); assertEquals(1, profiles.calls.size)
            fixture.time += 59_000; restarted.retryRankingConsent(); assertEquals(1, writes.calls.size)
            fixture.time += 1000; restarted.retryRankingConsent(); assertEquals(2, writes.calls.size)
            assertEquals(writes.calls[0].second.journal().toString(), writes.calls[1].second.journal().toString()); assertTrue(restarted.view.value.rankingConsent is RankingConsentState.Confirmed)
        } finally { vault.clear(); db.close() }
    }
    @Test fun consent401RenewsOnceAndUsesSameIntentWithNewToken() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }
        val writes = ConsentFixture { index, request -> if (index == 1) denied(401, "unauthorized") else consentReceipt(request) }
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readRankingConsents(); c.confirmRankingConsent(consentSource(c).id, true)
            assertEquals(2, fixture.calls); assertEquals(2, writes.calls.size)
            assertNotEquals(writes.calls[0].first.accessToken, writes.calls[1].first.accessToken)
            assertEquals(writes.calls[0].second.journal().toString(), writes.calls[1].second.journal().toString())
            assertTrue(c.view.value.rankingConsent is RankingConsentState.Confirmed)
        } finally { vault.clear(); db.close() }
    }
    @Test fun consentDoubleTapAndLateAckCannotLeakAfterLogoutAToBToA() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }; val writes = ConsentFixture().apply { hold = CompletableDeferred() }
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            val original = c.view.value.binding!!.lease; c.readRankingConsents(); val source = consentSource(c)
            val held = async { c.confirmRankingConsent(source.id, true) }; withTimeout(10_000) { writes.started.await() }
            c.confirmRankingConsent(source.id, false); c.retryRankingConsent(); c.readRankingConsents(); c.readProfile(); c.bootstrap()
            assertEquals(1, writes.calls.size); assertEquals(1, profiles.calls.size)
            c.logout(); login(c, fixture, "fixture-B"); c.logout(); login(c, fixture, "fixture-A")
            assertNotEquals(original, c.view.value.binding!!.lease); writes.hold!!.complete(Unit); held.await()
            assertEquals(RankingConsentState.NotRequested, c.view.value.rankingConsent); assertFalse(vault.read().has("rankingConsentAttempt"))
        } finally { writes.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun cancelledConsentCanResumeButManualRefreshDiscardsItsLateAck() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }; val writes = ConsentFixture().apply { hold = CompletableDeferred() }
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readRankingConsents(); val held = async { c.confirmRankingConsent(consentSource(c).id, true) }; withTimeout(10_000) { writes.started.await() }
            held.cancelAndJoin(); assertEquals(RankingConsentState.Pending(true), c.view.value.rankingConsent)
            val old = async { c.retryRankingConsent() }; withTimeout(10_000) { while (writes.calls.size < 2) yield() }
            val oldHold = writes.hold!!; c.refresh(); writes.hold = null; c.retryRankingConsent()
            val fresh = c.view.value.rankingConsent; assertTrue(fresh is RankingConsentState.Confirmed)
            oldHold.complete(Unit); old.await(); assertSame(fresh, c.view.value.rankingConsent)
            assertEquals(3, writes.calls.size); assertTrue(writes.calls.map { it.second.key }.distinct().size == 1)
        } finally { writes.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun changedConsentContextBeforeSendCannotWriteOrPublishOldIntent() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }; val writes = ConsentFixture().apply { beforeHold = CompletableDeferred() }
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readRankingConsents(); val source = consentSource(c); val owner = c.view.value.binding!!.lease.storageScope
            val task = async { c.confirmRankingConsent(source.id, true) }; withTimeout(10_000) { writes.preparing.await() }
            val old = db.bootstrapDao().binding(owner)!!; db.bootstrapDao().update(old.copy(syncEpoch = newEpoch, contextRevision = old.contextRevision + 1, requiresRecovery = true))
            writes.beforeHold!!.complete(Unit); task.await()
            assertTrue(writes.calls.isEmpty()); assertTrue(c.view.value.requiresRecovery); assertEquals(RankingConsentState.NotRequested, c.view.value.rankingConsent)
        } finally { writes.beforeHold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun staleConsentProposalNonceAgeAndGenerationRequireFreshReadWithoutPut() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }; val writes = ConsentFixture()
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readRankingConsents(); val expired = consentSource(c); fixture.time += 300_001; c.confirmRankingConsent(expired.id, true); assertTrue(writes.calls.isEmpty())
            c.readRankingConsents(); val fresh = consentSource(c); assertNotEquals(expired.id, fresh.id)
            c.confirmRankingConsent(expired.id, true); assertTrue(writes.calls.isEmpty()); assertFalse(vault.read().has("rankingConsentAttempt"))
            c.readRankingConsents(); val next = consentSource(c); val owner = c.view.value.binding!!.lease.storageScope
            val binding = db.bootstrapDao().binding(owner)!!; db.bootstrapDao().update(binding.copy(accountGeneration = binding.accountGeneration + 1))
            c.confirmRankingConsent(next.id, true); assertTrue(writes.calls.isEmpty()); assertFalse(vault.read().has("rankingConsentAttempt"))
        } finally { vault.clear(); db.close() }
    }
    @Test fun inconsistentConsentPreflightAndLateSourceCannotCreateApproval() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer(ranking = false) }; val motivation = MotivationFixture { rankingMotivationAnswer() }; val writes = ConsentFixture()
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readRankingConsents(); assertTrue(c.view.value.rankingConsent is RankingConsentState.Failed); assertTrue(writes.calls.isEmpty())
            profiles.answer = { rankingProfileAnswer() }; profiles.hold = CompletableDeferred()
            val read = async { c.readRankingConsents() }; withTimeout(10_000) { while (profiles.calls.size < 2) yield() }
            c.logout(); login(c, fixture, "fixture-A"); profiles.hold!!.complete(Unit); read.await()
            assertEquals(RankingConsentState.NotRequested, c.view.value.rankingConsent); assertEquals(1, motivation.calls.size); assertTrue(writes.calls.isEmpty())
        } finally { profiles.hold?.complete(Unit); vault.clear(); db.close() }
    }
    @Test fun invalidReceiptOrMissingEtagKeepsExactPendingIntentForSafeRetry() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }
        val writes = ConsentFixture { _, req -> BootstrapHttpResult(200, consentReceipt(req).body) }
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readRankingConsents(); c.confirmRankingConsent(consentSource(c).id, true); assertEquals(RankingConsentState.Pending(true), c.view.value.rankingConsent)
            writes.answer = { _, req -> BootstrapHttpResult(200, JSONObject(String(consentReceipt(req).body)).put("automatic_energy_adjustment", false).toString().toByteArray(), etag = "\"2\"") }
            c.retryRankingConsent(); assertEquals(RankingConsentState.Pending(true), c.view.value.rankingConsent)
            writes.answer = { _, req -> consentReceipt(req) }; c.retryRankingConsent(); assertTrue(c.view.value.rankingConsent is RankingConsentState.Confirmed)
            assertEquals(1, writes.calls.map { it.second.key }.distinct().size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun failedAtomicConsentPersistencePreventsAnyNetworkMutationAndKeepsDiary() = runBlocking<Unit> {
        val db = memory(); val vaultName = name(); val vault = SessionVault(context, vaultName); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }; val writes = ConsentFixture()
        val base = File(context.noBackupFilesDir, vaultName); val sentinel = File(base, "fixture-blocked-rename")
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap(); c.readRankingConsents()
            val source = consentSource(c); val owner = c.view.value.binding!!.lease.storageScope; val queue = db.dao().operationCount(owner)
            assertTrue(base.delete()); assertTrue(base.mkdir()); sentinel.writeText("synthetic fixture only")
            c.confirmRankingConsent(source.id, true); assertTrue(writes.calls.isEmpty()); assertEquals(queue, db.dao().operationCount(owner))
            c.retryRankingConsent(); assertTrue(writes.calls.isEmpty())
        } finally { sentinel.delete(); base.delete(); vault.clear(); db.close() }
    }

    @Test fun privateRoomObserverClearsCachedProfileAndConsentAcrossContextAndOwnerChanges() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = ProfileFixture { rankingProfileAnswer() }; val motivation = MotivationFixture { rankingMotivationAnswer() }; val writes = ConsentFixture()
        var observer: Job? = null
        try {
            val c = client(db, vault, fixture, api, profiles, motivation = motivation, consents = writes); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readProfile(); assertNotNull(c.view.value.serverProfile)
            observer = launch(start = CoroutineStart.UNDISPATCHED) { c.observeMotivationContext() }
            val owner = c.view.value.binding!!.lease.storageScope; val old = db.bootstrapDao().binding(owner)!!
            db.bootstrapDao().update(old.copy(contextRevision = old.contextRevision + 1))
            withTimeout(10_000) { while (c.view.value.serverProfile != null) yield() }
            c.readRankingConsents(); assertTrue(c.view.value.rankingConsent is RankingConsentState.Ready)
            val current = db.bootstrapDao().binding(owner)!!; db.bootstrapDao().update(current.copy(accountGeneration = current.accountGeneration + 1))
            withTimeout(10_000) { while (c.view.value.rankingConsent !is RankingConsentState.NotRequested) yield() }
            c.readProfile(); assertNotNull(c.view.value.serverProfile)
            val other = LocalOwnerStore(db).registerIdentity(issuer, "fixture-B"); LocalOwnerStore(db).select(other.id)
            withTimeout(10_000) { while (c.view.value.binding?.owner?.subject != "fixture-B") yield() }
            assertNull(c.view.value.serverProfile); assertEquals(RankingConsentState.NotRequested, c.view.value.rankingConsent); assertTrue(writes.calls.isEmpty())
        } finally { observer?.cancelAndJoin(); vault.clear(); db.close() }
    }

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
    private val rankingToken = "rk1." + "A".repeat(43)
    private fun rankingAnswer(time: Long, more: Boolean = false): BootstrapHttpResult {
        val now = java.time.Instant.ofEpochMilli(time)
        val rows = JSONArray((0 until if (more) 25 else 3).map { index -> JSONObject().put("position", if (index < 2 || more) 1 else 3)
            .put("pseudonym", "Ranking-fixture").put("points", if (index < 2 || more) 10 else 8).put("rank", "Rekrut").put("active_badges", 2) })
        return BootstrapHttpResult(200, JSONObject().put("rule_version", "regularity_v1").put("pagination", "live_keyset_v1")
            .put("as_of", now.toString()).put("items", rows).put("has_more", more).put("next_page_token", if (more) rankingToken else JSONObject.NULL)
            .put("cursor_expires_at", if (more) now.plusSeconds(600).toString() else JSONObject.NULL).toString().toByteArray())
    }
    private class RankingFixture(var answer: (Int, RankingQuery) -> BootstrapHttpResult) : RankingGateway {
        val calls = mutableListOf<Pair<ApiSession, RankingQuery>>()
        var hold: CompletableDeferred<Unit>? = null
        var before: suspend () -> Unit = {}
        val started = CompletableDeferred<Unit>()
        override suspend fun get(session: ApiSession, query: RankingQuery, beforeSend: suspend () -> Unit): BootstrapHttpResult {
            before(); beforeSend(); calls.add(session to query); started.complete(Unit); hold?.await()
            return answer(calls.size, query)
        }
    }
    @Test fun rankingIsExplicitPreservesDuplicatesAndNeverPersistsPeersOrCursors() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        val ranking = RankingFixture { _, q -> rankingAnswer(fixture.time, q.pageToken == null) }
        try {
            val c = client(db, vault, fixture, api, motivation = motivation, ranking = ranking); c.start(); c.readRanking(); assertTrue(ranking.calls.isEmpty())
            login(c, fixture, "fixture-A"); c.readRanking(); assertTrue(ranking.calls.isEmpty()); c.bootstrap()
            val lease = c.view.value.binding!!.lease; val queue = db.dao().operationCount(lease.storageScope); val binding = db.bootstrapDao().binding(lease.storageScope)
            c.readRanking(); val first = (c.view.value.ranking as RankingState.Ready).page
            assertEquals(25, first.items.size); assertEquals(1, motivation.calls.size); assertEquals(1, ranking.calls.size)
            c.nextRankingPage(); val next = (c.view.value.ranking as RankingState.Ready).page
            assertEquals(listOf(1L, 1L, 3L), next.items.map { it.position }); assertEquals(3, next.items.size)
            assertEquals(rankingToken, ranking.calls.last().second.pageToken); assertEquals(2, motivation.calls.size)
            assertEquals(binding, db.bootstrapDao().binding(lease.storageScope)); assertEquals(queue, db.dao().operationCount(lease.storageScope))
            assertFalse(vault.read().toString().contains("Ranking-fixture")); assertFalse(vault.read().toString().contains(rankingToken))
            val restarted = client(db, vault, fixture, api, motivation = motivation, ranking = ranking); restarted.start()
            assertEquals(RankingState.NotRequested, restarted.view.value.ranking); assertEquals(2, ranking.calls.size)
            c.clearRankingPreview(); c.nextRankingPage(); c.retryRankingPage(); assertEquals(2, ranking.calls.size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun lostRankingPageResponseRetriesSameInputWhileGoneCursorRequiresRestart() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        val ranking = RankingFixture { call, q -> if (call == 2) throw java.io.IOException("fixture loss") else rankingAnswer(fixture.time, q.pageToken == null) }
        try {
            val c = client(db, vault, fixture, api, motivation = motivation, ranking = ranking); c.start(); login(c, fixture, "fixture-A"); c.bootstrap(); c.readRanking()
            c.nextRankingPage(); assertTrue((c.view.value.ranking as RankingState.Failed).canRetry)
            val lost = ranking.calls.last().second; c.retryRankingPage(); assertEquals(lost.encoded(), ranking.calls.last().second.encoded())
            assertEquals(3, (c.view.value.ranking as RankingState.Ready).page.items.size)
            ranking.answer = { _, q -> if (q.pageToken == null) rankingAnswer(fixture.time, true) else denied(410, "ranking_cursor_restart_required") }
            c.readRanking(); c.nextRankingPage(); assertFalse((c.view.value.ranking as RankingState.Failed).canRetry)
            val count = ranking.calls.size; c.retryRankingPage(); c.nextRankingPage(); assertEquals(count, ranking.calls.size)
            c.readRanking(); fixture.time += 600_001; c.nextRankingPage()
            assertFalse((c.view.value.ranking as RankingState.Failed).canRetry); assertEquals(count + 1, ranking.calls.size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun rankingRetryAfterIsSharedDurableAndRestartNeverFetchesAutomatically() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        val ranking = RankingFixture { _, _ -> BootstrapHttpResult(429, byteArrayOf(), "120") }
        try {
            val c = client(db, vault, fixture, api, motivation = motivation, ranking = ranking); c.start(); login(c, fixture, "fixture-A"); c.bootstrap(); c.readRanking()
            assertTrue((c.view.value.ranking as RankingState.Failed).canRetry); val m = motivation.calls.size
            c.retryRankingPage(); c.readMotivation(); assertEquals(1, ranking.calls.size); assertEquals(m, motivation.calls.size)
            val restarted = client(db, vault, fixture, api, motivation = motivation, ranking = ranking); restarted.start(); restarted.readRanking()
            assertEquals(1, ranking.calls.size); assertEquals(m, motivation.calls.size)
            fixture.time += 121_000; ranking.answer = { _, _ -> rankingAnswer(fixture.time) }; restarted.readRanking()
            assertTrue(restarted.view.value.ranking is RankingState.Ready); assertEquals(2, ranking.calls.size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun rankingUnauthorizedRenewsOnceWithoutChangingContinuationQuery() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        val ranking = RankingFixture { call, q -> if (call == 2) denied(401, "unauthorized") else rankingAnswer(fixture.time, q.pageToken == null) }
        try {
            val c = client(db, vault, fixture, api, motivation = motivation, ranking = ranking); c.start(); login(c, fixture, "fixture-A"); c.bootstrap(); c.readRanking(); c.nextRankingPage()
            assertTrue(c.view.value.ranking is RankingState.Ready); assertEquals(3, ranking.calls.size); assertEquals(2, fixture.calls)
            assertEquals(ranking.calls[1].second.encoded(), ranking.calls[2].second.encoded())
            assertNotEquals(ranking.calls[1].first.accessToken, ranking.calls[2].first.accessToken)
            assertEquals(2, motivation.calls.size); assertFalse(c.view.value.rankingBusy)
        } finally { vault.clear(); db.close() }
    }
    @Test fun rankingPreflightAndPhysicalSendRejectChangedEpochOrBindingBeforeDisclosure() = runBlocking<Unit> {
        for (mode in listOf("preflight", "before-send")) {
            val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
            val motivation = if (mode == "preflight") MotivationFixture { motivationAnswer { it.put("sync_epoch", newEpoch) } } else MotivationFixture()
            val ranking = RankingFixture { _, _ -> rankingAnswer(fixture.time) }
            try {
                val c = client(db, vault, fixture, api, motivation = motivation, ranking = ranking); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
                if (mode == "before-send") ranking.before = {
                    val lease = c.view.value.binding!!.lease; val old = db.bootstrapDao().binding(lease.storageScope)!!
                    db.bootstrapDao().update(old.copy(contextRevision = old.contextRevision + 1))
                }
                c.readRanking(); assertTrue(ranking.calls.isEmpty()); assertFalse(c.view.value.ranking is RankingState.Ready)
                if (mode == "preflight") assertTrue(c.view.value.requiresRecovery)
            } finally { vault.clear(); db.close() }
        }
    }
    @Test fun heldRankingAndObserverCannotLeakAfterCloseLogoutOrGenerationChange() = runBlocking<Unit> {
        for (mode in listOf("close", "logout", "generation")) {
            val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
            val ranking = RankingFixture { _, _ -> rankingAnswer(fixture.time) }.apply { hold = CompletableDeferred() }
            var watch: Job? = null
            try {
                val c = client(db, vault, fixture, api, motivation = motivation, ranking = ranking); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
                val read = async { c.readRanking() }; withTimeout(10_000) { ranking.started.await() }
                c.readRanking(); assertEquals(1, ranking.calls.size)
                when (mode) {
                    "close" -> c.clearRankingPreview()
                    "logout" -> { c.logout(); login(c, fixture, "fixture-B"); c.logout(); login(c, fixture, "fixture-A") }
                    else -> {
                        watch = launch { c.observeMotivationContext() }
                        val lease = c.view.value.binding!!.lease; val old = db.bootstrapDao().binding(lease.storageScope)!!
                        db.bootstrapDao().update(old.copy(accountGeneration = old.accountGeneration + 1))
                        withTimeout(10_000) { while (c.view.value.rankingBusy) delay(10) }
                    }
                }
                ranking.hold!!.complete(Unit); read.await(); assertEquals(RankingState.NotRequested, c.view.value.ranking); assertFalse(c.view.value.rankingBusy)
            } finally { ranking.hold?.complete(Unit); watch?.cancelAndJoin(); vault.clear(); db.close() }
        }
    }

    private val nemesisId = "12345678-1234-5678-9234-123456789abc"
    private fun nemesisJson(name: String) = JSONObject(androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context.assets
        .open("nemesis/$name.json").bufferedReader().use { it.readText() })
    private fun nemesisAnswer(query: NemesisQuery): BootstrapHttpResult = BootstrapHttpResult(200, when (query) {
        is NemesisQuery.Listing -> JSONObject().put("items", JSONArray(listOf(nemesisJson("metadata")))).put("next_cursor", JSONObject.NULL)
        is NemesisQuery.Detail -> nemesisJson("metadata")
        is NemesisQuery.Statistics -> nemesisJson("provisional")
    }.toString().toByteArray())
    private inner class NemesisFixture(var answer: (NemesisQuery) -> BootstrapHttpResult = ::nemesisAnswer) : NemesisGateway {
        val calls = mutableListOf<Triple<ApiSession, String, NemesisQuery>>()
        var hold: CompletableDeferred<Unit>? = null
        var before: suspend () -> Unit = {}
        val started = CompletableDeferred<Unit>()
        override suspend fun get(session: ApiSession, epoch: String, query: NemesisQuery, beforeSend: suspend () -> Unit): BootstrapHttpResult {
            before(); beforeSend(); calls.add(Triple(session, epoch, query))
            if (query is NemesisQuery.Statistics && hold != null) { started.complete(Unit); hold!!.await() }
            return answer(query)
        }
    }
    @Test fun nemesisReadsRequireBootstrapPreserveDiaryAndNeverPersistPartnerOrSnapshots() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val motivation = MotivationFixture(); val nemesis = NemesisFixture()
        try {
            val c = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); c.start(); c.readNemesis(); assertTrue(nemesis.calls.isEmpty())
            login(c, fixture, "fixture-A"); c.readNemesis(); assertTrue(nemesis.calls.isEmpty()); c.bootstrap(); assertTrue(nemesis.calls.isEmpty())
            val lease = c.view.value.binding!!.lease; val day = LocalDate.now()
            val repo = DiaryRepository(db, context, lease).apply { initialize() }
            repo.setGoal(2400.0, 140.0, 70.0, 250.0); repo.add("basic-banana", 100.0, MealType.LUNCH, day, "nemesis-preserved")
            val profile = db.dao().currentProfile(lease.storageScope); val goals = db.dao().goalsThrough(lease.storageScope, day.toString()).first()
            val meals = db.dao().day(lease.storageScope, day.toString()).first(); val queue = db.dao().operationCount(lease.storageScope)
            val server = db.bootstrapDao().binding(lease.storageScope)
            c.readNemesis(); assertEquals(1, (c.view.value.nemesis as NemesisState.ListReady).page.items.size)
            c.readNemesisChallenge(nemesisId); val detail = c.view.value.nemesis as NemesisState.DetailReady
            assertEquals("provisional", detail.statistics!!.status); assertEquals(java.math.BigDecimal("-15"), (detail.statistics!!.self!!.deficit as NemesisMetric.Available).value)
            assertEquals(listOf("/me/nemesis?limit=25", "/nemesis/$nemesisId", "/nemesis/$nemesisId/statistics"), nemesis.calls.map { it.third.path() })
            assertTrue(nemesis.calls.all { it.second == epoch }); assertEquals(2, motivation.calls.size)
            assertEquals(profile, db.dao().currentProfile(lease.storageScope)); assertEquals(goals, db.dao().goalsThrough(lease.storageScope, day.toString()).first())
            assertEquals(meals, db.dao().day(lease.storageScope, day.toString()).first()); assertEquals(queue, db.dao().operationCount(lease.storageScope)); assertEquals(server, db.bootstrapDao().binding(lease.storageScope))
            assertFalse(vault.read().toString().contains("Nemesis fixture")); assertFalse(vault.read().toString().contains(nemesisId))
            val restarted = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); restarted.start()
            assertEquals(NemesisState.NotRequested, restarted.view.value.nemesis); assertEquals(3, nemesis.calls.size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun lostNemesisStatisticsAreRevalidatedWhile404AndCancelledMetadataRemovePartner() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        var lost = true; val nemesis = NemesisFixture { query -> if (query is NemesisQuery.Statistics && lost) { lost = false; throw java.io.IOException("fixture loss") } else nemesisAnswer(query) }
        try {
            val c = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            c.readNemesisChallenge(nemesisId); assertTrue((c.view.value.nemesis as NemesisState.Failed).canRetry)
            c.retryNemesis(); assertTrue(c.view.value.nemesis is NemesisState.DetailReady); assertEquals(4, nemesis.calls.size)
            assertEquals(nemesis.calls[0].third.path(), nemesis.calls[2].third.path()); assertEquals(nemesis.calls[1].third.path(), nemesis.calls[3].third.path())
            nemesis.answer = { q -> if (q is NemesisQuery.Statistics) denied(404, "nemesis_not_found") else nemesisAnswer(q) }
            c.readNemesisChallenge(nemesisId); assertFalse((c.view.value.nemesis as NemesisState.Failed).canRetry)
            val count = nemesis.calls.size; c.retryNemesis(); assertEquals(count, nemesis.calls.size)
            nemesis.answer = { q -> if (q is NemesisQuery.Detail) BootstrapHttpResult(200, nemesisJson("metadata").put("status", "cancelled").put("cancel_reason", "sharing_revoked").toString().toByteArray()) else error("Cancelled challenge must not read statistics") }
            c.readNemesisChallenge(nemesisId); val cancelled = c.view.value.nemesis as NemesisState.DetailReady
            assertNull(cancelled.challenge.partner); assertNull(cancelled.statistics); assertEquals(count + 1, nemesis.calls.size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun nemesisRetryAfterIsSharedDurableAndNeverFetchesOnRestart() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        val nemesis = NemesisFixture { BootstrapHttpResult(503, byteArrayOf(), "120") }
        try {
            val c = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); c.start(); login(c, fixture, "fixture-A"); c.bootstrap(); c.readNemesis()
            assertTrue((c.view.value.nemesis as NemesisState.Failed).canRetry); c.retryNemesis(); c.readMotivation()
            assertEquals(1, nemesis.calls.size); assertEquals(1, motivation.calls.size)
            val restarted = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); restarted.start(); restarted.readNemesis()
            assertEquals(1, nemesis.calls.size); assertEquals(1, motivation.calls.size)
            fixture.time += 121_000; nemesis.answer = ::nemesisAnswer; restarted.readNemesis()
            assertTrue(restarted.view.value.nemesis is NemesisState.ListReady); assertEquals(2, nemesis.calls.size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun heldNemesisStatisticsCannotReturnAfterCloseLogoutGenerationOrEpochChanges() = runBlocking<Unit> {
        for (mode in listOf("close", "logout", "generation", "epoch")) {
            val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
            val nemesis = NemesisFixture().apply { hold = CompletableDeferred() }; var watch: Job? = null
            try {
                val c = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
                val read = async { c.readNemesisChallenge(nemesisId) }; withTimeout(10_000) { nemesis.started.await() }
                c.readNemesis(); assertEquals(2, nemesis.calls.size)
                when (mode) {
                    "close" -> c.clearNemesisPreview()
                    "logout" -> { c.logout(); login(c, fixture, "fixture-B"); c.logout(); login(c, fixture, "fixture-A") }
                    else -> {
                        watch = launch { c.observeMotivationContext() }
                        val lease = c.view.value.binding!!.lease; val old = db.bootstrapDao().binding(lease.storageScope)!!
                        db.bootstrapDao().update(if (mode == "generation") old.copy(accountGeneration = old.accountGeneration + 1) else old.copy(syncEpoch = newEpoch))
                        withTimeout(10_000) { while (c.view.value.nemesisBusy) delay(10) }
                    }
                }
                nemesis.hold!!.complete(Unit); read.await(); assertEquals(NemesisState.NotRequested, c.view.value.nemesis); assertFalse(c.view.value.nemesisBusy)
            } finally { nemesis.hold?.complete(Unit); watch?.cancelAndJoin(); vault.clear(); db.close() }
        }
    }
    @Test fun nemesisPreflightAndPhysicalSendRejectChangedContextBeforeDisclosure() = runBlocking<Unit> {
        for (mode in listOf("preflight", "before-send")) {
            val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
            val motivation = if (mode == "preflight") MotivationFixture { motivationAnswer { it.put("sync_epoch", newEpoch) } } else MotivationFixture()
            val nemesis = NemesisFixture()
            try {
                val c = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
                if (mode == "before-send") nemesis.before = {
                    val lease = c.view.value.binding!!.lease; val old = db.bootstrapDao().binding(lease.storageScope)!!
                    db.bootstrapDao().update(old.copy(contextRevision = old.contextRevision + 1))
                }
                c.readNemesis(); assertTrue(nemesis.calls.isEmpty()); assertFalse(c.view.value.nemesis is NemesisState.ListReady)
                if (mode == "preflight") assertTrue(c.view.value.requiresRecovery)
            } finally { vault.clear(); db.close() }
        }
    }
    @Test fun nemesis401RefreshesOnceAcrossMetadataAndStatistics() = runBlocking<Unit> {
        for (twice in listOf(false, true)) {
            val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
            var attempts = 0
            val nemesis = NemesisFixture { query -> attempts++; if (attempts == 1 || (twice && query is NemesisQuery.Statistics)) denied(401, "unauthorized") else nemesisAnswer(query) }
            try {
                val c = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
                c.readNemesisChallenge(nemesisId)
                assertEquals(2, fixture.calls); assertEquals(3, nemesis.calls.size); assertEquals(1, motivation.calls.size)
                assertEquals(nemesis.calls[0].third.path(), nemesis.calls[1].third.path()); assertNotEquals(nemesis.calls[0].first.accessToken, nemesis.calls[1].first.accessToken)
                if (twice) assertTrue(c.view.value.nemesis is NemesisState.Failed) else assertTrue(c.view.value.nemesis is NemesisState.DetailReady)
                assertFalse(c.view.value.nemesisBusy)
            } finally { vault.clear(); db.close() }
        }
    }
    @Test fun nemesisContinuationRetriesSameCursorAnd409RequiresAFreshList() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
        val cursor = "32345678-1234-5678-9234-123456789abc"; var lost = true
        val nemesis = NemesisFixture { query ->
            check(query is NemesisQuery.Listing)
            if (query.cursor != null && lost) { lost = false; throw java.io.IOException("fixture loss") }
            val rows = if (query.cursor == null) JSONArray((0 until 25).map { nemesisJson("metadata").put("id", UUID(0, it.toLong()).toString()) }) else JSONArray(listOf(nemesisJson("metadata")))
            BootstrapHttpResult(200, JSONObject().put("items", rows).put("next_cursor", if (query.cursor == null) cursor else JSONObject.NULL).toString().toByteArray())
        }
        try {
            val c = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); c.start(); login(c, fixture, "fixture-A"); c.bootstrap(); c.readNemesis()
            c.nextNemesisPage(); assertTrue((c.view.value.nemesis as NemesisState.Failed).canRetry); c.retryNemesis()
            assertEquals(cursor, (nemesis.calls[1].third as NemesisQuery.Listing).cursor); assertEquals(cursor, (nemesis.calls[2].third as NemesisQuery.Listing).cursor)
            assertEquals(1, (c.view.value.nemesis as NemesisState.ListReady).page.items.size)
            assertFalse(vault.read().toString().contains(cursor))
            nemesis.answer = { denied(409, "nemesis_cursor_unavailable") }; c.readNemesis()
            assertFalse((c.view.value.nemesis as NemesisState.Failed).canRetry); val count = nemesis.calls.size
            c.retryNemesis(); c.nextNemesisPage(); assertEquals(count, nemesis.calls.size)
        } finally { vault.clear(); db.close() }
    }
    @Test fun nemesisRejectsOlderReadRevisionOrAsOfWithinTheSameVisibleChallenge() = runBlocking<Unit> {
        for (older in listOf("revision", "clock")) {
            val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture(); val motivation = MotivationFixture()
            val nemesis = NemesisFixture()
            try {
                val c = client(db, vault, fixture, api, motivation = motivation, nemesis = nemesis); c.start(); login(c, fixture, "fixture-A"); c.bootstrap(); c.readNemesisChallenge(nemesisId)
                assertTrue(c.view.value.nemesis is NemesisState.DetailReady)
                nemesis.answer = { q -> if (q is NemesisQuery.Statistics) BootstrapHttpResult(200, nemesisJson("provisional")
                    .also { if (older == "revision") it.put("revision", 7) else it.put("as_of", "2026-10-19T00:00:00Z") }.toString().toByteArray()) else nemesisAnswer(q) }
                c.readNemesisChallenge(nemesisId); assertTrue((c.view.value.nemesis as NemesisState.Failed).canRetry)
                nemesis.answer = { q -> if (q is NemesisQuery.Statistics) BootstrapHttpResult(200, nemesisJson("provisional").put("revision", 9).toString().toByteArray()) else nemesisAnswer(q) }
                c.retryNemesis(); assertEquals(9L, (c.view.value.nemesis as NemesisState.DetailReady).statistics!!.revision)
                assertFalse(vault.read().toString().contains(nemesisId))
            } finally { vault.clear(); db.close() }
        }
    }
    private fun nemesisInvite()=nemesisJson("metadata").put("status","invited").also { value ->
        listOf("accepted_at","start_date","end_date","start_at","end_at","deadline","result_status").forEach { value.put(it,JSONObject.NULL) }
    }
    private fun nemesisWriteAnswer(request:NemesisAttempt,time:Long):BootstrapHttpResult {
        val command=request.command
        val json=when(command.action) {
            NemesisAction.ISSUE -> JSONObject().put("destination_code","A".repeat(43)).put("issued_at",java.time.Instant.ofEpochMilli(time).toString())
                .put("expires_at",java.time.Instant.ofEpochMilli(time).plusSeconds(86400).toString())
            NemesisAction.REVOKE -> JSONObject().put("revoked",true)
            NemesisAction.CREATE -> nemesisInvite().put("role","inviter")
            NemesisAction.ACCEPT -> nemesisJson("metadata").put("revision",command.baseRevision!!+1)
            NemesisAction.CANCEL -> nemesisJson("metadata").put("revision",command.baseRevision!!+1).put("status","cancelled")
                .put("cancel_reason",JSONObject(String(command.body()!!)).getString("reason"))
        }
        return BootstrapHttpResult(command.successStatus,json.toString().toByteArray())
    }
    private inner class NemesisWrites(var answer:(NemesisAttempt)->BootstrapHttpResult):NemesisWriteGateway {
        val calls=mutableListOf<Pair<ApiSession,NemesisAttempt>>();val started=CompletableDeferred<Unit>()
        var hold:CompletableDeferred<Unit>?=null;var before:suspend ()->Unit={}
        override suspend fun send(session:ApiSession,request:NemesisAttempt,beforeSend:suspend ()->Unit):BootstrapHttpResult {
            before();beforeSend();calls.add(session to request);started.complete(Unit);hold?.await();return answer(request)
        }
    }
    @Test fun nemesisMutationIsDurableBeforeSendAndLostAckUsesSameKeyAfterRestart()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();val api=ApiFixture();val motivation=MotivationFixture()
        var lost=true;val writes=NemesisWrites { request -> if(lost) { lost=false;throw java.io.IOException("fixture loss") } else nemesisWriteAnswer(request,fixture.time) }
        try {
            val c=client(db,vault,fixture,api,motivation=motivation,nemesisWrites=writes);c.start();c.issueNemesisCode();assertTrue(writes.calls.isEmpty())
            login(c,fixture,"fixture-A");c.issueNemesisCode();assertTrue(writes.calls.isEmpty());c.bootstrap()
            writes.before={assertTrue(vault.read().has("nemesisAttempt"))}
            c.issueNemesisCode();val first=writes.calls.single().second;assertTrue(c.view.value.nemesisMutation is NemesisMutationState.Pending)
            c.issueNemesisCode();assertEquals(1,writes.calls.size)
            val restarted=client(db,vault,fixture,api,motivation=motivation,nemesisWrites=writes);restarted.start()
            assertTrue(restarted.view.value.nemesisMutation is NemesisMutationState.Pending);assertEquals(1,writes.calls.size)
            restarted.retryNemesisMutation();val second=writes.calls.last().second
            assertEquals(first.key,second.key);assertEquals(first.epoch,second.epoch);assertArrayEquals(first.command.body(),second.command.body())
            assertTrue(restarted.view.value.nemesisMutation is NemesisMutationState.Issued);assertFalse(vault.read().has("nemesisAttempt"))
            assertFalse(vault.read().toString().contains("A".repeat(43)))
            restarted.clearNemesisPreview();assertEquals(NemesisMutationState.Idle,restarted.view.value.nemesisMutation)
        } finally {vault.clear();db.close()}
    }
    @Test fun nemesisAcceptNeedsFreshSourceAndEveryOffByDefaultScopeAcknowledgment()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();val api=ApiFixture();val motivation=MotivationFixture()
        val reads=NemesisFixture { q -> if(q is NemesisQuery.Detail) BootstrapHttpResult(200,nemesisInvite().toString().toByteArray()) else nemesisAnswer(q) }
        val writes=NemesisWrites { nemesisWriteAnswer(it,fixture.time) }
        try {
            val c=client(db,vault,fixture,api,motivation=motivation,nemesis=reads,nemesisWrites=writes);c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readNemesisChallenge(nemesisId)
            val source=c.view.value.nemesisDecision!!
            c.acceptNemesis(source.id,false,true,true);c.acceptNemesis(source.id,true,true,false);assertTrue(writes.calls.isEmpty());assertFalse(vault.read().has("nemesisAttempt"))
            c.acceptNemesis(source.id,true,true,true);val request=writes.calls.single().second
            assertEquals(NemesisAction.ACCEPT,request.command.action);assertEquals(1,request.command.baseRevision)
            assertEquals(nemesisId,request.command.target);assertEquals(NemesisState.NotRequested,c.view.value.nemesis)
            assertTrue(c.view.value.nemesisMutation is NemesisMutationState.Confirmed);assertNull(c.view.value.nemesisDecision)
        } finally {vault.clear();db.close()}
    }
    @Test fun nemesisWithdrawDoesNotDependOnMaterializationOrActivationPreflight()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();val api=ApiFixture();val motivation=MotivationFixture();val reads=NemesisFixture()
        val writes=NemesisWrites { nemesisWriteAnswer(it,fixture.time) }
        try {
            val c=client(db,vault,fixture,api,motivation=motivation,nemesis=reads,nemesisWrites=writes);c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readNemesisChallenge(nemesisId)
            val source=c.view.value.nemesisDecision!!;val count=motivation.calls.size;motivation.answer={BootstrapHttpResult(503,byteArrayOf(),"5")}
            c.cancelNemesis(source.id);c.revokeNemesisCode()
            assertEquals(listOf(NemesisAction.CANCEL,NemesisAction.REVOKE),writes.calls.map { it.second.command.action });assertEquals(count,motivation.calls.size)
            assertNull(writes.calls.last().second.command.body());assertEquals(NemesisState.NotRequested,c.view.value.nemesis)
        } finally {vault.clear();db.close()}
    }
    @Test fun heldNemesisAckCannotRestoreCodeAfterLeaveLogoutOrEpochChange()=runBlocking<Unit> {
        for(mode in listOf("leave","logout","epoch")) {
            val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();val api=ApiFixture();val motivation=MotivationFixture()
            val writes=NemesisWrites { nemesisWriteAnswer(it,fixture.time) }.apply {hold=CompletableDeferred()};var watch:Job?=null
            try {
                val c=client(db,vault,fixture,api,motivation=motivation,nemesisWrites=writes);c.start();login(c,fixture,"fixture-A");c.bootstrap()
                val task=async {c.issueNemesisCode()};withTimeout(10000) {writes.started.await()}
                when(mode) {
                    "leave"->c.clearNemesisPreview()
                    "logout"->{c.logout();login(c,fixture,"fixture-B");c.logout();login(c,fixture,"fixture-A")}
                    else->{watch=launch {c.observeMotivationContext()};val lease=c.view.value.binding!!.lease;val old=db.bootstrapDao().binding(lease.storageScope)!!
                        db.bootstrapDao().update(old.copy(syncEpoch=newEpoch));withTimeout(10000) {while(c.view.value.nemesisMutationBusy) delay(10)}}
                }
                writes.hold!!.complete(Unit);task.await();assertFalse(c.view.value.nemesisMutation is NemesisMutationState.Issued)
                if(mode=="leave") assertTrue(c.view.value.nemesisMutation is NemesisMutationState.Pending) else assertFalse(vault.read().has("nemesisAttempt"))
            } finally {writes.hold?.complete(Unit);watch?.cancelAndJoin();vault.clear();db.close()}
        }
    }
    @Test fun nemesisGrantPreflightAndSendFencesRejectEpochOrContextDrift()=runBlocking<Unit> {
        for(mode in listOf("preflight","send")) {
            val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();val api=ApiFixture()
            val motivation=if(mode=="preflight") MotivationFixture {motivationAnswer {it.put("sync_epoch",newEpoch)}} else MotivationFixture()
            val writes=NemesisWrites {nemesisWriteAnswer(it,fixture.time)}
            try {
                val c=client(db,vault,fixture,api,motivation=motivation,nemesisWrites=writes);c.start();login(c,fixture,"fixture-A");c.bootstrap()
                if(mode=="send") writes.before={val lease=c.view.value.binding!!.lease;val old=db.bootstrapDao().binding(lease.storageScope)!!;db.bootstrapDao().update(old.copy(contextRevision=old.contextRevision+1))}
                c.issueNemesisCode();assertTrue(writes.calls.isEmpty());assertFalse(c.view.value.nemesisMutation is NemesisMutationState.Issued)
                assertFalse(vault.read().has("nemesisAttempt"))
            } finally {vault.clear();db.close()}
        }
    }
    @Test fun nemesis503KeepsExactIntentButExpiredReceiptRequiresFreshDecision()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();val api=ApiFixture();val motivation=MotivationFixture()
        val writes=NemesisWrites {BootstrapHttpResult(503,byteArrayOf(),"120")}
        try {
            val c=client(db,vault,fixture,api,motivation=motivation,nemesisWrites=writes);c.start();login(c,fixture,"fixture-A");c.bootstrap();c.issueNemesisCode()
            val key=writes.calls.single().second.key;c.retryNemesisMutation();assertEquals(1,writes.calls.size)
            fixture.time+=121000;writes.answer={denied(409,"idempotency_result_expired")};c.retryNemesisMutation()
            assertEquals(key,writes.calls.last().second.key);assertFalse(vault.read().has("nemesisAttempt"));assertTrue(c.view.value.nemesisMutation is NemesisMutationState.Failed)
            c.retryNemesisMutation();assertEquals(2,writes.calls.size)
        } finally {vault.clear();db.close()}
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

    private fun photoAnswer() = BootstrapHttpResult(200,
        androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context.assets.open("photo-capabilities.json").use { it.readBytes() })

    @Test fun photoCapabilitiesReadIsFencedAcrossLogoutAndAtoBtoAWithoutChangingDiary() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val entered = CompletableDeferred<Unit>(); val release = CompletableDeferred<Unit>(); var calls = 0
        val photos = object : PhotoCapabilitiesGateway {
            override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit): BootstrapHttpResult {
                beforeSend(); calls++
                if (calls == 2) { entered.complete(Unit); release.await() }
                return photoAnswer()
            }
        }
        try {
            val c = client(db, vault, fixture, api, photos = photos); c.start()
            val guest = DiaryRepository(db, context).apply { initialize() }
            guest.add("basic-banana", 100.0, MealType.LUNCH, LocalDate.now(), "photo-capabilities-guest")
            c.readPhotoCapabilities(); assertEquals(0, calls)
            login(c, fixture, "fixture-A"); c.bootstrap()
            val lease = c.view.value.binding!!.lease
            val before = db.dao().operationCount(lease.storageScope); val beforeProfile = db.dao().currentProfile(lease.storageScope)
            c.readPhotoCapabilities(); assertTrue(c.view.value.photoCapabilities is PhotoCapabilitiesState.Ready)
            assertEquals(before, db.dao().operationCount(lease.storageScope)); assertEquals(beforeProfile, db.dao().currentProfile(lease.storageScope))
            val old = async { c.readPhotoCapabilities() }
            withTimeout(10_000) { entered.await() }
            assertTrue(c.view.value.photoCapabilitiesBusy)
            c.logout(); assertEquals(PhotoCapabilitiesState.NotRequested, c.view.value.photoCapabilities)
            login(c, fixture, "fixture-B"); login(c, fixture, "fixture-A")
            assertNotEquals(lease, c.view.value.binding!!.lease)
            release.complete(Unit); old.await()
            assertEquals(PhotoCapabilitiesState.NotRequested, c.view.value.photoCapabilities)
            assertFalse(c.view.value.photoCapabilitiesBusy)
            assertEquals(1, db.dao().operationCount("guest")); assertEquals(before, db.dao().operationCount(lease.storageScope))
        } finally { release.complete(Unit); vault.clear(); db.close() }
    }

    @Test fun photoCapabilitiesRetryAfterCancellationAndRecoveryFailClosed() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        var calls = 0; var held: CompletableDeferred<Unit>? = null; val entered = CompletableDeferred<Unit>()
        val photos = object : PhotoCapabilitiesGateway {
            override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit): BootstrapHttpResult {
                beforeSend(); calls++
                if (held != null) { entered.complete(Unit); held!!.await() }
                return if (calls == 1) denied(503, "service_unavailable", "60") else photoAnswer()
            }
        }
        try {
            val c = client(db, vault, fixture, api, photos = photos); c.start(); login(c, fixture, "fixture-A"); c.bootstrap()
            val lease = c.view.value.binding!!.lease
            c.readPhotoCapabilities(); assertTrue(c.view.value.photoCapabilities is PhotoCapabilitiesState.Failed)
            c.readPhotoCapabilities(); assertEquals(1, calls)
            fixture.time += 60_000
            held = CompletableDeferred(); val cancelled = async { c.readPhotoCapabilities() }
            withTimeout(10_000) { entered.await() }; cancelled.cancelAndJoin()
            assertFalse(c.view.value.photoCapabilitiesBusy); assertFalse(c.view.value.photoCapabilities is PhotoCapabilitiesState.Ready)
            held = null; c.readPhotoCapabilities(); assertTrue(c.view.value.photoCapabilities is PhotoCapabilitiesState.Ready)
            val mapping = db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(mapping.copy(requiresRecovery = true, contextRevision = mapping.contextRevision + 1))
            c.readPhotoCapabilities(); assertEquals(3, calls)
            assertEquals(PhotoCapabilitiesState.NotRequested, c.view.value.photoCapabilities)
            assertEquals(0, db.dao().operationCount(lease.storageScope))
        } finally { held?.complete(Unit); vault.clear(); db.close() }
    }

}
