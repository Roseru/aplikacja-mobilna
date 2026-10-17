package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.session.SessionView

@Composable fun PhotoUploadPanel(session:SessionView,onRetry:()->Unit,onDiscard:()->Unit,
    onRead:()->Unit={},onStop:()->Unit={}) {
    if(session.photoUpload==null && !session.photoUploadBusy && session.photoUploadMessage==null) return
    Card(Modifier.fillMaxWidth().testTag("photo-upload-panel")) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            Text("Zlecenie analizy",style=MaterialTheme.typography.titleMedium)
            if(session.photoUploadBusy){LinearProgressIndicator(Modifier.fillMaxWidth());Text(if(session.photoReadBusy) "Sprawdzanie wyniku analizy…" else "Przygotowanie lub wysyłanie zdjęcia…")}
            if(session.photoReadBusy) TextButton(onClick=onStop,modifier=Modifier.testTag("photo-analysis-stop")){Text("Zatrzymaj sprawdzanie")}
            session.photoUploadMessage?.let { Text(it,Modifier.testTag("photo-upload-message")) }
            session.photoUpload?.let { row->
                Text(when {
                    row.acknowledged->"Zdjęcie przyjęte do analizy. Posiłek nie został jeszcze zapisany."
                    row.blocked->"To zlecenie wymaga sprawdzenia stanu serwera. Zdjęcie i lokalny dziennik są zachowane."
                    row.attempted->"Próba wysyłki nie ma potwierdzenia. Ponowienie użyje tego samego zdjęcia i zlecenia."
                    else->"Niewysłane zlecenie zapisane na telefonie."
                },Modifier.testTag("photo-upload-state"))
                if(row.retryAtMillis>0 && !row.acknowledged) Text("Po przerwie wskazanej przez serwer możesz ponowić to samo zlecenie.")
                if(row.acknowledged && row.retryAtMillis>0) Text("Kolejny odczyt uwzględni przerwę wskazaną przez serwer.")
                if(row.acknowledged && !row.blocked) OutlinedButton(onClick=onRead,
                    enabled=!session.photoUploadBusy && !session.busy && !session.pendingLogin && !session.requiresRecovery &&
                        !session.bootstrapBusy && !session.profileBusy && !session.snapshotBusy && !session.motivationBusy &&
                        !session.rankingConsentBusy && !session.rankingBusy && !session.nemesisBusy && !session.nemesisMutationBusy && !session.photoCapabilitiesBusy,
                    modifier=Modifier.fillMaxWidth().testTag("photo-analysis-read")){Text("Sprawdź wynik")}
                if(!row.acknowledged && !row.blocked) OutlinedButton(onClick=onRetry,
                    enabled=!session.photoUploadBusy && !session.busy && !session.pendingLogin && !session.requiresRecovery,
                    modifier=Modifier.fillMaxWidth().testTag("photo-upload-retry")){Text("Ponów zlecenie")}
                if(!row.attempted && !row.acknowledged) TextButton(onClick=onDiscard,enabled=!session.photoUploadBusy,
                    modifier=Modifier.testTag("photo-upload-discard")){Text("Usuń niewysłane zlecenie")}
            }
        }
    }
}
