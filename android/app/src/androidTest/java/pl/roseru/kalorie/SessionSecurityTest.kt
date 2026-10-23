package pl.roseru.kalorie

import android.content.Context
import android.content.Intent
import androidx.room.Room
import androidx.room.withTransaction
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
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.photo.*
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
        consents: RankingConsentGateway? = null, ranking: RankingGateway? = null, nemesis: NemesisGateway? = null, nemesisWrites: NemesisWriteGateway? = null, photos: PhotoCapabilitiesGateway? = null, photoWrites:PhotoAnalysisGateway?=null, pushes:MealPushGateway?=null, projectDiary:Boolean=false) = SessionController(
        db, vault, fixture, issuer, context.packageName, now = { fixture.time }, bootstrapGateway = api, profileGateway = profiles, snapshotGateway = snapshots,
        snapshotProtocol = snapshots?.let { snapshotProtocol() }, motivationGateway = motivation, rankingConsentGateway = consents, rankingGateway = ranking, nemesisGateway = nemesis, nemesisWriteGateway = nemesisWrites, photoCapabilitiesGateway = photos,
        photoAnalysisGateway=photoWrites,photoAnalysisStores=if(photoWrites!=null) { lease:OwnerLease->PhotoAnalysisStore(context,db,lease) } else null,
        mealPushGateway=pushes,mealPushStore=pushes?.let {MealPushStore(db,CanonicalMealRows.schema(context))},
        mealPushProtocol=pushes?.let {PushProtocol(CanonicalMealRows.schema(context))},
        diaryStore=if(projectDiary)ServerDiaryStore(db,CanonicalMealRows.schema(context)) else null)
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
            withTimeout(10_000) { c.view.first { it.serverProfile == null } }
            c.readRankingConsents(); assertTrue(c.view.value.rankingConsent is RankingConsentState.Ready)
            val current = db.bootstrapDao().binding(owner)!!; db.bootstrapDao().update(current.copy(accountGeneration = current.accountGeneration + 1))
            withTimeout(10_000) { c.view.first { it.rankingConsent is RankingConsentState.NotRequested } }
            c.readProfile(); assertNotNull(c.view.value.serverProfile)
            val other = LocalOwnerStore(db).registerIdentity(issuer, "fixture-B"); LocalOwnerStore(db).select(other.id)
            withTimeout(10_000) { c.view.first { it.binding?.owner?.subject == "fixture-B" } }
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

    @Test fun lateProofConfirmsActualProfileParserAndExistingOwnerGuard() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = object : ProfileGateway {
            override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit): BootstrapHttpResult {
                beforeSend(); val response = profileAnswer()
                ApiReadObservation.lateRead.beforeReturn("GET", "/api/v1/me", 200, System.nanoTime() + 30_000_000_000)
                return response
            }
        }
        var ticket: LateReadGate.Ticket? = null
        try {
            val c = client(db,vault,fixture,api,profiles); c.start(); login(c,fixture,"fixture-A"); c.bootstrap()
            val guestOps = db.dao().operationCount("guest")
            val armed = ApiReadObservation.lateRead.arm("/api/v1/me"); ticket = armed
            val read = async { c.readProfile() }
            withTimeout(10_000) { armed.held.await() }
            c.logout(); assertEquals("guest",c.view.value.binding!!.owner.kind); armed.logoutCompleted()
            armed.release.complete(Unit); read.await()
            assertTrue(armed.parsed.isCompleted); assertTrue(armed.rejected.isCompleted)
            assertFalse(c.view.value.hasSession); assertNull(c.view.value.serverProfile)
            assertEquals(guestOps,db.dao().operationCount("guest"))
            armed.guestPreserved()
            assertEquals(listOf("held","logout","released","dto_parsed","stale_owner_rejected","guest_preserved"),armed.events())
        } finally { ticket?.let { it.release.complete(Unit); ApiReadObservation.lateRead.disarm(it) }; vault.clear(); db.close() }
    }

    @Test fun lateProofRejectsMalformedDtoBeforeClaimingOwnerRejection() = runBlocking<Unit> {
        val db = memory(); val vault = SessionVault(context, name()); val fixture = FixtureGateway(); val api = ApiFixture()
        val profiles = object : ProfileGateway {
            override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit): BootstrapHttpResult {
                beforeSend()
                ApiReadObservation.lateRead.beforeReturn("GET", "/api/v1/me", 200, System.nanoTime() + 30_000_000_000)
                return BootstrapHttpResult(200,"{}".toByteArray())
            }
        }
        var ticket: LateReadGate.Ticket? = null
        try {
            val c = client(db,vault,fixture,api,profiles); c.start(); login(c,fixture,"fixture-A"); c.bootstrap()
            val armed = ApiReadObservation.lateRead.arm("/api/v1/me"); ticket = armed
            val read = async { c.readProfile() }
            withTimeout(10_000) { armed.held.await() }
            c.logout(); armed.logoutCompleted(); armed.release.complete(Unit)
            read.await() // Unit completion alone was the old false-positive condition.
            assertEquals("released",armed.outcome.await())
            assertFalse(armed.parsed.isCompleted); assertFalse(armed.rejected.isCompleted)
            assertEquals(listOf("held","logout","released"),armed.events())
            assertEquals("guest",c.view.value.binding!!.owner.kind); assertNull(c.view.value.serverProfile)
        } finally { ticket?.let { it.release.complete(Unit); ApiReadObservation.lateRead.disarm(it) }; vault.clear(); db.close() }
    }

    private fun uploadAck()=androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context.assets
        .open("create-accepted.json").use { it.readBytes() }
    private fun uploadCapabilities():BootstrapHttpResult {
        val json=JSONObject(photoAnswer().body.toString(Charsets.UTF_8))
        val profile=JSONObject(uploadAck().toString(Charsets.UTF_8)).getJSONObject("profile")
        json.put("provider",profile.getString("provider")).put("profile",profile)
            .put("available",true).put("unavailable_reason",JSONObject.NULL)
        return BootstrapHttpResult(200,json.toString().toByteArray())
    }
    private fun uploadReader()=object:PhotoCapabilitiesGateway {
        override suspend fun get(session:ApiSession,beforeSend:suspend()->Unit):BootstrapHttpResult {beforeSend();return uploadCapabilities()}
    }
    private fun uploadConsent(c:SessionController)=(c.view.value.photoCapabilities as PhotoCapabilitiesState.Ready).read.let {
        PhotoUploadConsent(it.provider,it.model,it.noticeVersion)
    }
    private suspend fun uploadImage(db:CalorieDatabase,lease:OwnerLease):String {
        val bitmap=android.graphics.Bitmap.createBitmap(48,32,android.graphics.Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(android.graphics.Color.GREEN)
        val bytes=java.io.ByteArrayOutputStream().also {bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG,90,it);bitmap.recycle()}.toByteArray()
        return MealPhotoStore(context,db,lease).import(java.io.ByteArrayInputStream(bytes),LocalDate.now(),"gallery").id
    }
    private fun cleanUpload(scope:String?) {
        if(scope==null)return
        require(UUID.fromString(scope).toString()==scope)
        for(root in listOf("photo-analysis-inputs","meal-photo-drafts")) {
            val directory=File(context.filesDir,"$root/$scope")
            directory.listFiles()?.forEach {check(it.parentFile==directory && it.isFile);check(it.delete())}
            if(directory.exists())check(directory.delete())
        }
    }
    private class UploadCall(val key:String?,val bytes:ByteArray)
    @Test fun photoUploadRequiresExactConsentAndNeverWritesAMealOrSecondOperation()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val calls=mutableListOf<UploadCall>()
        val writes=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                assertFalse(db.inTransaction());beforeSend();calls+=UploadCall(request.key,request.body()!!)
                return BootstrapHttpResult(202,uploadAck())
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=writes);c.start()
            val guest=c.view.value.binding!!.lease
            c.uploadPhoto(guest,UUID.randomUUID().toString(),PhotoUploadConsent("mock","x","food-photo-notice-v1"),true)
            assertTrue(calls.isEmpty());assertNull(db.photoAnalysisDao().get("guest"))
            login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope;val image=uploadImage(db,lease)
            val consent=uploadConsent(c)
            c.uploadPhoto(lease,image,consent,false);assertNull(db.photoAnalysisDao().get(lease.storageScope))
            c.uploadPhoto(lease,image,PhotoUploadConsent(consent.provider,consent.model+"-changed",consent.noticeVersion),true)
            assertTrue(calls.isEmpty());assertNull(db.photoAnalysisDao().get(lease.storageScope))
            c.uploadPhoto(lease,image,consent,true)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!
            assertEquals(1,calls.size);assertTrue(row.attempted);assertNotNull(row.receiptJson)
            assertTrue(c.view.value.photoUpload!!.acknowledged);assertFalse(c.view.value.photoUploadBusy)
            c.uploadPhoto(lease,image,consent,true);assertEquals(1,calls.size);assertEquals(row,db.photoAnalysisDao().get(lease.storageScope))
            assertEquals(0,db.dao().operationCount(lease.storageScope));assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty())
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoUploadLostAckAndRestartRetryExactInputAfterOriginalPhotoDeletion()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val calls=mutableListOf<UploadCall>()
        val writes=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                assertFalse(db.inTransaction());beforeSend();calls+=UploadCall(request.key,request.body()!!)
                if(calls.size==1)throw java.io.IOException("fixture lost ACK")
                return BootstrapHttpResult(202,uploadAck())
            }
        }
        try {
            val api=ApiFixture();val c=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=writes)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope;val image=uploadImage(db,lease)
            c.uploadPhoto(lease,image,uploadConsent(c),true)
            assertEquals(1,calls.size);assertNull(db.photoAnalysisDao().get(lease.storageScope)!!.receiptJson)
            MealPhotoStore(context,db,lease).delete(image)
            val restarted=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=writes);restarted.start()
            assertEquals(1,calls.size);assertTrue(restarted.view.value.photoUpload!!.attempted)
            restarted.retryPhotoUpload(lease)
            assertEquals(2,calls.size);assertEquals(calls[0].key,calls[1].key);assertArrayEquals(calls[0].bytes,calls[1].bytes)
            assertTrue(restarted.view.value.photoUpload!!.acknowledged);assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoUploadHeldAckAndStaleUiLeaseCannotApplyAcrossAtoBtoA()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>();var calls=0
        val writes=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend();calls++;entered.complete(Unit);release.await();return BootstrapHttpResult(202,uploadAck())
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=writes)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val old=c.view.value.binding!!.lease;scope=old.storageScope;val image=uploadImage(db,old);val consent=uploadConsent(c)
            val work=async {c.uploadPhoto(old,image,consent,true)}
            withTimeout(10_000){entered.await()};assertTrue(c.view.value.photoUploadBusy)
            c.logout();assertNull(c.view.value.photoUpload);login(c,fixture,"fixture-B");assertNull(c.view.value.photoUpload)
            c.logout();login(c,fixture,"fixture-A");val newer=c.view.value.binding!!.lease;assertNotEquals(old,newer)
            release.complete(Unit);work.await()
            assertNull(db.photoAnalysisDao().get(old.storageScope)!!.receiptJson);assertFalse(c.view.value.photoUploadBusy)
            c.uploadPhoto(old,image,consent,true);assertEquals(1,calls)
            assertTrue(c.view.value.photoUpload!!.attempted);assertFalse(c.view.value.photoUpload!!.acknowledged)
            assertEquals(0,db.dao().operationCount(newer.storageScope))
        } finally {release.complete(Unit);vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoUpload401RefreshesOnceWithoutChangingKeyOrBytes()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val calls=mutableListOf<UploadCall>()
        val writes=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend();calls+=UploadCall(request.key,request.body()!!)
                return if(calls.size==1)denied(401,"unauthorized") else BootstrapHttpResult(202,uploadAck())
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=writes)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true)
            assertEquals(2,calls.size);assertEquals(2,fixture.calls)
            assertEquals(calls[0].key,calls[1].key);assertArrayEquals(calls[0].bytes,calls[1].bytes)
            assertTrue(c.view.value.photoUpload!!.acknowledged);assertFalse(c.view.value.photoUploadBusy)
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoUploadBackoffIsSharedDurableAndRestartNeverSendsAutomatically()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        var reads=0;var writes=0
        val caps=object:PhotoCapabilitiesGateway {
            override suspend fun get(session:ApiSession,beforeSend:suspend()->Unit):BootstrapHttpResult {beforeSend();reads++;return uploadCapabilities()}
        }
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend();writes++;return if(writes==1)denied(503,"service_unavailable","60") else BootstrapHttpResult(202,uploadAck())
            }
        }
        try {
            val api=ApiFixture();val c=client(db,vault,fixture,api,photos=caps,photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!
            assertTrue(row.retryAtMillis>fixture.time);assertEquals(row.retryAtMillis,vault.read().getJSONObject("session").getLong("apiRetryAt"))
            val restarted=client(db,vault,fixture,api,photos=caps,photoWrites=transport);restarted.start()
            restarted.retryPhotoUpload(lease);restarted.readPhotoCapabilities()
            assertEquals(1,writes);assertEquals(1,reads);assertEquals(row,db.photoAnalysisDao().get(lease.storageScope))
            fixture.time+=60_001;restarted.retryPhotoUpload(lease)
            assertEquals(2,writes);assertTrue(restarted.view.value.photoUpload!!.acknowledged)
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoUploadCancellationAndRecoveryKeepInputWithoutFalseAckOrBlindReplay()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val entered=CompletableDeferred<Unit>();val hold=CompletableDeferred<Unit>();var calls=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend();calls++;entered.complete(Unit);hold.await();return BootstrapHttpResult(202,uploadAck())
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope;val image=uploadImage(db,lease);val consent=uploadConsent(c)
            val work=async {c.uploadPhoto(lease,image,consent,true)}
            withTimeout(10_000){entered.await()};work.cancelAndJoin()
            val row=db.photoAnalysisDao().get(lease.storageScope)!!
            assertTrue(row.attempted);assertNull(row.receiptJson);assertFalse(c.view.value.photoUploadBusy)
            val mapping=db.bootstrapDao().binding(lease.storageScope)!!
            db.bootstrapDao().update(mapping.copy(requiresRecovery=true,contextRevision=mapping.contextRevision+1))
            c.retryPhotoUpload(lease);c.uploadPhoto(lease,image,consent,true)
            assertEquals(1,calls);assertEquals(row,db.photoAnalysisDao().get(lease.storageScope));assertTrue(c.view.value.photoUpload!!.blocked)
            assertTrue(File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg").exists())
        } finally {hold.complete(Unit);vault.clear();db.close();cleanUpload(scope)}
    }

    @Test fun photoUploadBusyConflictKeepsSameRequestRetryable()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val calls=mutableListOf<UploadCall>()
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend();calls+=UploadCall(request.key,request.body()!!)
                return if(calls.size==1)denied(409,"ai_operation_busy") else BootstrapHttpResult(202,uploadAck())
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!
            assertNull(row.blockedCode);assertNull(row.receiptJson);assertEquals(fixture.time+30_000,row.retryAtMillis)
            c.retryPhotoUpload(lease);assertEquals(1,calls.size)
            fixture.time+=30_001;c.retryPhotoUpload(lease)
            assertEquals(2,calls.size);assertEquals(calls[0].key,calls[1].key);assertArrayEquals(calls[0].bytes,calls[1].bytes)
            assertTrue(c.view.value.photoUpload!!.acknowledged)
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoUploadServerContextConflictsRequireRecoveryAndPreserveTheAttempt()=runBlocking<Unit> {
        for(code in listOf("sync_epoch_changed","account_generation_changed","analysis_context_changed")) {
            val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null;var calls=0
            val transport=object:PhotoAnalysisGateway {
                override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                    beforeSend();calls++;return denied(409,code)
                }
            }
            try {
                val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
                c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
                val lease=c.view.value.binding!!.lease;scope=lease.storageScope
                val original=db.bootstrapDao().binding(lease.storageScope)!!
                c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true)
                val mapping=db.bootstrapDao().binding(lease.storageScope)!!
                assertTrue(mapping.requiresRecovery);assertEquals(original.contextRevision+1,mapping.contextRevision)
                val row=db.photoAnalysisDao().get(lease.storageScope)!!
                assertTrue(row.attempted);assertNull(row.receiptJson);assertNotNull(row.blockedCode)
                assertTrue(c.view.value.photoUpload!!.blocked)
                c.retryPhotoUpload(lease);assertEquals(1,calls);assertEquals(row,db.photoAnalysisDao().get(lease.storageScope))
                assertEquals(0,db.dao().operationCount(lease.storageScope))
            } finally {vault.clear();db.close();cleanUpload(scope)}
        }
    }

    private fun analysisRead(state:String="succeeded",revision:Int=2):ByteArray {
        val value=JSONObject(androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context.assets
            .open("analysis-read-succeeded.json").bufferedReader().use {it.readText()})
        value.put("state",state).put("revision",revision)
        if(state!="succeeded")value.put("proposal",JSONObject.NULL)
        return value.toString().toByteArray(Charsets.UTF_8)
    }
    @Test fun photoReadRestoresCachedResultOfflineAfterRestartAndNeverPostsAgain()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        var posts=0;var reads=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                assertFalse(db.inTransaction());beforeSend()
                return when(request) {
                    is PhotoHttpRequest.Create->{posts++;BootstrapHttpResult(202,uploadAck())}
                    is PhotoHttpRequest.Read->{reads++;assertNull(request.key);assertNull(request.epoch);assertNull(request.body());BootstrapHttpResult(200,analysisRead())}
                    else->error("Unexpected photo mutation")
                }
            }
        }
        try {
            val api=ApiFixture();val c=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope;val image=uploadImage(db,lease)
            c.uploadPhoto(lease,image,uploadConsent(c),true);c.readPhotoAnalysis(lease)
            assertEquals("Banan",c.view.value.photoAnalysis!!.items.single().name);assertEquals(1,posts);assertEquals(1,reads)
            assertFalse(c.view.value.photoReadBusy)
            MealPhotoStore(context,db,lease).delete(image)
            assertTrue(File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${db.photoAnalysisDao().get(lease.storageScope)!!.operationId}.jpg").delete())
            fixture.time+=400_000 // expired access token must not prevent local restore
            val restarted=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport);restarted.start()
            assertNull(restarted.view.value.photoAnalysis);assertEquals(1,reads)
            restarted.loadPhotoAnalysis(lease)
            assertEquals("Banan",restarted.view.value.photoAnalysis!!.items.single().name)
            assertEquals(1,posts);assertEquals(1,reads);assertFalse(restarted.view.value.hasSession)
            assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty());assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoReadHeldGetAndStaleUiCannotApplyAcrossOwnerAba()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>();var reads=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend()
                if(request is PhotoHttpRequest.Create)return BootstrapHttpResult(202,uploadAck())
                assertTrue(request is PhotoHttpRequest.Read);reads++;entered.complete(Unit);release.await()
                return BootstrapHttpResult(200,analysisRead())
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true)
            val before=db.photoAnalysisDao().get(lease.storageScope);val guestOps=db.dao().operationCount("guest")
            val work=async {c.readPhotoAnalysis(lease)};withTimeout(10_000){entered.await()}
            c.logout();assertNull(c.view.value.photoAnalysis);login(c,fixture,"fixture-B")
            assertNull(c.view.value.photoUpload);c.logout();login(c,fixture,"fixture-A")
            release.complete(Unit);work.await()
            assertEquals(before,db.photoAnalysisDao().get(lease.storageScope));assertNull(c.view.value.photoAnalysis)
            assertFalse(c.view.value.photoReadBusy);c.readPhotoAnalysis(lease);assertEquals(1,reads)
            assertEquals(guestOps,db.dao().operationCount("guest"));assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {release.complete(Unit);vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoRead401RenewsOnceWithTheSameGetAndNoMutationKey()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val paths=mutableListOf<String>();var posts=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend()
                if(request is PhotoHttpRequest.Create){posts++;return BootstrapHttpResult(202,uploadAck())}
                assertTrue(request is PhotoHttpRequest.Read);assertNull(request.body());assertNull(request.key);assertNull(request.epoch)
                paths+=request.path
                return if(paths.size==1)denied(401,"unauthorized") else BootstrapHttpResult(200,analysisRead())
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
            assertEquals(2,paths.size);assertEquals(paths[0],paths[1]);assertEquals(2,fixture.calls);assertEquals(1,posts)
            assertNotNull(c.view.value.photoAnalysis);assertFalse(c.view.value.photoReadBusy)
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoReadBackoffSurvivesRestartAndIsSharedWithoutReposting()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        var posts=0;var reads=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend()
                if(request is PhotoHttpRequest.Create){posts++;return BootstrapHttpResult(202,uploadAck())}
                assertTrue(request is PhotoHttpRequest.Read);reads++
                return if(reads==1)denied(503,"service_unavailable","60") else BootstrapHttpResult(200,analysisRead())
            }
        }
        try {
            val api=ApiFixture();val c=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!
            assertNotNull(row.receiptJson);assertEquals(fixture.time+60_000,row.retryAtMillis)
            assertEquals(row.retryAtMillis,vault.read().getJSONObject("session").getLong("apiRetryAt"))
            val restarted=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport);restarted.start()
            restarted.loadPhotoAnalysis(lease);restarted.readPhotoAnalysis(lease);assertEquals(1,reads);assertEquals(1,posts)
            fixture.time+=60_001;restarted.readPhotoAnalysis(lease)
            assertEquals(2,reads);assertEquals(1,posts);assertNotNull(restarted.view.value.photoAnalysis)
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoReadLeavingTheScreenOrChangedContextRejectsHeldResponse()=runBlocking<Unit> {
        for(changeContext in listOf(false,true)) {
            val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
            val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
            val transport=object:PhotoAnalysisGateway {
                override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                    beforeSend();if(request is PhotoHttpRequest.Create)return BootstrapHttpResult(202,uploadAck())
                    entered.complete(Unit);release.await();return BootstrapHttpResult(200,analysisRead())
                }
            }
            try {
                val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
                c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
                val lease=c.view.value.binding!!.lease;scope=lease.storageScope
                c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true)
                val before=db.photoAnalysisDao().get(lease.storageScope)
                val work=async {c.readPhotoAnalysis(lease)};withTimeout(10_000){entered.await()}
                if(changeContext) {
                    val binding=db.bootstrapDao().binding(lease.storageScope)!!
                    db.bootstrapDao().update(binding.copy(contextRevision=binding.contextRevision+1))
                } else c.stopPhotoAnalysis(lease,clearPreview=true)
                release.complete(Unit);work.await()
                assertEquals(before,db.photoAnalysisDao().get(lease.storageScope));assertNull(c.view.value.photoAnalysis)
                assertFalse(c.view.value.photoReadBusy);assertEquals(0,db.dao().operationCount(lease.storageScope))
            } finally {release.complete(Unit);vault.clear();db.close();cleanUpload(scope)}
        }
    }
    @Test fun photoReadWorkingToSuccessPollsOnlyGetAndStopsOnTerminalResult()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        fixture.time=java.time.Instant.parse("2026-10-11T16:59:00Z").toEpochMilli()
        var posts=0;var reads=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                assertFalse(db.inTransaction());beforeSend()
                if(request is PhotoHttpRequest.Create){posts++;return BootstrapHttpResult(202,uploadAck())}
                assertTrue(request is PhotoHttpRequest.Read);reads++
                return BootstrapHttpResult(200,if(reads==1)analysisRead("running",2) else analysisRead("succeeded",3))
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);withTimeout(10_000){c.readPhotoAnalysis(lease)}
            assertEquals(2,reads);assertEquals(1,posts);assertEquals(3L,c.view.value.photoAnalysis!!.revision)
            assertEquals("succeeded",c.view.value.photoAnalysis!!.state);assertFalse(c.view.value.photoReadBusy)
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoReadUnacknowledgedAndMalformedResponsesNeverOverwriteOrCreateAMeal()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        var ackLost=true;var reads=0;var posts=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend()
                if(request is PhotoHttpRequest.Create){posts++;if(ackLost)throw java.io.IOException("fixture lost ACK");return BootstrapHttpResult(202,uploadAck())}
                reads++;return BootstrapHttpResult(200,"{}".toByteArray())
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport);c.start()
            c.readPhotoAnalysis(c.view.value.binding!!.lease);assertEquals(0,reads)
            login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
            assertEquals(0,reads);ackLost=false;c.retryPhotoUpload(lease)
            val before=db.photoAnalysisDao().get(lease.storageScope);c.readPhotoAnalysis(lease)
            assertEquals(1,reads);assertEquals(2,posts);assertEquals(before,db.photoAnalysisDao().get(lease.storageScope))
            assertNull(c.view.value.photoAnalysis);assertFalse(c.view.value.photoReadBusy)
            assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty());assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoReadServerContextConflictRequiresRecoveryAndPreservesSavedAck()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null;var reads=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend();if(request is PhotoHttpRequest.Create)return BootstrapHttpResult(202,uploadAck())
                reads++;return denied(409,"analysis_context_changed")
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true)
            val original=db.bootstrapDao().binding(lease.storageScope)!!
            val ack=db.photoAnalysisDao().get(lease.storageScope)!!.receiptJson
            c.readPhotoAnalysis(lease)
            val mapping=db.bootstrapDao().binding(lease.storageScope)!!
            assertTrue(mapping.requiresRecovery);assertEquals(original.contextRevision+1,mapping.contextRevision)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!
            assertEquals(ack,row.receiptJson);assertEquals("photo_read_rejected",row.blockedCode)
            assertNull(c.view.value.photoAnalysis);assertTrue(c.view.value.photoUpload!!.blocked)
            c.readPhotoAnalysis(lease);assertEquals(1,reads);assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }

    private fun cancellationAck(revision:Int=3)=JSONObject().put("analysis_id",JSONObject(String(uploadAck())).getString("analysis_id"))
        .put("revision",revision).put("state","failed").put("decision_state","cancelled")
        .put("error_code","analysis_cancelled").toString().toByteArray()

    @Test fun photoCancellationLostAckRestoresSameDecisionWithoutNetworkThenExplicitlyReleasesOnlyItsInput()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val calls=mutableListOf<UploadCall>();var posts=0;var reads=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                assertFalse(db.inTransaction());beforeSend()
                return when(request) {
                    is PhotoHttpRequest.Create->{posts++;BootstrapHttpResult(202,uploadAck())}
                    is PhotoHttpRequest.Read->{reads++;BootstrapHttpResult(200,analysisRead())}
                    is PhotoHttpRequest.Confirm->error("Unexpected confirm in cancellation fixture")
                    is PhotoHttpRequest.Cancel->{calls+=UploadCall(request.key,request.body());if(calls.size==1)throw java.io.IOException("Synthetic lost ACK");BootstrapHttpResult(200,cancellationAck())}
                }
            }
        }
        try {
            val api=ApiFixture();val c=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope;val image=uploadImage(db,lease)
            c.uploadPhoto(lease,image,uploadConsent(c),true);c.readPhotoAnalysis(lease)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!
            c.releaseCancelledPhoto(lease,row.operationId);assertEquals(row,db.photoAnalysisDao().get(lease.storageScope))
            c.cancelPhotoAnalysis(lease,row.operationId,2)
            assertEquals(1,calls.size);assertTrue(c.view.value.photoCancellation!!.canRetry);assertFalse(c.view.value.photoCancelBusy)
            val restarted=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport);restarted.start();restarted.loadPhotoAnalysis(lease)
            assertEquals(1,calls.size);assertEquals(1,reads);assertEquals(1,posts);assertTrue(restarted.view.value.photoCancellation!!.canRetry)
            restarted.retryPhotoCancellation(lease,row.operationId)
            assertEquals(2,calls.size);assertEquals(calls[0].key,calls[1].key);assertNotEquals(row.operationId,calls[0].key)
            assertArrayEquals(calls[0].bytes,calls[1].bytes);assertTrue(restarted.view.value.photoCancellation!!.cancelled)
            assertNull(restarted.view.value.photoAnalysis);assertNotNull(db.photoAnalysisDao().get(lease.storageScope))
            fixture.time+=400_000 // local release must work with expired access, without HTTP
            restarted.releaseCancelledPhoto(lease,row.operationId)
            assertNull(db.photoAnalysisDao().get(lease.storageScope));assertEquals(2,calls.size)
            assertFalse(File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg").exists())
            assertTrue(MealPhotoStore(context,db,lease).uploadBytes(image).isNotEmpty())
            assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty());assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }

    @Test fun photoCancellation401RefreshesOnlyOnceAndKeepsExactMutationKeyEpochAndBody()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val calls=mutableListOf<PhotoHttpRequest.Cancel>()
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend()
                return when(request) {
                    is PhotoHttpRequest.Create->BootstrapHttpResult(202,uploadAck())
                    is PhotoHttpRequest.Read->BootstrapHttpResult(200,analysisRead())
                    is PhotoHttpRequest.Confirm->error("Unexpected confirm in cancellation fixture")
                    is PhotoHttpRequest.Cancel->{calls+=request;denied(401,"unauthorized")}
                }
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!;c.cancelPhotoAnalysis(lease,row.operationId,2)
            assertEquals(2,calls.size);assertEquals(2,fixture.calls);assertSame(calls[0],calls[1])
            assertEquals(row.syncEpoch,calls[0].epoch);assertArrayEquals(calls[0].body(),calls[1].body())
            assertTrue(c.view.value.photoCancellation!!.canRetry);assertFalse(c.view.value.photoCancellation!!.cancelled)
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }

    @Test fun photoCancellationBackoffSurvivesRestartAndGuardsAllApiUntilExplicitRetry()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        val calls=mutableListOf<UploadCall>()
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend()
                return when(request) {
                    is PhotoHttpRequest.Create->BootstrapHttpResult(202,uploadAck())
                    is PhotoHttpRequest.Read->BootstrapHttpResult(200,analysisRead())
                    is PhotoHttpRequest.Confirm->error("Unexpected confirm in cancellation fixture")
                    is PhotoHttpRequest.Cancel->{calls+=UploadCall(request.key,request.body());if(calls.size==1)denied(429,"rate_limit_exceeded","60")else BootstrapHttpResult(200,cancellationAck())}
                }
            }
        }
        try {
            val api=ApiFixture();val c=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!;c.cancelPhotoAnalysis(lease,row.operationId,2)
            assertEquals(fixture.time+60_000,db.photoAnalysisDao().get(lease.storageScope)!!.retryAtMillis)
            assertEquals(fixture.time+60_000,vault.read().getJSONObject("session").getLong("apiRetryAt"))
            val restarted=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport);restarted.start();restarted.loadPhotoAnalysis(lease)
            restarted.retryPhotoCancellation(lease,row.operationId);assertEquals(1,calls.size)
            assertTrue(restarted.view.value.photoCancellation!!.canRetry)
            fixture.time+=60_001;restarted.retryPhotoCancellation(lease,row.operationId)
            assertEquals(2,calls.size);assertEquals(calls[0].key,calls[1].key);assertArrayEquals(calls[0].bytes,calls[1].bytes)
            assertTrue(restarted.view.value.photoCancellation!!.cancelled)
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }

    @Test fun photoCancellationHeldAckCannotApplyAfterLeavingContextChangeOrOwnerAba()=runBlocking<Unit> {
        for(change in listOf("leave","context","aba")) {
            val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
            val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>();var cancels=0
            val transport=object:PhotoAnalysisGateway {
                override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                    beforeSend()
                    return when(request) {
                        is PhotoHttpRequest.Create->BootstrapHttpResult(202,uploadAck())
                        is PhotoHttpRequest.Read->BootstrapHttpResult(200,analysisRead())
                        is PhotoHttpRequest.Confirm->error("Unexpected confirm in cancellation fixture")
                        is PhotoHttpRequest.Cancel->{cancels++;entered.complete(Unit);release.await();BootstrapHttpResult(200,cancellationAck())}
                    }
                }
            }
            try {
                val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
                c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
                val lease=c.view.value.binding!!.lease;scope=lease.storageScope
                c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
                val row=db.photoAnalysisDao().get(lease.storageScope)!!
                val work=async {c.cancelPhotoAnalysis(lease,row.operationId,2)};withTimeout(10_000){entered.await()}
                val attempted=db.photoAnalysisDao().get(lease.storageScope)
                when(change) {
                    "leave"->c.stopPhotoAnalysis(lease,clearPreview=true)
                    "context"->{val mapping=db.bootstrapDao().binding(lease.storageScope)!!;db.bootstrapDao().update(mapping.copy(contextRevision=mapping.contextRevision+1))}
                    else->{c.logout();login(c,fixture,"fixture-B");c.logout();login(c,fixture,"fixture-A");c.bootstrap()}
                }
                release.complete(Unit);work.await()
                assertEquals(attempted,db.photoAnalysisDao().get(lease.storageScope));assertFalse(c.view.value.photoCancelBusy)
                assertNull(c.view.value.photoAnalysis);assertNull(c.view.value.photoCancellation)
                c.cancelPhotoAnalysis(lease,row.operationId,2);assertEquals(1,cancels)
                assertEquals(0,db.dao().operationCount(lease.storageScope))
            } finally {release.complete(Unit);vault.clear();db.close();cleanUpload(scope)}
        }
    }

    @Test fun photoCancellationRevisionConflictNeedsFreshGetAndAnotherExplicitDecision()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null
        var revision=2;val calls=mutableListOf<PhotoHttpRequest.Cancel>()
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend()
                return when(request) {
                    is PhotoHttpRequest.Create->BootstrapHttpResult(202,uploadAck())
                    is PhotoHttpRequest.Read->BootstrapHttpResult(200,analysisRead(revision=revision))
                    is PhotoHttpRequest.Confirm->error("Unexpected confirm in cancellation fixture")
                    is PhotoHttpRequest.Cancel->{calls+=request;if(calls.size==1)denied(409,"proposal_revision_conflict")else BootstrapHttpResult(200,cancellationAck(4))}
                }
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!
            c.cancelPhotoAnalysis(lease,row.operationId,1);assertEquals(0,calls.size)
            c.cancelPhotoAnalysis(lease,row.operationId,2)
            assertTrue(c.view.value.photoCancellation!!.revisionConflict);assertFalse(c.view.value.photoCancellation!!.canStart)
            c.retryPhotoCancellation(lease,row.operationId);c.cancelPhotoAnalysis(lease,row.operationId,2);assertEquals(1,calls.size)
            revision=3;c.readPhotoAnalysis(lease);assertEquals(1,calls.size);assertTrue(c.view.value.photoCancellation!!.canStart)
            c.cancelPhotoAnalysis(lease,row.operationId,2);assertEquals(1,calls.size)
            c.cancelPhotoAnalysis(lease,row.operationId,3)
            assertEquals(2,calls.size);assertNotEquals(calls[0].key,calls[1].key)
            assertEquals(2L,calls[0].expectedRevision);assertEquals(3L,calls[1].expectedRevision)
            assertTrue(c.view.value.photoCancellation!!.cancelled)
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }

    @Test fun photoCancellationRejectsMalformedAckAndRequiresRecoveryOnChangedServerEpoch()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null;var cancels=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend()
                return when(request) {
                    is PhotoHttpRequest.Create->BootstrapHttpResult(202,uploadAck())
                    is PhotoHttpRequest.Read->BootstrapHttpResult(200,analysisRead())
                    is PhotoHttpRequest.Confirm->error("Unexpected confirm in cancellation fixture")
                    is PhotoHttpRequest.Cancel->{cancels++;if(cancels==1)BootstrapHttpResult(200,cancellationAck().let {JSONObject(String(it)).put("analysis_id",UUID.randomUUID().toString()).toString().toByteArray()})else denied(409,"sync_epoch_changed")}
                }
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!;c.cancelPhotoAnalysis(lease,row.operationId,2)
            assertTrue(c.view.value.photoCancellation!!.canRetry);assertFalse(c.view.value.photoCancellation!!.cancelled)
            c.retryPhotoCancellation(lease,row.operationId);assertTrue(db.bootstrapDao().binding(lease.storageScope)!!.requiresRecovery)
            assertTrue(c.view.value.photoUpload!!.blocked);assertNull(c.view.value.photoCancellation)
            c.retryPhotoCancellation(lease,row.operationId);assertEquals(2,cancels)
            assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }

    @Test fun photoMealCorrectionsWorkOfflineWithExpiredAccessAndSharedPauseAndRestoreWithoutImages()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null;var calls=0;var reads=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend();calls++
                return when(request) {
                    is PhotoHttpRequest.Create->BootstrapHttpResult(202,uploadAck())
                    is PhotoHttpRequest.Read->{reads++;if(reads==1)BootstrapHttpResult(200,analysisRead())else denied(429,"rate_limit_exceeded","600")}
                    else->error("No mutation from local corrections")
                }
            }
        }
        try {
            val api=ApiFixture();val c=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope;val image=uploadImage(db,lease)
            c.uploadPhoto(lease,image,uploadConsent(c),true);c.readPhotoAnalysis(lease);c.readPhotoAnalysis(lease)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!;val retryAt=row.retryAtMillis
            MealPhotoStore(context,db,lease).delete(image);assertTrue(File(context.filesDir,"photo-analysis-inputs/${lease.storageScope}/${row.operationId}.jpg").delete())
            fixture.time+=400_000
            c.startPhotoMealDraft(lease,row.operationId,2,LocalDate.of(2026,10,12))
            val first=c.view.value.photoMealDraft!!;assertEquals("2026-10-12",first.localDate)
            c.startPhotoMealDraft(lease,row.operationId,2,LocalDate.of(2026,10,13));assertEquals(first.localDate,c.view.value.photoMealDraft!!.localDate)
            c.replacePhotoMealDraftItem(lease,row.operationId,1,first.items.single().id,PhotoDraftInput("Banan poprawiony","275,25","g","89","0","","22.8"))
            assertEquals("245",c.view.value.photoMealDraft!!.nutrition.energy.display);assertFalse(c.view.value.photoDraftBusy)
            assertEquals(retryAt,db.photoAnalysisDao().get(lease.storageScope)!!.retryAtMillis)
            val restarted=client(db,vault,fixture,api,photos=uploadReader(),photoWrites=transport);restarted.start();restarted.loadPhotoAnalysis(lease)
            val restored=restarted.view.value.photoMealDraft!!
            assertEquals(first.items.single().id,restored.items.single().id);assertEquals("Banan poprawiony",restored.items.single().input.name)
            assertEquals(2L,restored.editRevision);assertEquals(3,calls);assertTrue(restarted.view.value.photoCanEditProposal)
            assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty());assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoMealDraftStaleUiAndUncertainCancelCannotOverwriteCorrections()=runBlocking<Unit> {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null;var cancels=0
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                beforeSend()
                return when(request) {
                    is PhotoHttpRequest.Create->BootstrapHttpResult(202,uploadAck())
                    is PhotoHttpRequest.Read->BootstrapHttpResult(200,analysisRead())
                    is PhotoHttpRequest.Confirm->error("Unexpected confirm in cancellation fixture")
                    is PhotoHttpRequest.Cancel->{cancels++;throw java.io.IOException("Synthetic uncertainty")}
                }
            }
        }
        try {
            val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
            c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            val lease=c.view.value.binding!!.lease;scope=lease.storageScope
            c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
            val row=db.photoAnalysisDao().get(lease.storageScope)!!;c.startPhotoMealDraft(lease,row.operationId,2,LocalDate.now())
            c.renamePhotoMealDraft(lease,row.operationId,1,"Własny tytuł");val before=db.photoAnalysisDao().get(lease.storageScope)
            c.discardPhotoMealDraft(lease,row.operationId,1);assertEquals(before,db.photoAnalysisDao().get(lease.storageScope))
            c.cancelPhotoAnalysis(lease,row.operationId,2);val attempted=db.photoAnalysisDao().get(lease.storageScope)
            c.renamePhotoMealDraft(lease,row.operationId,2,"Nie wolno");assertEquals(attempted,db.photoAnalysisDao().get(lease.storageScope))
            assertFalse(c.view.value.photoCanEditProposal);assertEquals("Własny tytuł",c.view.value.photoMealDraft!!.title)
            c.logout();login(c,fixture,"fixture-B");assertNull(c.view.value.photoMealDraft)
            c.logout();login(c,fixture,"fixture-A");c.renamePhotoMealDraft(lease,row.operationId,2,"Stale owner")
            assertEquals(attempted,db.photoAnalysisDao().get(lease.storageScope));assertEquals(1,cancels)
            assertEquals(0,db.dao().operationCount(lease.storageScope))
        } finally {vault.clear();db.close();cleanUpload(scope)}
    }
    @Test fun photoMealDraftTerminalGetPreservesReadOnlyCorrectionsAndNeverCreatesAMeal()=runBlocking<Unit> {
        for(decision in listOf("confirmed","cancelled")) {
            val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();var scope:String?=null;var reads=0
            val transport=object:PhotoAnalysisGateway {
                override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                    beforeSend()
                    if(request is PhotoHttpRequest.Create)return BootstrapHttpResult(202,uploadAck())
                    assertTrue(request is PhotoHttpRequest.Read);reads++
                    val response=JSONObject(String(analysisRead(revision=if(reads==1)2 else 3)))
                    if(reads>1)response.put("decision_state",decision)
                    if(reads>1 && decision=="cancelled")response.put("state","failed").put("proposal",JSONObject.NULL).put("error_code","analysis_cancelled")
                    return BootstrapHttpResult(200,response.toString().toByteArray())
                }
            }
            try {
                val c=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
                c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
                val lease=c.view.value.binding!!.lease;scope=lease.storageScope
                c.uploadPhoto(lease,uploadImage(db,lease),uploadConsent(c),true);c.readPhotoAnalysis(lease)
                val row=db.photoAnalysisDao().get(lease.storageScope)!!;c.startPhotoMealDraft(lease,row.operationId,2,LocalDate.now())
                val original=c.view.value.photoMealDraft!!;c.readPhotoAnalysis(lease)
                assertFalse(c.view.value.photoCanEditProposal);assertEquals(original.items.single().id,c.view.value.photoMealDraft!!.items.single().id)
                val before=db.photoAnalysisDao().get(lease.storageScope);c.discardPhotoMealDraft(lease,row.operationId,1)
                assertEquals(before,db.photoAnalysisDao().get(lease.storageScope));assertEquals(2,reads)
                assertTrue(db.dao().achievementMeals(lease.storageScope).isEmpty());assertEquals(0,db.dao().operationCount(lease.storageScope))
            } finally {vault.clear();db.close();cleanUpload(scope)}
        }
    }
    private inner class ConfirmHarness {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway()
        val calls=mutableListOf<PhotoHttpRequest.Confirm>();var reads=0
        var handler:suspend(PhotoHttpRequest.Confirm)->BootstrapHttpResult={BootstrapHttpResult(200,ack(it))}
        var readDecision="pending"
        var readHandler:suspend(ByteArray)->ByteArray={it}
        val transport=object:PhotoAnalysisGateway {
            override suspend fun send(session:ApiSession,request:PhotoHttpRequest,beforeSend:suspend()->Unit):BootstrapHttpResult {
                assertFalse(db.inTransaction());beforeSend()
                return when(request) {
                    is PhotoHttpRequest.Create->BootstrapHttpResult(202,uploadAck())
                    is PhotoHttpRequest.Read->{reads++;BootstrapHttpResult(200,readHandler(JSONObject(String(analysisRead(revision=if(reads==1)2 else 3)))
                        .put("decision_state",readDecision).toString().toByteArray()))}
                    is PhotoHttpRequest.Cancel->error("Confirm must fence cancellation")
                    is PhotoHttpRequest.Confirm->{
                        assertTrue(PhotoAnalysisStore(context,db,lease).stored(id).confirmation!!.attempted)
                        calls+=request;handler(request)
                    }
                }
            }
        }
        lateinit var c:SessionController;lateinit var lease:OwnerLease;lateinit var id:String;lateinit var image:String
        fun clientAgain()=client(db,vault,fixture,ApiFixture(),photos=uploadReader(),photoWrites=transport)
        suspend fun prepare() {
            c=clientAgain();c.start();login(c,fixture,"fixture-A");c.bootstrap();c.readPhotoCapabilities()
            lease=c.view.value.binding!!.lease;image=uploadImage(db,lease)
            c.uploadPhoto(lease,image,uploadConsent(c),true);c.readPhotoAnalysis(lease)
            id=db.photoAnalysisDao().get(lease.storageScope)!!.operationId
            c.startPhotoMealDraft(lease,id,2,LocalDate.of(2026,10,18))
            assertTrue(c.view.value.photoConfirmation!!.canStart)
        }
        suspend fun ack(request:PhotoHttpRequest.Confirm):ByteArray {
            val body=JSONObject(String(request.body()))
            val snapshot=PhotoAnalysisStore(context,db,LocalOwnerStore(db).currentLease()).stored(id)
            return JSONObject().put("analysis_id",snapshot.receipt.analysisId).put("meal",body.getJSONObject("meal"))
                .put("drafts",body.getJSONArray("drafts")).put("provenance",snapshot.confirmation!!.journal().getJSONObject("expected_provenance"))
                .toString().toByteArray()
        }
        fun close(){vault.clear();db.close();if(::lease.isInitialized)cleanUpload(lease.storageScope)}
    }

    @Test fun photoConfirmLostAckRestoresWithoutHttpThenCommitsExactlyOneMealAndOutbox()=runBlocking<Unit> {
        val h=ConfirmHarness()
        try {
            h.prepare();h.handler={if(h.calls.size==1)throw java.io.IOException("Synthetic lost ACK") else BootstrapHttpResult(200,h.ack(it))}
            h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            assertEquals(1,h.calls.size);assertTrue(h.c.view.value.photoConfirmation!!.canRetry)
            assertFalse(h.c.view.value.photoCanEditProposal);assertFalse(h.c.view.value.photoCancellation?.canStart==true)
            assertTrue(h.db.dao().achievementMeals(h.lease.storageScope).isEmpty());assertEquals(0,h.db.dao().operationCount(h.lease.storageScope))
            val restarted=h.clientAgain();restarted.start();restarted.loadPhotoAnalysis(h.lease)
            assertEquals(1,h.calls.size);assertEquals(1,h.reads);assertTrue(restarted.view.value.photoConfirmation!!.canRetry)
            restarted.retryPhotoConfirmation(h.lease,h.id)
            assertEquals(2,h.calls.size);assertEquals(h.calls[0].key,h.calls[1].key);assertArrayEquals(h.calls[0].body(),h.calls[1].body())
            assertEquals(1,h.db.dao().achievementMeals(h.lease.storageScope).size);assertEquals(1,h.db.dao().operationCount(h.lease.storageScope))
            assertNull(h.db.photoAnalysisDao().get(h.lease.storageScope));assertNull(restarted.view.value.photoMealDraft)
            assertTrue(MealPhotoStore(context,h.db,h.lease).uploadBytes(h.image).isNotEmpty())
            assertFalse(File(context.filesDir,"photo-analysis-inputs/${h.lease.storageScope}/${h.id}.jpg").exists())
            restarted.retryPhotoConfirmation(h.lease,h.id);assertEquals(2,h.calls.size)
            assertEquals(1,h.db.dao().operationCount(h.lease.storageScope))
        } finally {h.close()}
    }
    @Test fun photoConfirm401RefreshesOnlyOnceAndRetainsTheSameRequest()=runBlocking<Unit> {
        val h=ConfirmHarness()
        try {
            h.prepare();h.handler={denied(401,"unauthorized")};h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            assertEquals(2,h.calls.size);assertSame(h.calls[0],h.calls[1]);assertEquals(2,h.fixture.calls)
            assertTrue(h.c.view.value.photoConfirmation!!.canRetry);assertFalse(h.c.view.value.photoConfirmBusy)
            assertEquals(0,h.db.dao().operationCount(h.lease.storageScope))
        } finally {h.close()}
    }
    @Test fun photoConfirmBackoffIsDurableAndRetryDoesNotAllocateAnotherDecision()=runBlocking<Unit> {
        for(status in listOf(429,503,409)) {
        val h=ConfirmHarness()
        try {
            h.prepare();h.handler={BootstrapHttpResult(status,if(status==409)denied(409,"ai_operation_busy").body else byteArrayOf(),"60")};h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            val frozen=h.db.photoAnalysisDao().get(h.lease.storageScope)!!
            assertTrue(frozen.retryAtMillis>=h.fixture.time+60_000)
            val restarted=h.clientAgain();restarted.start();restarted.loadPhotoAnalysis(h.lease);restarted.retryPhotoConfirmation(h.lease,h.id)
            assertEquals(1,h.calls.size);assertEquals(frozen,h.db.photoAnalysisDao().get(h.lease.storageScope))
            h.fixture.time+=60_001;h.handler={BootstrapHttpResult(200,h.ack(it))};restarted.retryPhotoConfirmation(h.lease,h.id)
            assertEquals(2,h.calls.size);assertArrayEquals(h.calls[0].body(),h.calls[1].body());assertEquals(h.calls[0].key,h.calls[1].key)
            assertEquals(1,h.db.dao().achievementMeals(h.lease.storageScope).size)
        } finally {h.close()}
        }
    }
    @Test fun photoConfirmWrongAckCannotPartiallyCommitAndExplicitRetryUsesOriginalBody()=runBlocking<Unit> {
        val h=ConfirmHarness()
        try {
            h.prepare();h.handler={BootstrapHttpResult(200,JSONObject(String(h.ack(it))).put("analysis_id",UUID.randomUUID().toString()).toString().toByteArray())}
            h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            assertTrue(h.c.view.value.photoConfirmation!!.canRetry);assertEquals(0,h.db.dao().operationCount(h.lease.storageScope))
            assertTrue(h.db.dao().achievementMeals(h.lease.storageScope).isEmpty())
            h.handler={BootstrapHttpResult(200,h.ack(it))};h.c.retryPhotoConfirmation(h.lease,h.id)
            assertEquals(1,h.db.dao().operationCount(h.lease.storageScope));assertEquals(h.calls[0].key,h.calls[1].key)
        } finally {h.close()}
    }
    @Test fun photoConfirmOldDialogAndEditsCannotReplaceAnUncertainDecision()=runBlocking<Unit> {
        val h=ConfirmHarness()
        try {
            h.prepare();h.c.confirmPhotoMeal(h.lease,h.id,1,1);h.c.confirmPhotoMeal(h.lease,h.id,2,2);assertTrue(h.calls.isEmpty())
            h.handler={throw java.io.IOException("Synthetic uncertainty")};h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            val frozen=h.db.photoAnalysisDao().get(h.lease.storageScope)
            h.c.confirmPhotoMeal(h.lease,h.id,2,1);h.c.renamePhotoMealDraft(h.lease,h.id,1,"Cannot replace frozen intent")
            h.c.cancelPhotoAnalysis(h.lease,h.id,2)
            assertEquals(1,h.calls.size);assertEquals(frozen,h.db.photoAnalysisDao().get(h.lease.storageScope))
        } finally {h.close()}
    }
    @Test fun photoConfirmHeldAckCannotApplyAfterLogoutAndAtoBtoA()=runBlocking<Unit> {
        val h=ConfirmHarness();val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        try {
            h.prepare();h.handler={val ack=h.ack(it);entered.complete(Unit);release.await();BootstrapHttpResult(200,ack)}
            val job=async {h.c.confirmPhotoMeal(h.lease,h.id,2,1)};withTimeout(10_000){entered.await()}
            h.c.logout();login(h.c,h.fixture,"fixture-B");h.c.logout();login(h.c,h.fixture,"fixture-A")
            release.complete(Unit);job.await()
            assertTrue(h.db.dao().achievementMeals(h.lease.storageScope).isEmpty());assertNotNull(h.db.photoAnalysisDao().get(h.lease.storageScope))
            assertNull(h.c.view.value.photoMealDraft);h.c.retryPhotoConfirmation(h.lease,h.id);assertEquals(1,h.calls.size)
        } finally {release.complete(Unit);h.close()}
    }
    @Test fun photoConfirmHeldAckCannotApplyAfterContextRevisionChanges()=runBlocking<Unit> {
        val h=ConfirmHarness();val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        try {
            h.prepare();h.handler={val ack=h.ack(it);entered.complete(Unit);release.await();BootstrapHttpResult(200,ack)}
            val job=async {h.c.confirmPhotoMeal(h.lease,h.id,2,1)};withTimeout(10_000){entered.await()}
            val binding=h.db.bootstrapDao().binding(h.lease.storageScope)!!
            h.db.bootstrapDao().update(binding.copy(contextRevision=binding.contextRevision+1,requiresRecovery=true))
            release.complete(Unit);job.await()
            assertEquals(0,h.db.dao().operationCount(h.lease.storageScope));assertTrue(h.db.dao().achievementMeals(h.lease.storageScope).isEmpty())
            assertNotNull(h.db.photoAnalysisDao().get(h.lease.storageScope));assertNull(h.c.view.value.photoConfirmation)
        } finally {release.complete(Unit);h.close()}
    }
    @Test fun photoConfirmGetConfirmedDoesNotReplaceOwnAckOrImplicitlyWriteDiary()=runBlocking<Unit> {
        val h=ConfirmHarness()
        try {
            h.prepare();h.handler={throw java.io.IOException("Synthetic uncertainty")};h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            h.readDecision="confirmed";h.c.readPhotoAnalysis(h.lease)
            assertTrue(h.c.view.value.photoConfirmation!!.canRetry);assertEquals(0,h.db.dao().operationCount(h.lease.storageScope))
            h.handler={BootstrapHttpResult(200,h.ack(it))};h.c.retryPhotoConfirmation(h.lease,h.id)
            assertEquals(1,h.db.dao().operationCount(h.lease.storageScope));assertArrayEquals(h.calls[0].body(),h.calls[1].body())
        } finally {h.close()}
    }
    @Test fun photoConfirmConflictNeverCreatesANewKeyOrMealAndRecoveryIsExplicit()=runBlocking<Unit> {
        for(code in listOf("proposal_revision_conflict","photo_catalog_choice_changed","sync_epoch_changed")) {
            val h=ConfirmHarness()
            try {
                h.prepare();h.handler={denied(409,code)};h.c.confirmPhotoMeal(h.lease,h.id,2,1)
                h.c.retryPhotoConfirmation(h.lease,h.id);h.c.confirmPhotoMeal(h.lease,h.id,2,1)
                assertEquals(1,h.calls.size);assertEquals(0,h.db.dao().operationCount(h.lease.storageScope))
                assertNotNull(h.db.photoAnalysisDao().get(h.lease.storageScope))
                if(code=="sync_epoch_changed")assertTrue(h.db.bootstrapDao().binding(h.lease.storageScope)!!.requiresRecovery)
                else {assertTrue(h.c.view.value.photoConfirmation!!.rejected);assertFalse(h.c.view.value.photoConfirmation!!.canRetry)}
            } finally {h.close()}
        }
    }


    @Test fun photoConfirmStoppingScreenFencesHeldAckAndExplicitRetryCommitsOnce()=runBlocking<Unit> {
        val h=ConfirmHarness();val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        try {
            h.prepare();h.handler={val ack=h.ack(it);entered.complete(Unit);release.await();BootstrapHttpResult(200,ack)}
            val job=async {h.c.confirmPhotoMeal(h.lease,h.id,2,1)};withTimeout(10_000){entered.await()}
            h.c.stopPhotoAnalysis(h.lease,clearPreview=true);release.complete(Unit);job.await()
            assertEquals(0,h.db.dao().operationCount(h.lease.storageScope));assertNull(h.c.view.value.photoConfirmation)
            assertNotNull(h.db.photoAnalysisDao().get(h.lease.storageScope))
            h.c.loadPhotoAnalysis(h.lease);assertTrue(h.c.view.value.photoConfirmation!!.canRetry)
            h.handler={BootstrapHttpResult(200,h.ack(it))};h.c.retryPhotoConfirmation(h.lease,h.id)
            assertEquals(2,h.calls.size);assertEquals(h.calls[0].key,h.calls[1].key)
            assertArrayEquals(h.calls[0].body(),h.calls[1].body());assertEquals(1,h.db.dao().operationCount(h.lease.storageScope))
        } finally {release.complete(Unit);h.close()}
    }
    @Test fun photoReopenRequiresPostRejectionGetThenExplicitLocalReviewAndANewApprovedKey()=runBlocking<Unit> {
        val h=ConfirmHarness()
        try {
            h.prepare();h.handler={denied(409,"proposal_revision_conflict")};h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            val frozen=h.db.photoAnalysisDao().get(h.lease.storageScope)!!
            val original=h.db.photoConfirmationHistoryDao().get(h.lease.storageScope,h.calls.single().key!!)!!
            assertFalse(h.c.view.value.photoConfirmation!!.canReopen)
            h.c.reopenPhotoConfirmation(h.lease,h.id,2,1);assertEquals(frozen,h.db.photoAnalysisDao().get(h.lease.storageScope))
            h.c.readPhotoAnalysis(h.lease);assertTrue(h.c.view.value.photoConfirmation!!.canReopen)
            val restarted=h.clientAgain();restarted.start();restarted.loadPhotoAnalysis(h.lease)
            assertEquals(2,h.reads);assertEquals(1,h.calls.size);assertTrue(restarted.view.value.photoConfirmation!!.canReopen)
            restarted.reopenPhotoConfirmation(h.lease,h.id,3,1)
            assertEquals(2L,restarted.view.value.photoMealDraft!!.editRevision);assertTrue(restarted.view.value.photoCanEditProposal)
            assertEquals(1,h.calls.size);assertEquals(2,h.reads);assertEquals(0,h.db.dao().operationCount(h.lease.storageScope))
            restarted.confirmPhotoMeal(h.lease,h.id,3,1);restarted.reopenPhotoConfirmation(h.lease,h.id,3,1)
            assertEquals(1,h.calls.size)
            restarted.renamePhotoMealDraft(h.lease,h.id,2,"Nowa sprawdzona porcja")
            h.handler={BootstrapHttpResult(200,h.ack(it))};restarted.confirmPhotoMeal(h.lease,h.id,3,3)
            assertEquals(2,h.calls.size);assertNotEquals(h.calls[0].key,h.calls[1].key)
            assertEquals(1,h.db.dao().operationCount(h.lease.storageScope));assertEquals(1,h.db.dao().achievementMeals(h.lease.storageScope).size)
            assertNull(h.db.photoAnalysisDao().get(h.lease.storageScope))
            assertEquals(original.decisionJson,h.db.photoConfirmationHistoryDao().get(h.lease.storageScope,h.calls[0].key!!)!!.decisionJson)
        } finally {h.close()}
    }
    @Test fun photoReopenLocalReviewDoesNotRefreshExpiredAccessOrSendAnyRequest()=runBlocking<Unit> {
        val h=ConfirmHarness()
        try {
            h.prepare();h.handler={denied(409,"photo_catalog_choice_changed")};h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            h.c.readPhotoAnalysis(h.lease);val oidc=h.fixture.calls;val reads=h.reads
            h.fixture.time+=400_000;h.c.loadPhotoAnalysis(h.lease)
            assertFalse(h.c.view.value.hasSession);assertTrue(h.c.view.value.photoConfirmation!!.canReopen)
            h.c.reopenPhotoConfirmation(h.lease,h.id,3,1)
            assertTrue(h.c.view.value.photoCanEditProposal);assertEquals(2L,h.c.view.value.photoMealDraft!!.editRevision)
            assertEquals(oidc,h.fixture.calls);assertEquals(reads,h.reads);assertEquals(1,h.calls.size)
            assertEquals(0,h.db.dao().operationCount(h.lease.storageScope))
        } finally {h.close()}
    }
    @Test fun photoReopenNeverReplacesAnUncertainOrUnsafeDecisionEvenAfterGet()=runBlocking<Unit> {
        for(code in listOf("uncertain","idempotency_key_reused","analysis_already_confirmed","photo_confirm_rejected")) {
            val h=ConfirmHarness()
            try {
                h.prepare();h.handler={if(code=="uncertain")throw java.io.IOException("Synthetic uncertainty") else denied(409,code)}
                h.c.confirmPhotoMeal(h.lease,h.id,2,1);h.c.readPhotoAnalysis(h.lease)
                val before=h.db.photoAnalysisDao().get(h.lease.storageScope)
                assertFalse(h.c.view.value.photoConfirmation!!.canReopen)
                h.c.reopenPhotoConfirmation(h.lease,h.id,3,1)
                assertEquals(before,h.db.photoAnalysisDao().get(h.lease.storageScope));assertEquals(1,h.calls.size)
                assertEquals(0,h.db.dao().operationCount(h.lease.storageScope));assertFalse(h.c.view.value.photoCanEditProposal)
            } finally {h.close()}
        }
    }
    @Test fun photoReopenGetStartedBeforeRejectionCannotSupplyFreshReadProof()=runBlocking<Unit> {
        val h=ConfirmHarness();val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        try {
            h.prepare();h.handler={throw java.io.IOException("Synthetic uncertainty")};h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            h.readHandler={body->entered.complete(Unit);release.await();body}
            val job=async {h.c.readPhotoAnalysis(h.lease)};withTimeout(10_000){entered.await()}
            val store=PhotoAnalysisStore(context,h.db,h.lease)
            store.acceptConfirmationPrepared(store.prepareConfirmationRejection(h.id,"photo_catalog_choice_changed",h.calls.single()))
            release.complete(Unit);job.await();h.c.loadPhotoAnalysis(h.lease)
            assertFalse(h.c.view.value.photoConfirmation!!.canReopen)
            assertNull(h.db.photoConfirmationHistoryDao().get(h.lease.storageScope,h.calls.single().key!!)!!.lastReadSnapshotHash)
            h.readHandler={it};h.c.readPhotoAnalysis(h.lease);assertTrue(h.c.view.value.photoConfirmation!!.canReopen)
            assertEquals(1,h.calls.size);assertEquals(0,h.db.dao().operationCount(h.lease.storageScope))
        } finally {release.complete(Unit);h.close()}
    }
    @Test fun photoReopenStaleAccountCallbackCannotChangeTheOriginalArchivedDecision()=runBlocking<Unit> {
        val h=ConfirmHarness()
        try {
            h.prepare();h.handler={denied(409,"photo_catalog_choice_changed")};h.c.confirmPhotoMeal(h.lease,h.id,2,1)
            h.c.readPhotoAnalysis(h.lease)
            val before=h.db.photoAnalysisDao().get(h.lease.storageScope)
            val history=h.db.photoConfirmationHistoryDao().get(h.lease.storageScope,h.calls.single().key!!)
            h.c.logout();login(h.c,h.fixture,"fixture-B");h.c.logout();login(h.c,h.fixture,"fixture-A")
            h.c.reopenPhotoConfirmation(h.lease,h.id,3,1)
            assertEquals(before,h.db.photoAnalysisDao().get(h.lease.storageScope))
            assertEquals(history,h.db.photoConfirmationHistoryDao().get(h.lease.storageScope,h.calls.single().key!!))
            assertNull(h.c.view.value.photoMealDraft);assertEquals(1,h.calls.size)
        } finally {h.close()}
    }


    private inner class PushHarness(private val projectDiary:Boolean=false) {
        val db=memory();val vault=SessionVault(context,name());val fixture=FixtureGateway();val api=ApiFixture();val copies=SnapshotFixture()
        val calls=mutableListOf<PushBatch>();var before:suspend()->Unit={}
        var answer:suspend(PushBatch,Int)->BootstrapHttpResult={batch,_->BootstrapHttpResult(200,receipt(batch))}
        val transport=object:MealPushGateway {
            override suspend fun post(session:ApiSession,batch:PushBatch,beforeSend:suspend()->Unit):BootstrapHttpResult {
                assertFalse(db.inTransaction());before();beforeSend()
                assertTrue(db.pushDao().pending(session.lease.storageScope).single().attempted)
                calls+=batch;return answer(batch,calls.size)
            }
        }
        lateinit var c:SessionController;lateinit var lease:OwnerLease;lateinit var meal:String;lateinit var item:String
        fun again()=client(db,vault,fixture,api,snapshots=copies,pushes=transport,projectDiary=projectDiary)
        suspend fun prepare(full:Boolean=true) {
            c=again();c.start();login(c,fixture,"fixture-A");c.bootstrap();lease=c.view.value.binding!!.lease
            if(full)c.downloadSnapshot()
            val ids=enqueue();meal=ids.first;item=ids.second
        }
        suspend fun enqueue():Pair<String,String> {
            val bytes=androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context.assets
                .open("materialized-meal-operation.json").use {it.readBytes()}
            val source=JSONObject(String(bytes)).getJSONObject("payload")
            val id=UUID.randomUUID().toString();val itemId=UUID.randomUUID().toString();val op=UUID.randomUUID().toString()
            source.getJSONArray("items").getJSONObject(0).put("item_id",itemId)
            val schema=CanonicalMealRows.schema(context);val wire=MealWire.read(StrictJson.canonical(source),schema)
            val binding=db.bootstrapDao().binding(lease.storageScope)!!;val ctx=CanonicalMealRows.context(binding)
            db.withTransaction {
                db.dao().insertMeal(CanonicalMealRows.meal(id,lease.storageScope,wire,ctx))
                CanonicalMealRows.items(id,wire).forEach {db.dao().insertItem(it)}
                db.dao().enqueue(OutboxEntity(op,lease.storageScope,"meal",id,"upsert",null,wire.canonical,
                    "2026-10-19T00:00:00Z","pending","sync-v1",MealWire.operation(op,id,binding.syncEpoch,null,wire.canonical,schema),ctx))
            }
            return id to itemId
        }
        fun receipt(batch:PushBatch,status:String="accepted"):ByteArray {
            val request=batch.json();val operations=request.getJSONArray("operations");val results=JSONArray()
            for(i in 0 until operations.length()) {
                val op=operations.getJSONObject(i)
                results.put(JSONObject().put("operation_id",op.getString("operation_id")).put("entity_id",op.getString("entity_id"))
                    .put("status",status).put("revision",if(op.isNull("base_revision"))1 else op.getInt("base_revision")+1)
                    .put("recovery_mapping",JSONObject.NULL))
            }
            return JSONObject().put("sync_epoch",request.getString("sync_epoch")).put("server_time","2026-10-19T00:00:00Z")
                .put("results",results).toString().toByteArray()
        }
        suspend fun revision()=db.dao().meal(meal,lease.storageScope)!!.meal.serverRevision
        fun close(){vault.clear();db.close()}
    }
    @Test fun manualConsumptionAndAckGatePreserveFrozenWireAcrossCancelledAcknowledgementAndReplay()=runBlocking<Unit> {
        val h=PushHarness(projectDiary=true);var pending:Job?=null;var ticket:MealPushAckGate.Ticket?=null
        try {
            val day=LocalDate.now();val guestId=UUID.randomUUID().toString()
            val guest=DiaryRepository(h.db,context).apply {initialize()}
            guest.add("basic-banana",50.0,MealType.SNACK,day,guestId)
            val guestBefore=h.db.dao().day("guest",day.toString()).first()
            val guestQueue=h.db.dao().operationCount("guest")
            h.c=h.again();h.c.start();login(h.c,h.fixture,"fixture-A");h.c.bootstrap()
            h.lease=h.c.view.value.binding!!.lease;h.c.downloadSnapshot()
            assertNotNull(h.c.view.value.diaryApplication)
            h.meal=UUID.randomUUID().toString();val product=UUID.randomUUID().toString()
            DiaryRepository(h.db,context,h.lease).addCustomProduct(
                CustomProductDraft("Syntetyczny posiłek",100.5,null,0.0,12.25,"Etykieta testowa"),
                150.5,MealType.LUNCH,day,h.meal,product)
            h.item=h.db.dao().meal(h.meal,h.lease.storageScope)!!.items.single().id
            val store=MealPushStore(h.db,CanonicalMealRows.schema(context))
            val frozen=checkNotNull(store.prepare(h.lease));val operation=frozen.batch.json().getJSONArray("operations")
            assertEquals(1,operation.length());assertEquals(h.meal,operation.getJSONObject(0).getString("entity_id"))
            val payload=operation.getJSONObject(0).getJSONObject("payload").getJSONArray("items").getJSONObject(0)
            assertTrue(payload.isNull("product"));assertEquals("manual",payload.getString("nutrition_origin"))
            assertEquals("150.5",payload.getJSONObject("quantity").getString("amount"))
            assertTrue(payload.getJSONObject("nutrition_per_100").isNull("protein_g"))
            assertEquals("0",payload.getJSONObject("nutrition_per_100").getString("fat_g"))
            val held=MealPushObservation.ack.arm(frozen.id,frozen.row.requestHash);ticket=held
            pending=launch(start=CoroutineStart.UNDISPATCHED){h.c.synchronizeMeals(h.lease)}
            withTimeout(10_000){held.held.await()}
            assertEquals(listOf("held"),held.events())
            assertTrue(held.httpReceipts().isEmpty()) // Fixture transport is not evidence of a real HTTP receipt or COMMIT.
            val waiting=h.db.pushDao().batch(frozen.id)!!
            assertTrue(waiting.attempted);assertNull(waiting.responseJson);assertEquals(0,h.revision())
            assertEquals(frozen.row.requestJson,waiting.requestJson)
            assertEquals("pending",h.db.dao().canonicalMealOperations(h.lease.storageScope,h.meal).single().status)
            pending.cancelAndJoin();pending=null
            assertEquals("cancelled",withTimeout(10_000){held.outcome.await()})
            assertNull(h.db.pushDao().batch(frozen.id)!!.responseJson)
            h.c=h.again();h.c.start()
            h.answer={batch,_->BootstrapHttpResult(200,h.receipt(batch,"already_applied"))}
            // The normal post-ACK pull now projects the same server meal into Room as well.
            h.copies.answer={
                val copy=JSONObject(String(snapshotAnswer().body))
                    .put("server_time","2026-10-23T08:00:00Z")
                    .put("entities",JSONArray().put(JSONObject().put("entity_type","meal").put("entity_id",h.meal)
                        .put("revision",1).put("deleted",false).put("payload",operation.getJSONObject(0).getJSONObject("payload"))))
                BootstrapHttpResult(200,copy.toString().toByteArray())
            }
            h.c.synchronizeMeals(h.lease)
            assertEquals(2,h.calls.size);assertArrayEquals(frozen.batch.body(),h.calls[0].body())
            assertArrayEquals(h.calls[0].body(),h.calls[1].body());assertEquals(1,h.revision())
            assertEquals("complete",h.db.pushDao().batch(frozen.id)!!.state)
            assertEquals("acked",h.db.dao().operation(operation.getJSONObject(0).getString("operation_id"))!!.status)
            assertTrue(h.db.dao().canonicalMealOperations(h.lease.storageScope,h.meal).isEmpty())
            val saved=h.db.dao().meal(h.meal,h.lease.storageScope)!!.items.single()
            assertEquals(h.item,saved.id);assertEquals(product,saved.productId)
            assertEquals("Etykieta testowa",h.db.dao().product(product,h.lease.storageScope)!!.source)
            assertEquals(2,h.db.dao().operationCount(h.lease.storageScope)) // Private product draft and its independent Meal.
            val applied=checkNotNull(h.c.view.value.diaryApplication)
            assertEquals(1,applied.included);assertEquals(0,applied.held)
            val observed=h.db.serverDiaryDao().records(h.lease.storageScope).single()
            assertEquals("meal",observed.entityType);assertEquals(h.meal,observed.entityId)
            assertEquals(1,observed.knownRevision);assertEquals("applied",observed.disposition)
            assertEquals(applied.runId,observed.runId)
            assertEquals(guestBefore,h.db.dao().day("guest",day.toString()).first())
            assertEquals(guestQueue,h.db.dao().operationCount("guest"))
        }finally{pending?.cancelAndJoin();ticket?.let {MealPushObservation.ack.disarm(it)};h.close()}
    }
    @Test fun mealPushLostAckRestartResendsIdenticalBatchThenPullsWithoutChangingGuest()=runBlocking<Unit> {
        val h=PushHarness()
        try {
            h.prepare();val guest=LocalOwnerStore(h.db).ensureGuest();val guestCount=h.db.dao().operationCount(guest.storageScope)
            h.answer={batch,n->if(n==1)throw java.io.IOException("Synthetic lost ACK") else BootstrapHttpResult(200,h.receipt(batch,"already_applied"))}
            h.c.synchronizeMeals(h.lease);assertEquals(0,h.revision());val saved=h.db.pushDao().pending(h.lease.storageScope).single()
            assertTrue(saved.attempted);assertNull(saved.responseJson);assertEquals(1,h.copies.calls.size)
            h.c=h.again();h.c.start();assertTrue(h.c.view.value.mealPush!!.persistedBatch);assertFalse(h.c.view.value.mealPushBusy)
            h.c.synchronizeMeals(h.lease)
            assertEquals(2,h.calls.size);assertArrayEquals(h.calls[0].body(),h.calls[1].body())
            assertEquals(1,h.revision());assertEquals("complete",h.db.pushDao().batch(saved.id)!!.state)
            assertTrue(h.db.dao().canonicalMealOperations(h.lease.storageScope,h.meal).all {it.status=="acked"})
            assertEquals(guestCount,h.db.dao().operationCount(guest.storageScope));assertEquals(2,h.copies.calls.size)
            assertEquals(0,h.c.view.value.mealPush!!.pending)
        }finally{h.close()}
    }
    @Test fun mealPushRequiresFullSnapshotBeforeFreezingAndSingleFlightBlocksOtherHttp()=runBlocking<Unit> {
        val h=PushHarness();val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        try {
            h.prepare(false);h.c.synchronizeMeals(h.lease);assertTrue(h.calls.isEmpty());assertTrue(h.db.pushDao().pending(h.lease.storageScope).isEmpty())
            assertFalse(h.db.dao().canonicalMealOperations(h.lease.storageScope,h.meal).single().attempted)
            h.c.downloadSnapshot();h.answer={batch,_->entered.complete(Unit);release.await();BootstrapHttpResult(200,h.receipt(batch))}
            coroutineScope {
                val task=launch(start=CoroutineStart.UNDISPATCHED){h.c.synchronizeMeals(h.lease)};entered.await()
                assertTrue(h.c.view.value.mealPushBusy);h.c.synchronizeMeals(h.lease);h.c.bootstrap();h.c.downloadSnapshot();h.c.readProfile()
                assertEquals(1,h.calls.size);assertEquals(1,h.api.calls.size);assertEquals(1,h.copies.calls.size)
                release.complete(Unit);task.join()
            }
            assertEquals(1,h.revision());assertFalse(h.c.view.value.mealPushBusy)
        }finally{release.complete(Unit);h.close()}
    }
    @Test fun mealPushRefreshesOnceAfter401AndKeepsExactEnvelope()=runBlocking<Unit> {
        val h=PushHarness()
        try {
            h.prepare();h.answer={batch,n->if(n==1)syncDenied(401,"unauthorized") else BootstrapHttpResult(200,h.receipt(batch))}
            h.c.synchronizeMeals(h.lease);assertEquals(2,h.fixture.calls);assertEquals(2,h.calls.size)
            assertArrayEquals(h.calls[0].body(),h.calls[1].body());assertEquals(1,h.revision())
        }finally{h.close()}
    }
    @Test fun mealPushRepeated401AndInitiallyExpiredAccessCannotRefreshInALoop()=runBlocking<Unit> {
        for(expired in listOf(false,true)) {
            val h=PushHarness()
            try {
                h.prepare();if(expired)h.fixture.time+=301_000
                h.answer={_,_->syncDenied(401,"unauthorized")};h.c.synchronizeMeals(h.lease)
                assertEquals(2,h.fixture.calls);assertEquals(if(expired)1 else 2,h.calls.size)
                assertEquals(0,h.revision());assertTrue(h.db.pushDao().pending(h.lease.storageScope).single().attempted)
                assertFalse(h.c.view.value.mealPushBusy)
            }finally{h.close()}
        }
    }
    @Test fun mealPushBackoffIsDurableAcrossRestartAndDoesNotShortenRetryAfter()=runBlocking<Unit> {
        for(status in listOf(429,503)) {
            val h=PushHarness()
            try {
                h.prepare();h.answer={_,_->BootstrapHttpResult(status,ByteArray(0),"86400")}
                h.c.synchronizeMeals(h.lease);val expected=h.fixture.time+86_400_000
                assertEquals(expected,h.c.view.value.mealPushRetryAt);assertEquals(1,h.calls.size)
                h.c=h.again();h.c.start();h.c.synchronizeMeals(h.lease);assertEquals(1,h.calls.size)
                h.fixture.time=expected-1;h.c.synchronizeMeals(h.lease);assertEquals(1,h.calls.size)
                h.fixture.time=expected;h.answer={batch,_->BootstrapHttpResult(200,h.receipt(batch))}
                h.c.synchronizeMeals(h.lease);assertEquals(2,h.calls.size);assertEquals(1,h.revision())
                assertArrayEquals(h.calls[0].body(),h.calls[1].body())
            }finally{h.close()}
        }
    }
    @Test fun mealPushLateAckAfterLogoutAToBToACannotAcknowledgeOriginalOrNewOwner()=runBlocking<Unit> {
        val h=PushHarness();val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        try {
            h.prepare();h.answer={batch,_->entered.complete(Unit);release.await();BootstrapHttpResult(200,h.receipt(batch))}
            coroutineScope {
                val task=launch(start=CoroutineStart.UNDISPATCHED){h.c.synchronizeMeals(h.lease)};entered.await()
                h.c.logout();login(h.c,h.fixture,"fixture-B");login(h.c,h.fixture,"fixture-A")
                val current=h.c.view.value.binding!!.lease;assertNotEquals(h.lease,current)
                release.complete(Unit);task.join();assertEquals(0,h.revision());assertEquals(1,h.copies.calls.size)
                h.c.synchronizeMeals(h.lease);assertEquals(1,h.calls.size)
                assertTrue(h.db.dao().canonicalMealOperations(h.lease.storageScope,h.meal).all{it.status=="pending"})
            }
        }finally{release.complete(Unit);h.close()}
    }
    @Test fun mealPushPreflightAndHeldAckRejectChangedContextWithoutMutatingQueue()=runBlocking<Unit> {
        for(preflight in listOf(true,false)) {
            val h=PushHarness()
            try {
                h.prepare()
                suspend fun change(){val b=h.db.bootstrapDao().binding(h.lease.storageScope)!!;h.db.bootstrapDao().update(b.copy(contextRevision=b.contextRevision+1))}
                if(preflight)h.before={change()} else h.answer={batch,_->change();BootstrapHttpResult(200,h.receipt(batch))}
                h.c.synchronizeMeals(h.lease);assertEquals(if(preflight)0 else 1,h.calls.size)
                assertEquals(0,h.revision());val batch=h.db.pushDao().pending(h.lease.storageScope).single()
                assertEquals(!preflight,batch.attempted);assertNull(batch.responseJson);assertEquals(1,h.copies.calls.size)
            }finally{h.close()}
        }
    }
    @Test fun mealPushInFlightPortionEditBecomesNextOperationWithAcknowledgedRevision()=runBlocking<Unit> {
        val h=PushHarness()
        try {
            h.prepare();h.answer={batch,n->
                if(n==1)DiaryRepository(h.db,context,h.lease).editItem(h.meal,h.item,200.000001,"200.000001")
                BootstrapHttpResult(200,h.receipt(batch))}
            h.c.synchronizeMeals(h.lease);assertEquals(2,h.calls.size);assertEquals(2,h.revision())
            val first=h.calls[0].json().getJSONArray("operations").getJSONObject(0)
            val next=h.calls[1].json().getJSONArray("operations").getJSONObject(0)
            assertEquals(first.getString("entity_id"),next.getString("entity_id"));assertNotEquals(first.getString("operation_id"),next.getString("operation_id"))
            assertEquals(1,next.getInt("base_revision"));assertEquals("200.000001",next.getJSONObject("payload").getJSONArray("items").getJSONObject(0).getJSONObject("quantity").getString("amount"))
            assertEquals(h.item,h.db.dao().meal(h.meal,h.lease.storageScope)!!.items.single().id)
            assertTrue(h.db.dao().canonicalMealOperations(h.lease.storageScope,h.meal).all{it.status=="acked"})
        }finally{h.close()}
    }
    @Test fun mealPushMalformedLaterAckCannotAcknowledgePrefixAndCommitFailureRollsBackEverything()=runBlocking<Unit> {
        for(malformed in listOf(true,false)) {
            val h=PushHarness()
            try {
                h.prepare();if(malformed)h.enqueue()
                if(malformed)h.answer={batch,_->val json=JSONObject(String(h.receipt(batch)));json.getJSONArray("results").getJSONObject(1).put("revision",99);BootstrapHttpResult(200,json.toString().toByteArray())}
                else h.db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_push_ack BEFORE UPDATE ON sync_push_batches WHEN NEW.state='complete' BEGIN SELECT RAISE(ABORT,'synthetic full'); END")
                h.c.synchronizeMeals(h.lease);assertEquals(0,h.revision());assertEquals(1,h.copies.calls.size)
                val row=h.db.pushDao().pending(h.lease.storageScope).single();assertNull(row.responseJson)
                assertTrue(h.db.dao().canonicalMealOperations(h.lease.storageScope,h.meal).all{it.status=="pending"})
                if(!malformed)h.db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_push_ack")
                h.answer={batch,_->BootstrapHttpResult(200,h.receipt(batch,"already_applied"))};h.c.synchronizeMeals(h.lease)
                assertEquals(1,h.revision());assertArrayEquals(h.calls[0].body(),h.calls[1].body())
            }finally{h.close()}
        }
    }
    @Test fun mealPushContextRefusalAndDeletingRemainBlockedAfterRestartWithoutLosingBatch()=runBlocking<Unit> {
        for(code in listOf("sync_epoch_changed","account_generation_changed","sync_reconciliation_required","account_deleting","invalid_sync_token")) {
            val h=PushHarness()
            try {
                h.prepare();val status=when(code){"account_deleting"->403;"invalid_sync_token"->422;else->409}
                h.answer={_,_->syncDenied(status,code)};h.c.synchronizeMeals(h.lease)
                val saved=h.db.pushDao().pending(h.lease.storageScope).single();assertTrue(saved.attempted);assertNull(saved.responseJson)
                h.c=h.again();h.c.start();h.c.synchronizeMeals(h.lease);assertEquals(1,h.calls.size);assertEquals(0,h.revision())
                if(code=="account_deleting")assertTrue(h.c.view.value.snapshot!!.blocked)
                else {assertTrue(h.c.view.value.requiresRecovery);assertTrue(h.c.view.value.snapshot!!.needsBootstrap)}
                assertEquals(saved,h.db.pushDao().batch(saved.id))
            }finally{h.close()}
        }
    }
    @Test fun mealPushAckSurvivesFailedFollowingPullWithoutResendingConfirmedOperations()=runBlocking<Unit> {
        val h=PushHarness()
        try {
            h.prepare();h.copies.answer={if(it==1)snapshotAnswer() else throw java.io.IOException("Synthetic pull loss")}
            h.c.synchronizeMeals(h.lease);assertEquals(1,h.calls.size);assertEquals(1,h.revision())
            assertTrue(h.db.pushDao().pending(h.lease.storageScope).isEmpty());assertEquals(0,h.c.view.value.mealPush!!.pending)
            h.c.synchronizeMeals(h.lease);assertEquals(1,h.calls.size)
            h.copies.answer={snapshotAnswer()};h.c.downloadSnapshot();assertEquals(1,h.calls.size);assertEquals(3,h.copies.calls.size)
        }finally{h.close()}
    }
    @Test fun mealPushMixedAckReportsConflictWithoutReplacingLocalMeal()=runBlocking<Unit> {
        val h=PushHarness()
        try {
            h.prepare();val other=h.enqueue();val original=h.db.dao().meal(other.first,h.lease.storageScope)
            h.answer={batch,_->
                val json=JSONObject(String(h.receipt(batch)));val conflict=json.getJSONArray("results").getJSONObject(1)
                conflict.remove("revision");conflict.put("status","conflict").put("code","revision_conflict")
                    .put("message","fixture").put("current",JSONObject.NULL).put("details_retained",true)
                BootstrapHttpResult(200,json.toString().toByteArray())}
            h.c.synchronizeMeals(h.lease);assertEquals(1,h.revision())
            assertEquals(original,h.db.dao().meal(other.first,h.lease.storageScope))
            assertEquals(1,h.c.view.value.mealPush!!.refused);assertEquals(0,h.c.view.value.mealPush!!.pending)
            assertEquals(2,h.copies.calls.size);assertTrue(h.c.view.value.mealPushMessage!!.contains("Wymagają uzgodnienia: 1"))
        }finally{h.close()}
    }
    @Test fun mealPushCancellationAndManualRefreshLeaveUnknownBatchPending()=runBlocking<Unit> {
        for(cancel in listOf(true,false)) {
            val h=PushHarness();val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
            try {
                h.prepare();h.answer={batch,_->entered.complete(Unit);release.await();BootstrapHttpResult(200,h.receipt(batch))}
                coroutineScope {
                    val task=launch(start=CoroutineStart.UNDISPATCHED){h.c.synchronizeMeals(h.lease)};entered.await()
                    if(cancel)task.cancelAndJoin() else {h.c.refresh();release.complete(Unit);task.join()}
                }
                assertEquals(0,h.revision());assertTrue(h.db.pushDao().pending(h.lease.storageScope).single().attempted)
                assertFalse(h.c.view.value.mealPushBusy);assertEquals(1,h.copies.calls.size)
            }finally{release.complete(Unit);h.close()}
        }
    }


    @Test fun mealPushBatchBackoffSurvivesLogoutOtherAccountAndRestart()=runBlocking<Unit> {
        val h=PushHarness()
        try {
            h.prepare();h.answer={_,_->BootstrapHttpResult(429,ByteArray(0),"86400")}
            h.c.synchronizeMeals(h.lease);val deadline=h.fixture.time+86_400_000
            val saved=h.db.pushDao().pending(h.lease.storageScope).single();assertEquals(deadline,saved.retryAtMillis)
            h.c.logout();login(h.c,h.fixture,"fixture-B");assertEquals(0L,h.c.view.value.mealPushRetryAt)
            login(h.c,h.fixture,"fixture-A");val active=h.c.view.value.binding!!.lease
            assertEquals(deadline,h.c.view.value.mealPushRetryAt);h.c.synchronizeMeals(active);assertEquals(1,h.calls.size)
            h.c=h.again();h.c.start();h.c.synchronizeMeals(active);assertEquals(1,h.calls.size)
            assertEquals(saved,h.db.pushDao().batch(saved.id))
            h.fixture.time=deadline;h.answer={batch,_->BootstrapHttpResult(200,h.receipt(batch))}
            h.c.synchronizeMeals(active);assertEquals(2,h.calls.size);assertEquals(1,h.revision())
            assertArrayEquals(h.calls[0].body(),h.calls[1].body())
        }finally{h.close()}
    }

    @Test fun mealPushWithoutPullSeparatesDurableAckFromFollowingArchive()=runBlocking<Unit> {
        val h=PushHarness()
        try {
            h.prepare()
            h.c=client(h.db,h.vault,h.fixture,h.api,snapshots=h.copies,pushes=h.transport,projectDiary=true)
            h.c.start();h.c.applyDiaryCopy(h.lease)
            val request=MealPushStore(h.db,CanonicalMealRows.schema(context)).prepare(h.lease)!!
            val payload=request.batch.json().getJSONArray("operations").getJSONObject(0).getJSONObject("payload")
            val date=payload.getString("local_date");val dayId=UUID.randomUUID().toString()
            assertNull(h.db.dao().currentDiaryDay(h.lease.storageScope,date))
            h.copies.answer={
                val copy=JSONObject(String(snapshotAnswer().body)).put("server_time","2026-10-23T08:00:00Z")
                    .put("entities",JSONArray()
                        .put(JSONObject().put("entity_type","meal").put("entity_id",h.meal).put("revision",1)
                            .put("deleted",false).put("payload",payload))
                        .put(JSONObject().put("entity_type","diary_day").put("entity_id",dayId).put("revision",1)
                            .put("deleted",false).put("payload",JSONObject().put("local_date",date)
                                .put("time_zone",payload.getString("time_zone")).put("declared_complete",false))))
                BootstrapHttpResult(200,copy.toString().toByteArray())
            }
            val copiesBefore=h.copies.calls.size
            h.c.synchronizeMealsWithoutPull(h.lease)
            assertEquals(1,h.calls.size);assertEquals(1,h.revision())
            assertEquals(copiesBefore,h.copies.calls.size)
            assertNull(h.db.dao().currentDiaryDay(h.lease.storageScope,date))
            assertTrue(h.db.dao().canonicalMealOperations(h.lease.storageScope,h.meal).all{it.status=="acked"})
            assertTrue(h.db.pushDao().pending(h.lease.storageScope).isEmpty())
            val frozen=h.db.pushDao().batch(request.id)
            h.c.downloadSnapshot(h.lease)
            assertEquals(copiesBefore+1,h.copies.calls.size);assertEquals(1,h.calls.size)
            assertEquals(1,h.revision());assertEquals(frozen,h.db.pushDao().batch(request.id))
            val day=h.db.dao().currentDiaryDay(h.lease.storageScope,date)!!
            assertEquals(dayId,day.id);assertFalse(day.declaredComplete);assertEquals(1,day.localRevision)
            val observed=h.db.serverDiaryDao().records(h.lease.storageScope).single{it.entityType=="diary_day"}
            assertEquals(dayId,observed.localId);assertEquals(1,observed.knownRevision)
            assertEquals("applied",observed.disposition)
        }finally{h.close()}
    }
}
