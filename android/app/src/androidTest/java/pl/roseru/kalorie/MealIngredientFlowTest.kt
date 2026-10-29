package pl.roseru.kalorie

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Surface
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.MealWire
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.ui.*
import java.time.LocalDate
import java.util.UUID
import java.math.BigDecimal

class MealIngredientFlowTest {
    @get:Rule val compose=createComposeRule()
    @Test fun replacementCannotReuseTheOriginalIngredientsDensity() {
        val input=MealIngredientInput("Napój","125",QuantityUnit.GRAMS,QuantityUnit.MILLILITRES,
            ExactNutrition(BigDecimal("42"),null,null,null),ExactDensity(BigDecimal("1.25"),"etykieta napoju"))
        val item=MealItemEntity("density-ui","meal",null,"Napój",125.0,42.0,null,null,null,
            wirePayload=StrictJson.canonical(MealWire.manualIngredient("density-ui",input)))
        var saved:MealIngredientInput?=null
        compose.setContent {CalorieTheme(false){MealIngredientDialog(item,false,{},{saved=it})}}
        compose.onNodeWithTag("confirm-ingredient").assertIsEnabled()
        compose.onNodeWithTag("ingredient-name").performScrollTo().performTextReplacement("Olej")
        compose.onNodeWithTag("confirm-ingredient").assertIsNotEnabled()
        compose.onNodeWithTag("basis-unit-g").performScrollTo().performClick()
        compose.onNodeWithTag("confirm-ingredient").assertIsEnabled().performClick()
        assertEquals("Olej",saved!!.name);assertNull(saved!!.density)
        assertEquals("52.5",NutritionV1.calculate(listOf(saved!!.portion())).energy.canonical)
    }
    @Test fun savedDiaryIngredientCanBeReplacedWithNullableNutrientsAndAnotherIngredientAddedAtLargeFont() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val views=ViewModelStore();lateinit var model:DiaryViewModel
        val meal=UUID.randomUUID().toString();lateinit var item:MealItemEntity
        try {
            val lease=runBlocking {
                val owners=LocalOwnerStore(db);owners.ensureGuest();val lease=owners.currentLease()
                val repo=DiaryRepository(db,context,lease);repo.initialize()
                db.dao().insertProduct(ProductEntity("ingredient-ui-product","Original","original",100.0,1.0,2.0,3.0,100.0,"Test","Fixture",1))
                repo.add("ingredient-ui-product",100.0,MealType.LUNCH,LocalDate.of(2026,10,17),meal)
                item=db.dao().meal(meal,"guest")!!.items.single();lease
            }
            compose.runOnUiThread {
                model=DiaryViewModel(DiaryRepository(db,context,lease),Preferences(context),SavedStateHandle(mapOf("date" to "2026-10-17")))
                views.put("ingredient-flow",model)
            }
            compose.setContent {
                val density=LocalDensity.current
                CompositionLocalProvider(LocalDensity provides Density(density.density,1.5f)) {
                    CalorieTheme(false){Surface{Box(Modifier.width(320.dp).fillMaxHeight()){DiaryScreen(model,{},{})}}}
                }
            }
            compose.waitUntil(15_000){model.ready.value}
            compose.onNodeWithTag("diary-content").performScrollToNode(hasTestTag("diary-item-${item.id}"))
            compose.onNodeWithTag("diary-item-${item.id}").performClick()
            compose.onNodeWithTag("correct-ingredient").performClick()
            fun fill(tag:String,value:String){compose.onNodeWithTag("ingredient-$tag").performScrollTo().performTextReplacement(value)}
            fill("name","Napój poprawiony");fill("amount","250")
            compose.onNodeWithTag("quantity-unit-ml").performScrollTo().performClick()
            compose.onNodeWithTag("basis-unit-ml").performScrollTo().performClick()
            fill("energy","42");fill("protein","");fill("fat","0");fill("carbs","10,123456")
            compose.onNodeWithTag("ingredient-preview").performScrollTo()
                .assertTextEquals("Spożycie: 105 kcal · B brak g · T 0.0 g · W 25.3 g")
            compose.onNodeWithTag("confirm-ingredient").performClick()
            compose.waitUntil(15_000){!model.busy.value && model.day.value.meals.any {it.items.any {row->row.productName=="Napój poprawiony"}}}
            val corrected=runBlocking {db.dao().meal(meal,"guest")!!}
            assertEquals(item.id,corrected.items.single().id);assertEquals("ml",corrected.items.single().unit)
            assertEquals("105",corrected.items.single().consumed().asExact().energy.canonical)
            assertFalse(corrected.items.single().consumed().asExact().protein.complete)
            compose.onNodeWithTag("diary-content").performScrollToNode(hasTestTag("add-ingredient-$meal"))
            compose.onNodeWithTag("add-ingredient-$meal").performClick()
            fill("name","Drugi składnik");fill("amount","50");fill("energy","20")
            compose.onNodeWithTag("confirm-ingredient").performClick()
            compose.waitUntil(15_000){!model.busy.value && model.day.value.meals.singleOrNull()?.items?.size==2}
            val totals=model.day.value.totals.asExact()
            assertEquals("115",totals.energy.canonical);assertFalse(totals.protein.complete)
            assertEquals(3,runBlocking {db.dao().operationCount("guest")})
        } finally {compose.runOnUiThread {views.clear()};db.close()}
    }
}
