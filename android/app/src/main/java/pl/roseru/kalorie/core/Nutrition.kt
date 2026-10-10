package pl.roseru.kalorie.core

import java.text.Normalizer
import java.util.Locale
import java.math.BigDecimal
import java.math.RoundingMode

data class Nutrients(val kcal: Double, val protein: Double?, val fat: Double?, val carbs: Double?, val exact: ExactTotals? = null) {
    fun portion(grams: Double): Nutrients {
        require(grams.isFinite() && grams > 0 && grams <= MAX_GRAMS)
        val fields = asExact().fields().map { if (it.complete) it.knownSum else null }
        return fromExact(NutritionV1.calculate(listOf(ExactPortion(BigDecimal.valueOf(grams), QuantityUnit.GRAMS,
            QuantityUnit.GRAMS, ExactNutrition(fields[0], fields[1], fields[2], fields[3])))))
    }
    fun asExact(): ExactTotals {
        fun field(value: Double?, scale: Int) = FieldAggregate(value?.let(BigDecimal::valueOf) ?: BigDecimal.ZERO, if (value == null) 1 else 0, scale)
        return exact ?: ExactTotals(field(kcal, 0), field(protein, 1), field(fat, 1), field(carbs, 1))
    }
    companion object {
        const val MAX_GRAMS = 10_000.0
        fun fromExact(value: ExactTotals): Nutrients = Nutrients(value.energy.knownSum.toDouble(),
            value.protein.takeIf { it.complete }?.knownSum?.toDouble(), value.fat.takeIf { it.complete }?.knownSum?.toDouble(),
            value.carbs.takeIf { it.complete }?.knownSum?.toDouble(), value)
    }
}

fun Iterable<Nutrients>.total(): Nutrients {
    val values = map { it.asExact().fields() }
    fun field(index: Int) = FieldAggregate(values.fold(BigDecimal.ZERO) { sum, value -> sum.add(value[index].knownSum) },
        values.sumOf { it[index].missingCount }, if (index == 0) 0 else 1)
    return Nutrients.fromExact(ExactTotals(field(0), field(1), field(2), field(3)))
}

fun parseAmount(text: String): Double? = text.trim().replace(',', '.').toDoubleOrNull()
    ?.takeIf { it.isFinite() && it > 0 && it <= Nutrients.MAX_GRAMS }

fun normalizeSearch(text: String): String = Normalizer.normalize(text.lowercase(Locale.ROOT).replace('ł', 'l'), Normalizer.Form.NFD)
    .replace(Regex("\\p{M}+"), "").trim()

fun decimal(value: Double): String = BigDecimal.valueOf(value).setScale(1, RoundingMode.HALF_UP).toPlainString().replace('.', ',').removeSuffix(",0")

enum class MealType(val label: String) {
    BREAKFAST("Śniadanie"), LUNCH("Obiad"), DINNER("Kolacja"), SNACK("Przekąska")
}

fun Nutrients.energyText(): String = asExact().energy.let { (if (it.complete) "" else "≥ ") + it.display }
fun quantityText(value: String): String = value.replace('.', ',')
