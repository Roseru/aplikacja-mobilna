package pl.roseru.kalorie.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable internal fun SavedPreviewNotice(fetchedAtMillis:Long,warning:String?=null) {
    val date=Instant.ofEpochMilli(fetchedAtMillis).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm"))
    Text("Zapisany podgląd · pobrano $date",Modifier.testTag("saved-preview-date"),style=MaterialTheme.typography.labelLarge)
    Text("Dane historyczne do odczytu. Wyniki i udostępnianie mogły się zmienić. Odśwież po odzyskaniu połączenia.",
        Modifier.testTag("saved-preview-readonly"),style=MaterialTheme.typography.bodySmall)
    warning?.let {Text(it,Modifier.testTag("saved-preview-warning"),style=MaterialTheme.typography.bodySmall)}
}
