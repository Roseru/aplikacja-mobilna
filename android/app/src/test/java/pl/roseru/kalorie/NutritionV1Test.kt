package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import pl.roseru.kalorie.core.*
import java.math.BigDecimal

@RunWith(Parameterized::class)
class NutritionV1Test(private val name: String, private val fixture: JSONObject) {
    companion object {
        @JvmStatic @Parameterized.Parameters(name = "{0}")
        fun cases(): Collection<Array<Any>> {
            val input = requireNotNull(NutritionV1Test::class.java.getResourceAsStream("/contracts/nutrition-v1.json"))
                .bufferedReader(Charsets.UTF_8).use { it.readText() }
            val document = JSONObject(input)
            check(document.getString("formula_version") == NutritionV1.FORMULA)
            val rows = document.getJSONArray("cases")
            return (0 until rows.length()).map { index ->
                val row = rows.getJSONObject(index)
                arrayOf(row.getString("id"), row)
            }
        }
    }

    @Test fun matchesSharedBackendVector() {
        val rows = fixture.getJSONArray("items")
        val items = (0 until rows.length()).map { index ->
            val row = rows.getJSONObject(index)
            val nutrition = row.getJSONObject("nutrition_per_100")
            val fields = ExactNutrition.fields.associateWith { field ->
                if (nutrition.isNull(field)) null else nutrition.getString(field)
            }
            val density = if (row.isNull("density_g_per_ml")) null else
                ExactDensity(ContractDecimal.read(row.getString("density_g_per_ml")), "vector-density")
            ExactPortion(BigDecimal(row.getString("amount")), QuantityUnit.read(row.getString("unit")),
                QuantityUnit.read(row.getString("basis_unit")), ExactNutrition.read(fields), density)
        }
        if (fixture.has("expected_error")) {
            val failure = assertThrows(NutritionError::class.java) { NutritionV1.calculate(items) }
            assertEquals(name, fixture.getString("expected_error"), failure.code)
        } else {
            val expected = fixture.getJSONObject("expected")
            NutritionV1.calculate(items).fields().forEachIndexed { index, actual ->
                val field = ExactNutrition.fields[index]
                val result = expected.getJSONObject(field)
                assertEquals("$name/$field sum", result.getString("known_sum"), actual.canonical)
                assertEquals("$name/$field display", result.getString("display"), actual.display)
                assertEquals("$name/$field missing", result.getInt("missing_count"), actual.missingCount)
                assertEquals("$name/$field complete", result.getBoolean("complete"), actual.complete)
            }
        }
    }
}

class DecimalInputTest {
    @Test fun rejectsNonCanonicalWireNumbers() {
        listOf("1.0", "01", "+1", "-1", "1e2", ".5", "1.", "NaN", "Infinity", " 1", "1000000", "0.0000001").forEach {
            assertThrows(it, NutritionError::class.java) { ContractDecimal.read(it) }
        }
        assertEquals(BigDecimal("999999.999999"), ContractDecimal.read("999999.999999"))
        assertEquals(BigDecimal.ZERO, ContractDecimal.read("0"))
    }
    @Test fun acceptsPolishInputWithoutBinaryFloatingPointOrSilentRounding() {
        assertEquals(BigDecimal("120.500001"), ContractDecimal.userQuantity(" 120,500001 "))
        assertEquals("120.5", ContractDecimal.canonical(ContractDecimal.userQuantity("120,500000")!!))
        listOf("0", "-1", "1e2", "10000.000001", "1.0000001", "NaN").forEach { assertNull(it, ContractDecimal.userQuantity(it)) }
    }
    @Test fun requiredNullableFieldsAreNotOmitted() {
        assertThrows(NutritionError::class.java) { ExactNutrition.read(mapOf("energy_kcal" to "0")) }
    }
    @Test fun emptyDiaryHasCompleteKnownZeroAndNoMissingEntries() {
        NutritionV1.calculate(emptyList()).fields().forEach {
            assertEquals("0", it.canonical); assertTrue(it.complete); assertEquals(0, it.missingCount)
        }
    }
    @Test fun conversionNeedsPositiveDensityWithProvenance() {
        assertThrows(NutritionError::class.java) { ExactDensity(BigDecimal.ZERO, "source") }
        assertThrows(NutritionError::class.java) { ExactDensity(BigDecimal.ONE, "") }
    }
    @Test fun legacyDisplayUsesExplicitHalfUp() {
        assertEquals("1,3", decimal(1.25)); assertEquals("2,4", decimal(2.35))
    }
}
