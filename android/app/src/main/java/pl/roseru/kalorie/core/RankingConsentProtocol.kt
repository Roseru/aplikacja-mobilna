package pl.roseru.kalorie.core

import org.json.JSONObject

class RankingConsentSource(val id: String, val consents: ServerConsents, val ranking: MotivationRanking, val readAtMillis: Long) {
    override fun toString() = "RankingConsentSource(redacted)"
}
sealed interface RankingConsentState {
    data object NotRequested : RankingConsentState
    data object Loading : RankingConsentState
    data class Ready(val source: RankingConsentSource) : RankingConsentState
    data class Pending(val enabled: Boolean) : RankingConsentState
    data class Confirmed(val consents: ServerConsents) : RankingConsentState
    data class Failed(val message: String) : RankingConsentState
}

/** An explicitly approved online operation, encrypted with the session; never a diary outbox entry. */
internal class RankingConsentAttempt(val key: String, val ownerScope: String, val leaseGeneration: Long,
    val accountId: String, val accountGeneration: Int, val syncEpoch: String, val contextRevision: Long,
    val baseRevision: Int, val ranking: Boolean, val automaticEnergyAdjustment: Boolean, val consentEpoch: String?) {
    init {
        listOf(key, ownerScope, accountId, syncEpoch).forEach { require(BootstrapProtocol.uuid.matches(it)) }
        require(leaseGeneration > 0 && accountGeneration > 0 && contextRevision > 0)
        require(baseRevision in 1 until Int.MAX_VALUE)
        require(if (ranking) consentEpoch == syncEpoch else consentEpoch == null)
    }
    fun body(): ByteArray = "{\"ranking\":$ranking,\"automatic_energy_adjustment\":$automaticEnergyAdjustment}".toByteArray(Charsets.UTF_8)
    fun journal(): JSONObject = JSONObject().put("key", key).put("ownerScope", ownerScope).put("leaseGeneration", leaseGeneration)
        .put("accountId", accountId).put("accountGeneration", accountGeneration).put("syncEpoch", syncEpoch)
        .put("contextRevision", contextRevision).put("baseRevision", baseRevision).put("ranking", ranking)
        .put("automaticEnergyAdjustment", automaticEnergyAdjustment).put("consentEpoch", consentEpoch ?: JSONObject.NULL)
    fun parseReceipt(bytes: ByteArray): ServerConsents = ProfileReadProtocol.parseConsents(bytes).also {
        require(it.revision == Math.addExact(baseRevision, 1) && it.ranking == ranking && it.automaticEnergyAdjustment == automaticEnergyAdjustment)
    }
    override fun toString() = "RankingConsentAttempt(redacted)"
    companion object {
        fun restore(json: JSONObject): RankingConsentAttempt {
            require(json.keys().asSequence().toSet() == setOf("key", "ownerScope", "leaseGeneration", "accountId", "accountGeneration",
                "syncEpoch", "contextRevision", "baseRevision", "ranking", "automaticEnergyAdjustment", "consentEpoch"))
            fun integer(key: String): Long {
                val value = json.get(key)
                require(value is Int || value is Long)
                return (value as Number).toLong()
            }
            fun positiveInt(key: String) = Math.toIntExact(integer(key)).also { require(it > 0) }
            return RankingConsentAttempt(json.get("key") as String, json.get("ownerScope") as String, integer("leaseGeneration"),
                json.get("accountId") as String, positiveInt("accountGeneration"), json.get("syncEpoch") as String,
                integer("contextRevision"), positiveInt("baseRevision"), json.get("ranking") as Boolean,
                json.get("automaticEnergyAdjustment") as Boolean,
                if (json.get("consentEpoch") === JSONObject.NULL) null else json.get("consentEpoch") as String)
        }
    }
}
