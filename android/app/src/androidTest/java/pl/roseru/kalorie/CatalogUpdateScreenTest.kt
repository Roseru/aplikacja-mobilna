package pl.roseru.kalorie

import android.content.Context
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.catalogupdate.*
import pl.roseru.kalorie.core.network.*
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.ui.*
import java.io.File
import java.util.UUID

/** Real Settings, lifecycle models, DataStore and Room; the public download is synthetic. */
class CatalogUpdateScreenTest {
    @get:Rule val compose=createComposeRule()
    @Test fun guestCanInspectSourcesWhileBlockedThenExplicitlyEnableAndDownloadWithoutDiaryMutation() {
        val context=ApplicationProvider.getApplicationContext<Context>()
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val folder=File(context.cacheDir,"catalog-screen-${UUID.randomUUID()}").apply{mkdirs()}
        val preferenceContext=CatalogUpdateFixtures.PreferenceContext(context)
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
        val store=PreferenceDataStoreFactory.create(scope=scope,produceFile={File(folder,"device.preferences_pb")})
        val policy=DeviceNetworkPolicy(store,scope)
        val gateway=CatalogUpdateFixtures.Gateway(CatalogUpdateFixtures.official(context))
        val catalogRepository=CatalogUpdateRepository(db,CatalogUpdateFixtures.schema(context),gateway,policy,
            File(folder,"downloads"),PreferencesCatalogRetryStore(preferenceContext))
        val views=ViewModelStore()
        lateinit var diary:DiaryViewModel
        lateinit var catalog:CatalogUpdateViewModel
        lateinit var network:NetworkPolicyViewModel
        try {
            val lease=runBlocking{LocalOwnerStore(db).also{it.ensureGuest()}.currentLease()}
            compose.runOnUiThread {
                diary=DiaryViewModel(DiaryRepository(db,context,lease),Preferences(context),SavedStateHandle())
                catalog=CatalogUpdateViewModel(catalogRepository);network=NetworkPolicyViewModel(policy)
                views.put("diary",diary);views.put("catalog",catalog);views.put("network",network)
            }
            compose.setContent{CalorieTheme(false){SettingsScreen(diary,catalog,network)}}
            compose.waitUntil(10_000){diary.ready.value && catalog.state.value.networkAllowed && catalog.state.value.installed.isNotEmpty()}
            val original=CatalogUpdateFixtures.privateRows(db)
            compose.onNodeWithTag("field-mode-switch").performScrollTo().performClick()
            compose.waitUntil(10_000){policy.state.value==NetworkAccessState.Blocked && !network.state.value.saving}
            compose.onNodeWithTag("catalog-check").performScrollTo().assertIsNotEnabled()
            compose.onNodeWithTag("catalog-sources-demo").performScrollTo().assertIsEnabled().performClick()
            compose.waitUntil(10_000){compose.onAllNodesWithText("Szczegóły źródła").fetchSemanticsNodes().isNotEmpty()}
            compose.onNodeWithText("Szczegóły źródła").performClick()
            compose.onNodeWithTag("catalog-source-detail").assertExists()
            compose.onNodeWithText("Wróć do listy źródeł").performClick()
            compose.onNodeWithText("Zamknij źródła").performClick()
            compose.onNodeWithTag("catalog-sources-mre").performScrollTo().assertIsEnabled().performClick()
            compose.waitUntil(10_000){compose.onAllNodesWithText("Szczegóły źródła").fetchSemanticsNodes().isNotEmpty()}
            compose.onNodeWithText("MRE 2026 · źródła v1").assertExists()
            compose.onAllNodesWithText("Szczegóły źródła")[0].performClick()
            compose.onNodeWithTag("catalog-source-detail").assertExists()
            compose.onNodeWithText("Wróć do listy źródeł").performClick()
            compose.onNodeWithText("Zamknij źródła").performClick()
            assertEquals(0,gateway.checks.get());assertEquals(0,gateway.downloads.get())
            compose.onNodeWithTag("field-mode-switch").performScrollTo().performClick()
            compose.waitUntil(10_000){policy.state.value is NetworkAccessState.Allowed && !network.state.value.saving && catalog.state.value.networkAllowed}
            compose.onNodeWithTag("catalog-check").performScrollTo().assertIsEnabled().performClick()
            compose.waitUntil(10_000){catalog.state.value.phase==CatalogUpdatePhase.AVAILABLE}
            compose.onNodeWithTag("catalog-download").performScrollTo().assertIsEnabled().performClick()
            compose.waitUntil(10_000){catalog.state.value.phase==CatalogUpdatePhase.INSTALLED && catalog.state.value.installed.any{it is InstalledCatalog.Ready && it.manifest.kind=="official"}}
            compose.onNodeWithTag("catalog-local-official").performScrollTo().assertExists()
            assertEquals(1,gateway.checks.get());assertEquals(1,gateway.downloads.get())
            assertEquals(original,CatalogUpdateFixtures.privateRows(db))
        }finally {
            compose.runOnUiThread{views.clear()}
            runBlocking{scope.coroutineContext.job.cancelAndJoin()}
            db.close();preferenceContext.clear();folder.deleteRecursively()
        }
    }
}
