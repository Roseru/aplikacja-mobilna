package pl.roseru.kalorie.importing

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.LegacyImportWire
import pl.roseru.kalorie.data.ImportSource
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.Base64

/** Options contain a Polish display label followed by its stored wire value. */
data class ImportFormField(val key: String, val label: String, val original: String, val value: String,
    val required: Boolean = false, val decimal: Boolean = false, val options: List<Pair<String, String>> = emptyList())

/** A normal form edits a derivative choice; the source archive is never modified. */
data class LegacyImportForm(val fields: List<ImportFormField>, val standaloneGoal: Boolean = false) {
    fun choice(values: Map<String, String>, standaloneGoal: Boolean = this.standaloneGoal): String {
        require(values.keys.all { key -> fields.any { it.key == key } }) { "Nieznane pole formularza" }
        val result = JSONObject().put("choice", "metadata")
        val row = JSONObject(); val items = linkedMapOf<String, JSONObject>()
        for (field in fields) {
            val input = values[field.key] ?: field.value
            val blank = input.isBlank()
            require(!field.required || !blank) { "Uzupełnij pole: ${field.label}" }
            if (!blank && field.options.isNotEmpty()) require(field.options.any { it.second == input }) {
                "Wybierz wartość: ${field.label}"
            }
            val value: Any = if (blank) JSONObject.NULL else if (field.decimal) decimal(input, field.label) else input
            if (!blank) validateText(field.key, input, field.label)
            val parts = field.key.split(':', limit = 3)
            when (parts[0]) {
                "meta" -> {
                    result.put(parts[1], value)
                    if (input != field.original) when (parts[1]) {
                        "goal_decided_at" -> row.put("decidedAt", value)
                        "goal_reason" -> row.put("reason", value)
                    }
                }
                "row" -> if (input != field.original) {
                    row.put(parts[1], if (parts[1] == "declaredComplete") input == "true" else value)
                }
                "item" -> if (input != field.original) {
                    val id = String(Base64.getUrlDecoder().decode(parts[1]), Charsets.UTF_8)
                    items.getOrPut(id) { JSONObject().put("id", id) }.put(parts[2], value)
                }
            }
        }
        if (standaloneGoal) {
            require(fields.any { it.key == "meta:goal_reason" }) { "Wybór dotyczy wyłącznie celu" }
            result.put("standalone_goal", true).put("goal_reason", "user_decision")
            row.put("reason", "user_decision")
        }
        if (row.length() > 0) result.put("row_overrides", row)
        if (items.isNotEmpty()) result.put("item_overrides", JSONArray(items.values.toList()))
        return StrictJson.canonical(result)
    }

    companion object {
        private val activities = listOf("Etat biurowy" to "GARRISON", "Linia" to "LINE", "Komandos" to "COMMANDO")
        private val goalActivities = listOf("Etat biurowy" to "stationary", "Linia" to "line", "Komandos" to "commando")
        private val aims = listOf("Redukcja" to "reduce", "Utrzymanie" to "maintain", "Nadwyżka" to "gain")
        private val reasons = listOf("Nowa decyzja" to "user_decision", "Korekta historii" to "history_correction")
        private val units = listOf("Gramy" to "g", "Mililitry" to "ml")
        private val nutrients = listOf("energy_kcal" to "Energia (kcal)", "protein_g" to "Białko (g)",
            "fat_g" to "Tłuszcz (g)", "carbs_g" to "Węglowodany (g)")
        private fun decimal(input: String, label: String): String {
            val number = try { BigDecimal(input.trim().replace(',', '.')) } catch (_: Exception) {
                throw IllegalArgumentException("Niepoprawna liczba: $label")
            }
            require(number.signum() >= 0 && number <= BigDecimal("999999.999999") && number.stripTrailingZeros().scale() <= 6) {
                "Podaj dokładną liczbę z najwyżej 6 miejscami po przecinku: $label"
            }
            return ContractDecimal.canonical(number)
        }
        private fun validateText(key: String, value: String, label: String) {
            try {
                when (key.substringAfterLast(':')) {
                    "localDate", "validFrom" -> LocalDate.parse(value)
                    "occurredAt", "decidedAt", "goal_decided_at" -> {
                        require(Instant.parse(value).nano % 1000 == 0)
                    }
                    "zoneId", "zone" -> require(value in ZoneId.getAvailableZoneIds())
                }
                require(value.none { it == '\u0000' })
            } catch (_: Exception) { throw IllegalArgumentException("Sprawdź pole: $label") }
        }
        private fun display(row: JSONObject, key: String): String = if (!row.has(key) || row.isNull(key)) "" else row.get(key).toString()
        private fun parse(raw: String) = LegacyImportWire.readSource(raw)
        private fun wireActivity(value: String) = when (value) {
            "GARRISON", "STATIONARY", "stationary" -> "stationary"
            "LINE", "line" -> "line"
            "COMMANDO", "commando" -> "commando"
            else -> ""
        }
        private fun wireAim(value: String) = when (value) {
            "REDUCE", "reduce" -> "reduce"
            "MAINTAIN", "maintain" -> "maintain"
            "SURPLUS", "gain" -> "gain"
            else -> ""
        }

        fun from(source: ImportSource): LegacyImportForm {
            val archive = parse(source.sourceJson); val row = archive.getJSONObject("row")
            val fields = mutableListOf<ImportFormField>()
            fun field(key: String, label: String, value: String, required: Boolean = false,
                decimal: Boolean = false, options: List<Pair<String, String>> = emptyList()) {
                fields += ImportFormField(key, label, value, value, required, decimal, options)
            }
            fun rowField(key: String, label: String, required: Boolean = false, decimal: Boolean = false,
                options: List<Pair<String, String>> = emptyList(), value: String = display(row, key)) =
                field("row:$key", label, value, required, decimal, options)

            when (source.entityType) {
                "weight" -> {
                    rowField("kg", "Masa ciała (kg)", true, true)
                    rowField("localDate", "Data pomiaru", true); rowField("occurredAt", "Czas pomiaru (UTC)", true)
                    rowField("zoneId", "Strefa czasowa pomiaru", true)
                }
                "profile" -> {
                    rowField("nickname", "Pseudonim", true); rowField("heightCm", "Wzrost (cm)", decimal = true)
                    rowField("zoneId", "Strefa czasowa profilu", true)
                    rowField("activityClass", "Klasa aktywności", true, options = activities)
                }
                "goal" -> {
                    rowField("kcal", "Cel energii (kcal)", true, true)
                    for ((local, label) in listOf("protein" to "Cel białka (g)", "fat" to "Cel tłuszczu (g)", "carbs" to "Cel węglowodanów (g)"))
                        rowField(local, label, decimal = true)
                    rowField("validFrom", "Obowiązuje od", true)
                    field("meta:goal_decided_at", "Czas podjęcia decyzji (UTC)", display(row, "decidedAt"), true)
                    rowField("zoneId", "Strefa czasowa celu", true)
                    val reason = display(row, "reason").takeIf { it in setOf("user_decision", "history_correction") } ?: ""
                    field("meta:goal_reason", "Powód zmiany celu", reason, true, options = reasons)
                    if (reason.isEmpty()) fields[fields.lastIndex] = fields.last().copy(original = display(row, "reason"))
                    val evidence = mutableListOf(row)
                    val outboxes = archive.optJSONArray("outboxes") ?: JSONArray()
                    for (i in 0 until outboxes.length()) {
                        val original = outboxes.getJSONObject(i)
                        if (display(original, "entityType") != "goal" || display(original, "entityId") != source.sourceId) continue
                        val raw = original.opt("payload")
                        val payload = when (raw) { is String -> parse(raw); is JSONObject -> raw; else -> continue }
                        if (display(payload, "id") == source.sourceId) evidence += payload
                    }
                    fun intent(key: String, normalize: (String) -> String): String {
                        val known = evidence.map { normalize(display(it, if (key == "activity_class" && it.has("activityClass")) "activityClass" else key)) }.filter(String::isNotEmpty).toSet()
                        return known.singleOrNull() ?: ""
                    }
                    field("meta:goal_aim", "Rodzaj celu", intent("goal_type", ::wireAim), true, options = aims)
                    field("meta:goal_activity", "Klasa aktywności przy decyzji", intent("activity_class", ::wireActivity), true, options = goalActivities)
                }
                "diary_day" -> {
                    rowField("localDate", "Data dziennika", true); rowField("zoneId", "Strefa czasowa dnia", true)
                    val raw = display(row, "declaredComplete")
                    rowField("declaredComplete", "Dzień zadeklarowany jako kompletny", true,
                        options = listOf("Tak" to "true", "Nie" to "false"), value = when (raw) { "1", "true" -> "true"; "0", "false" -> "false"; else -> "" })
                }
                "meal" -> {
                    rowField("localDate", "Data posiłku", true); rowField("occurredAt", "Czas posiłku (UTC)", true)
                    rowField("zoneId", "Strefa czasowa posiłku", true)
                    rowField("mealType", "Rodzaj posiłku", options = listOf("Nieokreślony" to "UNSPECIFIED", "Śniadanie" to "BREAKFAST", "Obiad" to "LUNCH", "Kolacja" to "DINNER", "Przekąska" to "SNACK"))
                    rowField("rationName", "Nazwa racji")
                    val items = archive.optJSONArray("items") ?: JSONArray()
                    for (i in 0 until items.length()) {
                        val item = items.getJSONObject(i); val id = item.getString("id")
                        val prefix = "item:" + Base64.getUrlEncoder().withoutPadding().encodeToString(id.toByteArray(Charsets.UTF_8)) + ":"
                        val snapshot = display(item, "snapshotJson").takeIf(String::isNotEmpty)?.let(::parse)
                        val product = snapshot?.optJSONObject("private_product") ?: snapshot?.optJSONObject("product")
                        val quantity = snapshot?.optJSONObject("quantity")
                        fun itemField(key: String, label: String, value: String, required: Boolean = false,
                            decimal: Boolean = false, options: List<Pair<String, String>> = emptyList()) =
                            field(prefix + key, "Składnik ${i + 1}: $label", value, required, decimal, options)
                        itemField("name", "nazwa", product?.let { display(it, "name") } ?: display(item, "productName"), true)
                        itemField("amount", "ilość", quantity?.let { display(it, "amount") }
                            ?: display(item, "quantityText").ifEmpty { display(item, "grams") }, true, true)
                        itemField("unit", "jednostka ilości", quantity?.let { display(it, "unit") } ?: "g", true, options = units)
                        itemField("basis_unit", "jednostka wartości na 100", product?.let { display(it, "basis_unit") } ?: "g", true, options = units)
                        for ((index, nutrient) in nutrients.withIndex()) {
                            val value = product?.optJSONObject("nutrition_per_100")?.let { display(it, nutrient.first) }
                                ?: display(item, listOf("kcalPer100", "proteinPer100", "fatPer100", "carbsPer100")[index])
                            itemField(nutrient.first, nutrient.second, value, decimal = true)
                        }
                        val catalogDensity = product?.optJSONObject("density_g_per_ml")
                        itemField("density", "gęstość (g/ml)", catalogDensity?.let { display(it, "amount") }
                            ?: product?.let { display(it, "density_g_per_ml") } ?: "", decimal = true)
                        val densityReference = catalogDensity?.let { display(it, "source_id") }
                            ?: product?.let { display(it, "density_source") } ?: ""
                        val densityDescription = if (Regex("[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}").matches(densityReference)) {
                            val sources = snapshot?.optJSONArray("sources") ?: JSONArray()
                            val originalSource = (0 until sources.length()).map { sources.getJSONObject(it) }
                                .singleOrNull { display(it, "source_id") == densityReference }
                            originalSource?.optJSONArray("notes")?.let { notes ->
                                (0 until notes.length()).joinToString("; ") { notes.getString(it) }
                            } ?: ""
                        } else densityReference
                        itemField("density_source", "źródło gęstości", densityDescription)
                    }
                }
                "product_draft" -> {
                    val product = display(row, "wirePayload").takeIf(String::isNotEmpty)?.let(::parse)
                    rowField("name", "Nazwa produktu", true, value = product?.let { display(it, "name") } ?: display(row, "name"))
                    rowField("basisUnit", "Jednostka wartości na 100", true, options = units,
                        value = product?.let { display(it, "basis_unit") } ?: "g")
                    for ((index, nutrient) in nutrients.withIndex()) rowField(listOf("kcal", "protein", "fat", "carbs")[index], nutrient.second,
                        decimal = true, value = product?.optJSONObject("nutrition_per_100")?.let { display(it, nutrient.first) }
                            ?: display(row, listOf("kcal", "protein", "fat", "carbs")[index]))
                    rowField("source", "Źródło wartości odżywczych", true,
                        value = product?.let { display(it, "source_description") } ?: display(row, "source"))
                    rowField("density", "Gęstość (g/ml)", decimal = true, value = product?.let { display(it, "density_g_per_ml") } ?: "")
                    rowField("densitySource", "Źródło gęstości", value = product?.let { display(it, "density_source") } ?: "")
                }
                else -> throw IllegalArgumentException("Nieobsługiwany rodzaj danych importu")
            }
            val previous = parse(source.metadataJson)
            val rowOverrides = previous.optJSONObject("row_overrides")
            val itemOverrides = previous.optJSONArray("item_overrides") ?: JSONArray()
            val restored = fields.map { field ->
                val parts = field.key.split(':', limit = 3)
                val override: String? = when (parts[0]) {
                    "meta" -> if (previous.has(parts[1])) display(previous, parts[1]) else null
                    "row" -> rowOverrides?.takeIf { it.has(parts[1]) }?.let { display(it, parts[1]) }
                    "item" -> {
                        val id = String(Base64.getUrlDecoder().decode(parts[1]), Charsets.UTF_8)
                        (0 until itemOverrides.length()).map { itemOverrides.getJSONObject(it) }.singleOrNull { it.optString("id") == id }
                            ?.takeIf { it.has(parts[2]) }?.let { display(it, parts[2]) }
                    }
                    else -> null
                }
                field.copy(value = override ?: field.value)
            }
            return LegacyImportForm(restored, previous.optBoolean("standalone_goal", false))
        }
    }
}
