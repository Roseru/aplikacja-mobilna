package pl.roseru.kalorie.core

import java.math.BigDecimal
import java.math.RoundingMode

class NutritionError(val code: String) : IllegalArgumentException(code)

/** Canonical E0 input. Computed results deliberately have no six-place truncation. */
object ContractDecimal {
    private val pattern = Regex("^(0|[1-9][0-9]{0,5})(\\.[0-9]{0,5}[1-9])?$")
    fun read(text: String, code: String = "decimal_format"): BigDecimal {
        if (!pattern.matches(text)) throw NutritionError(code)
        return BigDecimal(text)
    }
    fun canonical(value: BigDecimal): String = value.stripTrailingZeros().toPlainString()
    fun userQuantity(text: String, maxPlaces: Int = 6): BigDecimal? {
        val normalized = text.trim().replace(',', '.')
        require(maxPlaces in 1..12)
        if (!Regex("^(0|[1-9][0-9]{0,5})(\\.[0-9]{1,$maxPlaces})?$").matches(normalized)) return null
        val value = BigDecimal(normalized)
        return value.takeIf { it > BigDecimal.ZERO && it <= BigDecimal("10000") }
    }
}

enum class QuantityUnit(val wire: String) {
    GRAMS("g"), MILLILITRES("ml");
    companion object {
        fun read(text: String): QuantityUnit = entries.firstOrNull { it.wire == text }
            ?: throw NutritionError("quantity_unit")
    }
}

data class ExactNutrition(val energy: BigDecimal?, val protein: BigDecimal?, val fat: BigDecimal?, val carbs: BigDecimal?) {
    fun values(): List<BigDecimal?> = listOf(energy, protein, fat, carbs)
    companion object {
        val fields = listOf("energy_kcal", "protein_g", "fat_g", "carbs_g")
        fun read(values: Map<String, String?>): ExactNutrition {
            if (values.keys != fields.toSet()) throw NutritionError("nutrition_fields")
            val numbers = fields.map { field -> values[field]?.let { ContractDecimal.read(it, "nutrition_range") } }
            return ExactNutrition(numbers[0], numbers[1], numbers[2], numbers[3])
        }
    }
}

data class ExactDensity(val gramsPerMl: BigDecimal, val sourceId: String) {
    init {
        if (gramsPerMl <= BigDecimal.ZERO) throw NutritionError("density_range")
        if (sourceId.isBlank()) throw NutritionError("density_required")
    }
}

data class ExactPortion(val amount: BigDecimal, val unit: QuantityUnit, val basisUnit: QuantityUnit,
    val per100: ExactNutrition, val density: ExactDensity? = null)

data class FieldAggregate(val knownSum: BigDecimal, val missingCount: Int, val displayScale: Int) {
    val complete: Boolean get() = missingCount == 0
    val canonical: String get() = ContractDecimal.canonical(knownSum)
    val display: String get() = knownSum.setScale(displayScale, RoundingMode.HALF_UP).toPlainString()
}

data class ExactTotals(val energy: FieldAggregate, val protein: FieldAggregate, val fat: FieldAggregate, val carbs: FieldAggregate) {
    fun fields(): List<FieldAggregate> = listOf(energy, protein, fat, carbs)
}

object NutritionV1 {
    const val FORMULA = "nutrition_v1"
    private val maximumAmount = BigDecimal("10000")
    private val maximumNutrition = BigDecimal("999999.999999")

    fun calculate(items: Iterable<ExactPortion>): ExactTotals {
        val sums = MutableList(4) { BigDecimal.ZERO }
        val missing = IntArray(4)
        items.forEach { item ->
            if (item.amount <= BigDecimal.ZERO || item.amount > maximumAmount) throw NutritionError("quantity_range")
            var amount = item.amount
            if (item.unit != item.basisUnit) {
                val density = item.density ?: throw NutritionError("density_required")
                if (density.gramsPerMl > maximumNutrition) throw NutritionError("density_range")
                amount = if (item.unit == QuantityUnit.MILLILITRES) amount.multiply(density.gramsPerMl)
                    else amount.divide(density.gramsPerMl, 12, RoundingMode.HALF_UP)
            }
            item.per100.values().forEachIndexed { index, value ->
                if (value == null) missing[index]++
                else {
                    if (value < BigDecimal.ZERO || value > maximumNutrition) throw NutritionError("nutrition_range")
                    sums[index] = sums[index].add(value.multiply(amount).movePointLeft(2))
                }
            }
        }
        fun field(index: Int) = FieldAggregate(sums[index], missing[index], if (index == 0) 0 else 1)
        return ExactTotals(field(0), field(1), field(2), field(3))
    }
}
