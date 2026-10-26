package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.awaitCancellation
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.session.*
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable internal fun RankingScreen(view: SessionView, actions: SessionActions, onBack: () -> Unit, onAccount: () -> Unit, onConsent: () -> Unit) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val liveActions by rememberUpdatedState(actions)
    val clear by rememberUpdatedState(actions.clearRanking)
    LaunchedEffect(lifecycle,view.binding?.lease) {lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
        view.binding?.lease?.let {liveActions.restorePrivatePreview(it,PrivatePreviewKind.RANKING,null)}
        awaitCancellation()
    }}
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP) clear() }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); clear() }
    }
    val account = view.binding?.owner?.kind == "account"
    val available = account && view.rankingConfigured && view.serverLinked && !view.requiresRecovery && !view.pendingLogin
    val busy = view.mealPushBusy || view.busy || view.bootstrapBusy || view.profileBusy || view.motivationBusy || view.snapshotBusy || view.rankingConsentBusy || view.rankingBusy
    val visible=account && view.serverLinked && !view.requiresRecovery && !view.pendingLogin && !view.busy
    val state = if (visible && (available || view.ranking is RankingState.Saved)) view.ranking else RankingState.NotRequested
    val listState = rememberLazyListState()
    val page = when(state){is RankingState.Ready->state.page;is RankingState.Saved->state.page;else->null}
    LaunchedEffect(page) { if (page != null) listState.scrollToItem(0) }
    LazyColumn(Modifier.fillMaxSize().testTag("ranking-content"), state = listState, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { TextButton(onClick = onBack) { Text("Wróć") } }
        item {
            Text("Ranking", style = MaterialTheme.typography.headlineLarge)
            Text("Punkty za regularność", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Kompletne dni i realizacja celu dają punkty. Większy deficyt nie zwiększa wyniku.", style = MaterialTheme.typography.bodySmall)
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
            is RankingState.Saved -> {
                SavedPreviewNotice(state.fetchedAtMillis,state.warning)
                Text("Zapisana strona rankingu",Modifier.testTag("ranking-state"),style=MaterialTheme.typography.labelLarge)
                if(state.page.items.isEmpty())Text("Zapisana strona jest pusta.",Modifier.testTag("ranking-empty"))
                TextButton(onClick={view.binding?.lease?.let {actions.clearSavedPrivatePreview(it,PrivatePreviewKind.RANKING)}},modifier=Modifier.testTag("ranking-saved-clear")){Text("Usuń zapisany podgląd")}
            }
            is RankingState.Ready -> {
                Text("Odczyt: " + state.page.asOf.atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm")), Modifier.testTag("ranking-state"), style = MaterialTheme.typography.labelLarge)
                Text("Remisy mają wspólną pozycję. Lista jest zmienna: między stronami możliwe powtórzenia lub pominięcia.", style = MaterialTheme.typography.bodySmall)
                if (state.page.items.isEmpty()) Text("Na tej stronie nie ma osób do wyświetlenia. Możesz odświeżyć listę od początku.", Modifier.testTag("ranking-empty"))
            }
        } }
        if (page!=null) itemsIndexed(page.items, key = { index, _ -> index }) { index, entry ->
            Card(Modifier.fillMaxWidth().testTag("ranking-entry-$index")) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    // Keep long server counts readable without squeezing the name or clipping digits.
                    if (LocalDensity.current.fontScale > 1.3f || entry.position > 99_999 || entry.points > 99_999) {
                        Text("Pozycja ${entry.position}", style = MaterialTheme.typography.labelLarge)
                        Text("${entry.points} pkt", style = MaterialTheme.typography.titleMedium)
                    } else {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("Pozycja ${entry.position}", Modifier.weight(1f), style = MaterialTheme.typography.labelLarge)
                            Text("${entry.points} pkt", style = MaterialTheme.typography.titleMedium)
                        }
                    }
                    Text(entry.pseudonym, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text("${entry.rank} · Odznaki: ${entry.activeBadges}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        item {
            if(visible && state is RankingState.Failed)TextButton(onClick={view.binding?.lease?.let {actions.restorePrivatePreview(it,PrivatePreviewKind.RANKING,null)}},modifier=Modifier.testTag("ranking-saved-open")){Text("Pokaż zapisany podgląd")}
            if (available) {
                if (state is RankingState.Ready && state.page.hasMore) Button(onClick = actions.nextRankingPage, enabled = !busy, modifier = Modifier.testTag("ranking-next")) { Text("Następna strona") }
                if (state is RankingState.Failed && state.canRetry) OutlinedButton(onClick = actions.retryRankingPage, enabled = !busy, modifier = Modifier.testTag("ranking-retry")) { Text("Ponów tę samą stronę") }
                TextButton(onClick = actions.readRanking, enabled = !busy, modifier = Modifier.testTag("ranking-read")) { Text(if (state == RankingState.NotRequested) "Pobierz ranking" else "Odśwież od początku") }
            } else TextButton(onClick = onAccount, modifier = Modifier.testTag("ranking-account")) { Text("Konto i połączenie") }
        }
    }
}
