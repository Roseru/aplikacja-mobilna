package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.sync.SnapshotMaintenanceViewModel

@Composable fun SnapshotMaintenancePanel(model:SnapshotMaintenanceViewModel,onAccount:(()->Unit)?=null) {
    val state by model.state.collectAsStateWithLifecycle()
    OutlinedCard(Modifier.fillMaxWidth().testTag("snapshot-maintenance")) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
            Text("Przerwane pobierania",style=MaterialTheme.typography.titleMedium)
            Text("Jeśli synchronizacja nie może rozpocząć kolejnego pobierania, sprawdź niedokończone próby z poprzednich sesji.",
                style=MaterialTheme.typography.bodyMedium)
            state.message?.let {Text(it,modifier=Modifier.testTag("snapshot-maintenance-message"),color=MaterialTheme.colorScheme.onSurfaceVariant)}
            OutlinedButton(onClick=model::prepare,enabled=!state.busy,modifier=Modifier.fillMaxWidth().testTag("snapshot-maintenance-check")) {
                Text(if(state.busy)"Sprawdzam…" else "Sprawdź wcześniejsze pobierania")
            }
            if(onAccount!=null)TextButton(onClick=onAccount,enabled=!state.busy,modifier=Modifier.fillMaxWidth()) {Text("Przejdź do synchronizacji konta")}
        }
    }
    state.review?.let {review->
        AlertDialog(onDismissRequest=model::dismiss,modifier=Modifier.testTag("snapshot-maintenance-dialog"),
            title={Text("Przerwać wcześniejsze pobierania?")},
            text={Text("Liczba prób: ${review.count}. Pobierania z poprzednich sesji zostaną zakończone. Posiłki, niewysłane zmiany i potwierdzenia pozostają zapisane. Kolejną synchronizację uruchomisz samodzielnie na ekranie konta.")},
            confirmButton={TextButton(onClick={model.confirm(review)},enabled=!state.busy,modifier=Modifier.testTag("snapshot-maintenance-confirm")) {Text("Przerwij pobierania")}},
            dismissButton={TextButton(onClick=model::dismiss,enabled=!state.busy,modifier=Modifier.testTag("snapshot-maintenance-cancel")) {Text("Anuluj")}})
    }
}
