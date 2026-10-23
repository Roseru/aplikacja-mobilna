package pl.roseru.kalorie.core.sync

import org.json.JSONObject
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/** Exact private-domain payloads. No projection, missing value or catalogue source is invented. */
object PrivateDomainsWire {
    val types: Set<String> = setOf("profile", "goal", "diary_day", "product_draft")
    private const val VALIDATION_ID = "11111111-1111-4111-8111-111111111111"

    /** Returns a detached canonical snapshot; ordinary input decimals remain limited to six places. */
    fun read(type: String, payload: String, schema: SyncWireSchema): String = safe {
        require(type in types)
        require(payload.toByteArray(Charsets.UTF_8).size <= PushProtocol.MAX_PAYLOAD_BYTES)
        val value = StrictJson.read(payload.toByteArray(Charsets.UTF_8))
        // Reuse the pinned domain definitions through Operation, without a second schema interpreter.
        val envelope = envelope(VALIDATION_ID, type, VALIDATION_ID, VALIDATION_ID, null, value)
        schema.validate(StrictJson.canonical(envelope).toByteArray(Charsets.UTF_8), "Operation")
        when (type) {
            "profile" -> {
                if (!value.isNull("height_cm")) require(decimal(value, "height_cm") <= BigDecimal(300))
            }
            "goal" -> validateGoal(value)
            "product_draft" -> {
                require(value.isNull("density_g_per_ml") == value.isNull("density_source"))
                if (!value.isNull("package_quantity")) {
                    val quantity = value.getJSONObject("package_quantity")
                    require(quantity.getString("unit") == value.getString("basis_unit") ||
                        !value.isNull("density_g_per_ml"))
                }
            }
        }
        StrictJson.canonical(value)
    }

    /** The optional timeline is an assertion, never a rewrite of an already persisted goal. */
    fun operation(opId: String, type: String, id: String, epoch: String, revision: Int?,
        payload: String?, schema: SyncWireSchema, timelineBaseRevision: Int? = null): String = safe {
        require(type in types)
        val value = payload?.let { StrictJson.read(read(type, it, schema).toByteArray(Charsets.UTF_8)) }
        if (timelineBaseRevision != null) {
            require(type == "goal" && value != null && timelineBaseRevision >= 0)
            require(value.getInt("timeline_base_revision") == timelineBaseRevision)
        }
        val wire = StrictJson.canonical(envelope(opId, type, id, epoch, revision, value))
        schema.validate(wire.toByteArray(Charsets.UTF_8), "Operation")
        wire
    }

    private fun envelope(opId: String, type: String, id: String, epoch: String,
        revision: Int?, payload: JSONObject?): JSONObject = JSONObject()
        .put("operation_id", opId).put("entity_type", type).put("entity_id", id)
        .put("action", if (payload == null) "delete" else "upsert")
        .put("base_revision", revision ?: JSONObject.NULL).put("sync_epoch", epoch)
        .put("payload", payload ?: JSONObject.NULL)

    private fun decimal(value: JSONObject, key: String) = ContractDecimal.read(value.getString(key))

    private fun validateGoal(value: JSONObject) {
        require(decimal(value, "energy_kcal") <= BigDecimal(20000))
        for (key in listOf("protein_g", "fat_g", "carbs_g")) {
            if (!value.isNull(key)) require(decimal(value, key) <= BigDecimal(5000))
        }
        val day = Instant.parse(value.getString("decided_at"))
            .atZone(ZoneId.of(value.getString("time_zone"))).toLocalDate()
        val effective = LocalDate.parse(value.getString("effective_from"))
        if (value.getString("reason") == "user_decision") {
            require(value.isNull("correction_of") && effective >= day)
        } else require(!value.isNull("correction_of"))
        if (!value.isNull("estimate")) validateEstimate(value.getJSONObject("estimate"))
    }

    private fun validateEstimate(value: JSONObject) {
        val input = value.getJSONObject("input")
        require(decimal(input, "height_cm") <= BigDecimal(300))
        require(decimal(input, "weight_kg") <= BigDecimal(1000))
        val resting = BigDecimal.TEN.multiply(decimal(input, "weight_kg"))
            .add(BigDecimal("6.25").multiply(decimal(input, "height_cm")))
            .subtract(BigDecimal(5).multiply(BigDecimal(input.getInt("age_years"))))
            .add(BigDecimal(if (input.getString("equation_variant") == "plus_5") 5 else -161))
        val pal = when (input.getString("activity_class")) {
            "stationary" -> "1.5"
            "line" -> "1.8"
            "commando" -> "2.2"
            else -> throw SyncWireException()
        }
        require(value.getString("pal") == pal)
        // ComputedDecimal intentionally permits twelve places, unlike six-place user input.
        require(BigDecimal(value.getString("resting_kcal")).compareTo(resting) == 0)
        require(BigDecimal(value.getString("maintenance_kcal")).compareTo(resting.multiply(BigDecimal(pal))) == 0)
    }

    private inline fun <T> safe(action: () -> T): T = try { action() }
        catch (_: Exception) { throw SyncWireException() }
}
