package pl.roseru.kalorie

import android.graphics.Bitmap
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Surface
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.ui.AnalyticsContent
import pl.roseru.kalorie.ui.CalorieTheme
import java.io.File
import java.math.BigDecimal
import java.time.LocalDate

/** Isolated, synthetic UI data: no user's diary, account or HTTP is read or written. */
class AnalyticsPresentationTest {
    @get:Rule val compose = createComposeRule()
    private val today = LocalDate.of(2026, 10, 12)
    private val window = AnalyticsWindow(today, AnalyticsPeriod.WEEK)
    private fun result(): AnalyticsResult {
        val first = today.minusDays(5)
        val last = today.minusDays(1)
        return Analytics.build(window, AnalyticsInput(
            meals = listOf(
                AnalyticsMeal(first, listOf(Nutrients(2100.0, 100.0, 70.0, 250.0))),
                AnalyticsMeal(last, listOf(Nutrients(1900.0, 110.0, 60.0, 220.0))),
                AnalyticsMeal(today.minusDays(2), listOf(Nutrients(600.0, null, null, null))),
                AnalyticsMeal(today, listOf(Nutrients(2200.0, 120.0, 75.0, 260.0)))),
            goals = listOf(AnalyticsGoal(window.start, BigDecimal("2000"))),
            declarations = setOf(first, last, today),
            weights = listOf(
                AnalyticsWeight("first", first, first.atStartOfDay().toInstant(java.time.ZoneOffset.UTC), BigDecimal("82.4")),
                AnalyticsWeight("last", last, last.atStartOfDay().toInstant(java.time.ZoneOffset.UTC), BigDecimal("81.9")))), today)
    }
    private fun show(result: AnalyticsResult, dark: Boolean = false, compact: Boolean = false,
        onPeriod: (AnalyticsPeriod) -> Unit = {}, onMove: (Int) -> Unit = {}, onDay: (LocalDate) -> Unit = {}) {
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, if (compact) 1.5f else 1f)) {
                CalorieTheme(dark) {
                    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                        Box(Modifier.fillMaxSize()) {
                            Box((if (compact) Modifier.width(320.dp).fillMaxHeight() else Modifier.fillMaxSize()).testTag("analytics-preview")) {
                                AnalyticsContent(window, today, result, onPeriod, onMove, {}, onDay)
                            }
                        }
                    }
                }
            }
        }
    }
    private fun scroll(tag: String) = compose.onNodeWithTag("analytics-content").performScrollToNode(hasTestTag(tag))
    private fun screenshot(name: String) {
        val image = compose.onNodeWithTag("analytics-preview").captureToImage().asAndroidBitmap()
        val directory = File(InstrumentationRegistry.getInstrumentation().targetContext.filesDir, "analytics-preview")
        directory.mkdirs()
        File(directory, "$name.png").outputStream().use { assertTrue(image.compress(Bitmap.CompressFormat.PNG, 100, it)) }
    }
    @Test fun closedDaySummaryAndRealWeightRemainSeparateFromPreliminaryAndMissingDays() {
        var selectedDay: LocalDate? = null
        show(result(), onDay = { selectedDay = it })
        compose.onNodeWithTag("average-kcal").assertTextEquals("2000 kcal")
        screenshot("light-summary")
        scroll("complete-days")
        compose.onNodeWithTag("complete-days").assertTextContains("2 / 7", substring = true)
        compose.onNodeWithTag("days-in-goal").assertTextContains("2 / 2", substring = true)
        scroll("metric-1")
        compose.onNodeWithTag("metric-1").performClick()
        compose.onNodeWithTag("metric-average").assertTextEquals("Średnia: 105,0 g · 2 dni")
        screenshot("light-chart")
        scroll("weight-change")
        compose.onNodeWithTag("weight-change").assertTextContains("Zmiana: -0,5 kg", substring = true)
        scroll("history-$today")
        compose.onNodeWithTag("history-$today").assertTextContains("Wynik wstępny", substring = true).performClick()
        assertEquals(today, selectedDay)
        val missing = today.minusDays(3)
        scroll("history-$missing")
        compose.onNodeWithTag("history-$missing").assertTextContains("Brak danych o spożyciu", substring = true)
    }
    @Test fun darkNarrowScreenWithEnlargedTextKeepsMetricAndPeriodControlsReachable() {
        var period: AnalyticsPeriod? = null
        var movement = 0
        show(result(), dark = true, compact = true, onPeriod = { period = it }, onMove = { movement = it })
        val viewport = compose.onNodeWithTag("analytics-preview").fetchSemanticsNode().boundsInRoot
        val density = InstrumentationRegistry.getInstrumentation().targetContext.resources.displayMetrics.density
        assertTrue("This case must use a real 320dp viewport", viewport.width <= 321 * density)
        compose.onNodeWithTag("period-90").performClick()
        assertEquals(AnalyticsPeriod.QUARTER, period)
        compose.onNodeWithTag("analytics-previous").performClick()
        assertEquals(-1, movement)
        screenshot("dark-large-text")
        scroll("days-in-goal")
        compose.onNodeWithTag("days-in-goal").assertTextContains("2 / 2", substring = true).assertIsDisplayed()
        for (index in 0..3) {
            scroll("metric-$index")
            compose.onNodeWithTag("metric-$index").assertIsDisplayed().performClick().assertIsSelected()
            val bounds = compose.onNodeWithTag("metric-$index").fetchSemanticsNode().boundsInRoot
            val root = compose.onNodeWithTag("analytics-preview").fetchSemanticsNode().boundsInRoot
            assertTrue("Metric must fit the narrow viewport", bounds.left >= root.left && bounds.right <= root.right)
        }
        screenshot("dark-large-chart")
        scroll("history-$today")
        compose.onNodeWithTag("history-$today").assertTextContains("Wynik wstępny", substring = true).assertIsDisplayed()
    }
    @Test fun emptyReportShowsUnknownAverageAndGoalInsteadOfAnInventedZeroPercent() {
        show(Analytics.build(window, AnalyticsInput(emptyList(), emptyList(), emptySet(), emptyList()), today))
        compose.onNodeWithTag("average-kcal").assertTextEquals("Brak kompletnych dni")
        scroll("days-in-goal")
        compose.onNodeWithTag("days-in-goal").assertTextContains("Brak dni do oceny", substring = true)
        scroll("weight-change")
        compose.onNodeWithTag("weight-change").assertTextEquals("Do zmiany masy potrzeba pomiarów z dwóch dni.")
        compose.onNodeWithTag("weight-chart").assertDoesNotExist()
    }
}
