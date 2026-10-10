package pl.roseru.kalorie.core.catalog

import org.json.JSONArray
import org.json.JSONObject
import java.math.BigDecimal
import java.net.URI
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime

/** Interpreter for the keywords used by the bundled, pinned E0 catalogue schemas. */
class CatalogSchema(common: JSONObject, catalog: JSONObject) {
    private val documents = mapOf("common.schema.json" to common, "catalog.schema.json" to catalog)
    fun validate(value: JSONObject, definition: String) = check(value,
        documents.getValue("catalog.schema.json").getJSONObject("\$defs").getJSONObject(definition), "catalog.schema.json")
    private fun check(value: Any?, schema: JSONObject, file: String) {
        if (schema.has("\$ref")) {
            val ref = schema.getString("\$ref").split('#', limit = 2)
            val document = ref[0].ifEmpty { file }
            var target: Any = documents[document] ?: fail()
            ref[1].split('/').filter { it.isNotEmpty() }.forEach { target = (target as JSONObject).get(it) }
            check(value, target as JSONObject, document)
        }
        if (schema.has("allOf")) schema.getJSONArray("allOf").objects().forEach { check(value, it, file) }
        if (schema.has("anyOf") && schema.getJSONArray("anyOf").objects().none { runCatching { check(value, it, file) }.isSuccess }) fail()
        if (schema.has("not") && runCatching { check(value, schema.getJSONObject("not"), file) }.isSuccess) fail()
        if (schema.has("const") && StrictJson.canonical(value) != StrictJson.canonical(schema.get("const"))) fail()
        if (schema.has("enum") && (0 until schema.getJSONArray("enum").length()).none {
                StrictJson.canonical(value) == StrictJson.canonical(schema.getJSONArray("enum").get(it)) }) fail()
        when (schema.optString("type")) {
            "null" -> if (value != null && value != JSONObject.NULL) fail()
            "boolean" -> if (value !is Boolean) fail()
            "integer" -> {
                if (value !is Number) fail()
                val number = value.toString().toBigDecimalOrNull() ?: fail()
                if (number.stripTrailingZeros().scale() > 0) fail()
                if (schema.has("minimum") && number < BigDecimal(schema.get("minimum").toString())) fail()
                if (schema.has("maximum") && number > BigDecimal(schema.get("maximum").toString())) fail()
            }
            "string" -> {
                if (value !is String) fail()
                val length = value.codePointCount(0, value.length)
                if (length < schema.optInt("minLength", 0) || length > schema.optInt("maxLength", Int.MAX_VALUE)) fail()
                if (schema.has("pattern")) {
                    val pattern = schema.getString("pattern")
                    val regex = Regex(pattern)
                    // Canonical wire fields must consume the entire string, including a final LF.
                    if (pattern.startsWith('^') && pattern.endsWith('$')) {
                        if (!regex.matches(value)) fail()
                    } else if (!regex.containsMatchIn(value)) fail()
                }
                try {
                    when (schema.optString("format")) {
                        "date" -> { if (LocalDate.parse(value).year !in 1..9999) fail() }
                        "date-time" -> {
                            if (!value.endsWith('Z') || LocalDateTime.parse(value.dropLast(1)).year !in 1..9999) fail()
                            Instant.parse(value)
                        }
                        "uri" -> {
                            val uri = URI(value)
                            if (!Regex("[A-Za-z0-9._~:/?#\\[\\]@!$&'()*+,;=%-]+").matches(value) ||
                                !uri.isAbsolute || uri.host.isNullOrBlank() || uri.scheme != "https" || uri.port !in -1..65535) fail()
                        }
                    }
                } catch (_: Exception) { fail() }
            }
            "array" -> {
                if (value !is JSONArray) fail()
                if (value.length() < schema.optInt("minItems", 0) || value.length() > schema.optInt("maxItems", Int.MAX_VALUE)) fail()
                if (schema.has("items")) for (index in 0 until value.length()) check(value.get(index), schema.getJSONObject("items"), file)
            }
            "object" -> {
                if (value !is JSONObject) fail()
                val required = schema.optJSONArray("required")
                if (required != null) for (index in 0 until required.length()) if (!value.has(required.getString(index))) fail()
                val properties = schema.optJSONObject("properties") ?: JSONObject()
                value.keys().forEach { key ->
                    if (!properties.has(key)) { if (schema.has("additionalProperties") && !schema.getBoolean("additionalProperties")) fail() }
                    else check(value.get(key), properties.getJSONObject(key), file)
                }
            }
        }
    }
    private fun fail(): Nothing = throw CatalogError("catalog_schema")
}

fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }
