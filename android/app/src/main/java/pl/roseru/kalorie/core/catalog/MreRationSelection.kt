package pl.roseru.kalorie.core.catalog

import org.json.JSONObject
import pl.roseru.kalorie.core.ContractDecimal
import pl.roseru.kalorie.core.ExactNutrition
import java.math.BigDecimal
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.security.MessageDigest

/** The collected COMRAD document uses JSON numbers, unlike the E2 decimal-string protocol. */
internal object MreSourceJson {
    fun read(bytes: ByteArray): JSONObject {
        require(bytes.size <= 1024 * 1024)
        val source = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
        val decimal = Regex("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?")
        val normalized = StringBuilder(source.length)
        var offset = 0
        var quoted = false
        var escaped = false
        while (offset < source.length) {
            val char = source[offset]
            if (quoted) {
                normalized.append(char); offset++
                if (escaped) escaped = false
                else if (char == '\\') escaped = true
                else if (char == '"') quoted = false
            } else if (char == '"') {
                quoted = true; normalized.append(char); offset++
            } else if (char == '-' || char in '0'..'9') {
                val token = decimal.find(source, offset) ?: throw MreCatalogueException()
                require(token.range.first == offset && token.value.length <= 64)
                offset += token.value.length
                // Quoting a numeric object key must not turn invalid source JSON into valid JSON.
                var next = offset
                while (source.getOrNull(next) in listOf(' ', '\t', '\r', '\n')) next++
                require(source.getOrNull(next) != ':')
                normalized.append('"').append(token.value).append('"')
            } else {
                normalized.append(char); offset++
            }
        }
        // The existing preflight still checks syntax, duplicate keys, escapes, UTF-8 and depth.
        // Numeric lexemes remain exact source text rather than passing through Double.
        return StrictJson.read(normalized.toString().toByteArray(Charsets.UTF_8))
    }
}

data class MreIngredientSource(val name: String, val sourceLocator: String, val portionGrams: String,
    val url: String, val page: Int, val nutritionStatus: String, val flavours: List<String>,
    val notes: List<String>, val values: Map<String, String?>)

data class MreMissingIngredient(val locator: String, val name: String, val equipment: Boolean, val reasons: List<String>)

data class MreManualInput(val amount: String, val nutrition: ExactNutrition) {
    fun validate() {
        val quantity = ContractDecimal.userQuantity(amount) ?: throw IllegalArgumentException("mre_quantity")
        require(quantity <= BigDecimal("10000"))
        nutrition.values().forEachIndexed { index, number -> if (number != null) {
            ContractDecimal.read(ContractDecimal.canonical(number))
            require(number <= BigDecimal(if (index == 0) "1000" else "100"))
        } }
    }
    companion object {
        fun read(amount: String, fields: Map<String, String>): MreManualInput {
            val quantity = ContractDecimal.userQuantity(amount) ?: throw IllegalArgumentException("mre_quantity")
            val nutrition = ExactNutrition.read(fields.mapValues { (_, value) ->
                value.trim().takeIf { it.isNotEmpty() }?.replace(',', '.')?.let { text ->
                    require(Regex("^(0|[1-9][0-9]{0,5})(\\.[0-9]{1,6})?$").matches(text))
                    ContractDecimal.canonical(BigDecimal(text))
                }
            })
            return MreManualInput(ContractDecimal.canonical(quantity), nutrition).also { it.validate() }
        }
    }
}

/** Selection describes the contents of one source menu, not simultaneous alternative flavours. */
class MreRationSelection internal constructor(val menu: String, val warnings: List<String>,
    val missing: List<MreMissingIngredient>, val origins: Map<Int, MreIngredientSource>,
    private val choices: List<Set<Int>>, private val packets: List<Pair<Set<Int>, Set<Int>>>) {
    private val positions = origins.keys

    fun accepts(selected: Set<Int>): Boolean = selected.all { it in positions } &&
        choices.all { group -> selected.count { it in group } <= 1 } &&
        packets.all { (aggregate, detail) -> selected.none { it in aggregate } || selected.none { it in detail } }

    fun toggle(selected: Set<Int>, position: Int, checked: Boolean): Set<Int> {
        require(position in positions)
        if (!checked) return selected - position
        var next = selected + position
        choices.filter { position in it }.forEach { next = next - (it - position) }
        packets.forEach { (aggregate, details) ->
            if (position in aggregate) next = next - details
            if (position in details) next = next - aggregate
        }
        require(accepts(next))
        return next
    }

    /** Leaves unresolved variants unselected; never guesses a flavour or chooses an older average. */
    fun selectUnambiguous(selected: Set<Int>): Set<Int> {
        require(accepts(selected))
        val variants = choices.flatten().toSet()
        val averages = packets.flatMap { it.first }.toSet()
        var next = selected + (positions - variants - averages)
        packets.forEach { (aggregate, details) -> if (next.any { it in details }) next = next - aggregate }
        require(accepts(next))
        return next
    }

    fun withoutPacketAverages(selected: Set<Int>): Set<Int> = selected - packets.flatMap { it.first }.toSet()
}

class MreCatalogueException(cause: Throwable? = null) : IllegalArgumentException("mre_reference_unavailable", cause)

/** Companion rules apply only to exactly the immutable ration revisions imported from this bundle. */
class MreCatalogueRules private constructor(private val entries: Map<String, Entry>) {
    private data class Entry(val revision: Int, val rationHash: String, val selection: MreRationSelection)

    fun forRation(catalogJson: String?): MreRationSelection? {
        if (catalogJson == null) return null
        val ration = StrictJson.read(catalogJson.toByteArray(Charsets.UTF_8))
        if (ration.getString("source_id") != SOURCE_ID) return null
        val entry = entries[ration.getString("ration_id")] ?: throw MreCatalogueException()
        if (ration.getInt("revision") != entry.revision || hash(canonicalRation(ration).toByteArray(Charsets.UTF_8)) != entry.rationHash)
            throw MreCatalogueException()
        return entry.selection
    }

    companion object {
        const val PACKAGE_ID = "3aa9b766-b01d-5111-8fd0-4c5b6257961b"
        const val SOURCE_ID = "304728b1-c81a-536f-9b95-7b70836cd3c3"
        private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        // Match the generator's UTF-8 canonical JSON. JSONObject.quote differs between
        // Android and the JVM test dependency for characters such as U+2014.
        private fun quote(text: String): String = buildString {
            append('"')
            text.forEach { char -> when (char) {
                '"' -> append("\\\"")
                '\\' -> append("\\\\")
                '\b' -> append("\\b")
                '\u000C' -> append("\\f")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> if (char.code < 32) append("\\u%04x".format(char.code)) else append(char)
            } }
            append('"')
        }
        private fun canonicalRation(value: Any?): String = when (value) {
            null, JSONObject.NULL -> "null"
            is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") { key ->
                quote(key) + ":" + canonicalRation(value.get(key))
            }
            is org.json.JSONArray -> (0 until value.length()).joinToString(",", "[", "]") { canonicalRation(value.get(it)) }
            is String -> quote(value)
            is Boolean -> value.toString()
            is Number -> BigDecimal(value.toString()).toPlainString()
            else -> throw MreCatalogueException()
        }
        private fun JSONObject.rows(key: String, limit: Int): List<JSONObject> = getJSONArray(key).let {
            require(it.length() <= limit); (0 until it.length()).map { index -> it.getJSONObject(index) }
        }
        private fun JSONObject.texts(key: String): List<String> = getJSONArray(key).let {
            require(it.length() <= 100); (0 until it.length()).map { index -> it.getString(index).also { s -> require(s.length <= 2000) } }
        }
        private fun JSONObject.positions(key: String): Set<Int> = getJSONArray(key).let {
            require(it.length() <= 1000)
            val list = (0 until it.length()).map { index -> it.getInt(index).also { n -> require(n > 0) } }
            require(list.distinct().size == list.size); list.toSet()
        }

        fun read(packageValue: ValidatedCatalog, rulesBytes: ByteArray, sourceBytes: ByteArray): MreCatalogueRules = try {
            require(rulesBytes.size <= 1024 * 1024 && sourceBytes.size <= 1024 * 1024)
            val rules = StrictJson.read(rulesBytes)
            val source = MreSourceJson.read(sourceBytes)
            require(rules.getInt("format") == 1 && rules.getInt("release") == packageValue.release &&
                rules.getString("package_id") == packageValue.packageId && rules.getString("kind") == packageValue.kind &&
                rules.getString("gzip_sha256") == packageValue.sha256 && rules.getString("input_sha256") == hash(sourceBytes))
            val payload = packageValue.payload()
            val products = payload.rows("products", 10000).associateBy { it.getString("product_id") }
            val rations = payload.rows("rations", 1000).associateBy { it.getString("ration_id") }
            val profiles = source.getJSONObject("nutrition_profiles")
            val menus = rules.rows("menus", 24)
            require(menus.size == 24 && menus.map { it.getString("ration_id") }.distinct().size == 24)
            val entries = menus.associate { menu ->
                val id = menu.getString("ration_id")
                val ration = rations[id] ?: throw MreCatalogueException()
                val rationHash = hash(canonicalRation(ration).toByteArray(Charsets.UTF_8))
                require(ration.getString("source_id") == SOURCE_ID && ration.getInt("revision") == menu.getInt("revision") &&
                    rationHash == menu.getString("ration_sha256"))
                val parts = ration.rows("components", 1000).associateBy { it.getInt("position") }
                val bindings = menu.rows("bindings", 1000)
                require(bindings.size == parts.size && bindings.map { it.getInt("position") }.distinct().size == bindings.size)
                val origins = bindings.associate { binding ->
                    val position = binding.getInt("position")
                    val part = parts[position] ?: throw MreCatalogueException()
                    val ref = part.getJSONObject("product")
                    require(ref.getString("product_id") == binding.getString("product_id") && ref.getInt("revision") == binding.getInt("revision"))
                    val product = products[ref.getString("product_id")] ?: throw MreCatalogueException()
                    require(product.getInt("revision") == ref.getInt("revision"))
                    val profile = profiles.getJSONObject(binding.getString("profile_id"))
                    val values = profile.getJSONObject("values")
                    val fields = values.keys().asSequence().associateWith { key -> if (values.isNull(key)) null else values.get(key).toString() }
                    position to MreIngredientSource(profile.getString("name_source"), binding.getString("source_locator"),
                        part.getJSONObject("quantity").getString("amount"), profile.getString("source_url"), profile.getInt("source_page"),
                        binding.getString("nutrition_status"), binding.texts("flavours"), binding.texts("notes") + profile.texts("quality_notes_pl"), fields)
                }
                val choices = menu.rows("choices", 1000).map { it.positions("positions").also { p -> require(p.size >= 2 && p.all { n -> n in origins }) } }
                require(choices.flatten().distinct().size == choices.sumOf { it.size })
                val packets = menu.rows("packets", 1000).map {
                    val average = it.positions("aggregate"); val details = it.positions("details")
                    require(average.intersect(details).isEmpty() && (average + details).all { n -> n in origins })
                    average to details
                }
                val missing = ration.rows("excluded_items", 1000).map {
                    MreMissingIngredient(it.getString("source_locator"), it.getString("name"), it.getString("classification") == "equipment", it.texts("reasons"))
                }
                id to Entry(ration.getInt("revision"), rationHash, MreRationSelection(
                    "Menu ${menu.getString("case")}${menu.getInt("number")} · MRE2026", menu.texts("warnings"), missing, origins, choices, packets))
            }
            MreCatalogueRules(entries)
        } catch (error: Exception) { throw MreCatalogueException(error) }
    }
}
