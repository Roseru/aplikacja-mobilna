package pl.roseru.kalorie

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.PhotoAnalysisSnapshot
import pl.roseru.kalorie.session.PhotoAnalysisPreview
import pl.roseru.kalorie.ui.CalorieTheme
import pl.roseru.kalorie.ui.PhotoAnalysisPanel

class PhotoAnalysisFailureScreenTest {
    @get:Rule val compose = createComposeRule()

    private fun preview(state: String = "failed", code: String = "provider_result_unknown"): PhotoAnalysisPreview {
        val assets = InstrumentationRegistry.getInstrumentation().context.assets
        val ack = assets.open("create-accepted.json").bufferedReader().use { it.readText() }
        val payload = JSONObject(assets.open("analysis-read-succeeded.json").bufferedReader().use { it.readText() })
        payload.put("state", state).put("proposal", JSONObject.NULL)
            .put("error_code", if (state == "failed") code else JSONObject.NULL)
        return PhotoAnalysisPreview.from(PhotoAnalysisSnapshot.read(ack, "mock")
            .withRead(payload.toString().toByteArray(Charsets.UTF_8)).latest!!)
    }

    @Composable private fun Panel(result: PhotoAnalysisPreview, manual: () -> Unit) {
        val density = LocalDensity.current
        CompositionLocalProvider(LocalDensity provides Density(density.density, 1.5f)) {
            CalorieTheme(true) { Surface {
                Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                    PhotoAnalysisPanel(result, onManual = manual)
                }
            } }
        }
    }

    @Test fun unknownResultHasExplicitLocalFallbackWithoutImplicitActionOrEstimatedCalories() {
        var manual = 0
        compose.setContent { Panel(preview()) { manual++ } }
        compose.onNodeWithTag("photo-analysis-title").assertTextEquals("Analiza bez propozycji")
        compose.onNodeWithTag("photo-analysis-state").assertTextContains("nie będzie automatycznie ponawiane", substring = true)
        compose.onNodeWithTag("photo-analysis-total").assertDoesNotExist()
        compose.runOnIdle { assertEquals(0, manual) }
        // This callback only opens the existing local editor. No session/network dependency.
        compose.onNodeWithTag("photo-analysis-manual").performScrollTo().assertIsEnabled().performClick()
        compose.runOnIdle { assertEquals(1, manual) }
    }

    @Test fun unknownServerCodeIsNotShownAndChangingResultRemovesStaleFailureAction() {
        val result = mutableStateOf(preview(code = "future_private_provider_detail"))
        var manual = 0
        compose.setContent { Panel(result.value) { manual++ } }
        compose.onNodeWithText("future_private_provider_detail", substring = true).assertDoesNotExist()
        compose.onNodeWithTag("photo-analysis-state").assertTextContains("poprawnej propozycji", substring = true)
        compose.runOnIdle { result.value = preview(state = "queued") }
        compose.onNodeWithTag("photo-analysis-title").assertTextEquals("Oczekiwanie na analizę")
        compose.onNodeWithTag("photo-analysis-manual").assertDoesNotExist()
        compose.onNodeWithText("poprawnej propozycji", substring = true).assertDoesNotExist()
        compose.runOnIdle { assertEquals(0, manual) }
    }
}
