package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.session.SessionView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.awaitCancellation
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Private, explicit GET. Rendering never changes ranking consent or the local diary. */
@Composable internal fun ServerMotivationPanel(view: SessionView, onRead: () -> Unit, onAccount: () -> Unit, onRanking: (() -> Unit)? = null,onRestore:(()->Unit)?=null,onClearSaved:(()->Unit)?=null) {
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val restore by rememberUpdatedState(onRestore)
    LaunchedEffect(lifecycle,view.binding?.lease) {lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {restore?.invoke();awaitCancellation()}}
    val account = view.binding?.owner?.kind == "account"
    val ready = account && view.motivationConfigured && view.serverLinked && !view.requiresRecovery && !view.pendingLogin
    val canRead = ready && !view.busy && !view.bootstrapBusy && !view.profileBusy && !view.mealPushBusy && !view.snapshotBusy && !view.motivationBusy && !view.rankingConsentBusy && !view.rankingBusy
    // The controller fences the result; this also hides it immediately during a visible transition.
    val visible=account && view.serverLinked && !view.requiresRecovery && !view.pendingLogin && !view.busy
    val state = if (visible && (ready || view.motivation is MotivationState.Saved)) view.motivation else MotivationState.NotRequested
    Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Potwierdzenie serwerowe", style = MaterialTheme.typography.titleSmall)
            when (state) {
                MotivationState.NotRequested -> {
                    Text("Jeszcze nie pobrane", Modifier.testTag("achievement-server-state"), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(when {
                        !account -> "Lokalny postęp działa bez konta. Potwierdzone odznaki możesz odczytać po zalogowaniu."
                        !view.motivationConfigured -> "Odczyt wymaga skonfigurowanego połączenia z serwerem. Lokalny postęp pozostaje dostępny."
                        !view.serverLinked || view.requiresRecovery -> "Najpierw połącz konto i uzgodnij stan serwera w ustawieniach konta."
                        else -> "Pobierz własne punkty i odznaki. Odczyt nie włącza udziału w rankingu."
                    }, style = MaterialTheme.typography.bodySmall)
                }
                MotivationState.Loading -> {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    Text("Pobieram potwierdzenie…", Modifier.testTag("achievement-server-state"))
                }
                is MotivationState.Failed -> Text(state.message, Modifier.testTag("achievement-server-state"), style = MaterialTheme.typography.bodySmall)
                is MotivationState.Ready -> ServerResult(state.read)
                is MotivationState.Saved -> {
                    SavedPreviewNotice(state.fetchedAtMillis,state.warning)
                    ServerResult(state.read,historical=true)
                    onClearSaved?.let {TextButton(onClick=it,modifier=Modifier.testTag("achievement-saved-clear")){Text("Usuń zapisany podgląd")}}
                }
            }
            if(visible && state is MotivationState.Failed)onRestore?.let {TextButton(onClick=it,modifier=Modifier.testTag("achievement-saved-open")){Text("Pokaż zapisany podgląd")}}
            if (ready) {
                FilledTonalButton(onClick = onRead, enabled = canRead, modifier = Modifier.testTag("achievement-server-read")) {
                    Text(if (state is MotivationState.Ready) "Odśwież potwierdzenie" else "Pobierz z serwera")
                }
            } else TextButton(onClick = onAccount, modifier = Modifier.testTag("achievement-server-account")) { Text("Konto i połączenie") }
            onRanking?.let { TextButton(onClick = it, modifier = Modifier.testTag("achievement-ranking")) { Text("Udział w rankingu") } }
        }
    }
}

@Composable private fun ServerResult(read: MotivationRead,historical:Boolean=false) {
    val status = when (read.status) {
        MotivationStatus.PENDING_BACKFILL -> "Serwer odtwarza historię"
        MotivationStatus.PENDING_MATERIALIZATION -> "Serwer przygotowuje aktualizację"
        MotivationStatus.FINAL -> if(historical)"Potwierdzone przy pobraniu" else "Potwierdzone przez serwer"
    }
    Text(status, Modifier.testTag("achievement-server-state"), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
    if (read.points == null) Text("Punkty i ranga jeszcze niedostępne", Modifier.testTag("achievement-server-points"), style = MaterialTheme.typography.bodySmall)
    else {
        Text("${read.points} pkt · ${read.rank}", Modifier.testTag("achievement-server-points"), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("Potwierdzone odznaki: ${read.badges.count { it.status == ServerBadgeStatus.FINAL }} / 4", style = MaterialTheme.typography.bodySmall)
    }
    val zone = ZoneId.systemDefault()
    Text("Stan na: ${read.asOf.atZone(zone).format(DateTimeFormatter.ofPattern("dd.MM.yyyy · HH:mm"))} · ${zone.id}",
        Modifier.testTag("achievement-server-updated"), style = MaterialTheme.typography.labelSmall)
    if(historical)Text("Status udziału w rankingu przy pobraniu:",style=MaterialTheme.typography.labelSmall)
    Text(when {
        read.ranking.pendingConsentRefresh -> "Ranking czeka na ponowne potwierdzenie zgody. Ten odczyt jej nie odnawia."
        read.ranking.effective && read.ranking.ownPosition != null -> "Twoje miejsce w rankingu: ${read.ranking.ownPosition}"
        read.ranking.effective -> "Udział w rankingu aktywny; miejsce jeszcze niedostępne."
        read.ranking.requested -> "Zgoda na ranking jest zapisana. Publikacja wyniku jest jeszcze niedostępna."
        else -> "Udział w rankingu wyłączony."
    }, Modifier.testTag("achievement-server-ranking"), style = MaterialTheme.typography.bodySmall)
    var expanded by rememberSaveable { mutableStateOf(false) }
    TextButton(onClick = { expanded = !expanded }, modifier = Modifier.testTag("achievement-server-details")) {
        Text(if (expanded) "Ukryj odznaki serwerowe" else "Pokaż odznaki serwerowe")
    }
    if (expanded) read.badges.forEach { badge ->
        HorizontalDivider()
        Text(when (badge.code) {
            AchievementCode.COMPLETE_STREAK -> "Rytm dziennika"
            AchievementCode.IN_GOAL_STREAK -> "Cel w zasięgu"
            AchievementCode.WEIGHT_DAYS -> "Regularny pomiar"
            AchievementCode.RATION_DAYS -> "Racje w terenie"
        }, style = MaterialTheme.typography.titleSmall)
        Text(when (badge.status) {
            ServerBadgeStatus.PENDING -> "Oczekuje · ${badge.progress} / ${badge.code.required}"
            ServerBadgeStatus.FINAL -> "Przyznana · ${badge.progress} / ${badge.code.required}"
            ServerBadgeStatus.REVOKED -> "Cofnięta po korekcie · ${badge.progress} / ${badge.code.required}"
        }, Modifier.testTag("server-badge-${badge.code.wire}"), style = MaterialTheme.typography.bodySmall)
        if (badge.witnessDates.isNotEmpty()) Text(badge.witnessDates.joinToString(" · ") { it.format(DateTimeFormatter.ofPattern("dd.MM.yyyy")) }, style = MaterialTheme.typography.bodySmall)
    }
    Text("Lokalne wpisy mogą jeszcze czekać na synchronizację. Lokalny podgląd może różnić się od wyniku serwera.", style = MaterialTheme.typography.bodySmall)
}
