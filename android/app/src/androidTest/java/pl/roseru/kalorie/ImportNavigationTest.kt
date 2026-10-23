package pl.roseru.kalorie

import android.app.Application
import android.content.Intent
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import net.openid.appauth.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.BootstrapResponse
import pl.roseru.kalorie.core.sync.SnapshotProtocol
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.importing.ImportViewModel
import pl.roseru.kalorie.photo.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.*
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Real app navigation/models/controller + Room; offline preview/import never invokes auth or HTTP. */
class ImportNavigationTest {
    @get:Rule val compose=createComposeRule()
    @Test fun accountNavigationShowsFullTargetAndRequiresConsentBeforeQueuingGuestWithoutFalseAck() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val views=ViewModelStore();val vault=SessionVault(context,"import-nav-"+UUID.randomUUID())
        val issuer="https://fixture.example/realms/navigation-import";val subject="synthetic-complete-subject-without-truncation"
        val epoch="55555555-5555-4555-8555-555555555555";val calls=AtomicInteger()
        val auth=object:OidcGateway {
            override suspend fun discover(issuer:String):AuthorizationServiceConfiguration {calls.incrementAndGet();error("Unexpected offline discovery")}
            override fun browser(request:AuthorizationRequest):Intent {calls.incrementAndGet();error("Unexpected offline browser")}
            override suspend fun tokens(request:TokenRequest):TokenResponse {calls.incrementAndGet();error("Unexpected offline tokens")}
        }
        lateinit var importModel:ImportViewModel;lateinit var diary:DiaryViewModel;lateinit var photo:MealPhotoViewModel
        try {
            val schema=CanonicalMealRows.schema(context)
            val lease=runBlocking {
                val owners=LocalOwnerStore(db);owners.ensureGuest()
                db.dao().saveWeight(WeightEntity("historical-guest-weight","guest","2001-01-02","2001-01-02T12:00:00Z","UTC",80.125))
                val lease=owners.select(owners.registerIdentity(issuer,subject).id)
                val boot=AccountBootstrapStore(db);boot.apply(boot.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),epoch,1,"2026-10-23T12:00:00Z"))
                val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema))
                val page=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-nav")
                    .put("page_token",JSONObject.NULL).put("checkpoint","synthetic-checkpoint").put("server_time","2026-10-23T12:00:00Z")
                    .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
                snapshots.apply(snapshots.begin(lease),page.toString().toByteArray());lease
            }
            val controller=SessionController(db,vault,auth,issuer,context.packageName,reconciliationStore=ReconciliationStore(db,schema))
            runBlocking {controller.start()}
            compose.runOnUiThread {
                diary=DiaryViewModel(DiaryRepository(db,context,lease),Preferences(context),SavedStateHandle())
                photo=MealPhotoViewModel(context.applicationContext as Application,MealPhotoStore(context,db,lease),SavedStateHandle())
                importModel=ImportViewModel(db,schema,lease,controller,SavedStateHandle())
                views.put("diary",diary);views.put("photo",photo);views.put("import",importModel)
            }
            val original=runBlocking {db.dao().weight("historical-guest-weight","guest")!!}
            val actions=SessionActions({}, {}, {}, {}, {}, {})
            compose.setContent {
                val session by controller.view.collectAsState()
                CalorieTheme(false) {CalorieApp(diary,session,actions,photo,importModel)}
            }
            compose.waitUntil(10_000){compose.onAllNodesWithTag("open-profile").fetchSemanticsNodes().isNotEmpty()}
            compose.onNodeWithTag("open-profile").performClick()
            compose.onNodeWithTag("open-account").performScrollTo().performClick()
            compose.onNodeWithTag("session-import").performScrollTo().assertIsEnabled().performClick()
            compose.onNodeWithText("Przejrzyj dane gościa").performScrollTo().performClick()
            compose.waitUntil(10_000){!importModel.state.value.busy && importModel.state.value.plan!=null}
            compose.onNodeWithTag("import-target-issuer").performScrollTo().assertTextEquals("Dostawca: $issuer")
            compose.onNodeWithTag("import-target-subject").performScrollTo().assertTextEquals("Identyfikator konta u dostawcy: $subject")
            val plan=importModel.state.value.plan!!
            assertEquals(0,runBlocking {db.dao().operationCount(lease.storageScope)})
            compose.onNodeWithTag("import-approve").performScrollTo().assertIsNotEnabled()
            compose.onNodeWithTag("import-consent").performScrollTo().performClick()
            compose.onNodeWithTag("import-approve").performScrollTo().assertIsEnabled().performClick()
            compose.waitUntil(10_000){!importModel.state.value.busy && importModel.state.value.approved}
            compose.onNodeWithText("Przetwórz kolejną porcję").performScrollTo().performClick()
            compose.waitUntil(10_000){!importModel.state.value.busy && importModel.state.value.plan?.queued==1}
            compose.onNodeWithTag("import-not-configured").performScrollTo().assertExists()
            assertEquals(0,importModel.state.value.plan!!.acknowledged)
            val queue=runBlocking {db.serverDiaryDao().unsettled(lease.storageScope)}
            assertEquals(1,queue.size);assertEquals("pending",queue.single().status)
            assertEquals("80.125",JSONObject(queue.single().payload).getString("weight_kg"))
            assertEquals(original,runBlocking {db.dao().weight(original.id,"guest")})
            assertNotNull(runBlocking {db.importDao().source(plan.planId,"weight",original.id)})
            assertEquals(0,calls.get())
            compose.onNodeWithText("Wróć do konta").performScrollTo().performClick()
            compose.onNodeWithTag("session-owner").assertExists()
        }finally{
            compose.runOnUiThread {views.clear()};vault.clear();db.close()
        }
    }
}
