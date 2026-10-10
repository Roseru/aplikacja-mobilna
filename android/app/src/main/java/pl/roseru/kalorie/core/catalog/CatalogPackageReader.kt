package pl.roseru.kalorie.core.catalog

import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.security.MessageDigest
import java.util.zip.CRC32
import java.util.zip.Inflater

class ValidatedCatalog internal constructor(val packageId: String, val kind: String, val release: Int,
    val sha256: String, val manifestJson: String, val payloadJson: String) {
    fun payload() = JSONObject(payloadJson)
}

class CatalogPackageReader(private val schema: CatalogSchema, private val expectedId: String, private val expectedKind: String) {
    companion object {
        const val DEMO_ID = "47bdff67-e58b-5437-919b-ec00159afbc5"
        const val MAX_MANIFEST = 1024 * 1024
        const val MAX_GZIP = 10 * 1024 * 1024
        const val MAX_JSON = 50 * 1024 * 1024
    }
    fun read(manifestStream: InputStream, packageStream: InputStream): ValidatedCatalog {
        val manifest = StrictJson.read(manifestStream.use { bounded(it, MAX_MANIFEST) })
        header(manifest); schema.validate(manifest, "Manifest"); identity(manifest)
        val sourceIds = manifest.getJSONArray("source_ids")
        val sourceSet = (0 until sourceIds.length()).map { sourceIds.getString(it) }.toSet()
        if (sourceSet.size != sourceIds.length() || sourceSet.size != manifest.getJSONObject("counts").getInt("sources")) fail("catalog_counts")
        if (manifest.getString("path") != "base-pl.${manifest.getInt("release")}.json.gz") fail("catalog_manifest")
        val bytes = packageStream.use { bounded(it, minOf(MAX_GZIP, manifest.getInt("compressed_bytes"))) }
        if (bytes.size != manifest.getInt("compressed_bytes")) fail("compressed_size")
        val hash = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { (it.toInt() and 255).toString(16).padStart(2, '0') }
        if (hash != manifest.getString("sha256")) fail("hash_mismatch")
        val json = inflate(bytes, minOf(MAX_JSON, manifest.getInt("uncompressed_bytes")))
        if (json.size != manifest.getInt("uncompressed_bytes")) fail("uncompressed_size")
        val payload = StrictJson.read(json)
        header(payload); schema.validate(payload, "Package"); identity(payload)
        listOf("package_id", "kind", "release", "schema_version", "min_reader_version", "published_at", "counts").forEach { key ->
            if (StrictJson.canonical(payload.get(key)) != StrictJson.canonical(manifest.get(key))) fail("header_mismatch")
        }
        val actualSources = payload.getJSONArray("sources").objects().map { it.getString("source_id") }.toSet()
        if (sourceSet != actualSources) fail("source_ids_mismatch")
        graph(payload)
        return ValidatedCatalog(expectedId, expectedKind, payload.getInt("release"), hash,
            StrictJson.canonical(manifest), StrictJson.canonical(payload))
    }
    private fun identity(value: JSONObject) {
        if (value.getString("package_id") != expectedId || value.getString("kind") != expectedKind) fail("identity_mismatch")
    }
    private fun header(value: JSONObject) {
        if (value.opt("schema_version") != 1) fail("catalog_schema_version")
        if (value.opt("min_reader_version") != 1) fail("catalog_reader_version")
    }
    private fun graph(value: JSONObject) {
        val products = value.getJSONArray("products").objects()
        val sources = value.getJSONArray("sources").objects()
        val rations = value.getJSONArray("rations").objects()
        fun productKey(product: JSONObject) = "${product.getString("product_id")}@${product.getInt("revision")}"
        val productMap = products.associateBy(::productKey)
        val sourceMap = sources.associateBy { it.getString("source_id") }
        if (productMap.size != products.size || sourceMap.size != sources.size ||
            rations.map { "${it.getString("ration_id")}@${it.getInt("revision")}" }.toSet().size != rations.size) fail("catalog_duplicate")
        val counts = value.getJSONObject("counts")
        if (counts.getInt("products") != products.size || counts.getInt("sources") != sources.size || counts.getInt("rations") != rations.size ||
            counts.getInt("components") != rations.sumOf { it.getJSONArray("components").length() } || counts.getInt("components") > 100_000) fail("catalog_counts")
        products.forEach { product ->
            if (product.getString("source_id") !in sourceMap) fail("catalog_reference")
            val density = product.optJSONObject("density_g_per_ml")
            if (density != null && density.getString("source_id") !in sourceMap) fail("catalog_reference")
            if (product.getJSONObject("package_quantity").getString("unit") != product.getString("basis_unit") && density == null) fail("catalog_unit")
        }
        rations.forEach { ration ->
            if (ration.getString("source_id") !in sourceMap) fail("catalog_reference")
            val components = ration.getJSONArray("components").objects()
            if (components.map { it.getInt("position") } != (1..components.size).toList()) fail("catalog_order")
            if (ration.getBoolean("complete") && ration.getJSONArray("excluded_items").objects().any { it.getString("classification") != "equipment" }) fail("catalog_completeness")
            components.forEach { part ->
                val product = productMap[productKey(part.getJSONObject("product"))] ?: fail("catalog_reference")
                if (part.getJSONObject("quantity").getString("unit") != product.getString("basis_unit") && product.isNull("density_g_per_ml")) fail("catalog_unit")
                if (ration.getBoolean("complete") && product.getJSONObject("nutrition_per_100").keys().asSequence().any { product.getJSONObject("nutrition_per_100").isNull(it) }) fail("catalog_completeness")
            }
        }
        if (expectedKind == "official") {
            if (sources.any { it.getString("status") != "verified" || it.getJSONArray("missing_data").length() != 0 || it.getString("basis") == "assumed_listed_quantity" }) fail("catalog_official")
            if (products.any { it.getString("status") != "verified" || it.getJSONObject("nutrition_per_100").keys().asSequence().any { key -> it.getJSONObject("nutrition_per_100").isNull(key) } }) fail("catalog_official")
            if (rations.any { it.getString("status") != "verified" || !it.getBoolean("complete") || it.isNull("manufacturer") }) fail("catalog_official")
        }
    }
    private fun bounded(input: InputStream, limit: Int): ByteArray {
        val output = ByteArrayOutputStream(); val buffer = ByteArray(8192)
        while (true) {
            val count = input.read(buffer, 0, minOf(buffer.size, limit - output.size() + 1))
            if (count == -1) break
            if (count == 0) fail("catalog_stream")
            if (output.size() + count > limit) fail("catalog_size")
            output.write(buffer, 0, count)
        }
        return output.toByteArray()
    }
    private fun inflate(bytes: ByteArray, limit: Int): ByteArray {
        fun byte(index: Int): Int = if (index in bytes.indices) bytes[index].toInt() and 255 else fail("invalid_gzip")
        fun u16(index: Int) = byte(index) or (byte(index + 1) shl 8)
        fun u32(index: Int) = (0..3).fold(0L) { result, shift -> result or (byte(index + shift).toLong() shl (8 * shift)) }
        if (bytes.size < 18 || byte(0) != 31 || byte(1) != 139 || byte(2) != 8 || byte(3) and 224 != 0) fail("invalid_gzip")
        val flags = byte(3); var offset = 10
        if (flags and 4 != 0) { val extra = u16(offset); offset += 2 + extra; if (offset > bytes.size) fail("invalid_gzip") }
        if (flags and 8 != 0) { while (byte(offset++) != 0) {} }
        if (flags and 16 != 0) { while (byte(offset++) != 0) {} }
        if (flags and 2 != 0) {
            val crc = CRC32().apply { update(bytes, 0, offset) }.value and 65535
            if (crc != u16(offset).toLong()) fail("invalid_gzip"); offset += 2
        }
        if (offset + 8 >= bytes.size) fail("invalid_gzip")
        val decoder = Inflater(true); val output = ByteArrayOutputStream(); val crc = CRC32()
        try {
            decoder.setInput(bytes, offset, bytes.size - offset)
            val buffer = ByteArray(8192)
            while (!decoder.finished()) {
                val count = decoder.inflate(buffer, 0, minOf(buffer.size, limit - output.size() + 1))
                if (output.size() + count > limit) fail("uncompressed_size")
                if (count == 0 && !decoder.finished()) fail("invalid_gzip")
                output.write(buffer, 0, count); crc.update(buffer, 0, count)
            }
            val trailer = offset + decoder.totalIn
            if (trailer + 8 != bytes.size || u32(trailer) != crc.value || u32(trailer + 4) != output.size().toLong()) fail("invalid_gzip")
        } catch (error: CatalogError) { throw error }
        catch (_: Exception) { fail("invalid_gzip") }
        finally { decoder.end() }
        return output.toByteArray()
    }
    private fun fail(code: String): Nothing = throw CatalogError(code)
}
