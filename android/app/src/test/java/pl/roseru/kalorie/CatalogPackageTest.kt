package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.*
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.math.BigDecimal
import java.security.MessageDigest
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream

class CatalogPackageTest {
    private fun resource(name: String) = requireNotNull(javaClass.getResourceAsStream("/catalog/$name")).use { it.readBytes() }
    private fun reader(id: String = CatalogPackageReader.DEMO_ID, kind: String = "demo") = CatalogPackageReader(
        CatalogSchema(JSONObject(String(resource("common.schema.json"), Charsets.UTF_8)), JSONObject(String(resource("catalog.schema.json"), Charsets.UTF_8))), id, kind)
    private fun read(manifest: ByteArray = resource("manifest.json"), gzip: ByteArray = resource("base-pl.1.json.gz")) =
        reader().read(ByteArrayInputStream(manifest), ByteArrayInputStream(gzip))
    private fun rawJson() = GZIPInputStream(ByteArrayInputStream(resource("base-pl.1.json.gz"))).use { String(it.readBytes(), Charsets.UTF_8) }
    private fun gzip(json: String): ByteArray = ByteArrayOutputStream().also { bytes -> GZIPOutputStream(bytes).use { it.write(json.toByteArray(Charsets.UTF_8)) } }.toByteArray()
    private fun manifest(bytes: ByteArray, jsonSize: Int): JSONObject = JSONObject(String(resource("manifest.json"), Charsets.UTF_8))
        .put("compressed_bytes", bytes.size).put("uncompressed_bytes", jsonSize)
        .put("sha256", MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { (it.toInt() and 255).toString(16).padStart(2, '0') })
    private fun failure(code: String, block: () -> Unit) { assertEquals(code, assertThrows(CatalogError::class.java, block).code) }
    private fun modified(edit: (JSONObject) -> Unit): ValidatedCatalog {
        val value = JSONObject(rawJson()).apply(edit).toString()
        val bytes = gzip(value)
        return read(manifest(bytes, value.toByteArray().size).put("published_at", JSONObject(value).getString("published_at")).toString().toByteArray(), bytes)
    }
    @Test fun readsExactExportAndCalculatesWholeIncompleteDemo() {
        val document = read()
        assertEquals("65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef", document.sha256)
        val payload = document.payload()
        assertEquals(18, payload.getJSONArray("products").length())
        val products = payload.getJSONArray("products").objects().associateBy { it.getString("product_id") }
        val ration = payload.getJSONArray("rations").getJSONObject(0)
        assertFalse(ration.getBoolean("complete"))
        assertEquals("unverified", ration.getString("status"))
        val totals = NutritionV1.calculate(ration.getJSONArray("components").objects().map { part ->
            val quantity = part.getJSONObject("quantity")
            products.getValue(part.getJSONObject("product").getString("product_id"))
                .exactPortion(BigDecimal(quantity.getString("amount")), quantity.getString("unit"))
        })
        assertEquals("3466.00000145", totals.energy.canonical)
        assertEquals("3466", totals.energy.display)
    }
    @Test fun rejectsHashMismatchAndForeignIdentity() {
        val wrong = JSONObject(String(resource("manifest.json"))).put("sha256", "0".repeat(64))
        failure("hash_mismatch") { read(wrong.toString().toByteArray()) }
        failure("identity_mismatch") { reader("c12631e2-1a02-547c-a7f9-ebf87bb42e55").read(ByteArrayInputStream(resource("manifest.json")), ByteArrayInputStream(resource("base-pl.1.json.gz"))) }
        failure("identity_mismatch") { reader(kind = "official").read(ByteArrayInputStream(resource("manifest.json")), ByteArrayInputStream(resource("base-pl.1.json.gz"))) }
    }
    @Test fun rejectsBadReferencesDuplicatesAndPositions() {
        failure("catalog_reference") { modified { it.getJSONArray("products").getJSONObject(0).put("source_id", "00000000-0000-0000-0000-000000000000") } }
        failure("catalog_duplicate") { modified { it.getJSONArray("products").put(1, it.getJSONArray("products").getJSONObject(0)) } }
        failure("catalog_order") { modified { it.getJSONArray("rations").getJSONObject(0).getJSONArray("components").getJSONObject(0).put("position", 2) } }
    }
    @Test fun rejectsCountsHeadersAndNullableFieldOmission() {
        failure("header_mismatch") { modified { it.getJSONObject("counts").put("products", 17) } }
        failure("catalog_schema_version") { modified { it.put("schema_version", 2) } }
        failure("catalog_reader_version") { modified { it.put("min_reader_version", 2) } }
        failure("catalog_schema") { modified { it.getJSONArray("products").getJSONObject(0).getJSONObject("nutrition_per_100").remove("fat_g") } }
    }
    @Test fun rejectsNumbersAndNonCanonicalDecimalsAndInvalidDate() {
        failure("catalog_schema") { modified { it.getJSONArray("products").getJSONObject(0).getJSONObject("nutrition_per_100").put("energy_kcal", 87) } }
        failure("catalog_schema") { modified { it.getJSONArray("products").getJSONObject(0).getJSONObject("nutrition_per_100").put("energy_kcal", "87.0") } }
        failure("catalog_schema") { modified { it.getJSONArray("products").getJSONObject(0).getJSONObject("nutrition_per_100").put("energy_kcal", "87\n") } }
        failure("catalog_schema") { modified { it.getJSONArray("products").getJSONObject(0).put("product_id", "00000000-0000-0000-0000-000000000000\n") } }
        failure("catalog_schema") { modified { it.getJSONArray("sources").getJSONObject(0).put("checked_on", "2026-02-30") } }
    }
    @Test fun rejectsUnitConversionWithoutDensityAndFalseCompleteness() {
        failure("catalog_unit") { modified { it.getJSONArray("products").getJSONObject(0).put("basis_unit", "ml") } }
        failure("catalog_completeness") { modified { it.getJSONArray("rations").getJSONObject(0).put("complete", true) } }
    }
    @Test fun rejectsDemoPretendingToBeOfficial() {
        val value = JSONObject(rawJson()).put("kind", "official").toString()
        val bytes = gzip(value)
        val meta = manifest(bytes, value.toByteArray().size).put("kind", "official")
        failure("catalog_official") { reader(kind = "official").read(ByteArrayInputStream(meta.toString().toByteArray()), ByteArrayInputStream(bytes)) }
    }
    @Test fun acceptsAllContractTimestampPrecisionsAndRejectsInvalidCalendarTimes() {
        listOf("", ".1", ".12", ".123", ".1234", ".12345", ".123456").forEach { fraction ->
            assertEquals("2026-10-09T12:00:00${fraction}Z", JSONObject(modified {
                it.put("published_at", "2026-10-09T12:00:00${fraction}Z")
            }.payloadJson).getString("published_at"))
        }
        listOf("2026-02-30T12:00:00Z", "2026-10-09T24:00:00Z", "2026-10-09T23:59:60Z", "0000-01-01T00:00:00Z", "2026-10-09T12:00:00.1234567Z").forEach { time ->
            failure("catalog_schema") { modified { it.put("published_at", time) } }
        }
    }
    @Test fun rejectsCorruptCrcTruncationAndMultipleMembers() {
        val good = resource("base-pl.1.json.gz")
        val broken = good.clone().also { it[it.size - 8] = (it[it.size - 8].toInt() xor 1).toByte() }
        listOf(broken, good.copyOf(good.size - 4), good + good, good + byteArrayOf(0)).forEach { bytes ->
            failure("invalid_gzip") { read(manifest(bytes, 15691).toString().toByteArray(), bytes) }
        }
    }
    @Test fun limitsReadAndInflationBeforeAllocatingJson() {
        failure("catalog_size") { read(ByteArray(CatalogPackageReader.MAX_MANIFEST + 1) { ' '.code.toByte() }) }
        val bytes = gzip("x".repeat(100_000))
        failure("uncompressed_size") { read(manifest(bytes, 100).toString().toByteArray(), bytes) }
        failure("catalog_size") { read(gzip = resource("base-pl.1.json.gz") + byteArrayOf(0)) }
    }
    @Test fun strictJsonRejectsEscapedDuplicateKeysInvalidUtf8AndLenientSyntax() {
        failure("catalog_json_duplicate") { StrictJson.read("{\"x\":1,\"\\u0078\":2}".toByteArray()) }
        listOf("{'x':1}", "{\"x\":1,}", "{\"x\":01}", "{}{}", "{\"x\":NaN}", "{\"x\":\"\\uD800\"}").forEach { input ->
            assertThrows(input, CatalogError::class.java) { StrictJson.read(input.toByteArray()) }
        }
        failure("catalog_json") { StrictJson.read(byteArrayOf(123, 34, -1, 34, 58, 49, 125)) }
        failure("catalog_decimal") { StrictJson.read("{\"release\":1.0}".toByteArray()) }
    }
}
