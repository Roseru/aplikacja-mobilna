package pl.roseru.kalorie.core

enum class ActivityClass(val label: String, val goalFactor: String) {
    GARRISON("Etat biurowo-kawowy · mała aktywność", "1.00"),
    LINE("Linia · średnia aktywność", "1.25"),
    COMMANDO("Komandos · bardzo duża aktywność", "1.50")
}

// Relative goal presets, not an estimate of physiological energy expenditure.
fun activityCalorieGoal(currentKcal: Double, previous: ActivityClass, selected: ActivityClass): Double {
    require(currentKcal.isFinite() && currentKcal > 0 && currentKcal <= 20_000)
    if (previous == selected) return currentKcal
    return java.math.BigDecimal.valueOf(currentKcal)
        .multiply(java.math.BigDecimal(selected.goalFactor))
        .divide(java.math.BigDecimal(previous.goalFactor), 0, java.math.RoundingMode.HALF_UP)
        .toDouble().also { require(it > 0 && it <= 20_000) }
}
enum class DietAim(val label: String) { REDUCE("Redukcja"), MAINTAIN("Utrzymanie"), SURPLUS("Nadwyżka") }

/** Null means profile-only: compare the same initial choices as the profile editor. */
fun profileGoalCalories(currentKcal: Double, previousActivity: ActivityClass?, previousAim: DietAim?,
    selectedActivity: ActivityClass, selectedAim: DietAim): Double? {
    val previous = previousActivity ?: ActivityClass.GARRISON
    val aim = previousAim ?: DietAim.MAINTAIN
    val kcal = activityCalorieGoal(currentKcal, previous, selectedActivity)
    return kcal.takeIf { previous != selectedActivity || aim != selectedAim }
}

data class CustomProductDraft(val name: String, val kcal: Double, val protein: Double?, val fat: Double?,
    val carbs: Double?, val source: String) {
    fun validate() {
        require(name.trim().length in 2..100 && source.trim().length in 3..250)
        require(kcal.isFinite() && kcal in 0.0..1000.0)
        listOfNotNull(protein, fat, carbs).forEach { require(it.isFinite() && it in 0.0..100.0) }
    }
}

fun parseNumber(text: String): Double? = text.trim().replace(',', '.').toDoubleOrNull()?.takeIf { it.isFinite() }
