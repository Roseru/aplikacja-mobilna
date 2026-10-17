package pl.roseru.kalorie.session

import android.content.Intent
import android.net.Uri
import androidx.room.withTransaction
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import net.openid.appauth.*
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.data.*
import java.util.UUID

data class SessionBinding(val owner: LocalOwnerEntity, val lease: OwnerLease)
data class SessionView(val binding: SessionBinding? = null, val busy: Boolean = false,
    val pendingLogin: Boolean = false, val configured: Boolean = false, val hasSession: Boolean = false,
    val message: String? = null, val apiConfigured: Boolean = false, val bootstrapBusy: Boolean = false,
    val serverLinked: Boolean = false, val requiresRecovery: Boolean = false,
    val profileBusy: Boolean = false, val serverProfile: ProfileRead? = null,
    val snapshotBusy: Boolean = false, val snapshot: SnapshotStatus? = null,
    val motivationConfigured: Boolean = false, val motivationBusy: Boolean = false,
    val motivation: MotivationState = MotivationState.NotRequested,
    val rankingConsentConfigured: Boolean = false, val rankingConsentBusy: Boolean = false,
    val rankingConsent: RankingConsentState = RankingConsentState.NotRequested,
    val rankingConfigured: Boolean = false, val rankingBusy: Boolean = false,
    val ranking: RankingState = RankingState.NotRequested,
    val nemesisConfigured: Boolean = false, val nemesisBusy: Boolean = false,
    val nemesis: NemesisState = NemesisState.NotRequested,
    val nemesisDecision: NemesisDecisionSource? = null,
    val nemesisMutationConfigured: Boolean = false, val nemesisMutationBusy: Boolean = false,
    val nemesisMutation: NemesisMutationState = NemesisMutationState.Idle)

/** Serializes durable decisions, not network waits. A callback/refresh is fenced by a captured
 * owner lease AND an operation ID, so logout and A→B→A cannot apply an old response.
 */
class SessionController internal constructor(private val db: CalorieDatabase, private val vault: SessionVault,
    private val gateway: OidcGateway, private val issuer: String, private val applicationId: String,
    private val now: () -> Long = System::currentTimeMillis,
    private val bootstrapGateway: BootstrapGateway? = null,
    private val profileGateway: ProfileGateway? = null,
    private val snapshotGateway: SnapshotGateway? = null, snapshotProtocol: SnapshotProtocol? = null,
    private val motivationGateway: MotivationGateway? = null,
    private val rankingConsentGateway: RankingConsentGateway? = null,
    private val rankingGateway: RankingGateway? = null,
    private val nemesisGateway: NemesisGateway? = null,
    private val nemesisWriteGateway: NemesisWriteGateway? = null) {
    private val owners = LocalOwnerStore(db)
    private val mutex = Mutex()
    private var record = JSONObject()
    private var operation: String? = null
    private var bootstrapOperation: String? = null
    private var profileOperation: String? = null
    private enum class PrivateReadKind { PROFILE, MOTIVATION, CONSENTS, RANKING, NEMESIS }
    private enum class RankingStep { FIRST, NEXT, RETRY }
    private var privateReadKind = PrivateReadKind.PROFILE
    private var motivationState: MotivationState = MotivationState.NotRequested
    private var motivationFence: Pair<OwnerLease, Long>? = null
    private var consentState: RankingConsentState = RankingConsentState.NotRequested
    private var consentFence: Pair<OwnerLease, Long>? = null
    private var consentServerContext: Pair<Int, String>? = null
    private var consentOperation: String? = null
    private var rankingState: RankingState = RankingState.NotRequested
    private var rankingFence: Pair<OwnerLease, Long>? = null
    private var rankingServerContext: Triple<String, Int, String>? = null
    private var rankingRetryQuery: RankingQuery? = null
    private var rankingNextQuery: RankingQuery? = null
    private var rankingRetryExpiry: java.time.Instant? = null
    private var nemesisMutationOperation: String? = null
    private var nemesisMutationState: NemesisMutationState = NemesisMutationState.Idle
    private var nemesisMutationFence: Pair<OwnerLease,Long>? = null
    private var nemesisMutationContext: Triple<String,Int,String>? = null
    private var nemesisDecisionSource: NemesisDecisionSource? = null
    private var nemesisState: NemesisState = NemesisState.NotRequested
    private var nemesisFence: Pair<OwnerLease, Long>? = null
    private var nemesisServerContext: Triple<String, Int, String>? = null
    private var nemesisVersion: Pair<String, Pair<Long, java.time.Instant>>? = null
    private var nemesisRetryQuery: NemesisQuery? = null
    private var nemesisNextQuery: NemesisQuery.Listing? = null
    private var snapshotOperation: String? = null
    private val snapshots = snapshotProtocol?.let { ServerSnapshotStore(db, it) }
    private val snapshotProtocol = snapshotProtocol
    private var serverProfile: ProfileRead? = null
    private var profileFence: Pair<OwnerLease, Long>? = null
    private var profileServerContext: Pair<Int, String>? = null
    private var sessionRevision = 0L
    private val bootstraps = AccountBootstrapStore(db)
    private val mutable = MutableStateFlow(SessionView(configured = issuer.isNotEmpty()))
    val view = mutable.asStateFlow()
    /** In-memory confirmation is invalidated also by an external Room context update. */
    suspend fun observeMotivationContext() {
        try {
            db.invalidationTracker.createFlow("account_bindings", "local_active_owner", "local_owners").collect {
                mutex.withLock {
                    if (mutable.value.binding != null) publish(mutable.value.message)
                }
            }
        } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutex.withLock {
            clearMotivation()
            clearRanking(); clearNemesis()
            nemesisMutationOperation = null
            mutable.value = mutable.value.copy(motivation = MotivationState.NotRequested, rankingConsent = RankingConsentState.NotRequested,
                ranking = RankingState.NotRequested, nemesis = NemesisState.NotRequested,
                nemesisDecision = null, nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle)
        } }
    }
    private fun copyRecord() = JSONObject(record.toString())
    private suspend fun persist(value: JSONObject) {
        withContext(Dispatchers.IO) { vault.write(value) }; record = value; sessionRevision++
    }
    private suspend fun forget() {
        // A failed Keystore/storage cleanup never re-enables a session or blocks the diary.
        withContext(Dispatchers.IO) { try { vault.clear() } catch (_: Exception) { } }
        record = JSONObject()
        sessionRevision++
    }
    private suspend fun binding(): SessionBinding {
        val lease = owners.currentLease()
        return SessionBinding(checkNotNull(db.ownerDao().byScope(lease.storageScope)), lease)
    }
    private fun sessionFor(value: SessionBinding): JSONObject? = record.optJSONObject("session")?.takeIf {
        it.optString("ownerId") == value.owner.id && it.optString("issuer") == value.owner.issuer && it.optString("subject") == value.owner.subject
    }
    private fun clearMotivation() {
        motivationState = MotivationState.NotRequested
        motivationFence = null
        consentState = RankingConsentState.NotRequested
        consentFence = null
        consentServerContext = null
    }
    private fun clearRanking() {
        rankingState = RankingState.NotRequested; rankingFence = null; rankingServerContext = null
        rankingRetryQuery = null; rankingNextQuery = null; rankingRetryExpiry = null
    }
    /** Leave/stop of the ranking view removes peers, cursors and the authority of a held read. */
    suspend fun clearRankingPreview() = mutex.withLock {
        if (privateReadKind == PrivateReadKind.RANKING) profileOperation = null
        clearRanking()
        try { publish() } catch (_: Exception) { mutable.value = mutable.value.copy(rankingBusy = false, ranking = RankingState.NotRequested) }
    }
    private fun clearNemesis() {
        nemesisState = NemesisState.NotRequested; nemesisFence = null; nemesisServerContext = null
        nemesisRetryQuery = null; nemesisNextQuery = null; nemesisVersion = null
        nemesisDecisionSource = null; nemesisMutationState = NemesisMutationState.Idle
        nemesisMutationFence = null; nemesisMutationContext = null
    }
    suspend fun clearNemesisPreview() = mutex.withLock {
        if (privateReadKind == PrivateReadKind.NEMESIS) profileOperation = null
        nemesisMutationOperation = null
        clearNemesis()
        try { publish() } catch (_: Exception) {
            mutable.value = mutable.value.copy(nemesisBusy = false, nemesis = NemesisState.NotRequested,
                nemesisDecision = null, nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle)
        }
    }
    private fun pendingConsent(current: SessionBinding, server: AccountBindingEntity?): RankingConsentAttempt? = try {
        record.optJSONObject("rankingConsentAttempt")?.let(RankingConsentAttempt::restore)?.takeIf {
            sessionFor(current) != null && current.owner.kind == "account" && server != null && !server.requiresRecovery &&
                it.ownerScope == current.lease.storageScope && it.leaseGeneration == current.lease.generation &&
                it.accountId == server.accountId && it.accountGeneration == server.accountGeneration &&
                it.syncEpoch == server.syncEpoch && it.contextRevision == server.contextRevision
        }
    } catch (_: Exception) { null }
    private suspend fun publish(message: String? = null) {
        val current = binding()
        val session = sessionFor(current)
        val fresh = session?.let { AuthState.jsonDeserialize(it.getString("authState")).accessTokenExpirationTime?.let { expiry -> expiry > now() + 30_000 } } == true
        val server = db.bootstrapDao().binding(current.lease.storageScope)
        serverProfile?.let { confirmed ->
            if (session == null || server == null || server.requiresRecovery || profileFence != (current.lease to server.contextRevision) ||
                profileServerContext != (server.accountGeneration to server.syncEpoch) || confirmed.accountId != server.accountId || confirmed.syncEpoch != server.syncEpoch) {
                serverProfile = null; profileFence = null; profileServerContext = null
            }
        }
        (motivationState as? MotivationState.Ready)?.let { confirmed ->
            if (session == null || server == null || server.requiresRecovery ||
                motivationFence != (current.lease to server.contextRevision) ||
                confirmed.read.accountGeneration != server.accountGeneration || confirmed.read.syncEpoch != server.syncEpoch) clearMotivation()
        }
        if (consentState is RankingConsentState.Ready || consentState is RankingConsentState.Confirmed) {
            if (session == null || server == null || server.requiresRecovery || consentFence != (current.lease to server.contextRevision) ||
                consentServerContext != (server.accountGeneration to server.syncEpoch)) {
                consentState = RankingConsentState.NotRequested; consentFence = null
            }
        }
        if (rankingFence != null && (session == null || server == null || server.requiresRecovery ||
            rankingFence != (current.lease to server.contextRevision) ||
            rankingServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch))) {
            if (privateReadKind == PrivateReadKind.RANKING) profileOperation = null
            clearRanking(); clearNemesis()
        }
        if (nemesisFence != null && (session == null || server == null || server.requiresRecovery ||
            nemesisFence != (current.lease to server.contextRevision) ||
            nemesisServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch))) {
            if (privateReadKind == PrivateReadKind.NEMESIS) profileOperation = null
            clearNemesis()
        }
        if (nemesisMutationFence != null && (session == null || server == null || server.requiresRecovery ||
            nemesisMutationFence != (current.lease to server.contextRevision) ||
            nemesisMutationContext != Triple(server.accountId,server.accountGeneration,server.syncEpoch))) {
            nemesisMutationOperation = null; clearNemesis()
        }
        // Only an obsolete, well-formed context is discarded. A malformed unknown attempt blocks a new key.
        if (restoredNemesisAttempt() != null && currentNemesisAttempt(current,server) == null) {
            nemesisMutationOperation = null
            persist(copyRecord().also { it.remove("nemesisAttempt") }); clearNemesis()
        }
        val pendingNemesis = currentNemesisAttempt(current,server)
        val pendingConsent = pendingConsent(current, server)
        val consentBusy = consentOperation != null || (profileOperation != null && privateReadKind == PrivateReadKind.CONSENTS)
        mutable.value = SessionView(current, configured = issuer.isNotEmpty(), pendingLogin = record.has("pending"), hasSession = fresh,
            message = message, apiConfigured = bootstrapGateway != null, bootstrapBusy = bootstrapOperation != null,
            serverLinked = server != null, requiresRecovery = server?.requiresRecovery == true,
            profileBusy = profileOperation != null && privateReadKind == PrivateReadKind.PROFILE, serverProfile = serverProfile,
            snapshotBusy = snapshotOperation != null, snapshot = snapshots?.status(current.lease),
            motivationConfigured = motivationGateway != null,
            motivationBusy = profileOperation != null && privateReadKind == PrivateReadKind.MOTIVATION,
            motivation = if (profileOperation != null && privateReadKind == PrivateReadKind.MOTIVATION) MotivationState.Loading else motivationState,
            rankingConsentConfigured = rankingConsentGateway != null && profileGateway != null && motivationGateway != null,
            rankingConsentBusy = consentBusy,
            rankingConsent = if (consentBusy) RankingConsentState.Loading else pendingConsent?.let { RankingConsentState.Pending(it.ranking) } ?: consentState,
            rankingConfigured = rankingGateway != null && motivationGateway != null,
            rankingBusy = profileOperation != null && privateReadKind == PrivateReadKind.RANKING,
            ranking = if (profileOperation != null && privateReadKind == PrivateReadKind.RANKING) RankingState.Loading else rankingState,
            nemesisConfigured = nemesisGateway != null && motivationGateway != null,
            nemesisBusy = profileOperation != null && privateReadKind == PrivateReadKind.NEMESIS,
            nemesis = if (profileOperation != null && privateReadKind == PrivateReadKind.NEMESIS) NemesisState.Loading else nemesisState,
            nemesisDecision = nemesisDecisionSource,
            nemesisMutationConfigured = nemesisWriteGateway != null,
            nemesisMutationBusy = nemesisMutationOperation != null,
            nemesisMutation = if (nemesisMutationOperation != null) NemesisMutationState.Sending
                else pendingNemesis?.let { NemesisMutationState.Pending(it.command.action,message) }
                ?: if (record.has("nemesisAttempt")) NemesisMutationState.Blocked
                else nemesisMutationState)
    }
    suspend fun start() = mutex.withLock {
        if (mutable.value.binding != null) return@withLock
        try {
            var message: String? = null
            record = try { withContext(Dispatchers.IO) { vault.read() } } catch (_: Exception) {
                forget(); message = "Sesja wymaga ponownego logowania. Lokalny dziennik został zachowany."; JSONObject()
            }
            val current = binding()
            val pending = record.optJSONObject("pending")
            val validPending = pending != null && pending.optString("scope") == current.lease.storageScope &&
                pending.optLong("generation") == current.lease.generation && pending.optString("issuer") == issuer &&
                now() - pending.optLong("createdAt") in 0..600_000
            val next = copyRecord()
            if (!validPending) next.remove("pending")
            if (sessionFor(current)?.optString("issuer") != issuer) next.remove("session")
            if (next.has("session")) try {
                val state = AuthState.jsonDeserialize(next.getJSONObject("session").getString("authState"))
                validateDiscovery(checkNotNull(state.authorizationServiceConfiguration), issuer)
            } catch (_: Exception) {
                next.remove("session"); message = "Sesja wymaga ponownego logowania. Lokalny dziennik został zachowany."
            }
            // A session-storage failure must not prevent opening the existing offline diary.
            try { persist(next) } catch (_: Exception) { record = JSONObject(); message = "Pamięć sesji jest niedostępna. Dziennik działa offline." }
            publish(message)
        } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutable.value = mutable.value.copy(message = "Nie udało się otworzyć dziennika. Spróbuj ponownie.") }
    }
    private suspend fun fail(id: String, message: String) = mutex.withLock {
        if (operation != id) return@withLock
        operation = null
        publish(message)
    }
    suspend fun beginLogin(): Intent? {
        val id = UUID.randomUUID().toString()
        val captured = try { mutex.withLock {
            if (issuer.isEmpty() || mutable.value.busy || record.has("pending")) return null
            requireHttps(issuer)
            val lease = owners.currentLease()
            bootstrapOperation = null
            profileOperation = null
            snapshotOperation = null
            consentOperation = null
            nemesisMutationOperation = null
            if (record.has("nemesisAttempt")) persist(copyRecord().also { it.remove("nemesisAttempt") })
            serverProfile = null
            clearMotivation()
            clearRanking(); clearNemesis()
            operation = id
            mutable.value = mutable.value.copy(busy = true, bootstrapBusy = false, profileBusy = false, snapshotBusy = false, snapshot = null, serverProfile = null,
                motivationBusy = false, motivation = MotivationState.NotRequested, rankingConsentBusy = false,
                rankingConsent = RankingConsentState.NotRequested, rankingBusy = false, ranking = RankingState.NotRequested,
                nemesisBusy = false, nemesis = NemesisState.NotRequested, nemesisDecision = null, nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle, message = null)
            lease
        } } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutable.value = mutable.value.copy(message = "Logowanie jest niedostępne. Dziennik działa offline."); return null }
        try {
            val config = withTimeout(30_000) { gateway.discover(issuer) }
            validateDiscovery(config, issuer)
            val request = AuthorizationRequest.Builder(config, SessionClaims.CLIENT_ID, ResponseTypeValues.CODE,
                Uri.parse(AuthReturn.redirect(applicationId))).setScope("openid profile").setPrompt("login").build()
            check(request.codeVerifierChallengeMethod == "S256" && !request.nonce.isNullOrEmpty() && !request.state.isNullOrEmpty())
            val intent = gateway.browser(request)
            return mutex.withLock {
                if (operation != id) return@withLock null
                owners.requireCurrent(captured)
                persist(copyRecord().put("pending", JSONObject().put("id", id).put("issuer", issuer)
                    .put("scope", captured.storageScope).put("generation", captured.generation).put("createdAt", now())
                    .put("request", request.jsonSerializeString())))
                operation = null
                publish()
                intent
            }
        } catch (error: CancellationException) { fail(id, "Logowanie przerwane. Dziennik działa offline."); throw error }
        catch (_: Exception) { fail(id, "Nie udało się rozpocząć logowania. Sprawdź połączenie i spróbuj ponownie."); return null }
    }
    suspend fun cancelLogin() = mutex.withLock {
        operation = null
        val next = copyRecord().also { it.remove("pending") }
        try { persist(next) } catch (_: Exception) {
            forget()
        }
        publish("Logowanie anulowane. Dane lokalne zachowane.")
    }
    suspend fun completeLogin(intent: Intent?) {
        // The Android intent is untrusted, including the request serialized inside it.
        val response = try { intent?.let(AuthorizationResponse::fromIntent) } catch (_: Exception) { null }
        if (response == null) { cancelLogin(); return }
        var id: String? = null
        try {
            val captured = mutex.withLock {
                val pending = checkNotNull(record.optJSONObject("pending"))
                val lease = owners.currentLease()
                require(pending.getString("scope") == lease.storageScope && pending.getLong("generation") == lease.generation)
                require(pending.getString("issuer") == issuer && now() - pending.getLong("createdAt") in 0..600_000)
                val saved = AuthorizationRequest.jsonDeserialize(pending.getString("request"))
                require(StrictJson.canonical(saved.jsonSerialize()) == StrictJson.canonical(response.request.jsonSerialize()))
                require(response.state == saved.state && !response.authorizationCode.isNullOrEmpty())
                require(saved.redirectUri.toString() == AuthReturn.redirect(applicationId) && saved.clientId == SessionClaims.CLIENT_ID)
                validateDiscovery(saved.configuration, issuer)
                id = pending.getString("id")
                // Consume BEFORE exchanging the one-use code. After a lost response, log in again.
                persist(copyRecord().also { it.remove("pending") })
                operation = id
                mutable.value = mutable.value.copy(busy = true, pendingLogin = false, message = null)
                lease
            }
            val tokens = withTimeout(30_000) { gateway.tokens(response.createTokenExchangeRequest()) }
            val identity = SessionClaims.identity(checkNotNull(tokens.idToken), issuer, response.request.nonce, now() / 1000)
            require(tokens.tokenType.equals("Bearer", ignoreCase = true) && !tokens.accessToken.isNullOrEmpty())
            require(checkNotNull(tokens.accessTokenExpirationTime) > now())
            val state = AuthState(response, null).apply { update(tokens, null) }
            mutex.withLock {
                if (operation != id) return@withLock
                owners.requireCurrent(captured)
                val owner = owners.registerIdentity(identity.issuer, identity.subject)
                val next = copyRecord().put("session", JSONObject().put("ownerId", owner.id)
                    .put("issuer", identity.issuer).put("subject", identity.subject).put("authState", state.jsonSerializeString()))
                // Persist first. A crash before Room selection cannot activate this identity.
                persist(next)
                // UI is removed before selecting the new lease; stale writes also fail in Room.
                mutable.value = mutable.value.copy(binding = null)
                owners.selectIfCurrent(captured, owner.id)
                operation = null
                publish("Zalogowano. To konto ma osobny dziennik; dane gościa pozostają zachowane.")
            }
        } catch (error: CancellationException) { id?.let { fail(it, "Logowanie przerwane. Dziennik działa offline.") }; throw error }
        catch (_: Exception) {
            if (id != null) fail(id!!, "Logowanie nie zostało potwierdzone. Dane lokalne zachowane.")
            else mutex.withLock { mutable.value = mutable.value.copy(message = "Odrzucono nieaktualny lub nieprawidłowy powrót z logowania.") }
        }
    }
    suspend fun logout() {
        var previous = mutable.value.binding
        try { mutex.withLock {
        previous = mutable.value.binding
        val captured = owners.currentLease()
        val guest = owners.ensureGuest()
        // Local logout removes all tokens and pending codes; it does not delete any diary.
        operation = null
        bootstrapOperation = null
        profileOperation = null
        snapshotOperation = null
        consentOperation = null
        nemesisMutationOperation = null
        serverProfile = null
        clearMotivation()
        clearRanking(); clearNemesis()
        forget()
        mutable.value = mutable.value.copy(binding = null)
        owners.selectIfCurrent(captured, guest.id)
        publish("Wylogowano z aplikacji. Otwarty dziennik gościa.")
        } } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutex.withLock {
            operation = null
            try { publish("Nie udało się otworzyć gościa. Spróbuj ponownie; dziennik konta pozostaje lokalny.") }
            catch (_: Exception) { mutable.value = mutable.value.copy(binding = previous, busy = false, hasSession = false,
                motivationBusy = false, motivation = MotivationState.NotRequested,
                rankingBusy = false, ranking = RankingState.NotRequested,
                nemesisBusy = false, nemesis = NemesisState.NotRequested,
                nemesisDecision = null, nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle,
                message = "Pamięć dziennika jest niedostępna. Spróbuj ponownie.") }
        } }
    }
    suspend fun refresh() { refreshFor(null) }
    private suspend fun refreshFor(expected: OwnerLease?): Boolean {
        val id = UUID.randomUUID().toString()
        var registered = false
        try {
            val captured = mutex.withLock {
                expected?.let { owners.requireCurrent(it) }
                check(!mutable.value.busy && !record.has("pending"))
                val current = binding()
                val session = checkNotNull(sessionFor(current))
                require(session.getString("issuer") == issuer)
                val state = AuthState.jsonDeserialize(session.getString("authState"))
                validateDiscovery(checkNotNull(state.authorizationServiceConfiguration), issuer)
                operation = id
                registered = true
                serverProfile = null
                clearMotivation()
                // Manual renewal invalidates a held private read. Automatic renewal belongs to it.
                if (expected == null) { profileOperation = null; consentOperation = null; nemesisMutationOperation = null; clearRanking(); clearNemesis() }
                mutable.value = mutable.value.copy(busy = true, profileBusy = profileOperation != null && privateReadKind == PrivateReadKind.PROFILE,
                    motivationBusy = profileOperation != null && privateReadKind == PrivateReadKind.MOTIVATION,
                    serverProfile = null, motivation = MotivationState.NotRequested, rankingConsent = RankingConsentState.NotRequested,
                    rankingConsentBusy = expected != null && (consentOperation != null || (profileOperation != null && privateReadKind == PrivateReadKind.CONSENTS)),
                    rankingBusy = expected != null && profileOperation != null && privateReadKind == PrivateReadKind.RANKING,
                    ranking = if (expected != null && privateReadKind == PrivateReadKind.RANKING) RankingState.Loading else RankingState.NotRequested,
                    nemesisBusy = expected != null && profileOperation != null && privateReadKind == PrivateReadKind.NEMESIS,
                    nemesis = if (expected != null && privateReadKind == PrivateReadKind.NEMESIS) NemesisState.Loading else NemesisState.NotRequested,
                    nemesisDecision = null, nemesisMutationBusy = expected != null && nemesisMutationOperation != null,
                    nemesisMutation = if (expected != null && nemesisMutationOperation != null) NemesisMutationState.Sending else NemesisMutationState.Idle, message = null)
                Triple(current, state, SessionIdentity(session.getString("issuer"), session.getString("subject")))
            }
            val tokens = withTimeout(30_000) { gateway.tokens(captured.second.createTokenRefreshRequest()) }
            tokens.idToken?.let { SessionClaims.identity(it, issuer, null, now() / 1000, captured.third) }
            require(tokens.tokenType.equals("Bearer", ignoreCase = true) && !tokens.accessToken.isNullOrEmpty())
            require(checkNotNull(tokens.accessTokenExpirationTime) > now())
            return mutex.withLock {
                if (operation != id) return@withLock false
                owners.requireCurrent(captured.first.lease)
                captured.second.update(tokens, null)
                val session = checkNotNull(sessionFor(captured.first))
                persist(copyRecord().put("session", JSONObject(session.toString()).put("authState", captured.second.jsonSerializeString())))
                operation = null
                publish("Sesja odnowiona. Dziennik zachowany.")
                true
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { fail(id, "Odnowienie przerwane. Dziennik działa offline.") }; throw error
        }
        catch (_: Exception) {
            mutex.withLock {
                if (registered && operation != id) return@withLock
                if (operation != null && operation != id) return@withLock
                if (operation == id) operation = null
                publish("Sesji nie udało się odnowić. Dziennik działa offline; spróbuj zalogować się ponownie.")
            }
            return false
        }
    }

    /** Must be called under mutex. A refresh, pending login, logout or ABA invalidates the ticket. */
    private suspend fun captureApi(lease: OwnerLease): ApiSession {
        owners.requireCurrent(lease)
        check(operation == null && !record.has("pending"))
        val current = binding()
        val session = checkNotNull(sessionFor(current))
        val identity = SessionIdentity(session.getString("issuer"), session.getString("subject"))
        require(identity.issuer == issuer && identity.issuer == current.owner.issuer && identity.subject == current.owner.subject)
        val serialized = session.getString("authState")
        val state = AuthState.jsonDeserialize(serialized)
        require(checkNotNull(state.accessTokenExpirationTime) > now() + 30_000)
        val token = checkNotNull(state.accessToken)
        require(token.isNotBlank())
        return ApiSession(identity, lease, token, serialized, sessionRevision)
    }
    private suspend fun requireApi(ticket: ApiSession) {
        val current = captureApi(ticket.lease)
        check(current.identity == ticket.identity && current.authState == ticket.authState && current.revision == ticket.revision)
    }
    internal suspend fun apiSession(lease: OwnerLease): ApiSession = mutex.withLock { captureApi(lease) }
    internal suspend fun <T> withApiSession(ticket: ApiSession, block: suspend () -> T): T = mutex.withLock {
        db.withTransaction { requireApi(ticket); block() }
    }

    /** Explicit E3 connection, never a diary sync or an implicit guest import. */
    suspend fun bootstrap() {
        val gateway = bootstrapGateway ?: return
        val id = UUID.randomUUID().toString()
        val lease = try { mutex.withLock {
            if (bootstrapOperation != null || operation != null || record.has("pending")) return
            if (profileOperation != null || snapshotOperation != null || consentOperation != null || nemesisMutationOperation != null) return
            val current = binding()
            if (current.owner.kind != "account" || sessionFor(current) == null) {
                publish("Zaloguj się, aby połączyć konto z serwerem. Dziennik działa offline."); return
            }
            val retryAt = sessionFor(current)!!.optLong("apiRetryAt")
            if (retryAt > now()) {
                publish("Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s. Dziennik działa offline."); return
            }
            bootstrapOperation = id
            serverProfile = null
            clearMotivation()
            mutable.value = mutable.value.copy(bootstrapBusy = true, serverProfile = null, motivation = MotivationState.NotRequested, message = null)
            current.lease
        } } catch (error: CancellationException) { throw error }
        catch (_: Exception) {
            mutable.value = mutable.value.copy(bootstrapBusy = false, message = "Połączenie jest niedostępne. Dziennik pozostaje lokalny.")
            return
        }
        try {
            // Renew an expiring token only for the originally captured owner.
            val fresh = mutex.withLock {
                owners.requireCurrent(lease)
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(lease))
            var ticket = apiSession(lease)
            var request = withApiSession(ticket) { check(bootstrapOperation == id); bootstraps.begin(lease) }
            var renewedKey = false
            var refreshed = false
            while (true) {
                val captured = ticket
                val result = gateway.post(captured, request.operationId) {
                    withApiSession(captured) { check(bootstrapOperation == id) }
                }
                if (result.status == 200) {
                    val response = BootstrapProtocol.parse(result.body)
                    withApiSession(captured) {
                        check(bootstrapOperation == id)
                        val server = bootstraps.apply(request, response)
                        bootstrapOperation = null
                        publish(if (server.requiresRecovery) "Konto połączone. Zmiana stanu serwera wymaga uzgodnienia danych; lokalny dziennik zachowany."
                            else "Konto połączone z serwerem. Posiłki i kolejka nadal pozostają lokalne.")
                    }
                    return
                }
                val code = if (result.status in setOf(429, 503)) "" else BootstrapHttpProtocol.errorCode(result.body)
                withApiSession(captured) { check(bootstrapOperation == id) }
                if (result.status == 401 && code == "unauthorized" && !refreshed) {
                    refreshed = true
                    check(refreshFor(lease))
                    ticket = apiSession(lease)
                    withApiSession(ticket) { check(bootstrapOperation == id) }
                    continue // Same durable key, at most one renewal.
                }
                if (result.status == 409 && code in setOf("sync_epoch_changed", "account_generation_changed") && !renewedKey) {
                    request = withApiSession(captured) { check(bootstrapOperation == id); bootstraps.renew(request) }
                    renewedKey = true
                    continue // At most one new key; old mapping and diary are preserved.
                }
                val message = when (result.status) {
                    401 -> "Sesja wymaga ponownego logowania. Dziennik działa offline."
                    403 -> "Serwer nie pozwala połączyć tego konta. Dziennik działa offline."
                    409 -> "Serwer zwrócił konflikt połączenia. Zachowano lokalne dane i klucz próby."
                    429, 503 -> {
                        val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                        val retryAt = Math.addExact(now(), Math.multiplyExact(seconds, 1000))
                        withApiSession(captured) {
                            check(bootstrapOperation == id)
                            val session = checkNotNull(sessionFor(binding()))
                            persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                        }
                        "Serwer jest zajęty. Ponów za co najmniej $seconds s. Dziennik działa offline."
                    }
                    else -> "Nie udało się połączyć konta. Dziennik działa offline."
                }
                mutex.withLock {
                    if (bootstrapOperation == id) { owners.requireCurrent(lease); bootstrapOperation = null; publish(message) }
                }
                return
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { finishBootstrap(id, lease) }; throw error
        } catch (_: Exception) { finishBootstrap(id, lease) }
    }
    private suspend fun finishBootstrap(id: String, lease: OwnerLease) = mutex.withLock {
        if (bootstrapOperation != id) return@withLock
        bootstrapOperation = null
        try {
            if (owners.currentLease() == lease) publish("Połączenie nie zostało potwierdzone. Dane i klucz próby zachowane; możesz ponowić.")
            else publish()
        } catch (_: Exception) {
            mutable.value = mutable.value.copy(bootstrapBusy = false, message = "Połączenie nie zostało potwierdzone. Dziennik pozostaje lokalny.")
        }
    }

    /** Explicit online preview. Never upserts a local profile, recalculates goals or ACKs outbox. */
    suspend fun readProfile() = readPrivate(PrivateReadKind.PROFILE)
    suspend fun readMotivation() = readPrivate(PrivateReadKind.MOTIVATION)
    suspend fun readRankingConsents() = readPrivate(PrivateReadKind.CONSENTS)
    suspend fun readRanking() = readPrivate(PrivateReadKind.RANKING, RankingStep.FIRST)
    suspend fun nextRankingPage() = readPrivate(PrivateReadKind.RANKING, RankingStep.NEXT)
    suspend fun retryRankingPage() = readPrivate(PrivateReadKind.RANKING, RankingStep.RETRY)
    suspend fun readNemesis() = readPrivate(PrivateReadKind.NEMESIS, nemesisRequest = NemesisQuery.Listing())
    suspend fun readNemesisChallenge(id: String) {
        val query = try { NemesisQuery.Detail(id) } catch (_: Exception) { return }
        readPrivate(PrivateReadKind.NEMESIS, nemesisRequest = query)
    }
    suspend fun nextNemesisPage() {
        val query = mutex.withLock { if (nemesisState is NemesisState.ListReady) nemesisNextQuery else null } ?: return
        readPrivate(PrivateReadKind.NEMESIS, nemesisRequest = query, nemesisContinuation = true)
    }
    suspend fun retryNemesis() {
        val query = mutex.withLock { if ((nemesisState as? NemesisState.Failed)?.canRetry == true) nemesisRetryQuery else null } ?: return
        readPrivate(PrivateReadKind.NEMESIS, nemesisRequest = query, nemesisContinuation = true)
    }
    private suspend fun readPrivate(kind: PrivateReadKind, rankingStep: RankingStep? = null,
        nemesisRequest: NemesisQuery? = null, nemesisContinuation: Boolean = false) {
        val firstGateway: ProfileGateway = (if (kind in setOf(PrivateReadKind.MOTIVATION, PrivateReadKind.RANKING, PrivateReadKind.NEMESIS)) motivationGateway else profileGateway) ?: return
        if (kind == PrivateReadKind.CONSENTS && (motivationGateway == null || rankingConsentGateway == null)) return
        if (kind == PrivateReadKind.RANKING && rankingGateway == null) return
        if (kind == PrivateReadKind.NEMESIS && (nemesisGateway == null || nemesisRequest == null)) return
        val label = when (kind) { PrivateReadKind.PROFILE -> "profil"; PrivateReadKind.MOTIVATION -> "osiągnięcia"; PrivateReadKind.CONSENTS -> "zgody"; PrivateReadKind.RANKING -> "ranking"; PrivateReadKind.NEMESIS -> "Nemesis" }
        val id = UUID.randomUUID().toString()
        var capturedLease: OwnerLease? = null
        var rankingQuery: RankingQuery? = null
        val capturedBinding = try { mutex.withLock {
            if (profileOperation != null || consentOperation != null || snapshotOperation != null || bootstrapOperation != null || operation != null || nemesisMutationOperation != null || record.has("pending")) return
            val current = binding()
            capturedLease = current.lease
            if (current.owner.kind != "account" || sessionFor(current) == null) {
                publish("Zaloguj się, aby odczytać $label z serwera."); return
            }
            val server = db.bootstrapDao().binding(current.lease.storageScope)
            if (server == null || server.requiresRecovery) {
                publish("Najpierw połącz konto i uzgodnij stan serwera. Dziennik pozostaje lokalny."); return
            }
            if (kind == PrivateReadKind.CONSENTS && pendingConsent(current, server) != null) {
                publish("Poprzedni zapis zgody czeka na potwierdzenie. Ponów tę samą decyzję."); return
            }
            if (kind == PrivateReadKind.RANKING) {
                val continues = rankingStep != RankingStep.FIRST
                if (continues && (rankingFence != (current.lease to server.contextRevision) ||
                    rankingServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch))) { clearRanking(); publish(); return }
                rankingQuery = when (rankingStep) {
                    RankingStep.FIRST -> RankingQuery()
                    RankingStep.NEXT -> if (rankingState is RankingState.Ready) rankingNextQuery else null
                    RankingStep.RETRY -> if ((rankingState as? RankingState.Failed)?.canRetry == true) rankingRetryQuery else null
                    null -> null
                } ?: return
                val expiry = if (rankingStep == RankingStep.NEXT) (rankingState as RankingState.Ready).page.expiresAt else rankingRetryExpiry
                if (continues && expiry != null && expiry.toEpochMilli() <= now()) {
                    clearRanking(); rankingState = RankingState.Failed("Strona rankingu wygasła. Pobierz listę od początku.", false); publish(); return
                }
                rankingRetryExpiry = if (rankingStep == RankingStep.FIRST) null else expiry
            }
            if (kind == PrivateReadKind.NEMESIS && nemesisContinuation &&
                (nemesisFence != (current.lease to server.contextRevision) ||
                    nemesisServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch) ||
                    (nemesisRequest !== nemesisRetryQuery && nemesisRequest !== nemesisNextQuery))) {
                clearNemesis(); publish(); return
            }
            if (kind == PrivateReadKind.NEMESIS) {
                if (nemesisFence != (current.lease to server.contextRevision) ||
                    nemesisServerContext != Triple(server.accountId, server.accountGeneration, server.syncEpoch) ||
                    nemesisRequest !is NemesisQuery.Detail || nemesisVersion?.first != nemesisRequest.id) nemesisVersion = null
                nemesisFence = current.lease to server.contextRevision
                nemesisServerContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
                nemesisRetryQuery = nemesisRequest; nemesisNextQuery = null
            }
            val retryAt = sessionFor(current)!!.optLong("apiRetryAt")
            if (retryAt > now()) {
                val message = "Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s."
                if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Failed(message)
                if (kind == PrivateReadKind.CONSENTS) consentState = RankingConsentState.Failed(message)
                if (kind == PrivateReadKind.NEMESIS) nemesisState = NemesisState.Failed(message, true)
                if (kind == PrivateReadKind.RANKING) {
                    rankingRetryQuery = rankingQuery; rankingNextQuery = null
                    rankingFence = current.lease to server.contextRevision
                    rankingServerContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
                    rankingState = RankingState.Failed(message, rankingQuery != null)
                }
                publish(message); return
            }
            profileOperation = id
            privateReadKind = kind
            serverProfile = null
            clearMotivation()
            if (kind != PrivateReadKind.NEMESIS) clearNemesis() else nemesisState = NemesisState.Loading
            if (kind != PrivateReadKind.RANKING) clearRanking()
            else {
                rankingState = RankingState.Loading; rankingRetryQuery = rankingQuery; rankingNextQuery = null
                rankingFence = current.lease to server.contextRevision
                rankingServerContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
            }
            if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Loading
            publish()
            current.lease to server
        } } catch (error: CancellationException) {
            capturedLease?.let { withContext(NonCancellable) { finishPrivate(id, it, kind) } }
            throw error
        }
        catch (_: Exception) {
            capturedLease?.let { finishPrivate(id, it, kind) }
            return
        }
        val lease = capturedBinding.first
        val server = capturedBinding.second
        try {
            val fresh = mutex.withLock {
                owners.requireCurrent(lease)
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(lease))
            var ticket = apiSession(lease)
            var refreshed = false
            var stagedProfile: ProfileRead? = null
            var stagedMotivation: MotivationRead? = null
            var stagedNemesis: NemesisChallenge? = null
            var readGateway = firstGateway
            while (true) {
                val captured = ticket
                suspend fun ready() {
                    check(profileOperation == id)
                    val active = bootstraps.requireReady(lease, server.contextRevision)
                    require(active.accountId == server.accountId && active.accountGeneration == server.accountGeneration && active.syncEpoch == server.syncEpoch)
                }
                val result = readGateway.get(captured) { withApiSession(captured) { ready() } }
                if (result.status == 200) {
                    val profileStage = kind == PrivateReadKind.PROFILE || (kind == PrivateReadKind.CONSENTS && stagedProfile == null)
                    val response = if (profileStage) ProfileReadProtocol.parse(result.body) else null
                    val rankingStage = kind == PrivateReadKind.RANKING && stagedMotivation != null
                    val nemesisStage = kind == PrivateReadKind.NEMESIS && stagedMotivation != null
                    val motivation = if (!profileStage && !rankingStage && !nemesisStage) MotivationReadProtocol.parse(result.body) else null
                    val page = if (rankingStage) RankingReadProtocol.parse(result.body, checkNotNull(rankingQuery)) else null
                    val (nemesisPage, nemesisDetail, statistics) = if (nemesisStage) withContext(Dispatchers.Default) {
                        Triple(if (nemesisRequest is NemesisQuery.Listing) NemesisReadProtocol.page(result.body, nemesisRequest) else null,
                            if (nemesisRequest is NemesisQuery.Detail && stagedNemesis == null) NemesisReadProtocol.detail(result.body, nemesisRequest.id) else null,
                            stagedNemesis?.let { NemesisReadProtocol.statistics(result.body, it) })
                    } else Triple(null, null, null)
                    var continueRead = false
                    withApiSession(captured) {
                        ready()
                        // GET me has no account_generation; it cannot replace the bootstrap mapping.
                        require(response == null || response.accountId == server.accountId)
                        if ((response?.syncEpoch ?: motivation?.syncEpoch ?: checkNotNull(stagedMotivation).syncEpoch) != server.syncEpoch ||
                            (motivation != null && motivation.accountGeneration != server.accountGeneration)) {
                            db.bootstrapDao().update(server.copy(requiresRecovery = true,
                                contextRevision = Math.addExact(server.contextRevision, 1)))
                            profileOperation = null
                            clearMotivation()
                            clearRanking(); clearNemesis()
                            val message = "Stan serwera się zmienił. Lokalny dziennik zachowany; wymagane uzgodnienie danych."
                            if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Failed(message)
                            if (kind == PrivateReadKind.CONSENTS) consentState = RankingConsentState.Failed(message)
                            if (kind == PrivateReadKind.RANKING) rankingState = RankingState.Failed(message, false)
                            if (kind == PrivateReadKind.NEMESIS) nemesisState = NemesisState.Failed(message, false)
                            publish(message)
                        } else if (kind == PrivateReadKind.CONSENTS && response != null) {
                            stagedProfile = response
                            readGateway = checkNotNull(motivationGateway)
                            continueRead = true
                        } else if (kind == PrivateReadKind.NEMESIS && motivation != null) {
                            stagedMotivation = motivation
                            readGateway = object : ProfileGateway {
                                override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit) =
                                    checkNotNull(nemesisGateway).get(session, server.syncEpoch, checkNotNull(nemesisRequest), beforeSend)
                            }
                            continueRead = true
                        } else if (nemesisDetail != null && nemesisDetail.status in setOf("active", "finished")) {
                            stagedNemesis = nemesisDetail
                            readGateway = object : ProfileGateway {
                                override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit) =
                                    checkNotNull(nemesisGateway).get(session, server.syncEpoch, NemesisQuery.Statistics(nemesisDetail.id), beforeSend)
                            }
                            continueRead = true
                        } else if (kind == PrivateReadKind.RANKING && motivation != null) {
                            // Preflight each live page; no GET reaffirms ranking consent.
                            stagedMotivation = motivation
                            readGateway = object : ProfileGateway {
                                override suspend fun get(session: ApiSession, beforeSend: suspend () -> Unit) =
                                    checkNotNull(rankingGateway).get(session, checkNotNull(rankingQuery), beforeSend)
                            }
                            continueRead = true
                        } else {
                            serverProfile = response
                            if (response != null) {
                                profileFence = lease to server.contextRevision
                                profileServerContext = server.accountGeneration to server.syncEpoch
                            }
                            if (motivation != null) {
                                motivationState = MotivationState.Ready(motivation)
                                motivationFence = lease to server.contextRevision
                            }
                            if (kind == PrivateReadKind.CONSENTS) {
                                val source = checkNotNull(stagedProfile)
                                val ranking = checkNotNull(motivation).ranking
                                require(source.consents.ranking == ranking.requested && ranking.consentEpoch == server.syncEpoch)
                                consentState = RankingConsentState.Ready(RankingConsentSource(UUID.randomUUID().toString(), source.consents, ranking, now()))
                                consentFence = lease to server.contextRevision
                                consentServerContext = server.accountGeneration to server.syncEpoch
                            }
                            if (kind == PrivateReadKind.RANKING) {
                                rankingState = RankingState.Ready(checkNotNull(page))
                                rankingNextQuery = page.nextPageToken?.let(::RankingQuery)
                                motivationState = MotivationState.Ready(checkNotNull(stagedMotivation))
                                motivationFence = lease to server.contextRevision
                            }
                            if (kind == PrivateReadKind.NEMESIS) {
                                if (statistics != null) {
                                    val previous = nemesisVersion?.takeIf { it.first == checkNotNull(stagedNemesis).id }?.second
                                    require(previous == null || (statistics.revision >= previous.first && statistics.asOf >= previous.second))
                                    nemesisVersion = checkNotNull(stagedNemesis).id to (statistics.revision to statistics.asOf)
                                } else nemesisVersion = null
                                nemesisState = if (nemesisPage != null) NemesisState.ListReady(nemesisPage)
                                    else NemesisState.DetailReady(checkNotNull(nemesisDetail ?: stagedNemesis), statistics)
                                nemesisDecisionSource = (nemesisState as? NemesisState.DetailReady)?.challenge?.takeIf { it.status != "cancelled" }
                                    ?.let { NemesisDecisionSource(UUID.randomUUID().toString(),it,now()) }
                                nemesisNextQuery = nemesisPage?.nextCursor?.let { NemesisQuery.Listing(it) }
                                motivationState = MotivationState.Ready(checkNotNull(stagedMotivation)); motivationFence = lease to server.contextRevision
                            }
                            profileOperation = null
                            publish(if (kind == PrivateReadKind.PROFILE) "Odczytano profil serwerowy. Lokalny profil i cel kalorii zachowane."
                                else if (kind == PrivateReadKind.MOTIVATION) "Odczytano potwierdzenie serwerowe. Lokalny dziennik i zgoda rankingu zachowane."
                                else if (kind == PrivateReadKind.RANKING) "Odczytano bieżącą stronę rankingu. Kolejne strony mogą się zmieniać."
                                else if (kind == PrivateReadKind.NEMESIS) "Odczytano aktualne Nemesis. Lokalny dziennik i zgody zachowane."
                                else "Odczytano aktualne zgody. Udział w rankingu wymaga osobnej decyzji.")
                        }
                    }
                    if (continueRead) continue
                    return
                }
                val code = if (result.status in setOf(429, 503)) "" else BootstrapHttpProtocol.errorCode(result.body)
                withApiSession(captured) { ready() }
                if (result.status == 401 && code == "unauthorized" && !refreshed) {
                    refreshed = true
                    check(refreshFor(lease))
                    ticket = apiSession(lease)
                    withApiSession(ticket) { ready() }
                    continue
                }
                val message = when (result.status) {
                    401 -> "Sesja wymaga ponownego logowania. Dziennik działa offline."
                    403 -> if (code == "account_bootstrap_required") "Serwer wymaga ponownego połączenia konta."
                        else "Serwer nie pozwala odczytać danych tego konta."
                    409 -> if (kind == PrivateReadKind.NEMESIS && code == "nemesis_cursor_unavailable") "Strona Nemesis wygasła. Pobierz listę od początku."
                        else "Stan serwera wymaga ponownego sprawdzenia połączenia. Dane lokalne zachowane."
                    404 -> "Rywalizacja lub udostępnianie nie są już dostępne. Pobierz świeżą listę."
                    410 -> "Strona rankingu wygasła lub jest już niedostępna. Pobierz listę od początku."
                    429, 503 -> {
                        val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                        val retryAt = Math.addExact(now(), Math.multiplyExact(seconds, 1000))
                        withApiSession(captured) {
                            ready()
                            val session = checkNotNull(sessionFor(binding()))
                            persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                        }
                        "Serwer jest zajęty. Ponów za co najmniej $seconds s. Dziennik działa offline."
                    }
                    else -> "Nie udało się odczytać danych serwerowych. Dziennik działa offline."
                }
                mutex.withLock {
                    if (profileOperation == id) {
                        owners.requireCurrent(lease); profileOperation = null
                        if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Failed(message)
                        if (kind == PrivateReadKind.CONSENTS) consentState = RankingConsentState.Failed(message)
                        if (kind == PrivateReadKind.NEMESIS) {
                            val retry = result.status !in setOf(400, 403, 404, 409, 410, 422)
                            if (!retry) clearNemesis()
                            nemesisState = NemesisState.Failed(message, retry)
                        }
                        if (kind == PrivateReadKind.RANKING) {
                            val retry = result.status !in setOf(400, 403, 404, 409, 410, 422)
                            if (!retry) clearRanking()
                            rankingState = RankingState.Failed(message, retry)
                        }
                        publish(message)
                    }
                }
                return
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { finishPrivate(id, lease, kind) }; throw error
        } catch (_: Exception) { finishPrivate(id, lease, kind) }
    }
    private suspend fun finishPrivate(id: String, lease: OwnerLease, kind: PrivateReadKind) = mutex.withLock {
        if (profileOperation != id) return@withLock
        profileOperation = null
        serverProfile = null
        clearMotivation()
        val message = "Odczyt nie został potwierdzony. Możesz ponowić; dziennik zachowany."
        try {
            if (owners.currentLease() == lease) {
                if (kind == PrivateReadKind.MOTIVATION) motivationState = MotivationState.Failed(message)
                if (kind == PrivateReadKind.CONSENTS) consentState = RankingConsentState.Failed(message)
                if (kind == PrivateReadKind.RANKING) rankingState = RankingState.Failed(message, rankingRetryQuery != null)
                if (kind == PrivateReadKind.NEMESIS) nemesisState = NemesisState.Failed(message, nemesisRetryQuery != null)
                publish(message)
            }
            else publish()
        } catch (_: Exception) {
            mutable.value = mutable.value.copy(profileBusy = false, serverProfile = null, motivationBusy = false, motivation = MotivationState.NotRequested,
                rankingConsentBusy = false, rankingConsent = RankingConsentState.NotRequested, rankingBusy = false, ranking = RankingState.NotRequested,
                nemesisBusy = false, nemesis = NemesisState.NotRequested,
                message = "Odczyt nie został potwierdzony. Dziennik pozostaje lokalny.")
        }
    }

    suspend fun confirmRankingConsent(sourceId: String, enabled: Boolean) = writeRankingConsent(sourceId, enabled)
    suspend fun retryRankingConsent() = writeRankingConsent(null, null)
    private suspend fun writeRankingConsent(sourceId: String?, enabled: Boolean?) {
        val transport = rankingConsentGateway ?: return
        val id = UUID.randomUUID().toString()
        var lease: OwnerLease? = null
        val request = try { mutex.withLock {
            if (consentOperation != null || profileOperation != null || snapshotOperation != null || bootstrapOperation != null || operation != null || nemesisMutationOperation != null || record.has("pending")) return
            val current = binding()
            lease = current.lease
            check(current.owner.kind == "account" && sessionFor(current) != null)
            val server = checkNotNull(db.bootstrapDao().binding(current.lease.storageScope))
            check(!server.requiresRecovery)
            val retryAt = checkNotNull(sessionFor(current)).optLong("apiRetryAt")
            if (retryAt > now()) { publish("Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s."); return }
            val previous = pendingConsent(current, server)
            val attempt = if (sourceId == null) checkNotNull(previous) else {
                check(previous == null)
                val source = (consentState as? RankingConsentState.Ready)?.source ?: error("Fresh source required")
                check(source.id == sourceId && consentFence == (current.lease to server.contextRevision))
                check(consentServerContext == (server.accountGeneration to server.syncEpoch))
                require(Math.subtractExact(now(), source.readAtMillis) in 0..300_000)
                val desired = checkNotNull(enabled)
                RankingConsentAttempt(UUID.randomUUID().toString(), current.lease.storageScope, current.lease.generation,
                    server.accountId, server.accountGeneration, server.syncEpoch, server.contextRevision, source.consents.revision,
                    desired, source.consents.automaticEnergyAdjustment, if (desired) source.ranking.consentEpoch else null)
            }
            // Persist the exact decision BEFORE any PUT. Retry never creates a different key or body.
            persist(copyRecord().put("rankingConsentAttempt", attempt.journal()))
            // AtomicFile may report a failed rename only in system logs. Verify the durable record before sending.
            withContext(Dispatchers.IO) {
                val durable = checkNotNull(vault.read().optJSONObject("rankingConsentAttempt"))
                require(StrictJson.canonical(durable) == StrictJson.canonical(attempt.journal()))
            }
            consentOperation = id
            serverProfile = null
            clearMotivation()
            clearRanking(); clearNemesis()
            publish()
            attempt
        } } catch (error: CancellationException) { withContext(NonCancellable) { finishConsent(id) }; throw error }
        catch (_: Exception) {
            mutex.withLock {
                if (consentOperation == id) consentOperation = null
                if (lease == null || owners.currentLease() == lease) {
                    consentState = RankingConsentState.Failed("Zapis wymaga aktualnego odczytu zgód i decyzji. Dziennik zachowany.")
                    publish()
                }
            }
            return
        }
        val capturedLease = checkNotNull(lease)
        try {
            val fresh = mutex.withLock {
                owners.requireCurrent(capturedLease)
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(capturedLease))
            var ticket = apiSession(capturedLease)
            var refreshed = false
            while (true) {
                val captured = ticket
                suspend fun ready() {
                    check(consentOperation == id)
                    val server = bootstraps.requireReady(capturedLease, request.contextRevision)
                    require(server.accountId == request.accountId && server.accountGeneration == request.accountGeneration && server.syncEpoch == request.syncEpoch)
                    val pending = checkNotNull(pendingConsent(binding(), server))
                    require(StrictJson.canonical(pending.journal()) == StrictJson.canonical(request.journal()))
                }
                val result = transport.put(captured, request) { withApiSession(captured) { ready() } }
                if (result.status == 200) {
                    val response = request.parseReceipt(result.body)
                    require(result.etag == "\"${response.revision}\"")
                    withApiSession(captured) {
                        ready()
                        persist(copyRecord().also { it.remove("rankingConsentAttempt") })
                        consentOperation = null
                        clearMotivation()
                        consentState = RankingConsentState.Confirmed(response)
                        consentFence = capturedLease to request.contextRevision
                        consentServerContext = request.accountGeneration to request.syncEpoch
                        publish("Serwer potwierdził decyzję o udziale w rankingu. Odśwież, aby sprawdzić bieżący stan.")
                    }
                    return
                }
                val code = if (result.status in setOf(429, 503)) "" else BootstrapHttpProtocol.errorCode(result.body)
                withApiSession(captured) { ready() }
                if (result.status == 401 && code == "unauthorized" && !refreshed) {
                    refreshed = true
                    check(refreshFor(capturedLease))
                    ticket = apiSession(capturedLease)
                    continue
                }
                if (result.status in setOf(409, 400, 422)) {
                    withApiSession(captured) {
                        ready()
                        persist(copyRecord().also { it.remove("rankingConsentAttempt") })
                        consentOperation = null
                        clearMotivation()
                        consentState = RankingConsentState.Failed("Stan zgód się zmienił lub poprzedni wynik jest niedostępny. Pobierz aktualne zgody i podejmij nową decyzję.")
                        publish()
                    }
                    return
                }
                if (result.status in setOf(429, 503)) {
                    val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                    val retryAt = Math.addExact(now(), Math.multiplyExact(seconds, 1000))
                    withApiSession(captured) {
                        ready()
                        val session = checkNotNull(sessionFor(binding()))
                        persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                    }
                }
                finishConsent(id)
                return
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { finishConsent(id) }; throw error
        } catch (_: Exception) { finishConsent(id) }
    }
    private suspend fun finishConsent(id: String) = mutex.withLock {
        if (consentOperation != id) return@withLock
        consentOperation = null
        clearMotivation()
        try { publish("Zapis nie został potwierdzony. Możesz ponowić tę samą decyzję; nie zmieniamy jej klucza ani treści.") }
        catch (_: Exception) { mutable.value = mutable.value.copy(rankingConsentBusy = false, rankingConsent = RankingConsentState.NotRequested,
            message = "Potwierdzenie jest niedostępne. Dziennik pozostaje zapisany.") }
    }

    suspend fun issueNemesisCode() = writeNemesis { _, _ -> NemesisCommand.issue() }
    suspend fun revokeNemesisCode() = writeNemesis { _, _ -> NemesisCommand.revoke() }
    suspend fun createNemesis(code: String, days: Int, zone: String, weight: Boolean, deficit: Boolean, acknowledged: Boolean) {
        if (!acknowledged) return
        writeNemesis { _, _ -> NemesisCommand.create(code, NemesisTerms(days, java.time.ZoneId.of(zone), weight, deficit)) }
    }
    suspend fun acceptNemesis(sourceId: String, acknowledged: Boolean, weightAcknowledged: Boolean, deficitAcknowledged: Boolean) {
        if (!acknowledged) return
        writeNemesis { current, server ->
            val source = requireNemesisDecision(sourceId, current, server)
            require(!source.challenge.terms.weight || weightAcknowledged)
            require(!source.challenge.terms.deficit || deficitAcknowledged)
            NemesisCommand.accept(source.challenge)
        }
    }
    suspend fun cancelNemesis(sourceId: String) = writeNemesis { current, server -> NemesisCommand.cancel(requireNemesisDecision(sourceId, current, server).challenge) }
    suspend fun retryNemesisMutation() = writeNemesis(null)
    private fun requireNemesisDecision(sourceId: String, current: SessionBinding, server: AccountBindingEntity): NemesisDecisionSource {
        val source = checkNotNull(nemesisDecisionSource)
        require(source.id == sourceId && nemesisFence == (current.lease to server.contextRevision) &&
            nemesisServerContext == Triple(server.accountId, server.accountGeneration, server.syncEpoch))
        require(Math.subtractExact(now(), source.readAtMillis) in 0..300_000)
        return source
    }
    private fun restoredNemesisAttempt(): NemesisAttempt? = try { record.optJSONObject("nemesisAttempt")?.let(NemesisAttempt::restore) } catch (_: Exception) { null }
    private fun currentNemesisAttempt(current: SessionBinding, server: AccountBindingEntity?): NemesisAttempt? = restoredNemesisAttempt()?.takeIf {
        sessionFor(current) != null && current.owner.kind == "account" && server != null && !server.requiresRecovery &&
            it.ownerScope == current.lease.storageScope && it.leaseGeneration == current.lease.generation &&
            it.accountId == server.accountId && it.accountGeneration == server.accountGeneration && it.epoch == server.syncEpoch && it.contextRevision == server.contextRevision
    }
    private suspend fun writeNemesis(make: ((SessionBinding, AccountBindingEntity) -> NemesisCommand)?) {
        val transport = nemesisWriteGateway ?: return
        val id = UUID.randomUUID().toString()
        var lease: OwnerLease? = null
        val request = try { mutex.withLock {
            if (nemesisMutationOperation != null || consentOperation != null || profileOperation != null || snapshotOperation != null || bootstrapOperation != null || operation != null || record.has("pending")) return
            val current = binding(); lease = current.lease
            check(current.owner.kind == "account" && sessionFor(current) != null)
            val server = checkNotNull(db.bootstrapDao().binding(current.lease.storageScope)); check(!server.requiresRecovery)
            val retryAt = checkNotNull(sessionFor(current)).optLong("apiRetryAt")
            if (retryAt > now()) { publish("Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s."); return }
            val previous = currentNemesisAttempt(current, server)
            val attempt = if (make == null) checkNotNull(previous) else {
                check(!record.has("nemesisAttempt"))
                val command = make(current, server)
                check(!command.grantsSharing || motivationGateway != null)
                NemesisAttempt(UUID.randomUUID().toString(), current.lease.storageScope, current.lease.generation, server.accountId,
                    server.accountGeneration, server.syncEpoch, server.contextRevision, command)
            }
            persist(copyRecord().put("nemesisAttempt", attempt.journal()))
            withContext(Dispatchers.IO) {
                val durable = checkNotNull(vault.read().optJSONObject("nemesisAttempt"))
                require(StrictJson.canonical(durable) == StrictJson.canonical(attempt.journal()))
            }
            nemesisMutationOperation = id
            serverProfile = null; clearMotivation(); clearRanking(); clearNemesis()
            nemesisMutationFence = current.lease to server.contextRevision
            nemesisMutationContext = Triple(server.accountId, server.accountGeneration, server.syncEpoch)
            nemesisMutationState = NemesisMutationState.Sending
            publish(); attempt
        } } catch (error: CancellationException) { withContext(NonCancellable) { finishNemesisMutation(id) }; throw error }
        catch (_: Exception) {
            mutex.withLock {
                if (nemesisMutationOperation == id) nemesisMutationOperation = null
                if (lease == null || owners.currentLease() == lease) {
                    nemesisMutationState = NemesisMutationState.Failed("Decyzja wymaga aktualnego stanu i potwierdzenia. Dziennik zachowany.")
                    publish()
                }
            }
            return
        }
        val capturedLease = checkNotNull(lease)
        try {
            val fresh = mutex.withLock {
                owners.requireCurrent(capturedLease)
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(capturedLease))
            var ticket = apiSession(capturedLease); var refreshed = false
            var preflight = request.command.grantsSharing
            while (true) {
                val captured = ticket
                suspend fun ready() {
                    check(nemesisMutationOperation == id)
                    val server = bootstraps.requireReady(capturedLease, request.contextRevision)
                    require(server.accountId == request.accountId && server.accountGeneration == request.accountGeneration && server.syncEpoch == request.epoch)
                    val pending = checkNotNull(currentNemesisAttempt(binding(), server))
                    require(StrictJson.canonical(pending.journal()) == StrictJson.canonical(request.journal()))
                }
                val result = if (preflight) checkNotNull(motivationGateway).get(captured) { withApiSession(captured) { ready() } }
                    else transport.send(captured, request) { withApiSession(captured) { ready() } }
                if (preflight && result.status == 200) {
                    val state = MotivationReadProtocol.parse(result.body)
                    withApiSession(captured) {
                        ready()
                        if (state.accountGeneration != request.accountGeneration || state.syncEpoch != request.epoch) {
                            val server = checkNotNull(db.bootstrapDao().binding(capturedLease.storageScope))
                            db.bootstrapDao().update(server.copy(requiresRecovery = true, contextRevision = Math.addExact(server.contextRevision, 1)))
                            persist(copyRecord().also { it.remove("nemesisAttempt") }); nemesisMutationOperation = null
                            clearNemesis(); publish("Stan konta się zmienił. Wymagane uzgodnienie; dawnej decyzji nie wysyłamy.")
                        } else preflight = false
                    }
                    if (nemesisMutationOperation != id) return
                    continue
                }
                if (!preflight && result.status == request.command.successStatus) {
                    val code = withContext(Dispatchers.Default) { request.command.receipt(result.body) }
                    withApiSession(captured) {
                        ready(); persist(copyRecord().also { it.remove("nemesisAttempt") }); nemesisMutationOperation = null
                        clearMotivation(); clearRanking(); clearNemesis()
                        nemesisMutationFence = capturedLease to request.contextRevision
                        nemesisMutationContext = Triple(request.accountId, request.accountGeneration, request.epoch)
                        nemesisMutationState = code?.let(NemesisMutationState::Issued) ?: NemesisMutationState.Confirmed(request.command.action)
                        publish("Serwer potwierdził operację. Aktualne udostępnianie sprawdź przez świeży odczyt.")
                    }
                    return
                }
                val reason = if (result.status in setOf(429,503)) "" else BootstrapHttpProtocol.errorCode(result.body)
                withApiSession(captured) { ready() }
                if (result.status == 401 && reason == "unauthorized" && !refreshed) {
                    refreshed = true; check(refreshFor(capturedLease)); ticket = apiSession(capturedLease); continue
                }
                if (result.status in setOf(400,403,404,409,410,422)) {
                    withApiSession(captured) {
                        ready(); persist(copyRecord().also { it.remove("nemesisAttempt") }); nemesisMutationOperation = null
                        clearNemesis()
                        nemesisMutationState = NemesisMutationState.Failed("Poprzednia decyzja nie może zostać ponowiona. Pobierz świeżą listę i sprawdź aktualny stan przed nową decyzją.")
                        publish()
                    }
                    return
                }
                if (result.status in setOf(429,503)) {
                    val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                    val retryAt = Math.addExact(now(), Math.multiplyExact(seconds,1000))
                    withApiSession(captured) {
                        ready(); val session = checkNotNull(sessionFor(binding()))
                        persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                    }
                }
                finishNemesisMutation(id); return
            }
        } catch (error: CancellationException) { withContext(NonCancellable) { finishNemesisMutation(id) }; throw error }
        catch (_: Exception) { finishNemesisMutation(id) }
    }
    private suspend fun finishNemesisMutation(id: String) = mutex.withLock {
        if (nemesisMutationOperation != id) return@withLock
        nemesisMutationOperation = null
        try { publish("Odpowiedź nie została potwierdzona. Ponów dokładnie tę samą decyzję; bez zmiany klucza, warunków lub celu.") }
        catch (_: Exception) { mutable.value = mutable.value.copy(nemesisMutationBusy = false, nemesisMutation = NemesisMutationState.Idle,
            message = "Potwierdzenie jest niedostępne. Dziennik zachowany.") }
    }


    /** Full server archive. The local diary remains editable, and no queue entry is acknowledged. */
    suspend fun downloadSnapshot() {
        val transport = snapshotGateway ?: return
        val store = snapshots ?: return
        val protocol = snapshotProtocol ?: return
        val id = UUID.randomUUID().toString()
        val lease = try { mutex.withLock {
            if (snapshotOperation != null || profileOperation != null || consentOperation != null || bootstrapOperation != null || operation != null || nemesisMutationOperation != null || record.has("pending")) return
            val current = binding()
            if (current.owner.kind != "account" || sessionFor(current) == null || !mutable.value.serverLinked) {
                publish("Zaloguj się i połącz konto, aby pobrać kopię serwera."); return
            }
            val retryAt = sessionFor(current)!!.optLong("apiRetryAt")
            if (retryAt > now()) { publish("Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s."); return }
            snapshotOperation = id
            mutable.value = mutable.value.copy(snapshotBusy = true, message = null)
            current.lease
        } } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutable.value = mutable.value.copy(message = "Pobieranie jest niedostępne. Dziennik zachowany."); return }
        try {
            val fresh = mutex.withLock {
                owners.requireCurrent(lease)
                val state = AuthState.jsonDeserialize(checkNotNull(sessionFor(binding())).getString("authState"))
                (state.accessTokenExpirationTime ?: 0) > now() + 30_000
            }
            if (!fresh) check(refreshFor(lease))
            var ticket = apiSession(lease)
            var request = withApiSession(ticket) { check(snapshotOperation == id); store.begin(lease) }
            var refreshed = false
            while (true) {
                val captured = ticket
                val sent = request
                suspend fun ready() { check(snapshotOperation == id); store.requireCurrent(sent) }
                val result = transport.get(captured, sent.query) { withApiSession(captured) { ready() } }
                if (result.status == 200) {
                    val next = withApiSession(captured) {
                        ready()
                        store.apply(sent, result.body)
                    }
                    mutex.withLock {
                        if (snapshotOperation == id) {
                            requireApi(captured)
                            if (next == null) snapshotOperation = null
                            publish(if (next == null) "Kopia serwera pobrana. Lokalny dziennik i kolejka zachowane." else null)
                        }
                    }
                    if (next == null) return
                    request = next
                    continue
                }
                val code = if (result.status in setOf(429, 503)) "" else protocol.errorCode(result.body)
                withApiSession(captured) { ready() }
                if (result.status == 401 && code == "unauthorized" && !refreshed) {
                    refreshed = true
                    check(refreshFor(lease))
                    ticket = apiSession(lease)
                    withApiSession(ticket) { ready() }
                    continue
                }
                val message = withApiSession(captured) {
                    ready()
                    when {
                        result.status in setOf(429, 503) -> {
                            val seconds = BootstrapHttpProtocol.retrySeconds(result.retryAfter, now())
                            val retryAt = Math.addExact(now(), Math.multiplyExact(seconds, 1000))
                            val session = checkNotNull(sessionFor(binding()))
                            persist(copyRecord().put("session", JSONObject(session.toString()).put("apiRetryAt", retryAt)))
                            "Serwer jest zajęty. Ponów za co najmniej $seconds s; pobrane strony zachowane."
                        }
                        result.status == 403 && code == "account_deleting" -> {
                            store.block(sent)
                            "Konto jest usuwane. Pobieranie zostało zablokowane; dane lokalne zachowane."
                        }
                        result.status == 410 && code in setOf("snapshot_expired", "sync_cursor_expired") -> {
                            store.expire(sent)
                            "Próba pobrania wygasła. Ponów od początku; poprzednia kopia i dziennik zachowane."
                        }
                        result.status == 409 && code in setOf("sync_epoch_changed", "account_generation_changed", "sync_reconciliation_required") -> {
                            store.invalidate(sent)
                            "Stan serwera się zmienił. Połącz konto ponownie; wymagane uzgodnienie, dane zachowane."
                        }
                        result.status == 401 -> "Sesja wymaga ponownego logowania. Pobrane strony i dziennik zachowane."
                        else -> "Pobieranie przerwane. Możesz je wznowić; dziennik zachowany."
                    }
                }
                mutex.withLock {
                    if (snapshotOperation == id) { owners.requireCurrent(lease); snapshotOperation = null; publish(message) }
                }
                return
            }
        } catch (error: CancellationException) {
            withContext(NonCancellable) { finishSnapshot(id, lease) }; throw error
        } catch (error: SnapshotCapacityException) {
            finishSnapshot(id, lease, "Pamięć kopii serwera jest pełna. Dziennik zachowany; potrzebne uporządkowanie kopii.")
        } catch (_: Exception) { finishSnapshot(id, lease) }
    }
    private suspend fun finishSnapshot(id: String, lease: OwnerLease,
        message: String = "Pobieranie przerwane. Ponów, aby wznowić; pobrane strony i dziennik zachowane.") = mutex.withLock {
        if (snapshotOperation != id) return@withLock
        snapshotOperation = null
        try { publish(if (owners.currentLease() == lease) message else null) }
        catch (_: Exception) { mutable.value = mutable.value.copy(snapshotBusy = false, message = message) }
    }
}
