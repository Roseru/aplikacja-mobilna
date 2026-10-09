package pl.roseru.kalorie

import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.*

class NutritionTest {
    @Test fun `portion scales calories and each macro without rounding first`() {
        val portion = Nutrients(89.0, 1.1, 0.3, 22.8).portion(120.0)
        assertEquals(106.8, portion.kcal, .00001)
        assertEquals(1.32, portion.protein!!, .00001)
        assertEquals(.36, portion.fat!!, .00001)
        assertEquals(27.36, portion.carbs!!, .00001)
    }
    @Test fun `missing macros stay unknown while energy remains calculable`() {
        val sum = listOf(Nutrients(100.0, 10.0, 2.0, 5.0), Nutrients(90.0, null, null, null)).total()
        assertEquals(190.0, sum.kcal, .00001)
        assertNull(sum.protein)
        assertNull(sum.fat)
        assertNull(sum.carbs)
    }
    @Test fun `sum is calculated before display rounding`() {
        assertEquals(1.47, List(3) { Nutrients(.49, 0.0, 0.0, 0.0) }.total().kcal, .00001)
        assertEquals(0.0, emptyList<Nutrients>().total().kcal, 0.0)
    }
    @Test fun `Polish decimal input and invalid quantities`() {
        assertEquals(120.5, parseAmount(" 120,5 ")!!, 0.0)
        listOf("", "0", "-1", "NaN", "Infinity", "1e99", "10001", "abc").forEach { assertNull(it, parseAmount(it)) }
    }
    @Test fun `search ignores case and Polish diacritics`() {
        assertEquals("platki owsiane", normalizeSearch("PŁATKI OWSIANE"))
        assertTrue(normalizeSearch("Pierś z kurczaka").contains(normalizeSearch("piers")))
    }
    @Test(expected = IllegalArgumentException::class) fun `negative amount cannot produce negative intake`() {
        Nutrients(89.0, null, null, null).portion(-100.0)
    }
}
