package pl.roseru.kalorie.core

import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Instant
import java.time.ZoneOffset
import java.time.temporal.ChronoUnit

enum class EquationVariant(val wire: String, val label: String, val offset: Int) {
    PLUS_5("plus_5", "Wariant +5", 5), MINUS_161("minus_161", "Wariant −161", -161)
}

data class MaintenanceInput(val age: Int, val height: BigDecimal, val weight: BigDecimal,
    val variant: EquationVariant, val activity: ActivityClass) {
    init {
        require(age in 18..120)
        require(height > BigDecimal.ZERO && height <= BigDecimal("300") && height.stripTrailingZeros().scale() <= 6)
        require(weight > BigDecimal.ZERO && weight <= BigDecimal("1000") && weight.stripTrailingZeros().scale() <= 6)
    }
    override fun toString() = "MaintenanceInput(redacted)"
}

/** Exact mifflin_pal_v1 audit; maintenance and the explicitly selected food goal are separate. */
@ConsistentCopyVisibility
data class MaintenanceEstimate private constructor(val input: MaintenanceInput, val resting: BigDecimal,
    val pal: BigDecimal, val maintenance: BigDecimal, val estimatedAt: Instant) {
    val suggestedGoal: BigDecimal get() = maintenance.setScale(0, RoundingMode.HALF_UP)
    fun json(): JSONObject = JSONObject().put("method", "mifflin_pal_v1")
        .put("input", JSONObject().put("age_years", input.age).put("height_cm", canonical(input.height))
            .put("weight_kg", canonical(input.weight)).put("equation_variant", input.variant.wire)
            .put("activity_class", when(input.activity) {ActivityClass.GARRISON -> "stationary";ActivityClass.LINE -> "line";ActivityClass.COMMANDO -> "commando"}))
        .put("resting_kcal", canonical(resting)).put("pal", canonical(pal))
        .put("maintenance_kcal", canonical(maintenance)).put("estimated_at", estimatedAt.toString())
    fun stored(): String = StrictJson.canonical(json())
    override fun toString() = "MaintenanceEstimate(redacted)"

    companion object {
        fun calculate(input: MaintenanceInput, at: Instant = Instant.now()): MaintenanceEstimate {
            require(at.atOffset(ZoneOffset.UTC).year in 1..9999)
            val normalized=input.copy(height=input.height.stripTrailingZeros(),weight=input.weight.stripTrailingZeros())
            val resting = normalized.weight.multiply(BigDecimal.TEN).add(normalized.height.multiply(BigDecimal("6.25")))
                .subtract(BigDecimal(normalized.age).multiply(BigDecimal("5"))).add(BigDecimal(normalized.variant.offset))
            val pal = when(normalized.activity) {ActivityClass.GARRISON -> "1.5";ActivityClass.LINE -> "1.8";ActivityClass.COMMANDO -> "2.2"}.toBigDecimal()
            val maintenance = resting.multiply(pal)
            require(resting > BigDecimal.ZERO && maintenance > BigDecimal.ZERO)
            return MaintenanceEstimate(normalized, resting, pal, maintenance, at.truncatedTo(ChronoUnit.MICROS))
        }
        /** UI accepts a Polish decimal comma; wire uses canonical decimal strings. */
        fun inputDecimal(text: String): BigDecimal? = text.trim().replace(',', '.').let { value ->
            if (!Regex("[0-9]{1,6}(\\.[0-9]{1,6})?").matches(value)) null
            else value.toBigDecimalOrNull()?.takeIf {it > BigDecimal.ZERO}
        }
        fun canonical(value: BigDecimal): String = value.stripTrailingZeros().toPlainString()
        fun read(text: String): MaintenanceEstimate {
            require(text.toByteArray(Charsets.UTF_8).size in 1..8192)
            val value=StrictJson.read(text.toByteArray(Charsets.UTF_8))
            fun keys(json:JSONObject,expected:Set<String>) {require(json.keys().asSequence().toSet()==expected)}
            keys(value,setOf("method","input","resting_kcal","pal","maintenance_kcal","estimated_at"))
            require(value.getString("method")=="mifflin_pal_v1")
            val raw=value.getJSONObject("input")
            keys(raw,setOf("age_years","height_cm","weight_kg","equation_variant","activity_class"))
            val age=raw.get("age_years");require(age is Int || age is Long)
            val input=MaintenanceInput(Math.toIntExact((age as Number).toLong()),wireDecimal(raw,"height_cm",6),wireDecimal(raw,"weight_kg",6),
                EquationVariant.entries.single {it.wire==raw.getString("equation_variant")},when(raw.getString("activity_class")) {
                    "stationary"->ActivityClass.GARRISON;"line"->ActivityClass.LINE;"commando"->ActivityClass.COMMANDO;else->error("Unknown activity")})
            val timestamp=value.getString("estimated_at")
            require(Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?Z").matches(timestamp))
            val result=calculate(input,Instant.parse(timestamp))
            require(result.resting.compareTo(wireDecimal(value,"resting_kcal",12))==0 && result.pal.compareTo(wireDecimal(value,"pal",6))==0 &&
                result.maintenance.compareTo(wireDecimal(value,"maintenance_kcal",12))==0)
            return result
        }
        private fun wireDecimal(value:JSONObject,key:String,scale:Int):BigDecimal {
            val raw=value.get(key);require(raw is String)
            require(Regex("(0|[1-9][0-9]{0,5})(\\.[0-9]{0,"+(scale-1)+"}[1-9])?").matches(raw))
            return raw.toBigDecimal().also {require(it > BigDecimal.ZERO)}
        }
    }
}
