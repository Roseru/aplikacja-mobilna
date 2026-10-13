package pl.roseru.kalorie.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.PersistableBundle
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.session.*
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable internal fun NemesisMutationPanel(view: SessionView, actions: SessionActions, busy: Boolean) {
    val context=LocalContext.current
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    var dialog by remember { mutableStateOf<String?>(null) }
    var create by remember { mutableStateOf(false) }
    var decision by remember { mutableStateOf<NemesisDecisionSource?>(null) }
    DisposableEffect(lifecycle) {
        val observer=LifecycleEventObserver { _,event -> if(event==Lifecycle.Event.ON_STOP) { dialog=null;create=false;decision=null } }
        lifecycle.addObserver(observer); onDispose { lifecycle.removeObserver(observer) }
    }
    val status=view.nemesisMutation
    val pending=status is NemesisMutationState.Pending || status==NemesisMutationState.Blocked
    Card(Modifier.fillMaxWidth().testTag("nemesis-mutations")) {
        Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
            Text("Zaproś wybraną osobę",style=MaterialTheme.typography.titleMedium)
            Text("Odbiorca wydaje prywatny kod i przekazuje go wybranej osobie. Kod kieruje zaproszenie; rywalizacja zacznie się dopiero po akceptacji.",style=MaterialTheme.typography.bodySmall)
            when(status) {
                NemesisMutationState.Idle -> Unit
                NemesisMutationState.Sending -> { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Potwierdzam tę samą decyzję…",Modifier.testTag("nemesis-mutation-state")) }
                is NemesisMutationState.Pending -> {
                    Text("${actionLabel(status.action)} czeka na potwierdzenie.",Modifier.testTag("nemesis-mutation-state"))
                    Text(status.message ?: "Nowy wybór będzie dostępny po rozstrzygnięciu poprzedniej decyzji.",style=MaterialTheme.typography.bodySmall)
                    OutlinedButton(onClick=actions.retryNemesisMutation,enabled=!busy,modifier=Modifier.testTag("nemesis-mutation-retry")) { Text("Ponów tę samą decyzję") }
                }
                NemesisMutationState.Blocked -> Text("Nie można odczytać poprzedniej decyzji. Nowy zapis jest zablokowany; sprawdź konto i aktualny stan rywalizacji.",Modifier.testTag("nemesis-mutation-state"))
                is NemesisMutationState.Failed -> Text(status.message,Modifier.testTag("nemesis-mutation-state"))
                is NemesisMutationState.Confirmed -> Text("${actionLabel(status.action)} potwierdzone. Odśwież, aby sprawdzić aktualne udostępnianie.",Modifier.testTag("nemesis-mutation-state"))
                is NemesisMutationState.Issued -> {
                    val code=status.code
                    Text("Kod z potwierdzenia",style=MaterialTheme.typography.titleSmall)
                    Text(code.value,Modifier.testTag("nemesis-code"),softWrap=true)
                    Text("Termin: "+code.expiresAt.atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm")),style=MaterialTheme.typography.bodySmall)
                    Text("Prywatny, jednorazowy kod. Zużycie, unieważnienie lub nowy kod wyłącza poprzedni.",style=MaterialTheme.typography.bodySmall)
                    TextButton(onClick={
                        val clip=ClipData.newPlainText("Kod Nemesis",code.value)
                        clip.description.extras=PersistableBundle().apply { putBoolean("android.content.extra.IS_SENSITIVE",true) }
                        (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(clip)
                    },enabled=!busy && code.expiresAt>Instant.now(),modifier=Modifier.testTag("nemesis-copy-code")) { Text("Skopiuj kod") }
                }
            }
            if(!pending) {
                TextButton(onClick={dialog="issue"},enabled=!busy,modifier=Modifier.testTag("nemesis-issue-code")) { Text("Wydaj nowy kod dla mnie") }
                TextButton(onClick={dialog="revoke"},enabled=!busy,modifier=Modifier.testTag("nemesis-revoke-code")) { Text("Unieważnij mój kod") }
                Button(onClick={create=true},enabled=!busy,modifier=Modifier.testTag("nemesis-create")) { Text("Mam kod · wyślij zaproszenie") }
                view.nemesisDecision?.let { source ->
                    if(source.challenge.status=="invited" && source.challenge.role=="invitee") Button(onClick={decision=source;dialog="accept"},enabled=!busy,
                        modifier=Modifier.testTag("nemesis-accept")) { Text("Przejrzyj i zaakceptuj zaproszenie") }
                    if(source.challenge.status in setOf("invited","active","finished")) OutlinedButton(onClick={decision=source;dialog="cancel"},enabled=!busy,
                        modifier=Modifier.testTag("nemesis-cancel")) { Text(if(source.challenge.status=="invited") if(source.challenge.role=="inviter") "Wycofaj zaproszenie" else "Odrzuć zaproszenie" else "Zakończ udostępnianie") }
                }
            }
        }
    }
    if(create) CreateNemesisDialog(actions,busy,onDismiss={create=false})
    val kind=dialog
    if(kind in setOf("issue","revoke")) AlertDialog(onDismissRequest={dialog=null},title={Text(if(kind=="issue") "Wydać nowy kod?" else "Unieważnić kod?")},
        text={Text(if(kind=="issue") "Kod jest prywatny i ważny najwyżej 24 godziny. Przekaż go tylko wybranej osobie. Nowy kod wyłączy poprzedni; sam kod nie udostępnia wyników." else "Nieużyty kod przestanie przyjmować zaproszenia. Ta czynność nie anuluje już istniejącej rywalizacji.")},
        confirmButton={TextButton(onClick={dialog=null;if(kind=="issue") actions.issueNemesisCode() else actions.revokeNemesisCode()},enabled=!busy,
            modifier=Modifier.testTag("nemesis-confirm-code")) { Text("Potwierdź") }},dismissButton={TextButton(onClick={dialog=null}) { Text("Wróć") }})
    if(kind=="accept") decision?.let { source -> AcceptNemesisDialog(source,actions,busy,
        current=view.nemesisDecision?.id==source.id,onDismiss={dialog=null;decision=null}) }
    if(kind=="cancel") decision?.let { source -> AlertDialog(onDismissRequest={dialog=null;decision=null},title={Text("Zakończyć udostępnianie?")},
        text={Text("Wycofanie zaproszenia lub zgody zakończy tę rywalizację. Ponowne rozpoczęcie wymaga nowego zaproszenia i akceptacji obu osób.")},
        confirmButton={TextButton(onClick={dialog=null;decision=null;actions.cancelNemesis(source.id)},enabled=!busy && view.nemesisDecision?.id==source.id,
            modifier=Modifier.testTag("nemesis-confirm-cancel")) { Text("Potwierdź zakończenie") }},dismissButton={TextButton(onClick={dialog=null;decision=null}) { Text("Wróć") }}) }
}
@Composable private fun CreateNemesisDialog(actions: SessionActions,busy: Boolean,onDismiss:()->Unit) {
    val focus=LocalFocusManager.current;val keyboard=LocalSoftwareKeyboardController.current
    var code by remember { mutableStateOf("") }; var days by remember { mutableIntStateOf(30) }
    var zone by remember { mutableStateOf(ZoneId.systemDefault().id.takeIf { it in ZoneId.getAvailableZoneIds() } ?: "Europe/Warsaw") }
    var weight by remember { mutableStateOf(false) }; var deficit by remember { mutableStateOf(false) }; var ack by remember { mutableStateOf(false) }
    val valid=runCatching { NemesisCommand.validateCode(code) }.isSuccess && zone in ZoneId.getAvailableZoneIds()
    AlertDialog(onDismissRequest=onDismiss,title={Text("Warunki zaproszenia")},text={Column(dialogBody(),verticalArrangement=Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(code,{if(it.length<=43) code=it;ack=false},label={Text("Prywatny kod drugiej osoby")},singleLine=true,
            keyboardOptions=KeyboardOptions(imeAction=ImeAction.Done),keyboardActions=KeyboardActions(onDone={focus.clearFocus();keyboard?.hide()}),modifier=Modifier.testTag("nemesis-destination-code"))
        Text("Okres rywalizacji")
        Row(horizontalArrangement=Arrangement.spacedBy(6.dp)) { listOf(7,30,90).forEach { d -> FilterChip(selected=days==d,onClick={days=d;ack=false},label={Text("$d dni")},modifier=Modifier.testTag("nemesis-days-$d")) } }
        OutlinedTextField(zone,{zone=it;ack=false},label={Text("Strefa czasu, np. Europe/Warsaw")},singleLine=true,
            keyboardOptions=KeyboardOptions(imeAction=ImeAction.Done),keyboardActions=KeyboardActions(onDone={focus.clearFocus();keyboard?.hide()}),modifier=Modifier.testTag("nemesis-time-zone"))
        Text("Regularność v1: 1 punkt za kompletny dzień i 1 za dzień w celu. Wynik zależy od regularności, nie wielkości deficytu.",style=MaterialTheme.typography.bodySmall)
        Choice("Udostępniaj procentową zmianę masy",weight,{weight=it;ack=false},"nemesis-create-weight")
        Choice("Udostępniaj średni szacowany deficyt",deficit,{deficit=it;ack=false},"nemesis-create-deficit")
        Text("Tylko uzgodnione porównania; surowa masa i posiłki nie są udostępniane. Druga osoba musi zaakceptować identyczne warunki.",style=MaterialTheme.typography.bodySmall)
        Choice("Potwierdzam okres, strefę i zakres udostępnienia",ack,{ack=it},"nemesis-create-ack")
    }},confirmButton={TextButton(onClick={onDismiss();actions.createNemesis(code,days,zone,weight,deficit,ack)},enabled=valid && ack && !busy,
        modifier=Modifier.testTag("nemesis-confirm-create")) { Text("Wyślij zaproszenie") }},dismissButton={TextButton(onClick=onDismiss) { Text("Wróć") }})
}
@Composable private fun AcceptNemesisDialog(source: NemesisDecisionSource,actions: SessionActions,busy: Boolean,current: Boolean,onDismiss:()->Unit) {
    val terms=source.challenge.terms
    var regularity by remember(source.id) { mutableStateOf(false) }; var weight by remember(source.id) { mutableStateOf(false) }; var deficit by remember(source.id) { mutableStateOf(false) }
    AlertDialog(onDismissRequest=onDismiss,title={Text("Akceptacja warunków")},text={Column(dialogBody(),verticalArrangement=Arrangement.spacedBy(8.dp)) {
        Text("${terms.days} dni · ${terms.zone.id}")
        Text("Regularność v1: punkty za kompletne dni i realizację własnego celu. Rywalizacja zacznie się od następnej lokalnej daty.",style=MaterialTheme.typography.bodySmall)
        Choice("Akceptuję regularność, okres i strefę czasu",regularity,{regularity=it},"nemesis-accept-ack")
        if(terms.weight) Choice("Zgadzam się na procentową zmianę masy",weight,{weight=it},"nemesis-accept-weight") else Text("Zmiana masy nie jest udostępniana.")
        if(terms.deficit) Choice("Zgadzam się na średni szacowany deficyt",deficit,{deficit=it},"nemesis-accept-deficit") else Text("Deficyt nie jest udostępniany.")
        Text("Warunki są wspólne dla obu osób. Jeśli potrzebujesz innego zakresu, odrzuć zaproszenie i uzgodnij nowe.",style=MaterialTheme.typography.bodySmall)
        if(!current) Text("Odczyt warunków się zmienił. Wróć i przejrzyj aktualne zaproszenie.")
    }},confirmButton={TextButton(onClick={onDismiss();actions.acceptNemesis(source.id,regularity,weight,deficit)},enabled=current && regularity && (!terms.weight || weight) && (!terms.deficit || deficit) && !busy,
        modifier=Modifier.testTag("nemesis-confirm-accept")) { Text("Akceptuję") }},dismissButton={TextButton(onClick=onDismiss) { Text("Wróć") }})
}
@Composable private fun Choice(label: String,checked: Boolean,onChange:(Boolean)->Unit,tag:String) {
    Row(verticalAlignment=Alignment.CenterVertically) { Checkbox(checked,onChange,modifier=Modifier.testTag(tag)); Text(label,Modifier.weight(1f),style=MaterialTheme.typography.bodySmall) }
}
private fun actionLabel(action: NemesisAction)=when(action) { NemesisAction.ISSUE->"Wydanie kodu";NemesisAction.REVOKE->"Unieważnienie kodu";NemesisAction.CREATE->"Zaproszenie";NemesisAction.ACCEPT->"Akceptacja";NemesisAction.CANCEL->"Zakończenie udostępniania" }
@Composable private fun dialogBody():Modifier {
    val density=LocalDensity.current
    val ime=WindowInsets.ime.getBottom(density)/density.density
    val maximum=(LocalConfiguration.current.screenHeightDp-ime-200f).coerceAtLeast(100f).dp
    return Modifier.heightIn(max=maximum).verticalScroll(rememberScrollState())
}
