package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.*
import java.io.File
import java.math.BigDecimal

class MreRationSelectionTest {
    private val assets = File("src/main/assets/catalog")
    private data class Bundle(val catalog: ValidatedCatalog, val rules: MreCatalogueRules, val metadata: JSONObject)
    private fun bundle(): Bundle {
        val schema = CatalogSchema(JSONObject(File(assets, "e2/common.schema.json").readText()),
            JSONObject(File(assets, "e2/catalog.schema.json").readText()))
        val catalog = CatalogPackageReader(schema, MreCatalogueRules.PACKAGE_ID, "demo").read(
            File(assets, "mre2026/manifest.json").inputStream(), File(assets, "mre2026/base-pl.1.json.gz.bin").inputStream())
        val metadata = File(assets, "mre2026/selection-rules.json").readBytes()
        return Bundle(catalog, MreCatalogueRules.read(catalog, metadata, File(assets, "mre2026/source.json").readBytes()), JSONObject(String(metadata)))
    }
    private fun menu(bundle: Bundle, number: Int): JSONObject {
        val menus = bundle.metadata.getJSONArray("menus").objects()
        val id = menus.single { it.getInt("number") == number }.getString("ration_id")
        return bundle.catalog.payload().getJSONArray("rations").objects().single { it.getString("ration_id") == id }
    }

    @Test fun actualSourceReleaseKeepsPriorRowsAndCalculatesSourcePortionWithoutAddingWater() {
        val b = bundle(); val payload = b.catalog.payload()
        assertEquals(1, b.catalog.release)
        assertNotEquals(CatalogPackageReader.DEMO_ID, b.catalog.packageId)
        assertEquals(24, b.metadata.getJSONArray("menus").length())
        assertEquals(111, payload.getJSONArray("products").length())
        val old = java.util.zip.GZIPInputStream(File(assets, "e2/base-pl.1.json.gz.bin").inputStream()).use { JSONObject(String(it.readBytes())) }
        val oldIds=old.getJSONArray("products").objects().map { it.getString("product_id") }.toSet()
        assertEquals(18,oldIds.size)
        assertTrue(payload.getJSONArray("products").objects().none { it.getString("product_id") in oldIds })
        val first = menu(b, 1)
        val reference = b.rules.forRation(StrictJson.canonical(first))!!
        assertEquals("227", reference.origins.getValue(1).portionGrams)
        assertEquals("289.8", reference.origins.getValue(1).values.getValue("energy_kcal"))
        val productId = first.getJSONArray("components").getJSONObject(0).getJSONObject("product").getString("product_id")
        val product = payload.getJSONArray("products").objects().single { it.getString("product_id") == productId }
        val total = NutritionV1.calculate(listOf(product.exactPortion(BigDecimal("227"), "g")))
        assertEquals("290", total.energy.display)
        assertEquals("19.0", total.protein.display)
        assertEquals("11.2", total.fat.display)
        assertEquals("30.8", total.carbs.display)
    }

    @Test fun cakeAlternativesAndAccessoryAverageAreNeverSelectedImplicitlyOrSummedTogether() {
        val b = bundle(); val cake = menu(b, 9)
        val choice = b.metadata.getJSONArray("menus").objects().single { it.getInt("number") == 9 }
            .getJSONArray("choices").getJSONObject(0).getJSONArray("positions")
        assertEquals(3, choice.length())
        val first = choice.getInt(0); val second = choice.getInt(1)
        val rules = b.rules.forRation(StrictJson.canonical(cake))!!
        assertFalse(rules.accepts(setOf(first, second)))
        assertEquals(setOf(second), rules.toggle(setOf(first), second, true))
        assertTrue(rules.selectUnambiguous(emptySet()).intersect(setOf(first, second, choice.getInt(2))).isEmpty())
        val averageMenu = b.metadata.getJSONArray("menus").objects().first { entry ->
            entry.getJSONArray("packets").objects().any { it.getJSONArray("aggregate").length() > 0 }
        }
        val averageRation = menu(b, averageMenu.getInt("number"))
        val averageRules = b.rules.forRation(StrictJson.canonical(averageRation))!!
        val average = averageMenu.getJSONArray("packets").objects().flatMap { packet ->
            packet.getJSONArray("aggregate").let { a -> (0 until a.length()).map { a.getInt(it) } }
        }.toSet()
        assertTrue(average.isNotEmpty())
        assertTrue(averageRules.selectUnambiguous(emptySet()).intersect(average).isEmpty())
        assertTrue(averageRules.withoutPacketAverages(average).isEmpty())
    }

    @Test fun staleRationOrChangedSourceCannotReuseDifferentChoiceRules() {
        val b = bundle(); val first = menu(b, 1)
        assertThrows(MreCatalogueException::class.java) { b.rules.forRation(JSONObject(first.toString()).put("revision", 2).toString()) }
        val changedSource = File(assets, "mre2026/source.json").readBytes() + byteArrayOf(10)
        assertThrows(MreCatalogueException::class.java) { MreCatalogueRules.read(b.catalog,
            File(assets, "mre2026/selection-rules.json").readBytes(), changedSource) }
        val third = b.rules.forRation(StrictJson.canonical(menu(b, 3)))!!
        val source = JSONObject(File(assets, "mre2026/source.json").readText()).getJSONArray("menus").objects().single { it.getInt("menu_number") == 3 }
        val mismatch = source.getJSONArray("components").objects().single { it.getJSONObject("nutrition").getString("status") == "different_variant_reference_only" }
        val locator = source.getString("source_section") + "/position=" + mismatch.getInt("position")
        assertTrue(third.missing.any { !it.equipment && it.locator == locator })
        assertTrue(third.origins.values.none { it.sourceLocator == locator })
    }

    @Test fun manualMissingValueStaysMissingWhileExplicitZeroAndUserDecimalArePreserved() {
        val blank = ExactNutrition.fields.associateWith { "" }
        val unknown = MreManualInput.read("2,5", blank)
        assertNull(unknown.nutrition.energy)
        val totals = NutritionV1.calculate(listOf(ExactPortion(BigDecimal(unknown.amount), QuantityUnit.GRAMS, QuantityUnit.GRAMS, unknown.nutrition)))
        assertEquals(1, totals.energy.missingCount)
        assertFalse(totals.energy.complete)
        val provided = MreManualInput.read("2.50", blank + ("energy_kcal" to "0.0") + ("protein_g" to "1,20"))
        assertEquals(BigDecimal.ZERO, provided.nutrition.energy)
        assertEquals(BigDecimal("1.2"), provided.nutrition.protein)
        for (invalid in listOf("-1", "1e2", "NaN", "1000.000001", "0.0000001")) {
            assertThrows(IllegalArgumentException::class.java) { MreManualInput.read("2.5", blank + ("energy_kcal" to invalid)) }
        }
    }
}
