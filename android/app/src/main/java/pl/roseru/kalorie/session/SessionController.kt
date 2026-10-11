package pl.roseru.kalorie.session

import android.content.Intent
import android.net.Uri
import androidx.room.withTransaction
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import net.openid.appauth.*
import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.data.*
import java.util.UUID

data class SessionBinding(val owner: LocalOwnerEntity, val lease: OwnerLease)
data class SessionView(val binding: SessionBinding? = null, val busy: Boolean = false,
    val pendingLogin: Boolean = false, val configured: Boolean = false, val hasSession: Boolean = false,
    val message: String? = null, val apiConfigured: Boolean = false, val bootstrapBusy: Boolean = false,
    val serverLinked: Boolean = false, val requiresRecovery: Boolean = false)

/** Serializes durable decisions, not network waits. A callback/refresh is fenced by a captured
 * owner lease AND an operation ID, so logout and A→B→A cannot apply an old response.
 */
class SessionController internal constructor(private val db: CalorieDatabase, private val vault: SessionVault,
    private val gateway: OidcGateway, private val issuer: String, private val applicationId: String,
    private val now: () -> Long = System::currentTimeMillis,
    private val bootstrapGateway: BootstrapGateway? = null) {
    private val owners = LocalOwnerStore(db)
    private val mutex = Mutex()
    private var record = JSONObject()
    private var operation: String? = null
    private var bootstrapOperation: String? = null
    private var sessionRevision = 0L
    private val bootstraps = AccountBootstrapStore(db)
    private val mutable = MutableStateFlow(SessionView(configured = issuer.isNotEmpty()))
    val view = mutable.asStateFlow()
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
    private suspend fun publish(message: String? = null) {
        val current = binding()
        val session = sessionFor(current)
        val fresh = session?.let { AuthState.jsonDeserialize(it.getString("authState")).accessTokenExpirationTime?.let { expiry -> expiry > now() + 30_000 } } == true
        val server = db.bootstrapDao().binding(current.lease.storageScope)
        mutable.value = SessionView(current, configured = issuer.isNotEmpty(), pendingLogin = record.has("pending"), hasSession = fresh,
            message = message, apiConfigured = bootstrapGateway != null, bootstrapBusy = bootstrapOperation != null,
            serverLinked = server != null, requiresRecovery = server?.requiresRecovery == true)
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
            operation = id
            mutable.value = mutable.value.copy(busy = true, bootstrapBusy = false, message = null)
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
        forget()
        mutable.value = mutable.value.copy(binding = null)
        owners.selectIfCurrent(captured, guest.id)
        publish("Wylogowano z aplikacji. Otwarty dziennik gościa.")
        } } catch (error: CancellationException) { throw error }
        catch (_: Exception) { mutex.withLock {
            operation = null
            try { publish("Nie udało się otworzyć gościa. Spróbuj ponownie; dziennik konta pozostaje lokalny.") }
            catch (_: Exception) { mutable.value = mutable.value.copy(binding = previous, busy = false, hasSession = false,
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
                mutable.value = mutable.value.copy(busy = true, message = null)
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
            val current = binding()
            if (current.owner.kind != "account" || sessionFor(current) == null) {
                publish("Zaloguj się, aby połączyć konto z serwerem. Dziennik działa offline."); return
            }
            val retryAt = sessionFor(current)!!.optLong("apiRetryAt")
            if (retryAt > now()) {
                publish("Serwer jest zajęty. Ponów za co najmniej ${(retryAt - now() + 999) / 1000} s. Dziennik działa offline."); return
            }
            bootstrapOperation = id
            mutable.value = mutable.value.copy(bootstrapBusy = true, message = null)
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
}
