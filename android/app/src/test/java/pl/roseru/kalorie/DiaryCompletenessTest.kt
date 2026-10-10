package pl.roseru.kalorie

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test
import pl.roseru.kalorie.core.*
import java.math.BigDecimal

class DiaryCompletenessTest {
    @Test fun allFiveNormativeDayVectors() {
        val source = javaClass.getResourceAsStream("/contracts/nutrition-v1.json")!!.bufferedReader().use { it.readText() }
        val cases = JSONObject(source).getJSONArray("day_cases")
        assertEquals(5, cases.length())
        for (index in 0 until cases.length()) {
            val row = cases.getJSONObject(index)
            val totals = ExactTotals(FieldAggregate(BigDecimal(row.getString("known_energy")), row.getInt("missing_energy_count"), 0),
                FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1), FieldAggregate(BigDecimal.ZERO, 0, 1))
            assertEquals(row.getString("id"), row.getBoolean("expected_complete"), completeDiary(row.getBoolean("declared_complete"),
                row.getInt("meal_count"), Nutrients.fromExact(totals)))
        }
    }
}
