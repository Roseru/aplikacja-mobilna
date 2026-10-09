package pl.roseru.kalorie.core

enum class ActivityClass(val label: String) {
    GARRISON("Garnizon · mała aktywność"), LINE("Linia · średnia aktywność"), COMMANDO("Komandos · bardzo duża aktywność")
}
enum class DietAim(val label: String) { REDUCE("Redukcja"), MAINTAIN("Utrzymanie"), SURPLUS("Nadwyżka") }

data class CustomProductDraft(val name: String, val kcal: Double, val protein: Double?, val fat: Double?,
    val carbs: Double?, val source: String) {
    fun validate() {
        require(name.trim().length in 2..100 && source.trim().length in 3..250)
        require(kcal.isFinite() && kcal in 0.0..1000.0)
        listOfNotNull(protein, fat, carbs).forEach { require(it.isFinite() && it in 0.0..100.0) }
    }
}

fun parseNumber(text: String): Double? = text.trim().replace(',', '.').toDoubleOrNull()?.takeIf { it.isFinite() }
