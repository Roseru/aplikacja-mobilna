package pl.roseru.kalorie.session

import android.content.Intent
import android.net.Uri
import kotlinx.coroutines.CancellationException
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
    val message: String? = null)

/** Serializes durable decisions, not network waits. A callback/refresh is fenced by a captured
 * owner lease AND an operation ID, so logout and A→B→A cannot apply an old response.
 */
class SessionController internal constructor(private val db: CalorieDatabase, private val vault: SessionVault,
    private val gateway: OidcGateway, private val issuer: String, private val applicationId: String,
    private val now: () -> Long = System::currentTimeMillis) {
    private val owners = LocalOwnerStore(db)
    private val mutex = Mutex()
    private var record = JSONObject()
    private var operation: String? = null
    private val mutable = MutableStateFlow(SessionView(configured = issuer.isNotEmpty()))
    val view = mutable.asStateFlow()
    private fun copyRecord() = JSONObject(record.toString())
    private suspend fun persist(value: JSONObject) { withContext(Dispatchers.IO) { vault.write(value) }; record = value }
    private suspend fun forget() {
        // A failed Keystore/storage cleanup never re-enables a session or blocks the diary.
        withContext(Dispatchers.IO) { try { vault.clear() } catch (_: Exception) { } }
        record = JSONObject()
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
        mutable.value = SessionView(current, configured = issuer.isNotEmpty(), pendingLogin = record.has("pending"), hasSession = fresh, message = message)
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
            operation = id
            mutable.value = mutable.value.copy(busy = true, message = null)
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
    suspend fun refresh() {
        val id = UUID.randomUUID().toString()
        var registered = false
        try {
            val captured = mutex.withLock {
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
            mutex.withLock {
                if (operation != id) return@withLock
                owners.requireCurrent(captured.first.lease)
                captured.second.update(tokens, null)
                val session = checkNotNull(sessionFor(captured.first))
                persist(copyRecord().put("session", JSONObject(session.toString()).put("authState", captured.second.jsonSerializeString())))
                operation = null
                publish("Sesja odnowiona. Dziennik zachowany.")
            }
        } catch (error: CancellationException) { fail(id, "Odnowienie przerwane. Dziennik działa offline."); throw error }
        catch (_: Exception) {
            mutex.withLock {
                if (registered && operation != id) return@withLock
                if (operation != null && operation != id) return@withLock
                if (operation == id) operation = null
                publish("Sesji nie udało się odnowić. Dziennik działa offline; spróbuj zalogować się ponownie.")
            }
        }
    }
}
