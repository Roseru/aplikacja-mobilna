package pl.roseru.kalorie

import android.app.Application
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.SavedStateHandle
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.photo.*
import pl.roseru.kalorie.ui.MealPhotoScreen
import java.time.LocalDate

class MealPhotoAdaptiveTest {
    @get:Rule val compose=createComposeRule()
    @Test fun narrowPhotoScreenWithLargeTextKeepsCameraGalleryAndManualFallbackReachable() {
        val app=InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as Application
        val db=Room.inMemoryDatabaseBuilder(app,CalorieDatabase::class.java).build()
        try {
            val lease=runBlocking { LocalOwnerStore(db).ensureGuest();LocalOwnerStore(db).currentLease() }
            val model=MealPhotoViewModel(app,MealPhotoStore(app,db,lease),SavedStateHandle())
            var manual=false
            compose.setContent {
                val density=LocalDensity.current
                CompositionLocalProvider(LocalDensity provides Density(density.density,1.5f)) {
                    MaterialTheme { Box(Modifier.width(320.dp)) { MealPhotoScreen(model,LocalDate.of(2026,10,13),{}, {manual=true}) } }
                }
            }
            compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-gallery"))
            compose.onNodeWithTag("photo-gallery").assertIsDisplayed().assertIsEnabled()
            compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-camera"))
            compose.onNodeWithTag("photo-camera").assertIsDisplayed().assertIsEnabled()
            compose.onNodeWithTag("photo-content").performScrollToNode(hasTestTag("photo-manual"))
            compose.onNodeWithTag("photo-manual").performClick()
            assertTrue(manual)
            assertEquals(0,runBlocking { db.dao().operationCount(lease.storageScope) })
        } finally { db.close() }
    }
}
