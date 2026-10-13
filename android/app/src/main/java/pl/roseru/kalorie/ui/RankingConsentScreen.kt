package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.session.*

/** Reading and deciding are separate actions; composition never submits a consent. */
@Composable internal fun RankingConsentScreen(view: SessionView, actions: SessionActions, onBack: () -> Unit, onAccount: () -> Unit, onRanking: () -> Unit = {}) {
    val account = view.binding?.owner?.kind == "account"
    val available = account && view.rankingConsentConfigured && view.serverLinked && !view.requiresRecovery && !view.pendingLogin
    val busy = view.busy || view.bootstrapBusy || view.profileBusy || view.motivationBusy || view.snapshotBusy || view.rankingConsentBusy || view.rankingBusy
    val state = if (available && !view.busy) view.rankingConsent else RankingConsentState.NotRequested
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp).testTag("ranking-consent-content"),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        TextButton(onClick = onBack) { Text("Wróć do osiągnięć") }
        Text("Udział w rankingu", style = MaterialTheme.typography.headlineLarge)
        Text("Twoja decyzja. Twój postęp.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        TextButton(onClick = onRanking, modifier = Modifier.testTag("ranking-consent-list")) { Text("Zobacz ranking") }
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Co zobaczą inni", style = MaterialTheme.typography.titleMedium)
                Text("Pseudonim, punkty, rangę i liczbę potwierdzonych odznak. Dziennik posiłków i pomiary masy pozostają prywatne.", style = MaterialTheme.typography.bodySmall)
                Text("Korekta wpisów może obniżyć punkty, rangę lub liczbę odznak. Wyłączenie udziału zatrzyma kolejne odczyty publiczne po potwierdzeniu serwera; wcześniej pobrane kopie mogą pozostać u innych osób.", style = MaterialTheme.typography.bodySmall)
            }
        }
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                when (state) {
                    RankingConsentState.NotRequested -> Text(when {
                        !account -> "Zaloguj się, aby zarządzać udziałem. Lokalne osiągnięcia nadal działają bez konta."
                        !view.rankingConsentConfigured -> "Zarządzanie udziałem wymaga skonfigurowanego połączenia z serwerem."
                        !view.serverLinked || view.requiresRecovery -> "Najpierw połącz konto i uzgodnij stan serwera."
                        else -> "Pobierz aktualne zgody. Sam odczyt nie włącza ani nie odnawia udziału."
                    }, Modifier.testTag("ranking-consent-state"))
                    RankingConsentState.Loading -> {
                        LinearProgressIndicator(Modifier.fillMaxWidth())
                        Text("Sprawdzam lub zapisuję decyzję…", Modifier.testTag("ranking-consent-state"))
                    }
                    is RankingConsentState.Failed -> Text(state.message, Modifier.testTag("ranking-consent-state"))
                    is RankingConsentState.Confirmed -> {
                        Text(if (state.consents.ranking) "Serwer potwierdził decyzję o włączeniu udziału." else "Serwer potwierdził decyzję o wyłączeniu udziału.",
                            Modifier.testTag("ranking-consent-state"))
                        Text("Potwierdzenie dotyczy tego zapisu. Aktualny udział sprawdzisz przy ponownym odczycie.", style = MaterialTheme.typography.bodySmall)
                    }
                    is RankingConsentState.Pending -> {
                        Text("Zapis czeka na potwierdzenie", Modifier.testTag("ranking-consent-state"), style = MaterialTheme.typography.titleMedium)
                        Text(if (state.enabled) "Twoja zatwierdzona decyzja: włączyć udział." else "Twoja zatwierdzona decyzja: wyłączyć udział.")
                        Text("Po utracie odpowiedzi ponawiamy tę samą decyzję. Nowy wybór będzie dostępny po jej rozstrzygnięciu.", style = MaterialTheme.typography.bodySmall)
                        Button(onClick = actions.retryRankingConsent, enabled = !busy, modifier = Modifier.testTag("ranking-consent-retry")) { Text("Ponów tę samą decyzję") }
                    }
                    is RankingConsentState.Ready -> {
                        val source = state.source
                        var accepted by rememberSaveable(source.id) { mutableStateOf(false) }
                        Text(when {
                            source.ranking.pendingConsentRefresh -> "Zgoda wymaga ponownego potwierdzenia."
                            source.ranking.effective -> "Udział aktywny według ostatniego odczytu."
                            source.consents.ranking -> "Zgoda zapisana; publikacja jeszcze niedostępna."
                            else -> "Udział wyłączony według ostatniego odczytu."
                        }, Modifier.testTag("ranking-consent-state"))
                        Text("Automatyczna korekta zapotrzebowania pozostanie ${if (source.consents.automaticEnergyAdjustment) "włączona" else "wyłączona"}.",
                            Modifier.testTag("ranking-consent-energy"), style = MaterialTheme.typography.bodySmall)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(checked = accepted, onCheckedChange = { accepted = it }, enabled = !busy, modifier = Modifier.testTag("ranking-consent-ack"))
                            Text("Chcę udostępniać opisane informacje w rankingu.", style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
                        }
                        Button(onClick = { actions.confirmRankingConsent(source.id, true) }, enabled = accepted && !busy,
                            modifier = Modifier.testTag("ranking-consent-enable")) {
                            Text(if (source.consents.ranking) "Potwierdź udział" else "Włącz udział")
                        }
                        if (source.consents.ranking) OutlinedButton(onClick = { actions.confirmRankingConsent(source.id, false) }, enabled = !busy,
                            modifier = Modifier.testTag("ranking-consent-disable")) { Text("Wyłącz udział") }
                    }
                }
                if (available && state !is RankingConsentState.Pending) TextButton(onClick = actions.readRankingConsents, enabled = !busy,
                    modifier = Modifier.testTag("ranking-consent-read")) { Text("Pobierz aktualne zgody") }
                if (!available) TextButton(onClick = onAccount, modifier = Modifier.testTag("ranking-consent-account")) { Text("Konto i połączenie") }
                view.message?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
            }
        }
    }
}
