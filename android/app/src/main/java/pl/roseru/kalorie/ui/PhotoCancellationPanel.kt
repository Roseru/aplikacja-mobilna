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
import pl.roseru.kalorie.session.SessionView

/** Approval stays in memory and expires when its account, operation or shown revision changes. */
@Composable fun PhotoCancellationPanel(session:SessionView,onCancel:(String,Long)->Unit,
    onRetry:(String)->Unit,onRelease:(String)->Unit) {
    val status=session.photoCancellation
    val row=session.photoUpload
    var confirm by remember(session.binding?.lease,status?.operationId,status?.revision,status?.canStart,session.requiresRecovery) {mutableStateOf(false)}
    val lifecycle=LocalLifecycleOwner.current
    DisposableEffect(lifecycle,session.binding?.lease,status?.operationId,status?.revision,status?.canStart,session.requiresRecovery) {
        val observer=LifecycleEventObserver {_,event->if(event==Lifecycle.Event.ON_STOP)confirm=false}
        lifecycle.lifecycle.addObserver(observer)
        onDispose {lifecycle.lifecycle.removeObserver(observer)}
    }
    if(status==null || row==null || row.operationId!=status.operationId || row.blocked || !row.acknowledged)return
    val idle=!session.photoUploadBusy && !session.busy && !session.pendingLogin && !session.requiresRecovery &&
        !session.bootstrapBusy && !session.profileBusy && !session.mealPushBusy && !session.snapshotBusy && !session.motivationBusy &&
        !session.rankingConsentBusy && !session.rankingBusy && !session.nemesisBusy && !session.nemesisMutationBusy && !session.photoCapabilitiesBusy
    val network=idle && session.hasSession && session.binding?.owner?.kind=="account" && session.serverLinked
    Card(Modifier.fillMaxWidth().testTag("photo-cancellation-panel")) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            if(status.cancelled) {
                Text("Anulowanie potwierdzone",style=MaterialTheme.typography.titleMedium)
                Text("Zamknij to zlecenie, aby móc wysłać kolejne zdjęcie. Zdjęcie źródłowe i dziennik pozostaną na telefonie.")
                if(session.photoMealDraft!=null)Text("Zamknięcie usunie również szkic poprawek tego anulowanego zlecenia.")
                OutlinedButton(onClick={onRelease(status.operationId)},enabled=idle,
                    modifier=Modifier.fillMaxWidth().testTag("photo-cancellation-release")){Text("Zamknij anulowane zlecenie")}
            } else {
                if(status.revisionConflict)Text("Stan analizy zmienił się. Sprawdź wynik przed ponownym anulowaniem.")
                if(status.canRetry) {
                    Text("Zapisana decyzja anulowania",style=MaterialTheme.typography.titleMedium)
                    Text("Brak potwierdzenia nie oznacza, że serwer nie anulował analizy. Ponowienie dotyczy tej samej decyzji.")
                    OutlinedButton(onClick={onRetry(status.operationId)},enabled=network,
                        modifier=Modifier.fillMaxWidth().testTag("photo-cancellation-retry")){Text("Ponów anulowanie")}
                }
                if(status.canStart) TextButton(onClick={confirm=true},enabled=network,
                    modifier=Modifier.testTag("photo-cancellation-start")){Text("Anuluj analizę na serwerze")}
            }
        }
    }
    if(confirm && status.canStart && !status.cancelled) AlertDialog(onDismissRequest={confirm=false},
        title={Text("Anulować analizę zdjęcia?")},
        text={Column(Modifier.heightIn(max=320.dp).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            Text("Wyślemy do serwera prośbę o anulowanie tej analizy. Nie dodamy posiłku do dziennika.")
            Text("Jeśli zdjęcie przekazano już dostawcy AI, anulowanie nie cofnie jego wcześniejszego przetwarzania. Zdjęcie źródłowe na telefonie i zapisane posiłki pozostaną zachowane.")
        }},
        confirmButton={TextButton(onClick={confirm=false;onCancel(status.operationId,status.revision)},enabled=network,
            modifier=Modifier.testTag("photo-cancellation-confirm")){Text("Tak, anuluj analizę")}},
        dismissButton={TextButton(onClick={confirm=false},modifier=Modifier.testTag("photo-cancellation-dismiss")){Text("Wróć")}})
}
