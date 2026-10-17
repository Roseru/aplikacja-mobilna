package pl.roseru.kalorie

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Surface
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.MealWire
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.ui.*

class CanonicalDiaryScreenTest {
    @get:Rule val compose=createComposeRule()
    @Test fun unspecifiedMealAndMissingEnergyRemainVisibleAndExactQuantityEditPersistsAtLargeFont() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        check(context.packageName=="pl.roseru.kalorie.validation")
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val views=ViewModelStore();lateinit var model:DiaryViewModel
        try {
            val payload=JSONObject(InstrumentationRegistry.getInstrumentation().context.assets.open("corrected-meal-confirm.json").bufferedReader().use {it.readText()}).getJSONObject("meal").getJSONObject("payload")
            val item=payload.getJSONArray("items").getJSONObject(0);item.getJSONObject("quantity").put("unit","ml");item.put("basis_unit","ml")
            item.getJSONObject("nutrition_per_100").put("energy_kcal",JSONObject.NULL)
            val id="11111111-1111-4111-8111-111111111111";val itemId=item.getString("item_id")
            val lease=runBlocking {LocalOwnerStore(db).ensureGuest();LocalOwnerStore(db).currentLease()}
            val wire=MealWire.read(StrictJson.canonical(payload),CanonicalMealRows.schema(context))
            val binding=AccountBindingEntity("guest","44444444-4444-4444-8444-444444444444",1,"55555555-5555-4555-8555-555555555555","",1,false)
            runBlocking {
                db.bootstrapDao().insert(binding)
                db.dao().insertMeal(CanonicalMealRows.meal(id,"guest",wire,CanonicalMealRows.context(binding)))
                CanonicalMealRows.items(id,wire).forEach {db.dao().insertItem(it)}
            }
            compose.runOnUiThread {
                model=DiaryViewModel(DiaryRepository(db,context,lease),Preferences(context),SavedStateHandle(mapOf("date" to "2026-10-17")))
                views.put("canonical-diary",model)
            }
            compose.setContent {
                val density=LocalDensity.current
                CompositionLocalProvider(LocalDensity provides Density(density.density,1.5f)) {
                    CalorieTheme(true){Surface{Box(Modifier.width(320.dp).fillMaxHeight()){DiaryScreen(model,{},{})}}}
                }
            }
            compose.waitUntil(15_000){model.ready.value}
            compose.onNodeWithTag("diary-content").performScrollToNode(hasTestTag("diary-item-$itemId"))
            compose.onNodeWithText("Pozostałe").assertIsDisplayed()
            compose.onNodeWithText("Posiłek ze zdjęcia").assertIsDisplayed()
            compose.onNodeWithText("150,5 ml",substring=true).assertIsDisplayed()
            compose.onNodeWithTag("diary-item-$itemId").performClick()
            compose.onNodeWithTag("edit-amount").performTextReplacement("125,000001")
            compose.onNodeWithTag("confirm-edit-item").performClick()
            compose.waitUntil(15_000){!model.busy.value && model.day.value.meals.any {m->m.items.any {it.amountText=="125.000001"}}}
            val saved=runBlocking {db.dao().meal(id,"guest")!!};assertEquals("125.000001",saved.items.single().amountText)
            assertFalse(saved.items.single().consumed().asExact().energy.complete)
            compose.waitForIdle()
            InstrumentationRegistry.getInstrumentation().waitForIdleSync()
            val path="/data/local/tmp/calorie-v0819-canonical-diary.png"
            android.os.ParcelFileDescriptor.AutoCloseInputStream(InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand("screencap -p $path")).use {it.readBytes()}
        } finally {compose.runOnUiThread {views.clear()};db.close()}
    }
}
