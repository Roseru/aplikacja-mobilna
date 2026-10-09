package pl.roseru.kalorie.core

import java.text.Normalizer
import java.util.Locale

data class Nutrients(val kcal: Double, val protein: Double?, val fat: Double?, val carbs: Double?) {
    fun portion(grams: Double): Nutrients {
        require(grams.isFinite() && grams > 0 && grams <= MAX_GRAMS)
        val ratio = grams / 100.0
        return Nutrients(kcal * ratio, protein?.times(ratio), fat?.times(ratio), carbs?.times(ratio))
    }
    companion object { const val MAX_GRAMS = 10_000.0 }
}

fun Iterable<Nutrients>.total(): Nutrients {
    val values = toList()
    fun knownSum(read: (Nutrients) -> Double?): Double? =
        if (values.any { read(it) == null }) null else values.sumOf { read(it) ?: 0.0 }
    return Nutrients(values.sumOf { it.kcal }, knownSum { it.protein }, knownSum { it.fat }, knownSum { it.carbs })
}

fun parseAmount(text: String): Double? = text.trim().replace(',', '.').toDoubleOrNull()
    ?.takeIf { it.isFinite() && it > 0 && it <= Nutrients.MAX_GRAMS }

fun normalizeSearch(text: String): String = Normalizer.normalize(text.lowercase(Locale.ROOT).replace('ł', 'l'), Normalizer.Form.NFD)
    .replace(Regex("\\p{M}+"), "").trim()

fun decimal(value: Double): String = String.format(Locale.forLanguageTag("pl-PL"), "%.1f", value).removeSuffix(",0")

enum class MealType(val label: String) {
    BREAKFAST("Śniadanie"), LUNCH("Obiad"), DINNER("Kolacja"), SNACK("Przekąska")
}
