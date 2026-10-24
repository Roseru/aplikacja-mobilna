package pl.roseru.kalorie.session

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp

data class SessionActions(val login: () -> Unit, val logout: () -> Unit, val refresh: () -> Unit, val cancel: () -> Unit,
    val bootstrap: () -> Unit, val readProfile: () -> Unit, val downloadSnapshot: () -> Unit = {}, val readMotivation: () -> Unit = {},
    val readRankingConsents: () -> Unit = {}, val confirmRankingConsent: (String, Boolean) -> Unit = { _, _ -> }, val retryRankingConsent: () -> Unit = {},
    val readRanking: () -> Unit = {}, val nextRankingPage: () -> Unit = {}, val retryRankingPage: () -> Unit = {}, val clearRanking: () -> Unit = {},
    val readNemesis: () -> Unit = {}, val readNemesisChallenge: (String) -> Unit = {}, val nextNemesisPage: () -> Unit = {},
    val retryNemesis: () -> Unit = {}, val clearNemesis: () -> Unit = {},
    val issueNemesisCode: () -> Unit = {}, val revokeNemesisCode: () -> Unit = {},
    val createNemesis: (String,Int,String,Boolean,Boolean,Boolean) -> Unit = { _,_,_,_,_,_ -> },
    val acceptNemesis: (String,Boolean,Boolean,Boolean) -> Unit = { _,_,_,_ -> },
    val cancelNemesis: (String) -> Unit = {}, val retryNemesisMutation: () -> Unit = {},
    val readPhotoCapabilities: () -> Unit = {},
    val uploadPhoto:(String,PhotoUploadConsent,Boolean)->Unit={_,_,_->},
    val retryPhotoUpload:()->Unit={},val discardUnsentPhotoUpload:()->Unit={},
    val readPhotoAnalysis:()->Unit={},val restorePhotoAnalysis:()->Unit={},val stopPhotoAnalysis:()->Unit={},val clearPhotoAnalysis:()->Unit={},
    val cancelPhotoAnalysis:(String,Long)->Unit={_,_->},val retryPhotoCancellation:(String)->Unit={},val releaseCancelledPhoto:(String)->Unit={},val photoDraft:PhotoDraftActions=PhotoDraftActions(),
    val synchronizeMeals:(pl.roseru.kalorie.data.OwnerLease)->Unit={},
    val loadConflicts:(pl.roseru.kalorie.data.OwnerLease)->Unit={},
    val nextConflicts:(pl.roseru.kalorie.data.OwnerLease)->Unit={},
    val previousConflicts:(pl.roseru.kalorie.data.OwnerLease)->Unit={},
    val openConflict:(pl.roseru.kalorie.data.OwnerLease,String)->Unit={_,_->},
    val closeConflict:(pl.roseru.kalorie.data.OwnerLease)->Unit={},
    val resolveConflict:(pl.roseru.kalorie.data.OwnerLease,String,pl.roseru.kalorie.data.ConflictChoice)->Unit={_,_,_->},
    val applyDiaryCopy:(pl.roseru.kalorie.data.OwnerLease)->Unit={})

@Composable fun SessionScreen(view: SessionView, actions: SessionActions, back: () -> Unit, backLabel: String = "Wróć do profilu", onImport:(()->Unit)?=null,syncStatus:String?=null) {
    val account = view.binding?.owner?.kind == "account"
    var confirmLogout by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        TextButton(onClick = back) { Text(backLabel) }
        Text("Konto i logowanie", style = MaterialTheme.typography.headlineLarge)
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (account) "Konto · ${view.binding?.owner?.subject?.take(8)}" else "Gość poligonowy",
                    style = MaterialTheme.typography.titleLarge, modifier = Modifier.testTag("session-owner"))
                Text(if (account) "Dziennik tego konta zapisujesz również bez internetu." else "Zapisuj posiłki i wagę bez konta i internetu.")
                if (account) Text(if (view.hasSession) "Sesja dostępna" else "Sesja wymaga odnowienia", Modifier.testTag("session-status"))
            }
        }
        Text("Każde konto ma osobny dziennik. Logowanie nie przenosi wpisów gościa.")
        if (!view.configured) Text("Logowanie będzie dostępne po podłączeniu serwera aplikacji. Możesz dalej korzystać z dziennika offline.")
        view.message?.let { Text(it, modifier = Modifier.testTag("session-message")) }
        if (view.busy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Łączę z dostawcą logowania…") }
        Button(onClick = actions.login, enabled = view.configured && !view.busy && !view.pendingLogin,
            modifier = Modifier.fillMaxWidth().testTag("session-login")) { Text(if (account) "Zaloguj się ponownie / zmień konto" else "Zaloguj się w przeglądarce") }
        if (view.pendingLogin || view.busy) OutlinedButton(onClick = actions.cancel, modifier = Modifier.fillMaxWidth()) { Text("Anuluj logowanie") }
        if(account && onImport!=null) {
            OutlinedButton(onClick=onImport,enabled=view.serverLinked && !view.pendingLogin,
                modifier=Modifier.fillMaxWidth().testTag("session-import")) {Text("Import i uzgadnianie danych")}
            if(!view.serverLinked)Text("Najpierw połącz to konto z serwerem. Wpisy pozostają na urządzeniu.")
        }
        if(account && syncStatus!=null)Text(syncStatus,Modifier.testTag("sync-background-status"))
        if (account) {
            MealPushPanel(view,actions.synchronizeMeals)
            SyncConflictPanel(view,actions)
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Połączenie z serwerem", style = MaterialTheme.typography.titleMedium)
                    Text(when {
                        view.requiresRecovery -> "Stan serwera się zmienił. Dane wymagają uzgodnienia."
                        view.serverLinked -> "Konto powiązane z serwerem."
                        else -> "Konto nie jest jeszcze powiązane z serwerem."
                    }, modifier = Modifier.testTag("bootstrap-status"))
                    Text("Dziennik i oczekujące wpisy pozostają na urządzeniu. Połączenie konta nie wysyła posiłków ani wpisów gościa.")
                    if (!view.apiConfigured) Text("Połączenie będzie dostępne po podłączeniu serwera aplikacji.")
                    if (view.bootstrapBusy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Łączę konto z serwerem…") }
                    OutlinedButton(onClick = actions.bootstrap,
                        enabled = view.apiConfigured && !view.bootstrapBusy && !view.profileBusy && !view.mealPushBusy && !view.snapshotBusy && !view.rankingConsentBusy && !view.rankingBusy && !view.busy && !view.pendingLogin,
                        modifier = Modifier.fillMaxWidth().testTag("session-bootstrap")) {
                        Text(if (view.serverLinked) "Sprawdź połączenie" else "Połącz konto z serwerem")
                    }
                }
            }
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Profil na serwerze", style = MaterialTheme.typography.titleMedium)
                    Text("Odczyt pokazuje dane serwerowe osobno. Twój lokalny profil i cel kalorii pozostają bez zmian.")
                    if (view.profileBusy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Pobieram profil…") }
                    view.serverProfile?.let { result ->
                        val profile = result.profile
                        if (profile == null) Text("Na serwerze nie ma jeszcze profilu.", Modifier.testTag("server-profile-empty"))
                        else {
                            Text(profile.pseudonym, Modifier.testTag("server-profile-name"))
                            Text("Wzrost: ${profile.heightCm?.let { "$it cm" } ?: "brak danych"}")
                            Text(profile.activityClass.label)
                            Text("Strefa czasu: ${profile.timeZone}")
                        }
                        Text("Ranking: ${if (result.consents.ranking) "zgoda udzielona" else "zgoda nieudzielona"}")
                        Text("Automatyczna korekta zapotrzebowania: ${if (result.consents.automaticEnergyAdjustment) "zgoda udzielona" else "zgoda nieudzielona"}")
                        Text("Podgląd z ostatniego odczytu w tej sesji. Odśwież, aby sprawdzić zmiany.")
                    }
                    OutlinedButton(onClick = actions.readProfile,
                        enabled = view.apiConfigured && view.serverLinked && !view.requiresRecovery && !view.busy &&
                            !view.bootstrapBusy && !view.profileBusy && !view.mealPushBusy && !view.snapshotBusy && !view.motivationBusy && !view.rankingConsentBusy && !view.rankingBusy && !view.pendingLogin,
                        modifier = Modifier.fillMaxWidth().testTag("session-read-profile")) { Text("Pobierz profil z serwera") }
                }
            }
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Kopia danych serwera", style = MaterialTheme.typography.titleMedium)
                    Text("Pełna kopia uzupełnia posiłki, wagę, profil, cele, kompletność dni i prywatne produkty. Niewysłane lokalne poprawki pozostają zachowane do uzgodnienia.")
                    val status = view.snapshot
                    if (status?.completedTime != null) {
                        Text("Ostatnia pełna kopia: ${status.completedTime}", Modifier.testTag("snapshot-complete"))
                        Text("Rekordy: ${status.completedItems} · Strony: ${status.completedPages}")
                    } else Text("Pełna kopia nie została jeszcze pobrana.")
                    if (status != null && status.pendingPages > 0) Text("Zapisany postęp · Rekordy: ${status.pendingItems} · Strony: ${status.pendingPages}", Modifier.testTag("snapshot-progress"))
                    view.diaryApplication?.let { applied ->
                        Text("Dziennik uzupełniony: ${applied.appliedAt}", Modifier.testTag("diary-copy-applied"))
                        Text("Uwzględnione rekordy: ${applied.included} · Lokalne zmiany do uzgodnienia: ${applied.held}", Modifier.testTag("diary-copy-counts"))
                    }
                    if (view.snapshotBusy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text(if(view.diaryApplying) "Uzupełniam dziennik…" else "Pobieram kopię…") }
                    if (view.requiresRecovery) Text("Możesz pobrać kopię do uzgodnienia danych. Wysyłanie wpisów wymaga zakończenia uzgodnienia.")
                    if (status?.blocked == true) Text("Pobieranie zablokowane — konto jest usuwane.")
                    if (status?.needsBootstrap == true) Text("Najpierw wybierz Sprawdź połączenie, aby ponownie potwierdzić stan konta.")
                    OutlinedButton(onClick = actions.downloadSnapshot,
                        enabled = view.apiConfigured && view.serverLinked && status?.blocked != true && status?.needsBootstrap != true && !view.busy &&
                            !view.bootstrapBusy && !view.profileBusy && !view.mealPushBusy && !view.snapshotBusy && !view.motivationBusy && !view.rankingConsentBusy && !view.rankingBusy && !view.pendingLogin,
                        modifier = Modifier.fillMaxWidth().testTag("session-download-snapshot")) {
                        Text(if (status != null && status.pendingPages > 0) "Wznów pobieranie kopii" else "Pobierz kopię danych serwera")
                    }
                    if(status?.completedTime!=null && !view.requiresRecovery) OutlinedButton(
                        onClick={view.binding?.lease?.let(actions.applyDiaryCopy)},
                        enabled=!view.snapshotBusy && !view.mealPushBusy && !view.bootstrapBusy && !view.profileBusy &&
                            !view.busy && !view.pendingLogin && status.blocked!=true && status.needsBootstrap!=true,
                        modifier=Modifier.fillMaxWidth().testTag("session-apply-diary-copy")) {
                        Text("Uzupełnij dziennik z zapisanej kopii")
                    }
                }
            }
            OutlinedButton(onClick = actions.refresh, enabled = view.configured && !view.busy && !view.pendingLogin,
                modifier = Modifier.fillMaxWidth().testTag("session-refresh")) { Text("Odnów sesję") }
            OutlinedButton(onClick = { confirmLogout = true }, modifier = Modifier.fillMaxWidth().testTag("session-logout")) { Text("Wyloguj i otwórz gościa") }
        }
    }
    if (confirmLogout) AlertDialog(onDismissRequest = { confirmLogout = false }, title = { Text("Wylogować z aplikacji?") },
        text = { Text("Sesja na tym urządzeniu zostanie usunięta. Dzienniki konta i gościa pozostaną zapisane osobno. Sesja w przeglądarce pozostaje u dostawcy logowania.") },
        confirmButton = { TextButton(onClick = { confirmLogout = false; actions.logout() }, modifier = Modifier.testTag("confirm-session-logout")) { Text("Wyloguj") } },
        dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text("Anuluj") } })
}
