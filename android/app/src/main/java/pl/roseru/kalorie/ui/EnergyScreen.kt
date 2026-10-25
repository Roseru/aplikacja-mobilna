package pl.roseru.kalorie.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.network.NetworkAccessState
import pl.roseru.kalorie.energy.*
import pl.roseru.kalorie.session.SessionView
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private sealed interface EnergyDialog {
    data class Create(val token:String,val accepted:Boolean,val qualified:Boolean):EnergyDialog
    data class Affirm(val token:String,val accepted:Boolean,val qualified:Boolean):EnergyDialog
    data class Consent(val token:String,val enabled:Boolean):EnergyDialog
    data class Decide(val analysis:EnergyAnalysis,val accept:Boolean):EnergyDialog
    data class Revert(val version:EnergyVersion):EnergyDialog
    data class Discard(val id:String):EnergyDialog
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable internal fun EnergyScreen(model:EnergyViewModel,diary:DiaryViewModel,session:SessionView,
    network:NetworkAccessState?,onBack:()->Unit,onAccount:()->Unit,onConsents:()->Unit=onAccount,now:()->Long=System::currentTimeMillis) {
    val state by model.state.collectAsStateWithLifecycle()
    val foodGoal by diary.todayGoal.collectAsStateWithLifecycle()
    val data=state.local;val axis=data?.axis
    val zone=remember(data?.profile?.profile?.timeZone){runCatching {ZoneId.of(data?.profile?.profile?.timeZone)}.getOrDefault(ZoneId.systemDefault())}
    var clock by remember {mutableLongStateOf(now())}
    LaunchedEffect(Unit){while(true){clock=now();delay(30_000)}}
    val today=Instant.ofEpochMilli(clock).atZone(zone).toLocalDate()
    LaunchedEffect(model){model.reload()}
    DisposableEffect(model){onDispose {model.cancel()}}
    val online=state.configured && session.hasSession && session.serverLinked && !session.requiresRecovery && network is NetworkAccessState.Allowed
    val enabled=online && !state.busy && clock>=(data?.retryAt?:0)
    val reviewed=enabled && data?.reviewToken!=null && (data.profile?.consents?.revision?:0)>=state.externalConsentRevision && !state.externalConsentUncertain
    var tab by remember {mutableStateOf("analyses")}
    var manualNotice by remember(data?.reviewToken){mutableStateOf(false)}
    var manualQualified by remember(data?.reviewToken){mutableStateOf(false)}
    var automaticNotice by remember(data?.reviewToken){mutableStateOf(false)}
    var automaticQualified by remember(data?.reviewToken){mutableStateOf(false)}
    var dialog by remember(data?.scope?.wireContext,data?.reviewToken){mutableStateOf<EnergyDialog?>(null)}
    val selected=data?.analyses?.firstOrNull {it.id==state.selectedAnalysis}
    BackHandler {if(selected!=null && !state.busy)model.selectAnalysis(null)else {model.cancel();onBack()}}
    Scaffold(topBar={TopAppBar(title={Text("Zapotrzebowanie i korekty")},navigationIcon={IconButton(onClick={
        if(selected!=null && !state.busy)model.selectAnalysis(null)else {model.cancel();onBack()}
    }){Icon(Icons.AutoMirrored.Outlined.ArrowBack,"Wróć")}})}) {padding->
        LazyColumn(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding).testTag("energy-content"),
            contentPadding=PaddingValues(20.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
            item("status") {
                if(state.busy) {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    TextButton(onClick=model::cancel,modifier=Modifier.testTag("energy-cancel")){Text("Przerwij oczekiwanie")}
                }
                if(!online)Text(when {
                    data?.scope==null->"Korekty wymagają połączonego konta. Kalkulator i własny cel działają bez konta i internetu."
                    !state.configured->"Usługa korekt nie jest skonfigurowana w tej aplikacji."
                    session.requiresRecovery->"Najpierw uzgodnij stan konta. Zapisany podgląd pozostaje dostępny."
                    !session.hasSession->"Sesja wygasła. Możesz przeglądać zapisane wyniki; nowe decyzje wymagają logowania."
                    else->"Tryb offline. Wyświetlany jest ostatni zapisany podgląd."
                },style=MaterialTheme.typography.bodySmall,modifier=Modifier.testTag("energy-offline"))
                state.message?.let {Text(it,color=MaterialTheme.colorScheme.primary,modifier=Modifier.testTag("energy-message"))}
                if((data?.fetchedAt?:0)>0)Text("Podgląd pobrany ${energyTime(Instant.ofEpochMilli(data!!.fetchedAt),zone)}",style=MaterialTheme.typography.labelSmall)
                if((data?.retryAt?:0)>clock)Text("Przerwa od serwera do ${energyTime(Instant.ofEpochMilli(data!!.retryAt),zone)}",style=MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick=model::refresh,enabled=enabled,modifier=Modifier.testTag("energy-refresh")){Text("Odśwież")}
                    if(!session.hasSession || !session.serverLinked)TextButton(onClick=onAccount){Text("Konto i synchronizacja")}
                }
            }
            item("current") {
                val current=data?.versions?.firstOrNull {it.id==axis?.currentId}
                EnergyCard {
                    Text("Szacowane utrzymanie",style=MaterialTheme.typography.labelLarge)
                    Text(current?.maintenance?.let {energyNumber(it)+" kcal / dzień"}?:if(axis?.currentId!=null)"Pobierz historię oszacowania" else "Brak oszacowania na serwerze",
                        style=MaterialTheme.typography.headlineSmall,modifier=Modifier.testTag("energy-current"))
                    Text("Cel posiłków: ${foodGoal?.kcal?.toBigDecimal()?.let(::energyNumber)?:"—"} kcal",modifier=Modifier.testTag("energy-food-goal"))
                    Text("Przyjęcie korekty zmienia szacunek utrzymania. Cel kcal, makra i klasa aktywności wymagają osobnej decyzji.",style=MaterialTheme.typography.bodySmall)
                    axis?.nextApplyAt?.let {Text("Kolejna korekta najwcześniej ${energyTime(it,zone)}",style=MaterialTheme.typography.bodySmall)}
                }
            }
            if(selected!=null) {
                item("selected") {
                    EnergyCard {
                        Text(energyAnalysisLabel(selected,clock),style=MaterialTheme.typography.titleMedium)
                        Text("Okno: ${selected.dateFrom} – ${selected.dateTo}")
                        EnergyRule(selected.result)
                        selected.explanation?.let {Text(it)}
                        selected.uncertainty?.let {Text("Niepewność: "+when(it){"low"->"niska";"medium"->"średnia";else->"wysoka"},style=MaterialTheme.typography.bodySmall)}
                        selected.suggestedClass?.let {Text("Sugestia klasy: "+when(it){"stationary"->"etat biurowo-kawowy";"line"->"linia";else->"komandos"}+
                            ". Profil nie został zmieniony.",style=MaterialTheme.typography.bodySmall)}
                        selected.expiresAt?.let {Text("Ważność do ${energyTime(it,zone)}",style=MaterialTheme.typography.bodySmall)}
                        val same=axis!=null && selected.epoch==axis.epoch && selected.generation==axis.generation &&
                            selected.sourceAxisRevision==axis.axisRevision && selected.sourceEnergyId==axis.currentId
                        if(!same)Text("Analiza dotyczy wcześniejszego stanu. Nie można zastosować jej do aktualnych danych.",style=MaterialTheme.typography.bodySmall)
                        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                            Button(onClick={dialog=EnergyDialog.Decide(selected,true)},enabled=enabled && same && data.matchesAnalysis(selected,Instant.ofEpochMilli(clock)) &&
                                !state.externalConsentUncertain && (data.profile?.consents?.revision?:0)>=state.externalConsentRevision && selected.canAccept(Instant.ofEpochMilli(clock)),
                                modifier=Modifier.testTag("energy-accept")){Text("Przyjmij")}
                            OutlinedButton(onClick={dialog=EnergyDialog.Decide(selected,false)},enabled=enabled && same && selected.state !in setOf("accepted","rejected","expired","stale"),
                                modifier=Modifier.testTag("energy-reject")){Text("Odrzuć")}
                        }
                        TextButton(onClick={model.refreshAnalysis(selected.id)},enabled=enabled,modifier=Modifier.testTag("energy-refresh-analysis")){Text("Sprawdź aktualny wynik")}
                    }
                }
            } else {
                item("tabs") {Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected=tab=="analyses",onClick={tab="analyses"},label={Text("Analizy")},modifier=Modifier.testTag("energy-tab-analyses"))
                    FilterChip(selected=tab=="history",onClick={tab="history"},label={Text("Historia E")},modifier=Modifier.testTag("energy-tab-history"))
                }}
                if(tab=="analyses") {
                    item("new-analysis") {EnergyCard {
                        Text("Przeanalizuj ostatnie 14 dni",style=MaterialTheme.typography.titleMedium)
                        Text("Potrzebne są kompletne dni i pomiary wagi. Serwer sprawdza ich wystarczalność; braki nie stają się zerami.",style=MaterialTheme.typography.bodySmall)
                        EnergyNotice(data?.capabilities?.provider,false)
                        EnergyCheck("Potwierdzam zakres kalkulatora dla osoby pełnoletniej, bez ciąży/karmienia i stanów wymagających indywidualnego postępowania.",
                            manualQualified,{manualQualified=it},!state.busy,"energy-qualified")
                        EnergyCheck("Zgadzam się na tę jedną analizę opisanych agregatów.",manualNotice,{manualNotice=it},!state.busy,"energy-analysis-notice")
                        Button(onClick={dialog=EnergyDialog.Create(checkNotNull(data?.reviewToken),manualNotice,manualQualified)},
                            enabled=reviewed && manualNotice && manualQualified && data?.capabilities?.available==true,
                            modifier=Modifier.fillMaxWidth().testTag("energy-create")){Text("Zleć analizę")}
                    }}
                    data?.unavailable?.let {value->item("unavailable") {EnergyCard {
                        Text("Ostatnia próba zlecenia",style=MaterialTheme.typography.titleSmall)
                        EnergyRule(value.result)
                        Text("Ta odpowiedź nie utworzyła nowego zadania analizy.",style=MaterialTheme.typography.bodySmall)
                    }}}
                    items(data?.analyses?:emptyList(),key={"analysis:${it.id}"}) {analysis->
                        OutlinedCard(onClick={model.selectAnalysis(analysis.id)},enabled=!state.busy,modifier=Modifier.fillMaxWidth().testTag("energy-analysis-${analysis.id}")) {
                            Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(4.dp)) {
                                Text(energyAnalysisLabel(analysis,clock),fontWeight=FontWeight.SemiBold)
                                Text("${analysis.dateFrom} – ${analysis.dateTo}",style=MaterialTheme.typography.bodySmall)
                                analysis.result.proposed?.let {Text("Propozycja: ${energyNumber(it)} kcal / dzień")}
                            }
                        }
                    }
                    item("automatic") {EnergyCard {
                        Text("Automatyczne korekty",style=MaterialTheme.typography.titleMedium)
                        Text("Zgoda: "+when(data?.profile?.consents?.automaticEnergyAdjustment){true->"włączona";false->"wyłączona";null->"brak aktualnego odczytu"},
                            modifier=Modifier.testTag("energy-automatic-requested"))
                        Text(when {state.externalConsentUncertain || data?.consentUncertain==true->"Poprzednia zmiana zgód wymaga sprawdzenia.";state.automaticEffective->"Automat był potwierdzony w ostatnim pobranym stanie.";
                            data?.profile?.consents?.automaticEnergyAdjustment==true->"Automat oczekuje na osobne potwierdzenie aktualnego oszacowania.";else->"Automat jest nieaktywny."},
                            modifier=Modifier.testTag("energy-automatic-effective"))
                        if(state.externalConsentUncertain || data?.consentUncertain==true)TextButton(onClick=onConsents,enabled=!state.busy){Text("Sprawdź wcześniejszą zmianę zgód")}
                        Text("Każda nowa zmiana zgód, również samego rankingu, wymaga ponownego potwierdzenia energii. Odczyt i ponowienie starej zgody nie włączają automatu.",style=MaterialTheme.typography.bodySmall)
                        data?.profile?.consents?.let {consents->
                            OutlinedButton(onClick={dialog=EnergyDialog.Consent(checkNotNull(data.reviewToken),!consents.automaticEnergyAdjustment)},
                                enabled=reviewed,modifier=Modifier.testTag("energy-change-automatic-consent")) {Text(if(consents.automaticEnergyAdjustment)"Wyłącz zgodę" else "Zapisz zgodę na automat")}
                        }
                        if(data?.profile?.consents?.automaticEnergyAdjustment==true && !state.automaticEffective && axis?.currentId!=null) {
                            HorizontalDivider()
                            EnergyNotice(data.capabilities?.provider,true)
                            EnergyCheck("Potwierdzam opisany zakres v1 oraz aktualne oszacowanie jako świadomy punkt odniesienia.",automaticQualified,{automaticQualified=it},!state.busy,"energy-automatic-qualified")
                            EnergyCheck("Zgadzam się na przyszłe analizy i korekty automatyczne w opisanych granicach.",automaticNotice,{automaticNotice=it},!state.busy,"energy-automatic-notice")
                            Button(onClick={dialog=EnergyDialog.Affirm(checkNotNull(data.reviewToken),automaticNotice,automaticQualified)},
                                enabled=reviewed && automaticNotice && automaticQualified && data.capabilities?.available==true,
                                modifier=Modifier.fillMaxWidth().testTag("energy-affirm")){Text("Potwierdź bieżące oszacowanie")}
                        }
                    }}
                }else {
                    if(data?.versions.isNullOrEmpty())item("no-history"){Text("Brak pobranej historii oszacowania. Ustawienie samego celu kcal nie tworzy brakującego E.")}
                    items(data?.versions?:emptyList(),key={"version:${it.id}"}) {version->
                        EnergyCard {
                            Text("${energyNumber(version.maintenance)} kcal / dzień",style=MaterialTheme.typography.titleMedium)
                            Text("Od ${version.effectiveFrom} · wersja ${version.revision}")
                            Text(when(version.source){"legacy"->"Kalkulator początkowy";"automatic"->"Korekta automatyczna";"revert"->"Przywrócenie wcześniejszej wartości";else->"Propozycja przyjęta przez użytkownika"},style=MaterialTheme.typography.bodySmall)
                            if(version.id==axis?.currentId)Text("Obecnie obowiązująca",color=MaterialTheme.colorScheme.primary)
                            else if(version.effectiveFrom>today)Text("Wersja planowana",style=MaterialTheme.typography.bodySmall)
                            TextButton(onClick={dialog=EnergyDialog.Revert(version)},enabled=enabled && axis!=null && version.id!=axis.currentId &&
                                version.effectiveFrom<=today,modifier=Modifier.testTag("energy-revert-${version.id}")){Text("Przywróć od jutra")}
                        }
                    }
                    if((data?.versions?.minOfOrNull {it.revision}?:0)>1)item("older") {OutlinedButton(onClick=model::older,enabled=enabled,
                        modifier=Modifier.fillMaxWidth().testTag("energy-older")){Text("Pobierz starsze wersje")}}
                }
            }
            if(data!=null && data.attempts.isNotEmpty()) {
                item("operations-title"){Text("Ostatnie operacje",style=MaterialTheme.typography.titleMedium)}
                items(data.attempts.take(12),key={"operation:${it.id}"}) {attempt->
                    val same=attempt.wireContext==data.scope?.wireContext
                    val pending=attempt.state in EnergyStore.pendingStates
                    EnergyCard {
                        Text(when(attempt.kind){"create"->"Zlecenie analizy";"accept"->"Przyjęcie korekty";"reject"->"Odrzucenie analizy";"revert"->"Przywrócenie wartości";"affirm"->"Potwierdzenie automatu";else->"Zmiana zgody"},fontWeight=FontWeight.SemiBold)
                        Text(if(!same && pending)"Wymaga uzgodnienia wcześniejszego stanu konta"else when(attempt.state){"succeeded"->"Potwierdzona";"rejected"->energyMessage(attempt.errorCode?:"rejected");"prepared"->"Zapisana, jeszcze niewysłana";"needs_reconciliation"->"Wynik wymaga uzgodnienia";else->"Wynik niepewny — poprzednia decyzja jest zachowana"},style=MaterialTheme.typography.bodySmall)
                        if(pending && same && attempt.state!="needs_reconciliation") {
                            Text("Ponowienie użyje poprzedniej decyzji; nie utworzy drugiej operacji.",style=MaterialTheme.typography.bodySmall)
                            Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                                TextButton(onClick={model.retry(attempt.id)},enabled=enabled && clock>=attempt.retryAt,
                                    modifier=Modifier.testTag("energy-retry-${attempt.id}")){Text("Ponów")}
                                if(!attempt.attempted)TextButton(onClick={dialog=EnergyDialog.Discard(attempt.id)},enabled=!state.busy){Text("Usuń niewysłaną")}
                            }
                        }
                    }
                }
            }
        }
    }
    dialog?.let {choice->
        var replacement by remember(choice){mutableStateOf<String?>(null)}
        var approveReplacement by remember(choice){mutableStateOf(false)}
        val tomorrow=today.plusDays(1)
        val versions=data?.versions.orEmpty()
        val plans=versions.filter {it.effectiveFrom==tomorrow && versions.none {newer->newer.source!="legacy" && newer.supersedes==it.id && newer.effectiveFrom<=tomorrow}}
        AlertDialog(onDismissRequest={dialog=null},title={Text(when(choice){is EnergyDialog.Create->"Zlecić analizę?";is EnergyDialog.Affirm->"Potwierdzić automat?";
            is EnergyDialog.Consent->if(choice.enabled)"Zapisać zgodę?"else"Wyłączyć zgodę?";is EnergyDialog.Decide->if(choice.accept)"Przyjąć korektę?"else"Odrzucić analizę?";
            is EnergyDialog.Revert->"Przywrócić wcześniejszą wartość?";is EnergyDialog.Discard->"Usunąć niewysłaną operację?"})},text={
            Column(verticalArrangement=Arrangement.spacedBy(8.dp)) {
                Text(when(choice) {
                    is EnergyDialog.Create->"Do wyświetlonego dostawcy trafią wyłącznie opisane agregaty. Zlecenie nie zmienia E ani celu posiłków."
                    is EnergyDialog.Affirm->"Bieżące oszacowanie stanie się świadomym punktem odniesienia automatu. Nowe zastosowania są ograniczone do ±5% bieżącego E i ±10% tej wartości, z przerwami co najmniej 14 dni. Cel i makra pozostają bez zmian."
                    is EnergyDialog.Consent->if(choice.enabled)"Zapiszesz deklarację zgody. Uruchomienie automatu wymaga jeszcze osobnego potwierdzenia oszacowania i zakresu danych. Widoczność w rankingu zostanie zachowana."else"Zgoda na kolejne automatyczne analizy i korekty zostanie cofnięta. Dotychczasowe wersje E i ranking pozostaną."
                    is EnergyDialog.Decide->if(choice.accept)"Nowe E: ${choice.analysis.result.proposed?.let(::energyNumber)} kcal od $tomorrow. Cel kcal/B/T/W i profil nie zmienią się."else"Analiza zostanie odrzucona. Późny wynik nie zostanie zastosowany."
                    is EnergyDialog.Revert->"${energyNumber(choice.version.maintenance)} kcal / dzień od $tomorrow. Powstanie nowa wersja, a dotychczasowa historia zostanie zachowana. Gemini nie jest wywoływane."
                    is EnergyDialog.Discard->"Usunięta zostanie wyłącznie ta niewysłana decyzja. Potwierdzone i niepewne operacje pozostają zachowane."
                })
                if(choice is EnergyDialog.Revert && plans.isNotEmpty()) {
                    Text("Na jutro istnieje plan. Wskaż konkretną wersję, którą chcesz zastąpić.")
                    plans.forEach {plan->Row(Modifier.fillMaxWidth().clickable {replacement=plan.id;approveReplacement=false},verticalAlignment=Alignment.CenterVertically) {
                        RadioButton(selected=replacement==plan.id,onClick={replacement=plan.id;approveReplacement=false})
                        Text("Wersja ${plan.revision}: ${energyNumber(plan.maintenance)} kcal")
                    }}
                    EnergyCheck("Świadomie zastępuję wskazany plan na jutro.",approveReplacement,{approveReplacement=it},replacement!=null,"energy-replace-approved")
                }
            }
        },confirmButton={TextButton(onClick={
            dialog=null
            when(choice) {
                is EnergyDialog.Create->{model.create(choice.token,choice.accepted,choice.qualified);manualNotice=false;manualQualified=false}
                is EnergyDialog.Affirm->{model.affirm(choice.token,choice.accepted,choice.qualified);automaticNotice=false;automaticQualified=false}
                is EnergyDialog.Consent->model.automatic(choice.token,choice.enabled)
                is EnergyDialog.Decide->model.decide(choice.analysis.id,choice.accept)
                is EnergyDialog.Revert->model.revert(choice.version.id,replacement,approveReplacement)
                is EnergyDialog.Discard->model.discardUnsent(choice.id)
            }
        },enabled=(if(choice is EnergyDialog.Discard)!state.busy else enabled) && (choice !is EnergyDialog.Revert || plans.isEmpty() || (replacement!=null && approveReplacement)),
            modifier=Modifier.testTag("energy-confirm")){Text("Potwierdź")}},dismissButton={TextButton(onClick={dialog=null}){Text("Wróć")}})
    }
}

@Composable private fun EnergyCard(content:@Composable ColumnScope.()->Unit) {
    OutlinedCard(Modifier.fillMaxWidth()){Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(8.dp),content=content)}
}
@Composable private fun EnergyCheck(text:String,value:Boolean,onChange:(Boolean)->Unit,enabled:Boolean,tag:String) {
    Row(Modifier.fillMaxWidth().clickable(enabled=enabled){onChange(!value)}.testTag(tag),verticalAlignment=Alignment.CenterVertically) {
        Checkbox(checked=value,onCheckedChange=null,enabled=enabled);Text(text,style=MaterialTheme.typography.bodySmall,modifier=Modifier.padding(start=8.dp))
    }
}
@Composable private fun EnergyNotice(provider:String?,automatic:Boolean) {
    Text("Dostawca: "+when(provider){"gemini"->"Gemini";"mock"->"symulator developerski";else->"odśwież konfigurację"},style=MaterialTheme.typography.labelLarge)
    Text("Przekazywane są daty okna, reguły i werdykt, liczby kompletnych dni i dni pomiarów, dwie mediany masy oraz propozycja i granice E. Bez pełnego dziennika, zdjęć, pseudonimu lub diagnoz.",style=MaterialTheme.typography.bodySmall)
    if(automatic)Text("To osobna zgoda na opisany zakres przyszłych analiz i automatycznych korekt.",style=MaterialTheme.typography.bodySmall)
}
@Composable private fun EnergyRule(rule:EnergyRuleResult) {
    Text(when(rule.state){"insufficient_data"->"Za mało kompletnych dni lub pomiarów";"energy_history_unavailable"->"Brak spójnej historii oszacowania";
        "baseline_required"->"Potrzebne świadome potwierdzenie wartości bazowej";"baseline_range_conflict"->"Propozycja poza dopuszczalnym zakresem względem punktu odniesienia";
        "manual_review_required"->"Trend wymaga ręcznej oceny";"no_change"->"Brak zmiany do zastosowania";else->"Dane wystarczają do propozycji"},fontWeight=FontWeight.SemiBold)
    Text("Kompletne dni: ${rule.completeDays}/14 · dni z wagą: ${rule.weightDays}/14",style=MaterialTheme.typography.bodySmall)
    if(rule.firstMedian!=null || rule.secondMedian!=null)Text("Mediany masy: ${rule.firstMedian?.let(::energyNumber)?:"brak"} → ${rule.secondMedian?.let(::energyNumber)?:"brak"} kg")
    rule.proposed?.let {Text("Proponowane utrzymanie: ${energyNumber(it)} kcal / dzień")}
    if(rule.lower!=null && rule.upper!=null)Text("Dopuszczalny zakres: ${energyNumber(rule.lower)}–${energyNumber(rule.upper)} kcal",style=MaterialTheme.typography.bodySmall)
}
private fun energyNumber(value:BigDecimal)=value.setScale(2,RoundingMode.HALF_UP).stripTrailingZeros().toPlainString().replace('.',',')
private fun energyTime(value:Instant,zone:ZoneId)=DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm").withZone(zone).format(value)
private fun energyAnalysisLabel(value:EnergyAnalysis,now:Long):String {
    if(value.state in setOf("ready","no_change","manual_review_required") && value.expiresAt?.let {now>=it.toEpochMilli()}==true)return "Propozycja wygasła — odśwież"
    return when(value.state){"queued"->"Analiza w kolejce";"running"->"Trwa analiza";"ready"->"Propozycja do przejrzenia";"manual_review_required"->"Potrzebna ręczna ocena";
        "no_change"->"Bez zmiany";"accepted"->"Korekta przyjęta";"rejected"->"Analiza odrzucona";"expired"->"Propozycja wygasła";"stale"->"Dane analizy zmieniły się";else->"Analiza nieudana"}
}
