package pl.roseru.kalorie

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.core.network.NetworkAccessState
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.energy.*
import pl.roseru.kalorie.ui.CalorieTheme
import pl.roseru.kalorie.ui.EnergyScreen
import java.util.UUID

/** Physical Compose + real ViewModels/Room, with an explicit synthetic API/session boundary. */
class EnergyNavigationTest {
    @get:Rule val compose=createComposeRule()
    private fun node(tag:String):SemanticsNodeInteraction {
        compose.onNodeWithTag("energy-content").performScrollToNode(hasTestTag(tag))
        return compose.onNodeWithTag(tag).performScrollTo()
    }
    @Test fun noticeAndReviewAreExplicitAndAcceptedELeavesFoodGoalAndAutomaticAffirmationUntouched() {
        val name="energy-ui-${UUID.randomUUID()}";val db=EnergyFixture.database(name)
        val models=ViewModelStore()
        try {
            val scope=runBlocking {EnergyFixture.account(db)}
            val id=UUID.randomUUID().toString()
            runBlocking {DiaryRepository(db,EnergyFixture.context,scope.lease).setGoal(2500.0,null,null,null,id)}
            val original=runBlocking {db.dao().goalById(scope.lease.storageScope,id)}
            val server=EnergyFixture.Server()
            val repository=EnergyFixture.repository(db,scope,server)
            val model=EnergyViewModel(repository,scope.lease)
            val diary=DiaryViewModel(DiaryRepository(db,EnergyFixture.context,scope.lease),Preferences(EnergyFixture.context),SavedStateHandle())
            models.put("energy",model);models.put("diary",diary)
            val session=EnergyFixture.Sessions(db,scope).view.value
            compose.setContent {CalorieTheme(false) {EnergyScreen(model,diary,session,NetworkAccessState.Allowed(1),onBack={},onAccount={},
                now={EnergyFixture.instant.toEpochMilli()})}}
            compose.waitUntil(20_000){model.state.value.loaded && !model.state.value.busy}
            assertTrue(server.requests.isEmpty())
            node("energy-create").assertIsNotEnabled()
            node("energy-refresh").performClick()
            compose.waitUntil(20_000){model.state.value.local?.axis!=null && !model.state.value.busy}
            node("energy-create").assertIsNotEnabled()
            node("energy-qualified").performClick()
            node("energy-analysis-notice").performClick()
            assertTrue(server.requests.none {it.second!=null})
            node("energy-create").assertIsEnabled().performClick()
            assertTrue(server.requests.none {it.second!=null})
            compose.onNodeWithTag("energy-confirm").performClick()
            compose.waitUntil(20_000){model.state.value.local?.analyses?.isNotEmpty()==true && !model.state.value.busy}
            assertEquals(1,server.admissions)
            val analysisId=EnergyFixture.sample("analysis").getString("id")
            node("energy-analysis-$analysisId").performClick()
            node("energy-accept").assertIsEnabled().performClick()
            assertEquals(original,runBlocking {db.dao().goalById(scope.lease.storageScope,id)})
            compose.onNodeWithTag("energy-confirm").performClick()
            compose.waitUntil(20_000){model.state.value.local?.axis?.axisRevision==4 && !model.state.value.busy}
            assertEquals(original,runBlocking {db.dao().goalById(scope.lease.storageScope,id)})
            assertEquals(listOf("/me/energy/analyses","/me/energy/analyses/accept"),server.requests.filter {it.second!=null}.map {it.first})
            assertEquals(2,server.requests.filter {it.second!=null}.map {it.second}.distinct().size)
            assertFalse(model.state.value.automaticEffective)
            assertEquals("2500",runBlocking {db.dao().goalById(scope.lease.storageScope,id)}!!.kcal.toBigDecimal().stripTrailingZeros().toPlainString())
            compose.onNodeWithContentDescription("Wróć").performClick()
            node("energy-tab-history").performClick()
            compose.onNodeWithText("Wersja planowana").assertExists()
            node("energy-current").assertTextContains("3204",substring=true)
            assertTrue(server.requests.none {it.first=="/me/energy/affirm" || it.first=="/me/consents"})
        }finally {
            compose.runOnIdle {models.clear()}
            db.close();EnergyFixture.context.deleteDatabase(name)
        }
    }
}
