package pl.roseru.kalorie.core.catalog

import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.math.BigDecimal
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction

class CatalogError(val code: String) : IllegalArgumentException(code)

/** Preflight keeps Android's lenient JSONObject parser from accepting ambiguous input. */
object StrictJson {
    fun read(bytes: ByteArray): JSONObject {
        val text = try {
            Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
        } catch (_: Exception) { throw CatalogError("catalog_json") }
        Scanner(text).check()
        return try { JSONObject(text) } catch (_: Exception) { throw CatalogError("catalog_json") }
    }
    fun canonical(value: Any?): String = when (value) {
        null, JSONObject.NULL -> "null"
        is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") { key -> JSONObject.quote(key) + ":" + canonical(value.get(key)) }
        is JSONArray -> (0 until value.length()).joinToString(",", "[", "]") { canonical(value.get(it)) }
        is String -> JSONObject.quote(value)
        is Boolean -> value.toString()
        is Number -> BigDecimal(value.toString()).toPlainString()
        else -> throw CatalogError("catalog_json")
    }
    private class Scanner(val text: String) {
        var offset = 0
        fun check() {
            space(); if (peek() != '{') fail()
            value(0); space(); if (offset != text.length) fail()
        }
        fun peek(): Char? = text.getOrNull(offset)
        fun space() { while (peek() in listOf(' ', '\t', '\r', '\n')) offset++ }
        fun take(char: Char) { space(); if (peek() != char) fail(); offset++ }
        fun value(depth: Int) {
            if (depth > 64) fail()
            space()
            when (peek()) {
                '{' -> {
                    offset++; space(); val keys = mutableSetOf<String>()
                    if (peek() == '}') { offset++; return }
                    while (true) {
                        space(); val key = string()
                        if (!keys.add(key)) throw CatalogError("catalog_json_duplicate")
                        take(':'); value(depth + 1); space()
                        if (peek() == '}') { offset++; break }; take(',')
                    }
                }
                '[' -> {
                    offset++; space(); if (peek() == ']') { offset++; return }
                    while (true) { value(depth + 1); space(); if (peek() == ']') { offset++; break }; take(',') }
                }
                '"' -> string()
                't' -> literal("true")
                'f' -> literal("false")
                'n' -> literal("null")
                else -> {
                    val token = Regex("-?(0|[1-9][0-9]*)").find(text, offset)
                    if (token == null || token.range.first != offset || token.value.length > 19) fail()
                    offset += token.value.length
                    if (peek() in listOf('.', 'e', 'E')) throw CatalogError("catalog_decimal")
                }
            }
        }
        fun literal(word: String) { if (!text.startsWith(word, offset)) fail(); offset += word.length }
        fun string(): String {
            if (peek() != '"') fail()
            val start = offset++
            while (true) {
                val char = peek() ?: fail(); offset++
                if (char == '"') break
                if (char.code < 32) fail()
                if (char == '\\') {
                    val escape = peek() ?: fail(); offset++
                    if (escape == 'u') repeat(4) { if (peek()?.digitToIntOrNull(16) == null) fail(); offset++ }
                    else if (escape !in "\"\\/bfnrt") fail()
                }
            }
            val decoded = JSONTokener(text.substring(start, offset)).nextValue() as String
            decoded.forEachIndexed { index, char ->
                if (char.isHighSurrogate() && decoded.getOrNull(index + 1)?.isLowSurrogate() != true) fail()
                if (char.isLowSurrogate() && decoded.getOrNull(index - 1)?.isHighSurrogate() != true) fail()
            }
            return decoded
        }
        fun fail(): Nothing = throw CatalogError("catalog_json")
    }
}
