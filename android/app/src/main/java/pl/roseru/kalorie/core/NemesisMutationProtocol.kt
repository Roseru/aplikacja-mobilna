package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.time.Duration
import java.time.Instant
import java.util.Base64

enum class NemesisAction { ISSUE, REVOKE, CREATE, ACCEPT, CANCEL }
class NemesisCode(val value: String, val issuedAt: Instant, val expiresAt: Instant) {
    override fun toString() = "NemesisCode(redacted)"
}
class NemesisDecisionSource(val id: String, val challenge: NemesisChallenge, val readAtMillis: Long) {
    override fun toString() = "NemesisDecisionSource(redacted)"
}
sealed interface NemesisMutationState {
    data object Idle : NemesisMutationState
    data object Sending : NemesisMutationState
    data object Blocked : NemesisMutationState
    class Pending(val action: NemesisAction, val message: String?) : NemesisMutationState
    class Issued(val code: NemesisCode) : NemesisMutationState
    class Confirmed(val action: NemesisAction) : NemesisMutationState
    data class Failed(val message: String) : NemesisMutationState
}

internal fun NemesisTerms.wire() = JSONObject().put("rule_version", Achievements.RULE).put("duration_days", days).put("time_zone", zone.id)
    .put("scope", JSONObject().put("regularity", true).put("weight_change", weight).put("mean_deficit", deficit))

/** Typed semantic request; the canonical bytes are fixed once the user confirms. */
internal class NemesisCommand private constructor(val action: NemesisAction, private val encodedBody: String?, val target: String?,
    val baseRevision: Int?, val role: String?) {
    val grantsSharing get() = action in setOf(NemesisAction.ISSUE, NemesisAction.CREATE, NemesisAction.ACCEPT)
    val method get() = if (action == NemesisAction.REVOKE) "DELETE" else "POST"
    val successStatus get() = if (action == NemesisAction.CREATE) 201 else 200
    fun path() = when (action) {
        NemesisAction.ISSUE, NemesisAction.REVOKE -> "/me/nemesis/share-code"
        NemesisAction.CREATE -> "/nemesis"
        NemesisAction.ACCEPT -> "/nemesis/$target/accept"
        NemesisAction.CANCEL -> "/nemesis/$target/cancel"
    }
    fun body(): ByteArray? = encodedBody?.toByteArray(Charsets.UTF_8)
    fun journal(): JSONObject = JSONObject().put("action", action.name).put("body", encodedBody ?: JSONObject.NULL)
        .put("target", target ?: JSONObject.NULL).put("baseRevision", baseRevision ?: JSONObject.NULL).put("role", role ?: JSONObject.NULL)
    fun receipt(bytes: ByteArray): NemesisCode? {
        require(bytes.size in 1..NemesisReadProtocol.MAX_BYTES)
        when (action) {
            NemesisAction.ISSUE -> {
                val value = StrictJson.read(bytes); exact(value, "destination_code", "issued_at", "expires_at")
                val code = (value.get("destination_code") as String).also(::validateCode)
                val issued = NemesisReadProtocol.timestamp(value.get("issued_at") as String)
                val expiry = NemesisReadProtocol.timestamp(value.get("expires_at") as String)
                require(expiry > issued && Duration.between(issued, expiry) <= Duration.ofHours(24))
                return NemesisCode(code, issued, expiry)
            }
            NemesisAction.REVOKE -> { val value = StrictJson.read(bytes); exact(value, "revoked"); require(value.get("revoked") == true) }
            else -> {
                val value = NemesisReadProtocol.metadata(bytes)
                require(value.role == role)
                if (action == NemesisAction.CREATE) require(value.revision >= 1)
                else require(value.id == target && value.revision >= Math.addExact(checkNotNull(baseRevision), 1))
                val body = StrictJson.read(checkNotNull(body()))
                if (action == NemesisAction.CANCEL) require(value.status == "cancelled")
                else {
                    require(StrictJson.canonical(value.terms.wire()) == StrictJson.canonical(body.getJSONObject("terms")))
                    if (action == NemesisAction.ACCEPT) require(value.status in setOf("active", "finished", "cancelled") && value.acceptedAt != null)
                }
                // Replays return current metadata, possibly already cancelled. Never treat an ACK as sharing authority.
            }
        }
        return null
    }
    override fun toString() = "NemesisCommand(redacted)"
    companion object {
        fun issue() = NemesisCommand(NemesisAction.ISSUE, null, null, null, null)
        fun revoke() = NemesisCommand(NemesisAction.REVOKE, null, null, null, null)
        fun create(code: String, terms: NemesisTerms): NemesisCommand {
            validateCode(code); NemesisReadProtocol.terms(terms.wire())
            return NemesisCommand(NemesisAction.CREATE, StrictJson.canonical(JSONObject().put("destination_code", code).put("terms", terms.wire())), null, null, "inviter")
        }
        fun accept(challenge: NemesisChallenge): NemesisCommand {
            require(challenge.status == "invited" && challenge.role == "invitee")
            return bound(NemesisAction.ACCEPT, challenge, JSONObject().put("terms", challenge.terms.wire()))
        }
        fun cancel(challenge: NemesisChallenge): NemesisCommand {
            require(challenge.status in setOf("invited", "active", "finished"))
            val reason = if (challenge.status != "invited") "sharing_revoked" else if (challenge.role == "inviter") "withdrawn" else "declined"
            return bound(NemesisAction.CANCEL, challenge, JSONObject().put("reason", reason))
        }
        private fun bound(action: NemesisAction, challenge: NemesisChallenge, body: JSONObject): NemesisCommand {
            NemesisReadProtocol.uuid(challenge.id)
            require(challenge.revision in 1 until Int.MAX_VALUE && challenge.role in setOf("inviter", "invitee"))
            return NemesisCommand(action, StrictJson.canonical(body), challenge.id, challenge.revision, challenge.role)
        }
        internal fun restore(value: JSONObject): NemesisCommand {
            exact(value, "action", "body", "target", "baseRevision", "role")
            val action = NemesisAction.valueOf(value.get("action") as String)
            val target = optional(value, "target") { (it as String).also(NemesisReadProtocol::uuid) }
            val revision = optional(value, "baseRevision") { integer(it).also { v -> require(v in 1 until Int.MAX_VALUE) }.toInt() }
            val role = optional(value, "role") { (it as String).also { r -> require(r in setOf("inviter", "invitee")) } }
            val body = optional(value, "body") { (it as String).also { b -> require(b.toByteArray().size <= 16_384) } }
            if (action in setOf(NemesisAction.ISSUE, NemesisAction.REVOKE)) require(target == null && revision == null && role == null && body == null)
            else {
                val json = StrictJson.read(checkNotNull(body).toByteArray())
                require(StrictJson.canonical(json) == body)
                when (action) {
                    NemesisAction.CREATE -> { exact(json, "destination_code", "terms"); validateCode(json.get("destination_code") as String); NemesisReadProtocol.terms(json.getJSONObject("terms")); require(target == null && revision == null && role == "inviter") }
                    NemesisAction.ACCEPT -> { exact(json, "terms"); NemesisReadProtocol.terms(json.getJSONObject("terms")); require(target != null && revision != null && role == "invitee") }
                    NemesisAction.CANCEL -> {
                        exact(json, "reason"); val reason=json.get("reason")
                        require(reason in setOf("withdrawn", "declined", "sharing_revoked")); require(target != null && revision != null && role != null)
                        require(reason != "withdrawn" || role == "inviter"); require(reason != "declined" || role == "invitee")
                    }
                    else -> error("Unreachable")
                }
            }
            return NemesisCommand(action, body, target, revision, role)
        }
        internal fun validateCode(value: String) {
            require(Regex("[A-Za-z0-9_-]{43}").matches(value))
            val decoded = Base64.getUrlDecoder().decode(value + "=")
            require(decoded.size == 32 && Base64.getUrlEncoder().withoutPadding().encodeToString(decoded) == value)
        }
        private fun exact(value: JSONObject, vararg keys: String) = require(value.keys().asSequence().toSet() == keys.toSet())
        private fun integer(value: Any): Long { require(value is Int || value is Long); return (value as Number).toLong() }
        private fun <T> optional(value: JSONObject, key: String, parse: (Any) -> T): T? = if (value.get(key) === JSONObject.NULL) null else parse(value.get(key))
    }
}

internal class NemesisAttempt(val key: String, val ownerScope: String, val leaseGeneration: Long, val accountId: String,
    val accountGeneration: Int, val epoch: String, val contextRevision: Long, val command: NemesisCommand) {
    init {
        listOf(key, ownerScope, accountId, epoch).forEach(NemesisReadProtocol::uuid)
        require(leaseGeneration > 0 && accountGeneration > 0 && contextRevision > 0)
    }
    fun journal() = JSONObject().put("key", key).put("ownerScope", ownerScope).put("leaseGeneration", leaseGeneration).put("accountId", accountId)
        .put("accountGeneration", accountGeneration).put("epoch", epoch).put("contextRevision", contextRevision).put("command", command.journal())
    override fun toString() = "NemesisAttempt(redacted)"
    companion object {
        fun restore(value: JSONObject): NemesisAttempt {
            require(value.keys().asSequence().toSet() == setOf("key", "ownerScope", "leaseGeneration", "accountId", "accountGeneration", "epoch", "contextRevision", "command"))
            fun positive(key: String): Long { val n=value.get(key); require(n is Int || n is Long); return (n as Number).toLong().also { require(it > 0) } }
            return NemesisAttempt(value.get("key") as String, value.get("ownerScope") as String, positive("leaseGeneration"), value.get("accountId") as String,
                Math.toIntExact(positive("accountGeneration")), value.get("epoch") as String, positive("contextRevision"), NemesisCommand.restore(value.getJSONObject("command")))
        }
    }
}
