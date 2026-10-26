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
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.delay
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.session.*
import java.math.MathContext
import java.math.RoundingMode
import java.time.format.DateTimeFormatter

@Composable internal fun NemesisScreen(view: SessionView, actions: SessionActions, onBack: () -> Unit, onAccount: () -> Unit) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val liveActions by rememberUpdatedState(actions)
    var selected by remember { mutableStateOf<String?>(null) }
    val account = view.binding?.owner?.kind == "account"
    val available = account && view.nemesisConfigured && view.serverLinked && !view.requiresRecovery && !view.pendingLogin
    val busy = view.mealPushBusy || view.busy || view.nemesisBusy || view.bootstrapBusy || view.profileBusy || view.snapshotBusy ||
        view.motivationBusy || view.rankingBusy || view.rankingConsentBusy || view.nemesisMutationBusy
    val visible=account && view.serverLinked && !view.requiresRecovery && !view.pendingLogin && !view.busy
    val state = if (visible && (available || view.nemesis is NemesisState.Saved)) view.nemesis else NemesisState.NotRequested
    val page=when(state){is NemesisState.ListReady->state.page;is NemesisState.ListSaved->state.page;else->null}
    val detail=when(state){is NemesisState.DetailReady->state.challenge;is NemesisState.DetailSaved->state.challenge;else->null}
    val stats=when(state){is NemesisState.DetailReady->state.statistics;is NemesisState.DetailSaved->state.statistics;else->null}
    fun refresh() { (selected?:detail?.id)?.let(liveActions.readNemesisChallenge) ?: liveActions.readNemesis() }
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP) liveActions.clearNemesis() }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer); liveActions.clearNemesis() }
    }
    // Entry/resume restores a dated local copy. Network refresh and all decisions stay explicit.
    LaunchedEffect(lifecycle,available,view.binding?.lease) {lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
        view.binding?.lease?.let {
            if(available)liveActions.enterNemesisPreview(it)
            else liveActions.restorePrivatePreview(it,PrivatePreviewKind.NEMESIS_LIST,null)
        }
        awaitCancellation()
    }}
    val liveResult=state is NemesisState.ListReady || state is NemesisState.DetailReady
    val pollTarget by rememberUpdatedState(selected?:detail?.id)
    LaunchedEffect(lifecycle,available,view.binding?.lease,liveResult) {
        if(available && liveResult)lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while(true){delay(45_000);pollTarget?.let(liveActions.readNemesisChallenge)}
        }
    }
    LazyColumn(Modifier.fillMaxSize().testTag("nemesis-content"), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { TextButton(onClick = onBack) { Text("Wróć") } }
        item {
            Text("Nemesis", style = MaterialTheme.typography.headlineLarge)
            Text("Regularność we dwoje", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Punkty za kompletne dni i realizację własnego celu. Większy deficyt nie daje przewagi.", style = MaterialTheme.typography.bodySmall)
        }
        if (available && view.nemesisMutationConfigured && state !is NemesisState.Saved) item { NemesisMutationPanel(view, liveActions, busy) }
        item { when (state) {
            NemesisState.NotRequested -> Text(when {
                !account -> "Zaloguj się, aby zobaczyć swoje rywalizacje. Dziennik i osiągnięcia są dostępne offline."
                !view.nemesisConfigured -> "Nemesis wymaga połączenia z serwerem."
                !view.serverLinked || view.requiresRecovery -> "Najpierw połącz konto i uzgodnij stan serwera."
                else -> "Pobierz bieżącą listę rywalizacji."
            }, Modifier.testTag("nemesis-state"))
            NemesisState.Loading -> { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Sprawdzam aktualne udostępnianie…", Modifier.testTag("nemesis-state")) }
            is NemesisState.Failed -> Text(state.message, Modifier.testTag("nemesis-state"))
            is NemesisState.ListSaved -> {
                SavedPreviewNotice(state.fetchedAtMillis,state.warning)
                Text("Zapisana lista rywalizacji",Modifier.testTag("nemesis-state"),style=MaterialTheme.typography.titleMedium)
                if(state.page.items.isEmpty())Text("Zapisana lista jest pusta.",Modifier.testTag("nemesis-empty"))
            }
            is NemesisState.DetailSaved -> {
                SavedPreviewNotice(state.fetchedAtMillis,state.warning)
                Text(statusLabel(state.challenge.status),Modifier.testTag("nemesis-state"),style=MaterialTheme.typography.titleMedium)
            }
            is NemesisState.ListReady -> {
                Text("Twoje rywalizacje", Modifier.testTag("nemesis-state"), style = MaterialTheme.typography.titleMedium)
                if (state.page.items.isEmpty()) Text("Na tej stronie nie ma rywalizacji. Zaproszenie rozpocznie rywalizację dopiero po akceptacji drugiej osoby.", Modifier.testTag("nemesis-empty"))
                Text("Lista jest aktualizowana na żywo. Między stronami możliwe powtórzenia lub pominięcia.", style = MaterialTheme.typography.bodySmall)
            }
            is NemesisState.DetailReady -> Text(statusLabel(state.challenge.status), Modifier.testTag("nemesis-state"), style = MaterialTheme.typography.titleMedium)
        } }
        if (page!=null) itemsIndexed(page.items, key = { _, item -> item.id }) { index, challenge ->
            Card(Modifier.fillMaxWidth().testTag("nemesis-entry-$index")) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(if (challenge.status == "cancelled") "Zakończone udostępnianie" else challenge.partner ?: "Uczestnik Nemesis",
                        style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text("${statusLabel(challenge.status)} · ${challenge.terms.days} dni", style = MaterialTheme.typography.bodySmall)
                    val cached=state as? NemesisState.ListSaved
                    TextButton(onClick = { selected = challenge.id
                        if(cached==null)liveActions.readNemesisChallenge(challenge.id)
                        else view.binding?.lease?.let {liveActions.restorePrivatePreview(it,PrivatePreviewKind.NEMESIS_DETAIL,challenge.id)}
                    }, enabled = !busy && (cached==null || challenge.id in cached.cachedDetails),
                        modifier = Modifier.testTag("nemesis-open-$index")) { Text("Zobacz szczegóły") }
                }
            }
        }
        if (detail!=null) {
            val challenge = detail
            item {
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (challenge.status != "cancelled") Text(challenge.partner ?: "Uczestnik Nemesis", style = MaterialTheme.typography.titleLarge,
                        maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.testTag("nemesis-partner"))
                    Text("Uzgodnione zasady", style = MaterialTheme.typography.titleMedium)
                    Text("${challenge.terms.days} dni · ${challenge.terms.zone.id}")
                    Text("Regularność i realizacja celu — udostępniane obu osobom.", style = MaterialTheme.typography.bodySmall)
                    Text("Zmiana masy: ${if (challenge.terms.weight) "udostępniana w procentach" else "nieudostępniana"}.", style = MaterialTheme.typography.bodySmall)
                    Text("Średni deficyt: ${if (challenge.terms.deficit) "udostępniany w procentach" else "nieudostępniany"}.", style = MaterialTheme.typography.bodySmall)
                    if (challenge.startDate != null) Text("${challenge.startDate} – ${challenge.endDate!!.minusDays(1)}", Modifier.testTag("nemesis-period"))
                    if (challenge.status == "invited") Text("Czeka na akceptację. Wyniki drugiej osoby nie są jeszcze udostępniane.")
                    if (challenge.status == "cancelled") Text("Udostępnianie zakończone. Dane drugiej osoby są niedostępne.")
                } }
            }
            stats?.let { statistics ->
                item {
                    Text(when (statistics.status) { "pending" -> "Czekamy na pierwszy zamknięty dzień"; "final" -> "Wynik ostateczny"; else -> "Wynik wstępny" },
                        Modifier.testTag("nemesis-result-state"), style = MaterialTheme.typography.titleLarge)
                    Text("Odczyt: " + statistics.asOf.atZone(challenge.terms.zone).format(DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm")), style = MaterialTheme.typography.bodySmall)
                    if (statistics.status == "pending") Text("Nie ma jeszcze dojrzałych danych do porównania. Wynik pojawi się po zamknięciu dnia.")
                    else if (statistics.status == "provisional") Text("Wynik może się zmienić po synchronizacji lub korekcie do " + challenge.deadline!!.atZone(challenge.terms.zone).format(DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm")) + ".", style = MaterialTheme.typography.bodySmall)
                }
                if (statistics.self != null && statistics.opponent != null) {
                    item {
                        Text(when (statistics.outcome) { "self_wins" -> "Prowadzisz punktami"; "opponent_wins" -> "Druga osoba prowadzi punktami"; else -> "Remis punktowy" },
                            Modifier.testTag("nemesis-outcome"), style = MaterialTheme.typography.titleMedium)
                    }
                    item { ParticipantCard("Ty", statistics.self, "self") }
                    item { ParticipantCard("Druga osoba", statistics.opponent, "opponent") }
                }
            }
        }
        item {
            if(state is NemesisState.Saved) {
                if(detail!=null)TextButton(onClick={selected=null;view.binding?.lease?.let {liveActions.restorePrivatePreview(it,PrivatePreviewKind.NEMESIS_LIST,null)}},enabled=!busy,modifier=Modifier.testTag("nemesis-saved-list")){Text("Zapisana lista")}
                TextButton(onClick={view.binding?.lease?.let {liveActions.clearSavedPrivatePreview(it,PrivatePreviewKind.NEMESIS_LIST)}},modifier=Modifier.testTag("nemesis-saved-clear")){Text("Usuń zapisane podglądy Nemesis")}
            }
            if(visible && state is NemesisState.Failed)TextButton(onClick={view.binding?.lease?.let {liveActions.restorePrivatePreview(it,PrivatePreviewKind.NEMESIS_LIST,null)}},modifier=Modifier.testTag("nemesis-saved-open")){Text("Pokaż zapisany podgląd")}
            if (available) {
                if (state is NemesisState.ListReady && state.page.nextCursor != null) Button(onClick = liveActions.nextNemesisPage,
                    enabled = !busy, modifier = Modifier.testTag("nemesis-next")) { Text("Następna strona") }
                if (state is NemesisState.Failed && state.canRetry) OutlinedButton(onClick = liveActions.retryNemesis,
                    enabled = !busy, modifier = Modifier.testTag("nemesis-retry")) { Text("Ponów ten sam odczyt") }
                if (selected != null) TextButton(onClick = { selected = null; liveActions.readNemesis() }, enabled = !busy,
                    modifier = Modifier.testTag("nemesis-list")) { Text("Wróć do listy") }
                TextButton(onClick = { refresh() }, enabled = !busy, modifier = Modifier.testTag("nemesis-refresh")) { Text("Odśwież") }
            } else TextButton(onClick = onAccount, modifier = Modifier.testTag("nemesis-account")) { Text("Konto i połączenie") }
        }
    }
}
private fun statusLabel(status: String) = when (status) { "invited" -> "Zaproszenie"; "active" -> "Aktywna"; "finished" -> "Okres zakończony"; else -> "Anulowana" }
@Composable private fun ParticipantCard(label: String, participant: NemesisParticipant, tag: String) {
    Card(Modifier.fillMaxWidth().testTag("nemesis-score-$tag")) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(label, style = MaterialTheme.typography.titleMedium)
            Text("${participant.points} pkt", style = MaterialTheme.typography.headlineMedium)
            Text("Kompletne dni: ${participant.completeDays}/${participant.closedDays} · W celu: ${participant.daysInGoal}", style = MaterialTheme.typography.bodySmall)
            Metric("Zmiana masy", participant.weight, "nemesis-weight-$tag")
            Metric("Średni szacowany deficyt", participant.deficit, "nemesis-deficit-$tag")
        }
    }
}
@Composable private fun Metric(label: String, metric: NemesisMetric, tag: String) {
    val description = when (metric) {
        NemesisMetric.Hidden -> "Nieudostępniane"
        is NemesisMetric.Insufficient -> "Za mało danych · ${dayText(metric.days)}"
        is NemesisMetric.Available -> {
            val rounded = if (metric.value.precision() > 18) metric.value.round(MathContext(12, RoundingMode.HALF_UP)).stripTrailingZeros() else metric.value
            (if (rounded.compareTo(metric.value) != 0) "≈ " else "") + rounded.toEngineeringString().replace('.', ',') + "% · ${dayText(metric.days)}"
        }
    }
    Text("$label: $description", Modifier.testTag(tag), style = MaterialTheme.typography.bodyMedium)
    if (metric is NemesisMetric.Available && metric.first != null) Text("Pomiary: ${metric.first} – ${metric.last}", style = MaterialTheme.typography.bodySmall)
}
private fun dayText(days: Int) = "$days ${if (days == 1) "dzień" else "dni"}"
