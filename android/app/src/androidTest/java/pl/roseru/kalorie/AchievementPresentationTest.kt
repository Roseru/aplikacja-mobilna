package pl.roseru.kalorie

import android.os.ParcelFileDescriptor
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.AchievementState
import pl.roseru.kalorie.ui.AchievementsContent
import pl.roseru.kalorie.ui.CalorieTheme
import java.math.BigDecimal
import java.time.*

/** Every screenshot and entry is synthetic and belongs to the separate validation package. */
class AchievementPresentationTest {
    @get:Rule val compose = createComposeRule()
    private val today = LocalDate.of(2026, 10, 12)
    private fun fixture(): AchievementPreview {
        fun meal(date: LocalDate, kcal: Double = 2000.0, ration: Boolean = false) = AchievementMeal(date, "UTC", ration,
            listOf(AchievementPortion(Nutrients(kcal, null, null, null), BigDecimal("100"), if (ration) 1 else null)))
        val old = (30L downTo 21L).map { meal(today.minusDays(it), 1000.0) }
        val run = (9L downTo 0L).map { meal(today.minusDays(it), ration = it in 1L..5L) }
        val meals = old + run
        return Achievements.build(AchievementInput(meals, listOf(AnalyticsGoal(today.minusYears(1), BigDecimal("2000"))),
            meals.map { it.date }.toSet(), listOf(13L, 9L, 5L, 1L).map { AchievementWeight(today.minusDays(it), "UTC") }),
            today.atTime(12, 0).toInstant(ZoneOffset.UTC), ZoneOffset.UTC)
    }
    private fun show(state: androidx.compose.runtime.State<AchievementState>, compact: Boolean = false,
        onBack: () -> Unit = {}, onRetry: () -> Unit = {}) {
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, if (compact) 1.5f else 1f)) {
                CalorieTheme(compact) {
                    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                        Box(Modifier.fillMaxSize()) {
                            Box((if (compact) Modifier.width(320.dp).fillMaxHeight() else Modifier.fillMaxSize()).testTag("achievement-preview")) {
                                AchievementsContent(state.value, onBack, onRetry)
                            }
                        }
                    }
                }
            }
        }
    }
    private fun scroll(tag: String) = compose.onNodeWithTag("achievements-content").performScrollToNode(hasTestTag(tag))
    private fun screenshot(name: String) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        check(instrumentation.targetContext.packageName == "pl.roseru.kalorie.validation")
        check(name in setOf("light-summary", "light-badges", "dark-large-text"))
        val path = "/data/local/tmp/calorie-v085-$name.png"
        ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("screencap -p $path")).use { it.readBytes() }
        val bytes = ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand("head -c 8 $path")).use { it.readBytes() }
        assertTrue(bytes.contentEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 13, 10, 26, 10)))
    }

    @Test fun localWitnessAndTodayProgressStaySeparateFromServerAndCorrectionRemovesWitness() {
        val result = fixture()
        val state = mutableStateOf<AchievementState>(AchievementState.Ready(result))
        show(state)
        compose.onNodeWithTag("achievement-server-state").assertTextEquals("Jeszcze nie pobrane")
        scroll("achievement-count"); compose.onNodeWithTag("achievement-count").assertTextEquals("3 / 4")
        screenshot("light-summary")
        scroll("badge-progress-in_goal_streak_10")
        compose.onNodeWithTag("badge-progress-in_goal_streak_10").assertTextEquals("10 / 10 · wstępnie")
        compose.onNodeWithTag("badge-status-in_goal_streak_10").assertTextEquals("Wstępny postęp")
        scroll("badge-dates-weight_days_4_14"); compose.onNodeWithTag("badge-dates-weight_days_4_14").performClick()
        scroll("badge-witness-weight_days_4_14")
        compose.onNodeWithTag("badge-witness-weight_days_4_14").assertTextContains("29.09.2026", substring = true)
        screenshot("light-badges")
        compose.runOnIdle {
            state.value = AchievementState.Ready(result.copy(badges = result.badges.map { if (it.code == AchievementCode.WEIGHT_DAYS)
                it.copy(progress = 3, closedProgress = 3, witness = emptyList()) else it }))
        }
        scroll("badge-progress-weight_days_4_14")
        compose.onNodeWithTag("badge-progress-weight_days_4_14").assertTextEquals("3 / 4")
        compose.onNodeWithTag("badge-witness-weight_days_4_14").assertDoesNotExist()
        scroll("achievement-count"); compose.onNodeWithTag("achievement-count").assertTextEquals("2 / 4")
    }
    @Test fun darkNarrowLargeTextKeepsEveryBadgeAndBackActionAccessible() {
        var backs = 0
        show(mutableStateOf(AchievementState.Ready(fixture())), compact = true, onBack = { backs++ })
        compose.onNodeWithTag("achievements-back").performClick(); assertEquals(1, backs)
        AchievementCode.entries.forEach { code ->
            val tag = "badge-progress-${code.wire}"
            scroll(tag); compose.onNodeWithTag(tag).assertIsDisplayed()
            val node = compose.onNodeWithTag(tag).fetchSemanticsNode()
            val root = compose.onNodeWithTag("achievement-preview").fetchSemanticsNode()
            assertTrue(node.boundsInRoot.right <= root.boundsInRoot.right + 1f)
            assertTrue(node.boundsInRoot.left >= root.boundsInRoot.left)
        }
        screenshot("dark-large-text")
    }
    @Test fun loadingAndReadFailureHaveNoInventedBadgesAndRetryDoesNotChangeServerState() {
        val state = mutableStateOf<AchievementState>(AchievementState.Loading)
        var retries = 0
        show(state, onRetry = { retries++ })
        compose.onNodeWithTag("achievement-count").assertDoesNotExist()
        compose.runOnIdle { state.value = AchievementState.Unavailable }
        scroll("achievement-retry"); compose.onNodeWithTag("achievement-retry").performClick(); assertEquals(1, retries)
        compose.onNodeWithTag("badge-complete_streak_10").assertDoesNotExist()
        compose.runOnIdle { state.value = AchievementState.Ready(Achievements.build(AchievementInput(emptyList(), emptyList(), emptySet(), emptyList()),
            Instant.parse("2026-10-12T12:00:00Z"), ZoneOffset.UTC)) }
        scroll("achievement-count"); compose.onNodeWithTag("achievement-count").assertTextEquals("0 / 4")
        scroll("achievement-server-state"); compose.onNodeWithTag("achievement-server-state").assertTextEquals("Jeszcze nie pobrane")
    }
}
