package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.catalog.*
import java.io.File
import java.nio.charset.CharacterCodingException
import java.security.MessageDigest
import java.util.concurrent.CancellationException

class MreSourceJsonTest {
    private val assets=File("src/main/assets/catalog")
    private fun hash(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") {(it.toInt() and 255).toString(16).padStart(2,'0')}

    @Test fun pinnedSourceHasIdenticalCanonicalValuesToPreviousRegexReader() {
        val bytes=File(assets,"mre2026/source.json").readBytes()
        assertEquals("f519ef7390287c06293e7d45ff65371d5fa5cc68565994c948baebd2b0c2ad94",hash(bytes))
        val expected=StrictJson.canonical(previousReader(bytes))
        val actual=StrictJson.canonical(MreSourceJson.read(bytes))
        assertEquals(hash(expected.toByteArray()),hash(actual.toByteArray()))
    }

    @Test fun exactNumberLexemesAndEscapedStringContentsRemainUnchanged() {
        val numbers=listOf("0","-0","0.00","-1.2300","1e-6","1E+003","-0E-0")
        val text="dose 2.5; quote \"; backslash \\; newline\n; emoji \uD83D\uDE00"
        val json="{\"values\":[${numbers.joinToString(",")}],\"text\":${JSONObject.quote(text)},\"escaped\":\"\\u0031.25\\/2e3\"}"
        val value=MreSourceJson.read(json.toByteArray())
        assertEquals(numbers,numbers.indices.map {value.getJSONArray("values").getString(it)})
        assertEquals(text,value.getString("text"))
        assertEquals("1.25/2e3",value.getString("escaped"))
    }

    @Test fun invalidNumbersKeysUtf8AndPreflightAmbiguityAreRejected() {
        val numbers=listOf("-","+1",".1","1.","1e","1e+","1e-","01","-01","NaN","Infinity","1_2","--1","1e1.2","0x10")
        for(number in numbers) assertThrows(IllegalArgumentException::class.java) {
            MreSourceJson.read("{\"value\":$number}".toByteArray())
        }
        for(json in listOf("{1:2}","{1.2 \n :3}","{-1e2:3}","{\"a\":1,2:3}",
            "{\"a\":1.2,\"\\u0061\":2}","{\"a\":\"\\uD800\"}","{\"a\":\"\\q\"}")) {
            assertThrows(IllegalArgumentException::class.java) {MreSourceJson.read(json.toByteArray())}
        }
        assertThrows(CharacterCodingException::class.java) {MreSourceJson.read(byteArrayOf(0xc3.toByte(),0x28))}
    }

    @Test fun tokenAndDocumentLengthLimitsRemainEnforced() {
        val longest="1".repeat(64)
        assertEquals(longest,MreSourceJson.read("{\"a\":$longest}".toByteArray()).getString("a"))
        assertThrows(IllegalArgumentException::class.java) {MreSourceJson.read("{\"a\":${longest}1}".toByteArray())}
        assertThrows(IllegalArgumentException::class.java) {MreSourceJson.read(ByteArray(1024*1024+1) {32})}
    }

    @Test fun longSourceScanChecksCancellationBeforeCompletingTheDocument() {
        val bytes=("{\"padding\":\""+"x".repeat(20_000)+"\",\"value\":1.25}").toByteArray()
        val stop=CancellationException("synthetic cancellation")
        var checks=0
        val actual=assertThrows(CancellationException::class.java) {
            MreSourceJson.read(bytes) {if(++checks==4) throw stop}
        }
        assertSame(stop,actual)
        assertEquals(4,checks)
    }

    @Test fun cancelledRuleReadIsNotWrappedAsUnavailableReference() {
        val schema=CatalogSchema(JSONObject(File(assets,"e2/common.schema.json").readText()),
            JSONObject(File(assets,"e2/catalog.schema.json").readText()))
        val catalog=CatalogPackageReader(schema,MreCatalogueRules.PACKAGE_ID,"demo").read(
            File(assets,"mre2026/manifest.json").inputStream(),File(assets,"mre2026/base-pl.1.json.gz.bin").inputStream())
        val stop=CancellationException("synthetic cancellation")
        val actual=assertThrows(CancellationException::class.java) {
            MreCatalogueRules.read(catalog,File(assets,"mre2026/selection-rules.json").readBytes(),
                File(assets,"mre2026/source.json").readBytes()) {throw stop}
        }
        assertSame(stop,actual)
    }

    /** Frozen prior algorithm is an independent compatibility oracle for the pinned fixture. */
    private fun previousReader(bytes:ByteArray):JSONObject {
        val source=bytes.toString(Charsets.UTF_8)
        val decimal=Regex("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?")
        val normalized=StringBuilder(source.length)
        var offset=0;var quoted=false;var escaped=false
        while(offset<source.length) {
            val char=source[offset]
            if(quoted) {
                normalized.append(char);offset++
                if(escaped)escaped=false else if(char=='\\')escaped=true else if(char=='"')quoted=false
            } else if(char=='"') {quoted=true;normalized.append(char);offset++}
            else if(char=='-' || char in '0'..'9') {
                val token=requireNotNull(decimal.find(source,offset))
                require(token.range.first==offset && token.value.length<=64)
                offset+=token.value.length
                var next=offset
                while(source.getOrNull(next) in listOf(' ','\t','\r','\n'))next++
                require(source.getOrNull(next)!=':')
                normalized.append('"').append(token.value).append('"')
            } else {normalized.append(char);offset++}
        }
        return StrictJson.read(normalized.toString().toByteArray())
    }
}
