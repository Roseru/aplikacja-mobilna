package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.session.*
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable internal fun RankingScreen(view: SessionView, actions: SessionActions, onBack: () -> Unit, onAccount: () -> Unit, onConsent: () -> Unit) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val clear by rememberUpdatedState(actions.clearRanking)
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP) clear() }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); clear() }
    }
    val account = view.binding?.owner?.kind == "account"
    val available = account && view.rankingConfigured && view.serverLinked && !view.requiresRecovery && !view.pendingLogin
    val busy = view.busy || view.bootstrapBusy || view.profileBusy || view.motivationBusy || view.snapshotBusy || view.rankingConsentBusy || view.rankingBusy
    val state = if (available && !view.busy) view.ranking else RankingState.NotRequested
    LazyColumn(Modifier.fillMaxSize().testTag("ranking-content"), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { TextButton(onClick = onBack) { Text("Wróć") } }
        item {
            Text("Ranking", style = MaterialTheme.typography.headlineLarge)
            Text("Punkty za regularność", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Potwierdzone punkty za kompletne dni i realizację celu. Większy deficyt nie daje dodatkowych punktów.", style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = onConsent, modifier = Modifier.testTag("ranking-consents")) { Text("Udział w rankingu") }
        }
        item { when (state) {
            RankingState.NotRequested -> Text(when {
                !account -> "Zaloguj się, aby zobaczyć ranking. Lokalne osiągnięcia działają bez konta."
                !view.rankingConfigured -> "Ranking wymaga skonfigurowanego połączenia z serwerem."
                !view.serverLinked || view.requiresRecovery -> "Najpierw połącz konto i uzgodnij stan serwera."
                else -> "Pobierz aktualną listę. Jej przeglądanie nie włącza udziału."
            }, Modifier.testTag("ranking-state"))
            RankingState.Loading -> { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Pobieram bieżącą stronę…", Modifier.testTag("ranking-state")) }
            is RankingState.Failed -> Text(state.message, Modifier.testTag("ranking-state"))
            is RankingState.Ready -> {
                Text("Odczyt: " + state.page.asOf.atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm")), Modifier.testTag("ranking-state"), style = MaterialTheme.typography.labelLarge)
                Text("Lista zmienia się na żywo. Między stronami możliwe powtórzenia lub pominięcia; pozycje i remisy wylicza serwer.", style = MaterialTheme.typography.bodySmall)
                if (state.page.items.isEmpty()) Text("Nie ma jeszcze osób z potwierdzonym udziałem i punktami.", Modifier.testTag("ranking-empty"))
            }
        } }
        if (state is RankingState.Ready) itemsIndexed(state.page.items, key = { index, _ -> index }) { index, entry ->
            Card(Modifier.fillMaxWidth().testTag("ranking-entry-$index")) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Pozycja ${entry.position}", style = MaterialTheme.typography.labelLarge)
                    Text(entry.pseudonym, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text("${entry.points} pkt", style = MaterialTheme.typography.titleLarge)
                    Text("${entry.rank} · Odznaki: ${entry.activeBadges}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        item {
            if (available) {
                if (state is RankingState.Ready && state.page.hasMore) Button(onClick = actions.nextRankingPage, enabled = !busy, modifier = Modifier.testTag("ranking-next")) { Text("Następna strona") }
                if (state is RankingState.Failed && state.canRetry) OutlinedButton(onClick = actions.retryRankingPage, enabled = !busy, modifier = Modifier.testTag("ranking-retry")) { Text("Ponów tę samą stronę") }
                TextButton(onClick = actions.readRanking, enabled = !busy, modifier = Modifier.testTag("ranking-read")) { Text(if (state == RankingState.NotRequested) "Pobierz ranking" else "Odśwież od początku") }
            } else TextButton(onClick = onAccount, modifier = Modifier.testTag("ranking-account")) { Text("Konto i połączenie") }
        }
    }
}
