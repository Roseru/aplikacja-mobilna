package pl.roseru.kalorie.core.sync

import org.json.JSONObject
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/** Semantic constraints shared by the archive reader and its local projections. */
internal object ServerDiaryValues {
    fun json(entity: ServerDiaryEntity): JSONObject = StrictJson.read(checkNotNull(entity.payload).toByteArray(Charsets.UTF_8))
    fun decimal(value: JSONObject, field: String): Double? =
        if (value.isNull(field)) null else ContractDecimal.read(value.getString(field)).toDouble()
    fun activity(value: JSONObject): ActivityClass = when (value.getString("activity_class")) {
        "stationary" -> ActivityClass.GARRISON
        "line" -> ActivityClass.LINE
        "commando" -> ActivityClass.COMMANDO
        else -> throw SyncWireException()
    }
    fun aim(value: JSONObject): DietAim = when (value.getString("goal_type")) {
        "reduce" -> DietAim.REDUCE
        "maintain" -> DietAim.MAINTAIN
        "gain" -> DietAim.SURPLUS
        else -> throw SyncWireException()
    }
    fun validate(type: String, text: String) {
        val value = StrictJson.read(text.toByteArray(Charsets.UTF_8))
        when (type) {
            "profile" -> {
                ZoneId.of(value.getString("time_zone")); activity(value)
                if (!value.isNull("height_cm")) require(ContractDecimal.read(value.getString("height_cm")) <= BigDecimal(300))
            }
            "goal" -> {
                LocalDate.parse(value.getString("effective_from"))
                Instant.parse(value.getString("decided_at")); ZoneId.of(value.getString("time_zone"))
                activity(value); aim(value)
                require((value.getString("reason") == "history_correction") == !value.isNull("correction_of"))
            }
            "diary_day" -> { LocalDate.parse(value.getString("local_date")); ZoneId.of(value.getString("time_zone")) }
            "product_draft" -> {
                require(value.isNull("density_g_per_ml") == value.isNull("density_source"))
                // Exercise exact arithmetic even when every nutrient is unknown.
                PrivateProductWire.portion(text, "100", value.getString("basis_unit"))
            }
            else -> throw SyncWireException()
        }
    }

    fun validateSnapshot(entities: List<ServerDiaryEntity>, timeline: Int) {
        val live = entities.filterNot { it.deleted }
        require(live.count { it.type == "profile" } <= 1)
        val dates = live.filter { it.type == "diary_day" }.map { json(it).getString("local_date") }
        require(dates.size == dates.toSet().size)
        val goals = live.filter { it.type == "goal" }.associateBy { it.id }
        val sequences = mutableSetOf<Int>()
        goals.forEach { (id, row) ->
            val goal = json(row)
            val base = goal.getInt("timeline_base_revision")
            require(base < timeline && sequences.add(base))
            if (!goal.isNull("correction_of")) {
                val parent = checkNotNull(goals[goal.getString("correction_of")])
                val prior = json(parent)
                require(parent.id != id && prior.getInt("timeline_base_revision") < base &&
                    prior.getString("effective_from") == goal.getString("effective_from"))
            }
        }
    }
}
