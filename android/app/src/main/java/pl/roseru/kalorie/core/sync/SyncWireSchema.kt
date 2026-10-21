package pl.roseru.kalorie.core.sync

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.BootstrapProtocol
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.net.URI
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId

class SyncWireException : IllegalArgumentException("Niepoprawny kontrakt synchronizacji")

/** Interpreter of the pinned E0 sync schemas, not a general JSON Schema implementation.
 * Structural wire validation is separate from domain semantics and Room context checks.
 */
class SyncWireSchema(documents: Map<String, ByteArray>) {
    private val documents = documents.mapValues { StrictJson.read(it.value) }
    init { require(this.documents.keys == FILES.toSet()) }
    fun validate(bytes: ByteArray, definition: String, maxBytes: Int = 4 * 1_048_576) {
        if (bytes.size !in 1..maxBytes || definition !in DEFINITIONS) fail()
        val value = try { StrictJson.read(bytes) } catch (_: Exception) { fail() }
        check(value, documents.getValue("sync.schema.json").getJSONObject("\$defs").getJSONObject(definition), "sync.schema.json", 0)
    }
    fun validateMeal(bytes:ByteArray) = validateDomain(bytes, "Meal")
    fun validateWeight(bytes:ByteArray) = validateDomain(bytes, "Weight")
    private fun validateDomain(bytes:ByteArray, definition:String) {
        if(bytes.size !in 1..1_048_576)fail()
        val value=try{StrictJson.read(bytes)}catch(_:Exception){fail()}
        check(value,documents.getValue("domain.schema.json").getJSONObject("\$defs").getJSONObject(definition),"domain.schema.json",0)
    }
    private fun check(value: Any?, schema: JSONObject, file: String, depth: Int) {
        if (depth > 128 || schema.keys().asSequence().any { it !in KEYWORDS }) fail()
        fun branch(part: JSONObject) = check(value, part, file, depth + 1)
        fun matches(part: JSONObject) = try { branch(part); true } catch (_: SyncWireException) { false }
        if (schema.has("\$ref")) {
            val parts = schema.getString("\$ref").split('#', limit = 2)
            if (parts.size != 2) fail()
            val targetFile = parts[0].ifEmpty { file }
            var target: Any = documents[targetFile] ?: fail()
            for (part in parts[1].split('/').filter(String::isNotEmpty)) {
                target = (target as JSONObject).get(part.replace("~1", "/").replace("~0", "~"))
            }
            check(value, target as JSONObject, targetFile, depth + 1)
        }
        fun parts(name: String) = (0 until schema.getJSONArray(name).length()).map { schema.getJSONArray(name).getJSONObject(it) }
        if (schema.has("allOf")) parts("allOf").forEach(::branch)
        if (schema.has("anyOf") && parts("anyOf").none(::matches)) fail()
        if (schema.has("oneOf") && parts("oneOf").count(::matches) != 1) fail()
        if (schema.has("not") && matches(schema.getJSONObject("not"))) fail()
        if (schema.has("if")) {
            val selected = if (matches(schema.getJSONObject("if"))) "then" else "else"
            schema.optJSONObject(selected)?.let(::branch)
        }
        if (schema.has("const") && StrictJson.canonical(value) != StrictJson.canonical(schema.get("const"))) fail()
        if (schema.has("enum")) {
            val values = schema.getJSONArray("enum")
            if ((0 until values.length()).none { StrictJson.canonical(value) == StrictJson.canonical(values.get(it)) }) fail()
        }
        when (schema.optString("type")) {
            "" -> Unit
            "null" -> if (value != null && value !== JSONObject.NULL) fail()
            "boolean" -> if (value !is Boolean) fail()
            "integer" -> if (value !is Int && value !is Long) fail()
            "string" -> if (value !is String) fail()
            "object" -> if (value !is JSONObject) fail()
            "array" -> if (value !is JSONArray) fail()
            else -> fail()
        }
        if (value is Number) {
            val number = BigDecimal(value.toString())
            if (schema.has("minimum") && number < BigDecimal(schema.get("minimum").toString())) fail()
            if (schema.has("maximum") && number > BigDecimal(schema.get("maximum").toString())) fail()
        }
        if (value is String) {
            if ('\u0000' in value) fail()
            val length = value.codePointCount(0, value.length)
            if (length < schema.optInt("minLength", 0) || length > schema.optInt("maxLength", Int.MAX_VALUE)) fail()
            if (schema.has("pattern")) {
                val pattern = schema.getString("pattern")
                // The pinned UnicodeText regex has a repeated alternation. Java's regex engine
                // can overflow its stack on a valid 4096-character token. Check the exact same
                // UTF-16 language iteratively; other schema patterns retain their own semantics.
                if (pattern == UNICODE_TEXT_PATTERN) {
                    var index = 0
                    while (index < value.length) {
                        val char = value[index++]
                        if (char == '\u0000' || Character.isLowSurrogate(char)) fail()
                        if (Character.isHighSurrogate(char)) {
                            if (index == value.length || !Character.isLowSurrogate(value[index++])) fail()
                        }
                    }
                } else if (!Regex(pattern).matches(value)) fail()
            }
            try {
                when (schema.optString("format")) {
                    "" -> Unit
                    "uuid" -> if (!BootstrapProtocol.uuid.matches(value)) fail()
                    "date" -> if (LocalDate.parse(value).year !in 1..9999) fail()
                    "date-time" -> {
                        if (!value.endsWith('Z') || LocalDateTime.parse(value.dropLast(1)).year !in 1..9999) fail()
                        Instant.parse(value)
                    }
                    "iana-time-zone" -> if (value !in ZoneId.getAvailableZoneIds()) fail()
                    "uri" -> if (!URI(value).isAbsolute) fail()
                    else -> fail()
                }
            } catch (_: Exception) { fail() }
        }
        if (value is JSONObject) {
            schema.optJSONArray("required")?.let { keys ->
                for (index in 0 until keys.length()) if (!value.has(keys.getString(index))) fail()
            }
            val properties = schema.optJSONObject("properties") ?: JSONObject()
            value.keys().forEach { key ->
                if ('\u0000' in key) fail()
                if (properties.has(key)) check(value.get(key), properties.getJSONObject(key), file, depth + 1)
                else if (schema.opt("additionalProperties") == false) fail()
            }
        }
        if (value is JSONArray) {
            if (value.length() < schema.optInt("minItems", 0) || value.length() > schema.optInt("maxItems", Int.MAX_VALUE)) fail()
            if (schema.optBoolean("uniqueItems") && (0 until value.length()).map { StrictJson.canonical(value.get(it)) }.toSet().size != value.length()) fail()
            schema.optJSONObject("items")?.let { item ->
                for (index in 0 until value.length()) check(value.get(index), item, file, depth + 1)
            }
        }
    }
    private fun fail(): Nothing = throw SyncWireException()
    companion object {
        private const val UNICODE_TEXT_PATTERN = "^(?:[^\\u0000\\uD800-\\uDFFF]|[\\uD800-\\uDBFF][\\uDC00-\\uDFFF])*(?![\\s\\S])"
        val FILES = listOf("common.schema.json", "domain.schema.json", "sync.schema.json")
        private val DEFINITIONS = setOf("PullRequest", "PullResponse", "PushRequest", "PushResponse", "SyncError", "Operation")
        private val KEYWORDS = setOf("\$ref", "\$schema", "\$defs", "description", "title", "default", "type", "properties",
            "required", "additionalProperties", "allOf", "anyOf", "oneOf", "not", "if", "then", "else", "const", "enum",
            "minimum", "maximum", "minLength", "maxLength", "pattern", "format", "items", "minItems", "maxItems", "uniqueItems")
    }
}
