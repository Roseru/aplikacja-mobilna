package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.PhotoCapabilitiesState
import pl.roseru.kalorie.session.SessionView

@Composable fun PhotoCapabilitiesPanel(session: SessionView, onRead: () -> Unit) {
    Card(Modifier.fillMaxWidth().testTag("photo-capabilities")) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Analiza zdjęcia", style = MaterialTheme.typography.titleMedium)
            val eligible = session.binding?.owner?.kind == "account" && session.hasSession &&
                session.serverLinked && !session.requiresRecovery && !session.pendingLogin && !session.busy
            when {
                session.binding?.owner?.kind != "account" -> Text("Zaloguj się, aby sprawdzić dostępność analizy. Zdjęcia możesz zachować offline.")
                !session.photoCapabilitiesConfigured -> Text("Analiza nie jest jeszcze skonfigurowana. Możesz dodać posiłek ręcznie.")
                !eligible -> Text("Połącz konto z serwerem, aby sprawdzić analizę. Zdjęcia pozostają na telefonie.")
                else -> {
                    when (val state = session.photoCapabilities) {
                        PhotoCapabilitiesState.NotRequested -> Text("Sprawdź aktualnego dostawcę i limity przed wysłaniem zdjęcia.")
                        PhotoCapabilitiesState.Loading -> { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Sprawdzanie dostępności…") }
                        is PhotoCapabilitiesState.Failed -> Text(state.message, Modifier.testTag("photo-capabilities-error"))
                        is PhotoCapabilitiesState.Ready -> {
                            val read = state.read
                            Text(if (read.provider == "mock") "Scenariusz testowy serwera — bez rozpoznawania przez Gemini." else "Dostawca: Google Gemini · ${read.model}",
                                Modifier.testTag("photo-provider"))
                            Text(if (read.available) "Usługa jest dostępna." else "Usługa jest chwilowo niedostępna. Dodaj posiłek ręcznie.", Modifier.testTag("photo-availability"))
                            Text("Limit: ${read.dailyPhotos} zdjęć dziennie · obraz do ${read.imageBytes / 1024} KB. Sprawdzenie nie rezerwuje miejsca.")
                            Text("Przed analizą poprosimy o osobną zgodę na wybrane zdjęcie. Wynik będzie szacunkiem do poprawienia; obraz na serwerze jest przechowywany do zakończenia zadania, maksymalnie 24 godziny. Dostawca stosuje własne zasady przetwarzania.")
                            Text("Wybierz zapisane zdjęcie i potwierdź zgodę przed wysłaniem.", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    OutlinedButton(onClick = onRead, enabled = !session.photoCapabilitiesBusy && !session.bootstrapBusy &&
                        !session.profileBusy && !session.snapshotBusy && !session.motivationBusy && !session.rankingConsentBusy &&
                        !session.rankingBusy && !session.nemesisBusy && !session.nemesisMutationBusy && !session.photoUploadBusy,
                        modifier = Modifier.fillMaxWidth().testTag("photo-check-capabilities")) { Text("Sprawdź dostępność") }
                }
            }
        }
    }
}
