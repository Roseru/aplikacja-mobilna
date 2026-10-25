package pl.roseru.kalorie.energy

import org.json.JSONArray
import org.json.JSONObject
import pl.roseru.kalorie.core.catalog.StrictJson
import java.math.BigDecimal
import java.security.MessageDigest
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.util.UUID

class EnergyProtocolException : IllegalArgumentException("Niepoprawna odpowiedź dotycząca zapotrzebowania")

/** Only the pinned, self-contained E9 schema. Unknown schema keywords fail closed. */
class EnergySchema(bytes:ByteArray) {
    // Generated configuration contains bounds such as 0.0. Pin its LF representation
    // so Git checkouts using LF and CRLF load the same trusted document. This applies
    // only to build configuration; response/audit bytes keep StrictJson below.
    private val definitions=run {
        require(bytes.size in 1..1_048_576)
        val configuration=bytes.toString(Charsets.UTF_8).replace("\r\n","\n")
        val sha=MessageDigest.getInstance("SHA-256").digest(configuration.toByteArray(Charsets.UTF_8)).joinToString(""){"%02x".format(it)}
        require(sha==SCHEMA_SHA256)
        JSONObject(configuration).getJSONObject("\$defs")
    }
    fun read(bytes:ByteArray,definition:String,maxBytes:Int=2*1_048_576):JSONObject {
        if(bytes.size !in 1..maxBytes || !definitions.has(definition))fail()
        return try {StrictJson.read(bytes).also {check(it,definitions.getJSONObject(definition),0)}}
        catch(error:EnergyProtocolException){throw error}
        catch(_:Exception){fail()}
    }
    fun validate(value:JSONObject,definition:String):JSONObject = read(StrictJson.canonical(value).toByteArray(Charsets.UTF_8),definition)
    private fun check(value:Any?,schema:JSONObject,depth:Int) {
        if(depth>64 || schema.keys().asSequence().any {it !in KEYWORDS})fail()
        fun branch(part:JSONObject)=check(value,part,depth+1)
        fun matches(part:JSONObject)=try {branch(part);true}catch(_:EnergyProtocolException){false}
        schema.optString("\$ref").takeIf {it.isNotEmpty()}?.let {ref->
            if(!ref.startsWith("#/\$defs/"))fail()
            val name=ref.removePrefix("#/\$defs/")
            if(name.contains('/') || !definitions.has(name))fail()
            branch(definitions.getJSONObject(name))
        }
        schema.optJSONArray("allOf")?.let {parts->for(i in 0 until parts.length())branch(parts.getJSONObject(i))}
        schema.optJSONArray("anyOf")?.let {parts->if((0 until parts.length()).none {matches(parts.getJSONObject(it))})fail()}
        schema.optJSONArray("oneOf")?.let {parts->if((0 until parts.length()).count {matches(parts.getJSONObject(it))}!=1)fail()}
        schema.optJSONObject("not")?.let {if(matches(it))fail()}
        schema.optJSONObject("if")?.let {condition->schema.optJSONObject(if(matches(condition))"then" else "else")?.let(::branch)}
        if(schema.has("const") && StrictJson.canonical(value)!=StrictJson.canonical(schema.get("const")))fail()
        schema.optJSONArray("enum")?.let {values->if((0 until values.length()).none {StrictJson.canonical(value)==StrictJson.canonical(values.get(it))})fail()}
        when(schema.optString("type")) {
            ""->Unit
            "null"->if(value!=null && value!==JSONObject.NULL)fail()
            "boolean"->if(value !is Boolean)fail()
            "integer"->if(value !is Int && value !is Long)fail()
            "string"->if(value !is String)fail()
            "object"->if(value !is JSONObject)fail()
            "array"->if(value !is JSONArray)fail()
            else->fail()
        }
        if(value is Number) {
            val number=value.toString().toBigDecimalOrNull()?:fail()
            if(schema.has("minimum") && number<BigDecimal(schema.get("minimum").toString()))fail()
            if(schema.has("maximum") && number>BigDecimal(schema.get("maximum").toString()))fail()
        }
        if(value is String) {
            if(value.any {it=='\u0000'})fail()
            var offset=0
            while(offset<value.length) {
                val c=value[offset++]
                if(Character.isLowSurrogate(c))fail()
                if(Character.isHighSurrogate(c) && (offset==value.length || !Character.isLowSurrogate(value[offset++])))fail()
            }
            val length=value.codePointCount(0,value.length)
            if(length<schema.optInt("minLength",0) || length>schema.optInt("maxLength",Int.MAX_VALUE))fail()
            if(schema.has("pattern") && !Regex(schema.getString("pattern")).matches(value))fail()
            try {when(schema.optString("format")) {
                ""->Unit
                "uuid"->if(UUID.fromString(value).toString()!=value)fail()
                "date"->if(LocalDate.parse(value).year !in 1..9999)fail()
                "date-time"->{
                    if(!value.endsWith('Z') || LocalDateTime.parse(value.dropLast(1)).year !in 1..9999)fail()
                    Instant.parse(value)
                }
                else->fail()
            }}catch(_:Exception){fail()}
        }
        if(value is JSONObject) {
            schema.optJSONArray("required")?.let {keys->for(i in 0 until keys.length())if(!value.has(keys.getString(i)))fail()}
            val fields=schema.optJSONObject("properties")?:JSONObject()
            value.keys().forEach {key->
                if('\u0000' in key)fail()
                if(fields.has(key))check(value.get(key),fields.getJSONObject(key),depth+1)
                else when(val additional=schema.opt("additionalProperties")) {
                    false->fail()
                    is JSONObject->check(value.get(key),additional,depth+1)
                }
            }
        }
        if(value is JSONArray) {
            if(value.length()<schema.optInt("minItems",0) || value.length()>schema.optInt("maxItems",Int.MAX_VALUE))fail()
            if(schema.optBoolean("uniqueItems") && (0 until value.length()).map {StrictJson.canonical(value.get(it))}.toSet().size!=value.length())fail()
            schema.optJSONObject("items")?.let {item->for(i in 0 until value.length())check(value.get(i),item,depth+1)}
        }
    }
    private fun fail():Nothing=throw EnergyProtocolException()
    companion object {
        const val SCHEMA_SHA256="54baca27ddc062b8de98386dde964cd8259998e1c30cdb3e44ab4de9b0cb7764"
        private val KEYWORDS=setOf("\$ref","description","title","default","type","properties","required","additionalProperties",
            "allOf","anyOf","oneOf","not","if","then","else","const","enum","minimum","maximum","minLength","maxLength",
            "pattern","format","items","minItems","maxItems","uniqueItems")
    }
}
