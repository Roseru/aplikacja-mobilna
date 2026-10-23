package pl.roseru.kalorie

import android.app.Application
import android.content.Intent
import androidx.compose.runtime.collectAsState
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.first
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
import pl.roseru.kalorie.photo.*
import pl.roseru.kalorie.session.*
import pl.roseru.kalorie.ui.*
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/** Full app navigation after an empty applied snapshot; Room is real, transport is synthetic. */
class FirstAccountGoalNavigationTest {
    @get:Rule val compose=createComposeRule()

    @Test fun emptyAccountCanSaveProfileThenExplicitFirstGoalWithoutGuestFallbackOrFakeAck() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val db=Room.inMemoryDatabaseBuilder(context,CalorieDatabase::class.java).addCallback(DATABASE_GUARDS).build()
        val views=ViewModelStore();val vault=SessionVault(context,"first-goal-"+UUID.randomUUID())
        val issuer="https://fixture.example/realms/first-goal";val epoch=UUID.randomUUID().toString()
        val calls=AtomicInteger()
        val auth=object:OidcGateway {
            override suspend fun discover(issuer:String):AuthorizationServiceConfiguration {calls.incrementAndGet();error("Unexpected offline discovery")}
            override fun browser(request:AuthorizationRequest):Intent {calls.incrementAndGet();error("Unexpected offline browser")}
            override suspend fun tokens(request:TokenRequest):TokenResponse {calls.incrementAndGet();error("Unexpected offline tokens")}
        }
        lateinit var diary:DiaryViewModel;lateinit var photo:MealPhotoViewModel
        try {
            val schema=CanonicalMealRows.schema(context)
            val lease=runBlocking {
                val owners=LocalOwnerStore(db);owners.ensureGuest()
                DiaryRepository(db,context,owners.currentLease()).initialize()
                val account=owners.registerIdentity(issuer,"new-empty-account")
                val lease=owners.select(account.id)
                val bootstrap=AccountBootstrapStore(db)
                bootstrap.apply(bootstrap.begin(lease),BootstrapResponse(UUID.randomUUID().toString(),epoch,1,"2026-10-23T12:00:00Z"))
                val snapshots=ServerSnapshotStore(db,SnapshotProtocol(schema));val request=snapshots.begin(lease)
                val empty=JSONObject().put("sync_epoch",epoch).put("mode","snapshot").put("snapshot_token","synthetic-first-goal")
                    .put("page_token",JSONObject.NULL).put("checkpoint","empty-account").put("server_time","2026-10-23T12:00:00Z")
                    .put("goal_timeline_revision",0).put("entities",JSONArray()).put("recovery_mappings",JSONArray()).put("operation_receipts",JSONArray())
                assertNull(snapshots.apply(request,empty.toString().toByteArray()))
                ServerDiaryStore(db,schema).apply(lease,request.runId)
                assertNull(db.dao().currentProfile(lease.storageScope))
                assertNull(db.dao().goalOn(lease.storageScope,LocalDate.now().toString()))
                assertTrue(db.serverDiaryDao().unsettled(lease.storageScope).isEmpty())
                lease
            }
            val guestBefore=runBlocking {db.dao().goalsThrough("guest",LocalDate.now().toString()).first()}
            val controller=SessionController(db,vault,auth,issuer,context.packageName)
            runBlocking {controller.start()}
            compose.runOnUiThread {
                diary=DiaryViewModel(DiaryRepository(db,context,lease),Preferences(context),SavedStateHandle())
                photo=MealPhotoViewModel(context.applicationContext as Application,MealPhotoStore(context,db,lease),SavedStateHandle())
                views.put("diary",diary);views.put("photo",photo)
            }
            compose.setContent {CalorieTheme(false){CalorieApp(diary,controller.view.collectAsState().value,SessionActions({}, {}, {}, {}, {}, {}),photo)}}
            compose.waitUntil(10_000){compose.onAllNodesWithTag("open-profile").fetchSemanticsNodes().isNotEmpty()}
            compose.onNodeWithTag("open-profile").performClick()
            compose.onNodeWithTag("profile-content").performScrollToNode(hasTestTag("profile-nickname"))
            compose.onNodeWithTag("profile-nickname").performTextInput("Nowe konto")
            compose.onNodeWithTag("profile-height").performTextInput("180")
            compose.onNodeWithTag("profile-content").performScrollToNode(hasTestTag("confirm-profile"))
            compose.onNodeWithTag("confirm-profile").assertIsEnabled().performClick()
            compose.waitUntil(10_000){runBlocking{db.dao().currentProfile(lease.storageScope)}?.nickname=="Nowe konto"}
            assertNull(runBlocking {db.dao().goalOn(lease.storageScope,LocalDate.now().toString())})
            assertTrue(runBlocking {db.serverDiaryDao().unsettled(lease.storageScope)}.none{it.entityType=="goal"})
            compose.waitUntil(5_000){compose.onAllNodesWithText("Profil zapisany na urządzeniu.").fetchSemanticsNodes().isNotEmpty()}
            val feedback=hasText("Profil zapisany na urządzeniu.")
            compose.onNode(SemanticsMatcher.keyIsDefined(SemanticsActions.Dismiss) and (feedback or hasAnyDescendant(feedback)),useUnmergedTree=true)
                .performSemanticsAction(SemanticsActions.Dismiss){dismiss->assertTrue(dismiss())}

            compose.onNodeWithText("Ustawienia").performClick()
            compose.onNodeWithTag("first-goal-hint").performScrollTo().assertExists()
            compose.onNodeWithTag("goal-kcal").performScrollTo()
            assertEquals("",compose.onNodeWithTag("goal-kcal").fetchSemanticsNode().config[SemanticsProperties.EditableText].text)
            compose.onNodeWithTag("goal-kcal").performTextInput("2450")
            compose.onNodeWithTag("goal-protein").performScrollTo().performTextInput("125,5")
            compose.onNodeWithTag("confirm-goal").performScrollTo().assertIsEnabled().performClick()
            compose.waitUntil(10_000){runBlocking{db.dao().goalOn(lease.storageScope,LocalDate.now().toString())}?.kcal==2450.0}
            val goal=runBlocking {db.dao().goalOn(lease.storageScope,LocalDate.now().toString())!!}
            assertEquals(goal.id,UUID.fromString(goal.id).toString())
            assertEquals(125.5,goal.protein!!,0.0);assertNull(goal.fat);assertNull(goal.carbs)
            assertEquals("user_decision",goal.reason);assertNull(goal.correctionOf)
            val operation=runBlocking {db.serverDiaryDao().unsettled(lease.storageScope)}.single{it.entityType=="goal"}
            assertEquals(goal.id,operation.entityId);assertEquals("pending",operation.status)
            assertEquals("sync-v1",operation.wireFormat);assertFalse(operation.attempted)
            val wire=JSONObject(operation.wireJson!!);val payload=wire.getJSONObject("payload")
            assertEquals(epoch,wire.getString("sync_epoch"));assertEquals("2450",payload.getString("energy_kcal"))
            assertEquals(0,payload.getInt("timeline_base_revision"));assertTrue(payload.isNull("correction_of"))
            assertTrue(payload.isNull("fat_g"));assertTrue(payload.isNull("carbs_g"))
            assertEquals(guestBefore,runBlocking {db.dao().goalsThrough("guest",LocalDate.now().toString()).first()})
            compose.onNodeWithTag("settings-owner-info").performScrollTo().assertTextContains("Korzystasz z profilu konta.",substring=true)
            assertEquals(0,calls.get())
        }finally{
            compose.runOnUiThread{views.clear()};vault.clear();db.close()
        }
    }
}
