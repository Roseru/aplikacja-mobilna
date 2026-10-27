package pl.roseru.kalorie

import android.content.Context
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.catalog.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.ui.*

class MreRationScreenTest {
    @get:Rule val compose = createComposeRule()
    @Test fun switchingCakeKeepsOneChoiceAndUnknownManualSaveKeepsRemainingSelection() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = Room.inMemoryDatabaseBuilder(context, CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val views = ViewModelStore()
        lateinit var model: DiaryViewModel
        try {
            val repo = DiaryRepository(db, context)
            compose.runOnUiThread { model = DiaryViewModel(repo, Preferences(context), SavedStateHandle()); views.put("mre", model) }
            compose.setContent { CalorieTheme(false) { RationScreen(model) {} } }
            compose.waitUntil(15_000) { model.ready.value && model.mreCatalogue.value is MreCatalogueState.Ready && model.rations.value.size == 27 }
            val index = context.assets.open("catalog/mre2026/selection-rules.json").use { JSONObject(String(it.readBytes())) }
            val id = index.getJSONArray("menus").objects().single { it.getInt("number") == 9 }.getString("ration_id")
            val ration = model.rations.value.single { it.ration.catalogJson?.let(::JSONObject)?.optString("ration_id") == id }
            val policy = model.mreCatalogue.value.selectionFor(ration.ration.catalogJson)!!
            val cakes = ration.components.filter { policy.origins[it.position]?.nutritionStatus == "variant_profiles" }
            assertEquals(3, cakes.size)
            compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("ration-${ration.ration.id}"))
            compose.onNodeWithTag("ration-${ration.ration.id}").performClick()
            fun click(part: RationComponentEntity) {
                compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("ration-check-${part.id}"))
                compose.onNodeWithTag("ration-check-${part.id}").performClick()
            }
            click(cakes[0]); click(cakes[1])
            compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("ration-check-${cakes[0].id}"))
            compose.onNodeWithTag("ration-check-${cakes[0].id}").assertIsOff()
            val missing = policy.missing.first { !it.equipment }
            compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("mre-manual-${missing.locator}"))
            compose.onNodeWithTag("mre-manual-${missing.locator}").performClick()
            compose.onNodeWithTag("mre-unknown-grams").performTextInput("2,5")
            compose.onNodeWithTag("mre-unknown-grams").performImeAction()
            compose.onNodeWithTag("mre-unknown-save").performClick()
            compose.waitUntil(10_000) { model.uncertainMreSaveVersion.value == 1 }
            compose.onNodeWithTag("mre-unknown-save").assertDoesNotExist()
            compose.onNodeWithTag("ration-content").performScrollToNode(hasTestTag("ration-check-${cakes[1].id}"))
            compose.onNodeWithTag("ration-check-${cakes[1].id}").assertIsOn()
            compose.onNodeWithTag("confirm-ration").performClick()
            val meals = runBlocking { withTimeout(10_000) { db.dao().day(DiaryRepository.GUEST, model.day.value.date.toString()).first { it.size == 2 } } }
            assertEquals(1, meals.count { it.meal.rationId == ration.ration.id })
            assertEquals(1, meals.flatMap { it.items }.sumOf { it.consumed().asExact().energy.missingCount })
            assertEquals(2, runBlocking { db.dao().operationCount(DiaryRepository.GUEST) })
        } finally { compose.runOnUiThread { views.clear() }; db.close() }
    }
}
