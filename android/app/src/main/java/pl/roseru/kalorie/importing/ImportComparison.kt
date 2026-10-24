package pl.roseru.kalorie.importing

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.sync.LegacyImportWire
import pl.roseru.kalorie.data.ImportSource

enum class ImportSideState { PRESENT, ABSENT, DELETED, UNVERIFIED, UNREADABLE }
data class ImportComparisonValue(val label: String, val value: String)
data class ImportComparisonSide(val state: ImportSideState, val values: List<ImportComparisonValue> = emptyList())

/** Read-only presentation of exact archived values and an already verified server version. */
object ImportComparison {
    private const val UNKNOWN = "Brak danych"
    private val uuid = Regex("[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
    private fun read(text: String) = LegacyImportWire.readSource(text)
    private fun scalar(row: JSONObject, vararg keys: String): String? {
        val key = keys.firstOrNull { row.has(it) } ?: return null
        if (row.isNull(key)) return null
        val value = row.get(key)
        if (value !is String && value !is Boolean) return null
        val text = value.toString()
        if (text.isEmpty() || uuid.containsMatchIn(text) || text.trimStart().startsWith('{') || text.trimStart().startsWith('[')) return null
        return text
    }
    private fun deleted(row: JSONObject) = scalar(row, "deleted") in setOf("1", "true")
    fun local(source: ImportSource): ImportComparisonSide = try {
        val archive = read(source.sourceJson)
        // Read the canonical JSON explicitly; scalar deliberately excludes raw objects from display.
        if (archive.has("canonical_payload") && !archive.isNull("canonical_payload")) {
            val row = archive.getJSONObject("row")
            if (deleted(row)) ImportComparisonSide(ImportSideState.DELETED)
            else present(source.entityType, read(archive.getString("canonical_payload")))
        } else {
            val row = archive.getJSONObject("row")
            if (deleted(row)) ImportComparisonSide(ImportSideState.DELETED)
            else {
                val sourceRow = if (source.entityType == "product_draft" && row.has("wirePayload") && !row.isNull("wirePayload"))
                    read(row.getString("wirePayload")) else row
                if (source.entityType == "goal") addIntent(source, archive, sourceRow)
                present(source.entityType, sourceRow, archive.optJSONArray("items") ?: JSONArray())
            }
        }
    } catch (_: Exception) { ImportComparisonSide(ImportSideState.UNREADABLE) }

    fun server(type: String, payload: String?, deleted: Boolean = false): ImportComparisonSide = when {
        deleted -> ImportComparisonSide(ImportSideState.DELETED)
        payload == null -> ImportComparisonSide(ImportSideState.ABSENT)
        else -> try { present(type, read(payload)) } catch (_: Exception) { ImportComparisonSide(ImportSideState.UNREADABLE) }
    }

    private fun addIntent(source: ImportSource, archive: JSONObject, row: JSONObject) {
        val outboxes = archive.optJSONArray("outboxes") ?: JSONArray()
        val evidence = mutableListOf(row)
        for (i in 0 until outboxes.length()) {
            val operation = outboxes.getJSONObject(i)
            if (scalar(operation, "entityType") != "goal" || operation.optString("entityId") != source.sourceId) continue
            val raw = operation.opt("payload")
            val payload = when (raw) { is String -> try { read(raw) } catch (_: Exception) { continue }; is JSONObject -> raw; else -> continue }
            if (payload.optString("id") == source.sourceId) evidence += payload
        }
        for (key in listOf("goal_type", "activity_class")) {
            val values = evidence.mapNotNull { scalar(it, key) }.map {
                when (it) { "GARRISON", "STATIONARY" -> "stationary"; "LINE" -> "line"; "COMMANDO" -> "commando"; "REDUCE" -> "reduce"; "MAINTAIN" -> "maintain"; "SURPLUS" -> "gain"; else -> it }
            }.toSet()
            if (values.size == 1) row.put(key, values.single()) else if (values.size > 1) row.put(key, JSONObject.NULL)
        }
    }
    private fun present(type: String, row: JSONObject, legacyItems: JSONArray = JSONArray()): ImportComparisonSide {
        val values = mutableListOf<ImportComparisonValue>()
        fun add(label: String, value: String?, unit: String = "") {
            values += ImportComparisonValue(label, value?.let { it + if (unit.isEmpty()) "" else " $unit" } ?: UNKNOWN)
        }
        fun field(label: String, unit: String = "", vararg keys: String) = add(label, scalar(row, *keys), unit)
        fun nutrition(product: JSONObject, prefix: String = "", legacy: Boolean = false, basis: String = "g") {
            val nutrition = if (legacy) product else product.optJSONObject("nutrition_per_100") ?: JSONObject()
            for ((index, entry) in listOf("Energia" to "kcal", "Białko" to "g", "Tłuszcz" to "g", "Węglowodany" to "g").withIndex())
                add("$prefix${entry.first} na 100 $basis", scalar(nutrition, if (legacy) listOf("kcalPer100", "proteinPer100", "fatPer100", "carbsPer100")[index]
                    else listOf("energy_kcal", "protein_g", "fat_g", "carbs_g")[index]), entry.second)
        }
        when (type) {
            "weight" -> { field("Masa ciała", "kg", "weight_kg", "kg"); field("Data pomiaru", "", "local_date", "localDate"); field("Czas pomiaru (UTC)", "", "occurred_at", "occurredAt"); field("Strefa czasowa", "", "time_zone", "zoneId") }
            "profile" -> { field("Pseudonim", "", "pseudonym", "nickname"); field("Wzrost", "cm", "height_cm", "heightCm"); add("Klasa aktywności", activity(scalar(row, "activity_class", "activityClass"))); field("Strefa czasowa", "", "time_zone", "zoneId") }
            "goal" -> {
                field("Cel energii", "kcal", "energy_kcal", "kcal"); field("Cel białka", "g", "protein_g", "protein"); field("Cel tłuszczu", "g", "fat_g", "fat"); field("Cel węglowodanów", "g", "carbs_g", "carbs")
                add("Rodzaj celu", when (scalar(row, "goal_type")) { "reduce", "REDUCE" -> "Redukcja"; "maintain", "MAINTAIN" -> "Utrzymanie"; "gain", "SURPLUS" -> "Nadwyżka"; else -> null })
                add("Klasa aktywności", activity(scalar(row, "activity_class", "activityClass"))); field("Obowiązuje od", "", "effective_from", "validFrom")
                field("Czas decyzji (UTC)", "", "decided_at", "decidedAt"); field("Strefa czasowa", "", "time_zone", "zoneId")
                add("Powód decyzji", when (scalar(row, "reason")) { "user_decision" -> "Nowa decyzja"; "history_correction" -> "Korekta historii"; else -> null })
            }
            "diary_day" -> { field("Data dziennika", "", "local_date", "localDate"); field("Strefa czasowa", "", "time_zone", "zoneId"); add("Deklarowana kompletność", when (scalar(row, "declared_complete", "declaredComplete")) { "1", "true" -> "Tak"; "0", "false" -> "Nie"; else -> null }) }
            "product_draft" -> {
                field("Nazwa produktu", "", "name"); val basis = scalar(row, "basis_unit", "basisUnit") ?: "g"
                if (row.has("nutrition_per_100")) nutrition(row, basis = basis) else {
                    for ((key, label, unit) in listOf(Triple("kcal", "Energia", "kcal"), Triple("protein", "Białko", "g"), Triple("fat", "Tłuszcz", "g"), Triple("carbs", "Węglowodany", "g"))) field("$label na 100 $basis", unit, key)
                }
                field("Źródło wartości", "", "source_description", "source"); field("Gęstość", "g/ml", "density_g_per_ml", "density"); field("Źródło gęstości", "", "density_source", "densitySource")
            }
            "meal" -> {
                field("Nazwa posiłku lub racji", "", "title", "rationName"); field("Data posiłku", "", "local_date", "localDate"); field("Czas posiłku (UTC)", "", "occurred_at", "occurredAt"); field("Strefa czasowa", "", "time_zone", "zoneId")
                add("Rodzaj posiłku", when (scalar(row, "meal_type", "mealType")) { "breakfast", "BREAKFAST" -> "Śniadanie"; "lunch", "LUNCH" -> "Obiad"; "dinner", "DINNER" -> "Kolacja"; "snack", "SNACK" -> "Przekąska"; else -> null })
                val items = row.optJSONArray("items") ?: legacyItems
                for (i in 0 until items.length()) {
                    val prefix = "Składnik ${i + 1}: "
                    try {
                        val item = items.getJSONObject(i)
                        val snap = if (item.has("snapshotJson") && !item.isNull("snapshotJson")) read(item.getString("snapshotJson")) else null
                        val product = snap?.optJSONObject("private_product") ?: snap?.optJSONObject("product") ?: item
                        val quantity = snap?.optJSONObject("quantity") ?: item.optJSONObject("quantity")
                        add(prefix + "nazwa", scalar(product, "name", "productName"))
                        add(prefix + "ilość", if (quantity != null) scalar(quantity, "amount") else scalar(item, "quantityText") ?: scalar(item, "grams"), if (quantity != null) scalar(quantity, "unit") ?: "" else "g")
                        nutrition(product, prefix, legacy = product === item && !item.has("nutrition_per_100"), basis = scalar(product, "basis_unit") ?: "g")
                        val density = product.optJSONObject("density_g_per_ml")
                        add(prefix + "gęstość", if (density != null) scalar(density, "amount") else scalar(product, "density_g_per_ml"), "g/ml")
                        add(prefix + "źródło gęstości", scalar(product, "density_source"))
                    } catch (_: Exception) {
                        val name = items.optJSONObject(i)?.let { scalar(it, "productName", "name") }
                        if (name != null && values.none { it.label == prefix + "nazwa" }) add(prefix + "nazwa", name)
                        add(prefix + "zapis historyczny", "Nie można odczytać danych składnika")
                    }
                }
            }
            else -> return ImportComparisonSide(ImportSideState.UNREADABLE)
        }
        return ImportComparisonSide(ImportSideState.PRESENT, values)
    }
    private fun activity(value: String?): String? = when (value) { "stationary", "GARRISON", "STATIONARY" -> "Etat biurowy"; "line", "LINE" -> "Linia"; "commando", "COMMANDO" -> "Komandos"; else -> null }
}
