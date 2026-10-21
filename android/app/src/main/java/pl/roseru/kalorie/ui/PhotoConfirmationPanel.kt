package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import pl.roseru.kalorie.session.*

/** Approval is tied to the displayed account, proposal revision and local edit revision. */
@Composable fun PhotoConfirmationPanel(session:SessionView,actions:PhotoDraftActions) {
    val status=session.photoConfirmation
    val draft=session.photoMealDraft
    val row=session.photoUpload
    var approve by remember(session.binding?.lease,status,session.requiresRecovery) {mutableStateOf(false)}
    var reopen by remember(session.binding?.lease,status,session.requiresRecovery) {mutableStateOf(false)}
    val lifecycle=LocalLifecycleOwner.current
    DisposableEffect(lifecycle,session.binding?.lease,status,session.requiresRecovery) {
        val observer=LifecycleEventObserver {_,event->if(event==Lifecycle.Event.ON_STOP){approve=false;reopen=false}}
        lifecycle.lifecycle.addObserver(observer)
        onDispose {lifecycle.lifecycle.removeObserver(observer)}
    }
    if(status==null || draft==null || row==null || status.operationId!=row.operationId ||
        draft.operationId!=status.operationId || draft.editRevision!=status.editRevision || row.blocked)return
    val idle=!session.photoUploadBusy && !session.busy && !session.pendingLogin && !session.requiresRecovery &&
        !session.bootstrapBusy && !session.profileBusy && !session.mealPushBusy && !session.snapshotBusy && !session.motivationBusy &&
        !session.rankingConsentBusy && !session.rankingBusy && !session.nemesisBusy && !session.nemesisMutationBusy && !session.photoCapabilitiesBusy
    val network=idle && session.hasSession && session.serverLinked && session.binding?.owner?.kind=="account"
    Column(Modifier.fillMaxWidth().testTag("photo-confirmation-panel"),verticalArrangement=Arrangement.spacedBy(8.dp)) {
        if(status.canStart)Button(onClick={approve=true},enabled=network,
            modifier=Modifier.fillMaxWidth().testTag("photo-confirmation-start")){Text("Dodaj do dziennika")}
        if(status.canRetry) {
            Text("Decyzja dodania posiłku jest zapisana. Brak odpowiedzi nie oznacza, że serwer jej nie przyjął.")
            OutlinedButton(onClick={actions.retryConfirmation(status.operationId)},enabled=network,
                modifier=Modifier.fillMaxWidth().testTag("photo-confirmation-retry")){Text("Ponów dodanie posiłku")}
        }
        if(status.canReopen)OutlinedButton(onClick={reopen=true},
            enabled=idle && session.serverLinked && session.binding?.owner?.kind=="account",
            modifier=Modifier.fillMaxWidth().testTag("photo-confirmation-reopen")){Text("Wróć do poprawek")}
        if(status.rejected && !status.canReopen)Text("Decyzja odrzucona przez serwer. Sprawdź wynik analizy. Zapisane poprawki pozostają do odczytu.",
            modifier=Modifier.testTag("photo-confirmation-rejected"))
        if(!session.hasSession)Text("Połącz konto, aby zatwierdzić posiłek. Poprawki pozostają na telefonie.")
    }
    if(reopen && status.canReopen)AlertDialog(onDismissRequest={reopen=false},title={Text("Wrócić do poprawek?")},
        text={Text("Serwer odrzucił poprzednią decyzję. Zachowamy jej historię i udostępnimy edycję tych samych składników. Dodanie posiłku będzie wymagało osobnego zatwierdzenia.")},
        confirmButton={TextButton(onClick={reopen=false;actions.reopen(status.operationId,status.revision,status.editRevision)},
            enabled=idle && session.serverLinked && session.binding?.owner?.kind=="account",
            modifier=Modifier.testTag("photo-confirmation-reopen-approve")){Text("Wróć do poprawek")}},
        dismissButton={TextButton(onClick={reopen=false},modifier=Modifier.testTag("photo-confirmation-reopen-dismiss")){Text("Zachowaj obecny stan")}})
    if(approve && status.canStart)AlertDialog(onDismissRequest={approve=false},title={Text("Dodać posiłek do dziennika?")},
        text={Column(Modifier.heightIn(max=320.dp).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            Text(draft.title);Text("Dzień: ${draft.localDate}")
            Text("Zatwierdzisz zapisane składniki, porcje i wartości. Po potwierdzeniu serwera dodamy posiłek do dziennika na telefonie.")
            Text("Brakujące wartości pozostaną oznaczone jako brak danych. Wpis do synchronizacji będzie oczekiwał na osobne potwierdzenie.")
        }},
        confirmButton={TextButton(onClick={approve=false;actions.confirm(status.operationId,status.revision,status.editRevision)},
            enabled=network,modifier=Modifier.testTag("photo-confirmation-approve")){Text("Tak, dodaj posiłek")}},
        dismissButton={TextButton(onClick={approve=false},modifier=Modifier.testTag("photo-confirmation-dismiss")){Text("Wróć do poprawek")}})
}
