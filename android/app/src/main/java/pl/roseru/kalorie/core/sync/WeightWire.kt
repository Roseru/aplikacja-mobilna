package pl.roseru.kalorie.core.sync

import org.json.JSONObject
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit

/** Exact persisted weight payload. A local projection is never used to reconstruct a retry. */
class WeightWire private constructor(val canonical: String) {
    fun json() = StrictJson.read(canonical.toByteArray(Charsets.UTF_8))
    fun withWeight(kg: Double, schema: SyncWireSchema): WeightWire = read(
        StrictJson.canonical(json().put("weight_kg", decimal(kg))), schema)
    override fun toString() = "WeightWire(redacted)"

    companion object {
        private fun decimal(kg: Double): String {
            require(kg.isFinite() && kg in 20.0..400.0)
            return ContractDecimal.canonical(BigDecimal.valueOf(kg))
        }
        fun create(kg: Double, at: String, zone: String, date: String, schema: SyncWireSchema): WeightWire =
            read(StrictJson.canonical(JSONObject().put("weight_kg", decimal(kg))
                .put("occurred_at", Instant.parse(at).truncatedTo(ChronoUnit.MICROS).toString())
                .put("time_zone", zone).put("local_date", date)), schema)

        fun read(text: String, schema: SyncWireSchema): WeightWire = try {
            schema.validateWeight(text.toByteArray(Charsets.UTF_8))
            val value = StrictJson.read(text.toByteArray(Charsets.UTF_8))
            val kg = ContractDecimal.read(value.getString("weight_kg"))
            require(kg.signum() > 0)
            require(Instant.parse(value.getString("occurred_at")).atZone(ZoneId.of(value.getString("time_zone")))
                .toLocalDate() == LocalDate.parse(value.getString("local_date")))
            WeightWire(StrictJson.canonical(value))
        } catch (_: Exception) { throw SyncWireException() }

        fun operation(id: String, weightId: String, epoch: String, base: Int?, payload: String?, schema: SyncWireSchema): String {
            payload?.let { read(it, schema) }
            val wire = StrictJson.canonical(JSONObject().put("operation_id", id).put("entity_type", "weight")
                .put("entity_id", weightId).put("action", if (payload == null) "delete" else "upsert")
                .put("base_revision", base ?: JSONObject.NULL).put("sync_epoch", epoch)
                .put("payload", payload?.let { StrictJson.read(it.toByteArray(Charsets.UTF_8)) } ?: JSONObject.NULL))
            schema.validate(wire.toByteArray(Charsets.UTF_8), "Operation")
            return wire
        }
    }
}
