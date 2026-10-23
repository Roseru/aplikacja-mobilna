package pl.roseru.kalorie

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.importing.*
import pl.roseru.kalorie.ui.ImportContent

class ImportScreenTest {
    @get:Rule val compose=createComposeRule()
    private fun progress()=ImportProgress("plan","account","https://fixture.example/realms/full-import","exact-full-subject-with-no-truncation",
        "draft",1,0,0,0,emptyList(),pending=1)
    private fun render(state:ImportUiState,approved:(Boolean)->Unit={},kept:(ImportDecisionRow)->Unit={},corrected:(ImportDecisionRow,Map<String,String>,Boolean)->Unit={_,_,_->},serverChoice:(ImportDecisionRow)->Unit={}) {
        compose.setContent {MaterialTheme {ImportContent(state,{}, {}, {}, {}, {},approved,{}, {}, {}, {}, {},kept,{},serverChoice,{}, {}, {},corrected,{_,_->},{})}}
    }
    @Test fun previewDoesNotGrantConsentAndShowsCompleteTargetIdentity() {
        var approval=false
        render(ImportUiState(plan=progress()),approved={approval=it})
        compose.onNodeWithTag("import-target-subject").assertTextEquals("Identyfikator konta u dostawcy: exact-full-subject-with-no-truncation")
        compose.onNodeWithTag("import-target-issuer").assertTextEquals("Dostawca: https://fixture.example/realms/full-import")
        compose.onNodeWithTag("import-approve").performScrollTo().assertIsNotEnabled()
        compose.runOnIdle {assertFalse(approval)}
        compose.onNodeWithTag("import-consent").performScrollTo().performClick()
        compose.onNodeWithTag("import-approve").performScrollTo().assertIsEnabled().performClick()
        compose.runOnIdle {assertTrue(approval)}
    }
    private fun source():ImportSource {
        val row=JSONObject().put("id","old-weight").put("kg","1.234567890123").put("localDate","2001-01-02")
            .put("occurredAt","2001-01-02T12:00:00Z").put("zoneId","UTC")
        val root=JSONObject().put("row",row).put("items",JSONArray()).put("outboxes",JSONArray())
        return ImportSource("plan","weight","old-weight",0,root.toString(),"bound-source-hash","[]","local","wire",state="decision",decisionCode="precision_review")
    }
    @Test fun precisionSourceAndExplicitDerivativeAreSeparateAndConsentIsRequired() {
        val source=source();val form=LegacyImportForm.from(source)
        val row=ImportDecisionRow(source,"precision_review",form,null,false)
        var saved:Map<String,String>?=null
        render(ImportUiState(plan=progress().copy(state="decisions",pending=0),approved=true,rows=listOf(row)),corrected={_,values,_->saved=values})
        compose.onNodeWithText("Sprawdź i uzupełnij dane").performScrollTo().performClick()
        val kg=form.fields.single {it.key=="row:kg"}
        compose.onNodeWithText("Źródło · ${kg.label}: 1.234567890123").performScrollTo().assertExists()
        compose.onNodeWithText("Zapisz świadomą korektę").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithTag("import-field:row:kg").performScrollTo().performTextReplacement("1.234567")
        // The checkbox and its explanatory text are sibling semantics.
        compose.onAllNodes(isToggleable()).onLast().performScrollTo().performClick()
        compose.onNodeWithText("Zapisz świadomą korektę").performScrollTo().performClick()
        compose.runOnIdle {assertEquals("1.234567",saved!!["row:kg"]);assertTrue(source.sourceJson.contains("1.234567890123"))}
    }
    @Test fun knownAbsenceHasNoAutomaticServerChoiceOrRecreation() {
        val source=source().copy(sourceEpoch="epoch",state="decision")
        val row=ImportDecisionRow(source,"absent_same_epoch",null,null,true,server=ImportComparisonSide(ImportSideState.ABSENT),proofRunId="verified-full")
        var count=0
        render(ImportUiState(plan=progress().copy(state="decisions"),approved=true,recovery=true,rows=listOf(row)),kept={count++})
        compose.onNodeWithText("Odtwórz brakujący wpis jako nowy").assertDoesNotExist()
        compose.onNodeWithText("Ponów pierwotną operację").assertDoesNotExist()
        compose.runOnIdle {assertEquals(0,count)}
        compose.onNodeWithText("Zachowaj lokalnie bez wysyłania").performScrollTo().performClick()
        compose.runOnIdle {assertEquals(1,count)}
    }
    @Test fun queuedAndNotConfiguredAreNotPresentedAsCompleted() {
        render(ImportUiState(plan=progress().copy(state="running",pending=0,queued=1),approved=true,message="Połączenie synchronizacji nie jest skonfigurowane."))
        compose.onNodeWithTag("import-complete").assertDoesNotExist()
        compose.onNodeWithTag("import-progress").assertTextContains("W kolejce: 1. Potwierdzone: 0.",substring=true)
        compose.onNodeWithTag("import-message").assertTextEquals("Połączenie synchronizacji nie jest skonfigurowane.")
    }
    @Test fun laterLocalIntentRequiresExplicitChoiceBeforeFinishing() {
        val root=JSONObject(source().sourceJson);root.getJSONObject("row").put("kg","82")
        val source=source().copy(sourceJson=root.toString(),sourceEpoch="epoch",state="decision",operationId="original-acked")
        val server=JSONObject().put("weight_kg","80").put("local_date","2001-01-02").put("occurred_at","2001-01-02T12:00:00Z").put("time_zone","UTC")
        val row=ImportDecisionRow(source,"later_local_intent",null,null,true,local=ImportComparison.local(source),
            server=ImportComparison.server("weight",server.toString()),proofRunId="verified-full")
        var accepted=0
        render(ImportUiState(plan=progress().copy(state="decisions",pending=0),approved=true,recovery=true,rows=listOf(row)),serverChoice={accepted++})
        compose.onNodeWithText("Wersja lokalna").performScrollTo().assertExists()
        compose.onNodeWithText("Masa ciała: 82 kg").performScrollTo().assertExists()
        compose.onNodeWithText("Aktualna wersja serwera").performScrollTo().assertExists()
        compose.onNodeWithText("Masa ciała: 80 kg").performScrollTo().assertExists()
        compose.runOnIdle {assertEquals(0,accepted)}
        compose.onNodeWithText("Sprawdź i zakończ uzgodnienie").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText("Przyjmij stan serwera").performScrollTo().performClick()
        compose.runOnIdle {assertEquals(1,accepted)}
    }    @Test fun unavailableServerProofIsNeitherAbsenceNorPermissionToAcceptServer() {
        val row=ImportDecisionRow(source().copy(sourceEpoch="epoch"),"same_epoch_review",null,null,true)
        render(ImportUiState(plan=progress().copy(state="decisions",pending=0),approved=true,recovery=true,rows=listOf(row)))
        compose.onNodeWithText("Brak aktualnego dowodu. Pobierz pełną kopię przed decyzją.").performScrollTo().assertExists()
        compose.onNodeWithText("Brak wpisu w zweryfikowanej pełnej kopii").assertDoesNotExist()
        compose.onNodeWithText("Przyjmij stan serwera").performScrollTo().assertIsNotEnabled()
    }}
