package pl.roseru.kalorie.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import pl.roseru.kalorie.core.network.NetworkAccessState
import pl.roseru.kalorie.data.AccountSyncOverview
import pl.roseru.kalorie.session.SessionActions
import pl.roseru.kalorie.session.SessionView
import pl.roseru.kalorie.sync.AccountSyncOverviewViewModel
import pl.roseru.kalorie.sync.SnapshotMaintenanceViewModel
import pl.roseru.kalorie.sync.userStatus
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

private enum class SyncHelpAction { ACCOUNT,LOGIN,SETTINGS,IMPORT,RETRY,MAINTENANCE }
private data class SyncHelp(val title:String,val message:String,val action:SyncHelpAction?,val label:String="")

@Composable fun AccountSyncOverviewScreen(model:AccountSyncOverviewViewModel,session:SessionView,actions:SessionActions,
    network:NetworkAccessState?,maintenance:SnapshotMaintenanceViewModel?,onBack:()->Unit,onAccount:()->Unit,
    onSettings:()->Unit,onImport:(()->Unit)?=null) {
    val state by model.state.collectAsStateWithLifecycle()
    val selected=session.binding?.lease==model.lease && session.binding?.owner?.kind=="account"
    var showMaintenance by remember(model) {mutableStateOf(false)}
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    var now by remember {mutableLongStateOf(System.currentTimeMillis())}
    val deadline=state.overview?.retryAtMillis?:0
    LaunchedEffect(deadline,lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            now=System.currentTimeMillis()
            while(deadline>now) {delay(minOf(1_000L,deadline-now));now=System.currentTimeMillis()}
        }
    }
    if(showMaintenance && maintenance!=null && selected) {
        BackHandler {showMaintenance=false}
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),verticalArrangement=Arrangement.spacedBy(16.dp)) {
            TextButton(onClick={showMaintenance=false},modifier=Modifier.testTag("sync-maintenance-back")) {Text("Wróć do synchronizacji")}
            SnapshotMaintenancePanel(maintenance,onAccount)
        }
        return
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp).testTag("sync-overview-content"),
        verticalArrangement=Arrangement.spacedBy(16.dp)) {
        TextButton(onClick=onBack) {Text("Wróć do konta")}
        Text("Synchronizacja",style=MaterialTheme.typography.headlineLarge)
        Text("Zapisany stan tego konta na telefonie. Otwarcie ekranu nie wysyła danych.")
        if(!selected)Text("Wybrany profil się zmienił. Wróć do konta.",Modifier.testTag("sync-overview-stale"))
        else {
            if(state.loading)LinearProgressIndicator(Modifier.fillMaxWidth())
            state.message?.let {Text(it,Modifier.testTag("sync-overview-error"))}
            state.overview?.let {local->
                val help=syncHelp(local,session,network)
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
                        Text(help.title,style=MaterialTheme.typography.titleLarge,modifier=Modifier.testTag("sync-overview-title"))
                        Text(help.message,Modifier.testTag("sync-overview-guidance"))
                        local.work?.let {Text("Stan zadania z ${syncTime(it.updatedAtMillis)}: ${it.userStatus()}",style=MaterialTheme.typography.bodySmall)}
                        if(local.retryAtMillis>now)Text("Kolejna próba nie wcześniej niż ${syncTime(local.retryAtMillis)}.",
                            modifier=Modifier.testTag("sync-overview-deadline"))
                        val busy=session.busy || session.pendingLogin || session.bootstrapBusy || session.snapshotBusy ||
                            session.mealPushBusy || session.diaryApplying || session.profileBusy || session.conflictBusy ||
                            session.motivationBusy || session.rankingConsentBusy || session.rankingBusy || session.nemesisBusy ||
                            session.nemesisMutationBusy || session.photoCapabilitiesBusy || session.photoUploadBusy || session.photoReadBusy ||
                            session.photoCancelBusy || session.photoConfirmBusy || session.photoDraftBusy
                        val networkReady=network is NetworkAccessState.Allowed
                        val retryEnabled=networkReady && session.mealPushConfigured && local.linked && session.hasSession &&
                            !local.requiresRecovery && !local.accountBlocked && !session.requiresRecovery && local.work?.status!="running" &&
                            !busy && now>=local.retryAtMillis
                        help.action?.let {action->
                            if(action!=SyncHelpAction.IMPORT || onImport!=null)Button(
                                onClick={when(action) {
                                    SyncHelpAction.ACCOUNT->onAccount()
                                    SyncHelpAction.LOGIN->actions.login()
                                    SyncHelpAction.SETTINGS->onSettings()
                                    SyncHelpAction.IMPORT->onImport?.invoke()
                                    SyncHelpAction.RETRY->actions.synchronizeMeals(model.lease)
                                    SyncHelpAction.MAINTENANCE->showMaintenance=true
                                }},enabled=when(action) {
                                    SyncHelpAction.RETRY->retryEnabled
                                    SyncHelpAction.LOGIN->networkReady && session.configured && !busy
                                    SyncHelpAction.MAINTENANCE->maintenance!=null
                                    else->true
                                },modifier=Modifier.fillMaxWidth().testTag("sync-overview-action")) {Text(help.label)}
                        }
                    }
                }
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                        Text("Zmiany zapisane lokalnie",style=MaterialTheme.typography.titleMedium)
                        Text("Niepotwierdzone operacje: ${local.queued}",Modifier.testTag("sync-overview-queued"))
                        Text("Czekają na wcześniejsze kroki: ${local.waiting} · Do sprawdzenia: ${local.attention}")
                        val labels=mapOf("meal" to "Posiłki","weight" to "Waga","profile" to "Profil","goal" to "Cele",
                            "diary_day" to "Kompletność dni","product_draft" to "Prywatne produkty")
                        labels.forEach {(type,label)->local.domains[type]?.let {Text("$label: $it",Modifier.testTag("sync-overview-domain-$type"))}}
                        val other=local.domains.filterKeys {it !in labels}.values.sum()
                        if(other>0)Text("Inne dane: $other")
                        if(local.legacy>0)Text("Wpisy wymagające przygotowania lub importu: ${local.legacy}.")
                        if(local.unconfirmedWrite)Text("Istnieje wysłana próba bez końcowego potwierdzenia. Ponowienie zachowa jej zapisane operacje.",
                            Modifier.testTag("sync-overview-unknown-write"))
                        Text(local.lastAppliedAt?.let {"Ostatnia zastosowana kopia: ${syncTime(it)}"}?:"Brak potwierdzonego zastosowania kopii w bieżącym połączeniu konta.",
                            Modifier.testTag("sync-overview-last-copy"))
                        Text("Liczba operacji może różnić się od liczby posiłków: jeden wpis może mieć kilka zmian.",style=MaterialTheme.typography.bodySmall)
                    }
                }
                if(maintenance!=null) {
                    Text("Niedokończone pobierania: ${local.unfinishedCopies}. Możliwe do ponownego rozpoczęcia: ${local.restartableCopies}.")
                    OutlinedButton(onClick={showMaintenance=true},modifier=Modifier.fillMaxWidth().testTag("sync-overview-maintenance")) {
                        Text("Przejrzyj wcześniejsze pobierania")
                    }
                }
                if(onImport!=null)OutlinedButton(onClick=onImport,modifier=Modifier.fillMaxWidth().testTag("sync-overview-import")) {Text("Import i uzgadnianie danych")}
                OutlinedButton(onClick=onSettings,modifier=Modifier.fillMaxWidth().testTag("sync-overview-settings")) {Text("Ustawienia połączenia i trybu poligonowego")}
            }
        }
    }
}

private fun syncHelp(local:AccountSyncOverview,view:SessionView,network:NetworkAccessState?):SyncHelp=when {
    local.accountBlocked->SyncHelp("Synchronizacja konta wstrzymana",
        "Kopia konta jest zablokowana. Sprawdź jego stan na ekranie konta; lokalny dziennik pozostaje dostępny.",SyncHelpAction.ACCOUNT,"Sprawdź stan konta")
    local.requiresRecovery || view.requiresRecovery || local.work?.status=="reconciliation"->SyncHelp("Dane wymagają uzgodnienia",
        "Porównaj zapisane wersje i zatwierdź dalszy sposób synchronizacji.",SyncHelpAction.IMPORT,"Otwórz uzgadnianie danych")
    local.work?.status=="storage"->SyncHelp("Pobieranie zatrzymane",
        "Sprawdź niedokończone pobierania. Jeśli żadnej próby nie można przerwać, zachowaj dane i dokończ uzgadnianie konta.",SyncHelpAction.MAINTENANCE,"Sprawdź wcześniejsze pobierania")
    !view.apiConfigured || !view.mealPushConfigured->SyncHelp("Serwer nie jest skonfigurowany",
        "Ta wersja aplikacji zachowuje dane lokalnie. Do synchronizacji potrzebna jest wersja z konfiguracją serwera.",null)
    network==NetworkAccessState.Blocked->SyncHelp("Działasz bez połączenia",
        "Blokada poligonowa jest włączona. Zapisuj dalej posiłki; połączenie możesz odblokować w ustawieniach.",SyncHelpAction.SETTINGS,"Otwórz ustawienia połączenia")
    network==null || network==NetworkAccessState.Unavailable->SyncHelp("Czekam na ustawienia połączenia",
        "Nie rozpoczynamy połączeń, dopóki ustawienie sieci nie zostanie odczytane.",SyncHelpAction.SETTINGS,"Sprawdź ustawienia połączenia")
    !local.linked->SyncHelp("Połącz profil z serwerem",
        "Na ekranie konta potwierdź połączenie. Wpisy gościa wymagają osobnego importu.",SyncHelpAction.ACCOUNT,"Przejdź do połączenia konta")
    !view.hasSession || local.work?.status=="login"->SyncHelp("Odnów logowanie",
        "Zaloguj się w przeglądarce, aby kontynuować synchronizację tego konta.",SyncHelpAction.LOGIN,"Zaloguj się ponownie")
    local.work?.status=="running"->SyncHelp("Synchronizacja trwa",
        "Aplikacja zapisuje potwierdzenia na urządzeniu. Możesz wrócić do dziennika.",null)
    local.work?.status=="local_evidence"->SyncHelp("Sprawdź zapisane potwierdzenia",
        "Ponowna próba najpierw sprawdzi zachowane wyniki operacji. Nie twórz tych wpisów od nowa.",SyncHelpAction.RETRY,"Sprawdź synchronizację")
    local.attention>0->SyncHelp("Część zmian wymaga sprawdzenia",
        "Otwórz konto, aby porównać konflikty i wybrać wynik. Niewysłane zmiany pozostają na telefonie.",SyncHelpAction.ACCOUNT,"Otwórz konflikty na koncie")
    else->SyncHelp(if(local.queued==0 && !local.unconfirmedWrite)"Dziennik gotowy do odświeżenia" else "Zmiany czekają na potwierdzenie",
        "Synchronizacja pobierze bieżący stan i wyśle przygotowane zmiany. Zapisana kolejka zostaje do potwierdzenia przez serwer.",SyncHelpAction.RETRY,"Synchronizuj teraz")
}
private fun syncTime(value:Long):String=syncTime(Instant.ofEpochMilli(value).toString())
private fun syncTime(value:String):String=try {DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
    .withZone(ZoneId.systemDefault()).format(Instant.parse(value))}catch(_:Exception){"data niedostępna"}
