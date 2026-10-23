package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.importing.*

/** Decisions use normal fields. Source identifiers and serialized envelopes remain internal. */
@Composable fun ImportScreen(model:ImportViewModel,back:()->Unit,sendOrdinary:()->Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    ImportContent(state,back,model::refresh,model::previewGuest,model::previewOwn,model::selectPlan,model::approve,
        model::resume,model::downloadProof,model::sendApproved,model::finish,model::more,model::keep,model::separateCopy,
        model::acceptServer,model::replay,model::recreate,model::resolveMapped,model::correct,model::newGoal,sendOrdinary)
}

@Composable internal fun ImportContent(state:ImportUiState,back:()->Unit,refresh:()->Unit,guest:()->Unit,own:()->Unit,
    select:(String)->Unit,approve:(Boolean)->Unit,resume:()->Unit,proof:()->Unit,push:()->Unit,finish:()->Unit,more:()->Unit,
    keep:(ImportDecisionRow)->Unit,copy:(ImportDecisionRow)->Unit,server:(ImportDecisionRow)->Unit,replay:(ImportDecisionRow)->Unit,
    recreate:(ImportDecisionRow)->Unit,mapped:(ImportDecisionRow)->Unit,
    correct:(ImportDecisionRow,Map<String,String>,Boolean)->Unit,newGoal:(ImportDecisionRow,Map<String,String>)->Unit,sendOrdinary:()->Unit) {
    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(20.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
        TextButton(onClick=back){Text("Wróć do konta")}
        Text("Import i uzgadnianie",style=MaterialTheme.typography.headlineLarge)
        Text("Oryginały pozostają na urządzeniu. Zapisanie planu lub dodanie do kolejki nie oznacza potwierdzenia przez serwer.")
        if(state.busy)LinearProgressIndicator(Modifier.fillMaxWidth())
        state.message?.let {Text(it,Modifier.testTag("import-message"))}
        OutlinedButton(onClick=refresh,enabled=!state.busy){Text("Odśwież postęp")}
        if(state.requiresRecovery) {
            Text("Zmienił się stan synchronizacji. Najpierw uzgodnij kopię tego konta; import gościa będzie dostępny po uzgodnieniu.")
            Button(onClick=own,enabled=!state.busy){Text("Przygotuj uzgodnienie konta")}
        } else {
            Button(onClick=guest,enabled=!state.busy){Text("Przejrzyj dane gościa")}
            OutlinedButton(onClick=own,enabled=!state.busy){Text("Przejrzyj starsze dane tego konta")}
        }
        if(state.plans.size>1) {
            Text("Zapisane plany",style=MaterialTheme.typography.titleMedium)
            state.plans.forEachIndexed {index,plan->
                TextButton(onClick={select(plan.id)},enabled=!state.busy){Text("${when(plan.kind){"guest"->"Gość";"legacy"->"Starsze dane konta";else->"Uzgodnienie"}} · plan ${index+1} · ${plan.date}")}
            }
        }
        val plan=state.plan
        if(plan!=null) {
            HorizontalDivider()
            Text("Konto docelowe",style=MaterialTheme.typography.titleLarge)
            Text("Dostawca: ${plan.issuer}",Modifier.testTag("import-target-issuer"))
            Text("Identyfikator konta u dostawcy: ${plan.subject}",Modifier.testTag("import-target-subject"))
            Text("Łącznie: ${plan.total}. Gotowe do przetworzenia: ${plan.pending}. W kolejce: ${plan.queued}. Potwierdzone: ${plan.acknowledged}. Zachowane lokalnie: ${plan.retained}. Wcześniej przypisane: ${plan.alreadyImported}. Czekają na powiązany wpis: ${plan.waiting}.",Modifier.testTag("import-progress"))
            Text("Decyzje: ${plan.decisions.size}")
            if(!state.approved) {
                var consent by rememberSaveable(plan.planId){mutableStateOf(false)}
                Row {
                    Checkbox(consent,{consent=it},enabled=!state.busy,modifier=Modifier.testTag("import-consent"))
                    Text(if(state.recovery)"Potwierdzam uzgadnianie danych tego konta. Każdą niepewną zmianę rozstrzygnę osobno."
                        else "Potwierdzam przypisanie tych danych do wskazanego konta. Danych gościa nie będzie można przypisać do innego konta.")
                }
                Button(onClick={approve(consent)},enabled=consent && !state.busy,modifier=Modifier.testTag("import-approve")){Text("Zatwierdź konto i plan")}
            } else if(state.recovery && plan.state!="complete") {
                Text("Pobrane części dowodów: ${state.provedGroups}/${state.proofGroups}")
                OutlinedButton(onClick=proof,enabled=!state.busy){Text("Pobierz pełną kopię i dowody operacji")}
                Text("Po decyzjach wyślij zatwierdzone zmiany, a następnie ponownie pobierz pełną kopię. Uzgodnienie zakończy się po sprawdzeniu potwierdzeń.")
                Button(onClick=push,enabled=!state.busy && (plan.pending>0 || plan.queued>0)){Text("Wyślij zatwierdzone decyzje")}
                OutlinedButton(onClick=finish,enabled=!state.busy && state.rows.isEmpty() && plan.pending==0 && plan.queued==0 && plan.waiting==0 && state.provedGroups==state.proofGroups){Text("Sprawdź i zakończ uzgodnienie")}
            } else if(plan.state!="complete") {
                Button(onClick=resume,enabled=!state.busy && (plan.pending>0 || plan.waiting>0)){Text("Przetwórz kolejną porcję")}
                OutlinedButton(onClick=sendOrdinary,enabled=!state.busy && plan.queued>0){Text("Wyślij kolejkę konta")}
            }
            if(plan.state=="complete")Text("Plan zakończony. Historia decyzji i oryginały zostały zachowane.",Modifier.testTag("import-complete"))
            if(state.approved)state.rows.take(state.visible).forEach {row->
                key(row.source.planId,row.source.entityType,row.source.sourceId,row.source.metadataJson,row.code) {
                    ImportDecisionCard(row,state.busy,state.recovery,keep,copy,server,replay,recreate,mapped,correct,newGoal)
                }
            }
            if(state.rows.size>state.visible)TextButton(onClick=more){Text("Pokaż kolejne decyzje")}
        }
    }
}

@Composable private fun ImportDecisionCard(row:ImportDecisionRow,busy:Boolean,recovery:Boolean,
    keep:(ImportDecisionRow)->Unit,copy:(ImportDecisionRow)->Unit,server:(ImportDecisionRow)->Unit,replay:(ImportDecisionRow)->Unit,
    recreate:(ImportDecisionRow)->Unit,mapped:(ImportDecisionRow)->Unit,
    correct:(ImportDecisionRow,Map<String,String>,Boolean)->Unit,newGoal:(ImportDecisionRow,Map<String,String>)->Unit) {
    var edit by rememberSaveable {mutableStateOf(false)}
    var goal by rememberSaveable {mutableStateOf(false)}
    Card(Modifier.fillMaxWidth()) {Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
        Text(domainLabel(row.source.entityType),style=MaterialTheme.typography.titleLarge)
        Text(issueLabel(row.code))
        val local=row.local ?: remember(row.source.sourceHash){ImportComparison.local(row.source)}
        ImportVersion("Wersja lokalna",local)
        if(recovery) {
            ImportVersion("Aktualna wersja serwera",row.server)
            Text("Zachowanie lokalne pozostawi tę wersję na urządzeniu bez wysyłania. Przyjęcie stanu serwera zastąpi lokalny wpis pokazaną wersją serwera; brak wpisu zostanie zachowany jako brak, a nie zero.")
        }
        if(row.formFailure)Text("Nie można odczytać części historycznego wpisu. Oryginał i jego skrót pozostają zapisane. Możesz zachować ten wpis lokalnie i kontynuować pozostałe dane.")
        if(recovery) {
            val ready=row.code!="full_snapshot_required" && row.proofRunId!=null && row.server.state!=ImportSideState.UNVERIFIED
            OutlinedButton(onClick={keep(row)},enabled=!busy && ready){Text("Zachowaj lokalnie bez wysyłania")}
            OutlinedButton(onClick={server(row)},enabled=!busy && ready && row.source.sourceEpoch!=null){Text("Przyjmij stan serwera")}
            if(row.sameEpoch && row.code!="absent_same_epoch" && row.source.operationId==null)
                Button(onClick={replay(row)},enabled=!busy && ready){Text("Ponów pierwotną operację")}
            if(!row.sameEpoch && row.source.sourceEpoch!=null && row.source.operationId==null && !row.formFailure) {
                if(row.mapped!=null)OutlinedButton(onClick={mapped(row)},enabled=!busy && ready){Text("Użyj powiązanego wpisu z pełnej kopii")}
                if(row.source.entityType=="goal")OutlinedButton(onClick={goal=!goal},enabled=!busy && ready){Text("Podejmij nową decyzję o celu")}
                else OutlinedButton(onClick={recreate(row)},enabled=!busy && ready && row.mapped==null){Text("Odtwórz brakujący wpis jako nowy")}
            }
            if(goal)NewGoalForm(busy){newGoal(row,it)}
        } else {
            OutlinedButton(onClick={keep(row)},enabled=!busy && row.source.operationId==null){Text("Zachowaj lokalnie bez importu")}
            if(row.code in setOf("uuid_collision","item_identity_collision","previously_imported_source_changed"))
                OutlinedButton(onClick={copy(row)},enabled=!busy){Text("Utwórz osobną kopię")}
            if(row.code !in setOf("uuid_collision","item_identity_collision","previously_imported_source_changed","uncertain_original_operation","absent_same_epoch","natural_key_review") && row.source.operationId==null && !row.formFailure) {
                OutlinedButton(onClick={edit=!edit},enabled=!busy){Text("Sprawdź i uzupełnij dane")}
                if(edit)row.form?.let {ImportCorrectionFields(it,busy){values,standalone->correct(row,values,standalone)}}
            }
            if(row.code=="natural_key_review")Text("Konto ma już profil lub zapis tego dnia. Zachowaj źródło lokalnie i popraw wybrany wpis konta po zakończeniu importu.")
            if(row.source.operationId!=null)Text("Wysłana operacja wymaga rozstrzygnięcia w ekranie synchronizacji konta. Jej zapis i treść pozostają zachowane.")
        }
    }}
}

@Composable private fun ImportVersion(title:String,side:ImportComparisonSide) {
    Text(title,style=MaterialTheme.typography.titleMedium)
    when(side.state) {
        ImportSideState.ABSENT->Text("Brak wpisu w zweryfikowanej pełnej kopii")
        ImportSideState.DELETED->Text("Wpis usunięty na serwerze")
        ImportSideState.UNVERIFIED->Text("Brak aktualnego dowodu. Pobierz pełną kopię przed decyzją.")
        ImportSideState.UNREADABLE->Text("Części danych nie można odczytać; nie zastępujemy ich zerami ani pustą wersją.")
        ImportSideState.PRESENT->Unit
    }
    side.values.forEach {Text("${it.label}: ${it.value}")}
}
@Composable private fun ImportCorrectionFields(form:LegacyImportForm,busy:Boolean,save:(Map<String,String>,Boolean)->Unit) {
    val values=remember(form){mutableStateMapOf<String,String>().apply {form.fields.forEach {put(it.key,it.value)}}}
    var consent by rememberSaveable {mutableStateOf(false)}
    var standalone by rememberSaveable {mutableStateOf(form.standaloneGoal)}
    var invalid by remember {mutableStateOf(false)}
    Text("Wartości źródłowe pozostaną zachowane. Wpisz świadomą korektę; liczby mogą mieć do 6 miejsc po przecinku. Puste pole opcjonalne oznacza brak danych.")
    form.fields.forEach {field->
        Text("Źródło · ${field.label}: ${field.original.ifEmpty {"brak danych"}}",style=MaterialTheme.typography.bodySmall)
        if(field.options.isNotEmpty()) {
            Text(field.label)
            field.options.forEach {(label,value)->FilterChip(selected=values[field.key]==value,onClick={values[field.key]=value},label={Text(label)},enabled=!busy)}
        } else OutlinedTextField(values[field.key] ?: "",{values[field.key]=it},label={Text(field.label)},singleLine=true,
            enabled=!busy,modifier=Modifier.fillMaxWidth().testTag("import-field:${field.key}"))
    }
    if(form.fields.any {it.key.contains("goal")}) {
        Row {Checkbox(standalone,{standalone=it},enabled=!busy);Text("Ten cel jest osobną decyzją, bez powiązania jako korekta wcześniejszego celu")}
    }
    Row {Checkbox(consent,{consent=it},enabled=!busy);Text("Sprawdziłem wartości i potwierdzam uzupełnienia oraz korekty")}
    if(invalid)Text("Uzupełnij wymagane pola i sprawdź precyzję liczb. Żadna wartość nie została zaokrąglona.")
    Button(onClick={try {form.choice(values,standalone);invalid=false;save(values.toMap(),standalone)} catch(_:Exception){invalid=true}},enabled=consent && !busy){Text("Zapisz świadomą korektę")}
}

@Composable private fun NewGoalForm(busy:Boolean,save:(Map<String,String>)->Unit) {
    val values=remember {mutableStateMapOf<String,String>()}
    var consent by rememberSaveable {mutableStateOf(false)}
    Text("Nowa decyzja użyje aktualnej osi celów. Wpisz jej datę i wartości; wcześniejszy cel pozostanie w historii.")
    val fields=linkedMapOf("effective_from" to "Obowiązuje od (RRRR-MM-DD)","decided_at" to "Czas decyzji UTC (RRRR-MM-DDTgg:mm:ssZ)",
        "time_zone" to "Strefa decyzji, np. Europe/Warsaw","energy_kcal" to "Energia (kcal)","protein_g" to "Białko (g, opcjonalnie)",
        "fat_g" to "Tłuszcze (g, opcjonalnie)","carbs_g" to "Węglowodany (g, opcjonalnie)")
    fields.forEach {(key,label)->OutlinedTextField(values[key] ?: "",{values[key]=it},label={Text(label)},singleLine=true,enabled=!busy,modifier=Modifier.fillMaxWidth().testTag("new-goal-field:$key"))}
    Text("Rodzaj celu")
    listOf("reduce" to "Redukcja","maintain" to "Utrzymanie","gain" to "Nadwyżka").forEach {(value,label)->
        FilterChip(selected=values["goal_type"]==value,onClick={values["goal_type"]=value},label={Text(label)},enabled=!busy)}
    Text("Klasa aktywności przy tej decyzji")
    listOf("stationary" to "Stacjonarno-biurowa","line" to "Liniowa","commando" to "Komandos").forEach {(value,label)->
        FilterChip(selected=values["activity_class"]==value,onClick={values["activity_class"]=value},label={Text(label)},enabled=!busy)}
    Row {Checkbox(consent,{consent=it},enabled=!busy);Text("Potwierdzam nową decyzję o celu")}
    Button(onClick={save(values.toMap())},enabled=consent && !busy){Text("Zatwierdź nowy cel")}
}

private fun domainLabel(type:String)=when(type){"meal"->"Posiłek";"weight"->"Pomiar wagi";"goal"->"Cel";"profile"->"Profil";"diary_day"->"Kompletność dnia";else->"Prywatny produkt"}
private fun issueLabel(code:String)=when(code) {
    "precision_review"->"Źródło ma większą precyzję niż serwer. Potrzebna jest świadoma korekta."
    "uuid_collision","item_identity_collision"->"Tożsamość wpisu jest już zajęta. Wybierz osobną kopię lub zachowaj źródło lokalnie."
    "previously_imported_source_changed"->"Źródło zmieniło się po wcześniejszym imporcie. Poprzedni wpis nie zostanie nadpisany."
    "uncertain_original_operation","existing_wire_review"->"Niepewna operacja wymaga dowodu serwera. Nie tworzymy automatycznie drugiej kopii."
    "absent_same_epoch"->"Wpis znany w tej epoce jest nieobecny w pełnej kopii. Nie zostanie odtworzony automatycznie."
    "full_snapshot_required"->"Najpierw pobierz pełną kopię i dowody operacji."
    "later_local_intent"->"Potwierdzenie dotyczy wcześniejszej wersji. Późniejsza lokalna zmiana nadal wymaga decyzji."
    "epoch_recovery_review"->"Serwer używa nowej epoki. Wybierz sposób postępowania z historycznym wpisem."
    "same_epoch_review"->"Sprawdź stan serwera przed ponowieniem niepewnej operacji."
    "natural_key_review"->"Profil lub zapis tego dnia już istnieje na koncie."
    "legacy_import_after_reconciliation"->"Starsze dane bez dowodu synchronizacji pozostają lokalne. Można je zaimportować po uzgodnieniu konta."
    else->"Wpis wymaga sprawdzenia lub uzupełnienia danych."
}