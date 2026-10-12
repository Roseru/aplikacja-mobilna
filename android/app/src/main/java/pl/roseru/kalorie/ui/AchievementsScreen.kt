package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.AchievementState
import pl.roseru.kalorie.session.SessionView
import pl.roseru.kalorie.session.SessionActions
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable fun AchievementsScreen(model: DiaryViewModel, session: SessionView, actions: SessionActions, onAccount: () -> Unit, onBack: () -> Unit) {
    val state by model.achievements.collectAsStateWithLifecycle()
    AchievementsContent(state, onBack, model::retryAchievements) { ServerMotivationPanel(session, actions.readMotivation, onAccount) }
}

@Composable internal fun AchievementsContent(state: AchievementState, onBack: () -> Unit, onRetry: () -> Unit = {}, serverPanel: (@Composable () -> Unit)? = null) {
    LazyColumn(Modifier.fillMaxSize().testTag("achievements-content"), contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item(key = "header") {
            TextButton(onClick = onBack, modifier = Modifier.testTag("achievements-back")) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, null, Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp)); Text("Wróć do profilu")
            }
            Text("TWOJA REGULARNOŚĆ", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            Text("Osiągnięcia", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
            Text("Małe kroki. Trwałe nawyki.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        item(key = "server") {
            if (serverPanel != null) {
                serverPanel()
            } else {
                Card(shape = RoundedCornerShape(18.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text("Potwierdzenie serwerowe", style = MaterialTheme.typography.titleSmall)
                        Text("Jeszcze nie pobrane", Modifier.testTag("achievement-server-state"), color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("Ten ekran pokazuje lokalny postęp. Nie publikuje punktów, rangi ani miejsca w rankingu.", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        when (state) {
            AchievementState.Loading -> item(key = "loading") {
                Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator(); Text("Sprawdzam lokalną historię…", Modifier.padding(top = 12.dp))
                }
            }
            AchievementState.Unavailable -> item(key = "unavailable") {
                Text("Nie udało się odczytać postępu. Twój dziennik pozostaje zapisany.", Modifier.testTag("achievement-error"))
                Button(onClick = onRetry, modifier = Modifier.testTag("achievement-retry")) { Text("Spróbuj ponownie") }
            }
            is AchievementState.Ready -> {
                val preview = state.preview
                item(key = "summary") {
                    var details by rememberSaveable { mutableStateOf(false) }
                    Card(Modifier.testTag("achievement-summary"), shape = RoundedCornerShape(22.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
                        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text("PODGLĄD LOKALNY · OFFLINE", style = MaterialTheme.typography.labelSmall)
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                Text("${preview.badges.count { it.satisfied }} / 4", Modifier.testTag("achievement-count"),
                                    style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                                Text("warunki spełnione na tym urządzeniu", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                            }
                            Text("Dzisiaj wstępne · korekty mogą zmienić wynik.", style = MaterialTheme.typography.bodySmall)
                            val updated = preview.asOf.atZone(ZoneId.of(preview.zoneId)).format(DateTimeFormatter.ofPattern("dd.MM.yyyy · HH:mm"))
                            Text("Przeliczono: $updated · ${preview.zoneId}", style = MaterialTheme.typography.labelSmall)
                            TextButton(onClick = { details = !details }, modifier = Modifier.testTag("achievement-summary-details")) {
                                Text(if (details) "Ukryj szczegóły" else "Jak liczymy postęp")
                            }
                            if (details) {
                                Text("Najlepszy postęp z całej lokalnej historii. Korekta lub usunięcie wpisu może zmienić wynik.",
                                    Modifier.testTag("achievement-summary-explanation"), style = MaterialTheme.typography.bodySmall)
                                Text("Serie liczymy po zamknięciu dnia w strefie urządzenia; pomiary i racje w strefie zapisanej we wpisie.", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                items(preview.badges, key = { it.code.wire }) { badge -> AchievementCard(badge) }
                if (preview.legacyRationMeals > 0) item(key = "legacy") {
                    Text("Starsze wpisy racji bez zapisanej pozycji składnika: ${preview.legacyRationMeals}. Zachowują kalorie, ale nie potwierdzają warunku odznaki racji.",
                        Modifier.testTag("achievement-legacy"), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                item(key = "rules") {
                    Text("Regularność zamiast skrajności", style = MaterialTheme.typography.titleSmall)
                    Text("Większy deficyt, nadwyżka ani liczba posiłków nie podnoszą wyniku. Odznaki dotyczą nawyków i realizacji własnego celu.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

private data class BadgeCopy(val title: String, val description: String, val icon: ImageVector)
private fun AchievementCode.copy() = when (this) {
    AchievementCode.COMPLETE_STREAK -> BadgeCopy("Rytm dziennika", "10 kolejnych kompletnych dni. Oznacz dzień jako kompletny po zapisaniu całego spożycia.", Icons.Outlined.CalendarMonth)
    AchievementCode.IN_GOAL_STREAK -> BadgeCopy("Cel w zasięgu", "10 kolejnych kompletnych dni w granicach ±10% celu obowiązującego w każdym dniu.", Icons.Outlined.Flag)
    AchievementCode.WEIGHT_DAYS -> BadgeCopy("Regularny pomiar", "Pomiary w 4 różnych, zamkniętych dniach w dowolnym okresie 14 dni. Kilka pomiarów jednego dnia liczymy raz.", Icons.Outlined.MonitorWeight)
    AchievementCode.RATION_DAYS -> BadgeCopy("Racje w terenie", "Zjedzony składnik racji w 5 różnych, zamkniętych dniach. Liczy się zapisane pochodzenie składnika.", Icons.Outlined.Backpack)
}

@Composable private fun AchievementCard(badge: LocalAchievement) {
    val copy = badge.code.copy()
    var expanded by rememberSaveable(badge.code.wire) { mutableStateOf(false) }
    Card(Modifier.fillMaxWidth().testTag("badge-${badge.code.wire}"), shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.primaryContainer) {
                    Icon(copy.icon, null, Modifier.padding(10.dp).size(24.dp), tint = MaterialTheme.colorScheme.onPrimaryContainer)
                }
                Column(Modifier.weight(1f)) {
                    Text(copy.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text(when { badge.satisfied -> "Warunek spełniony lokalnie"; badge.preliminary -> "Wstępny postęp"; else -> "W trakcie" },
                        Modifier.testTag("badge-status-${badge.code.wire}"), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                }
            }
            Text(copy.description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text("${badge.progress} / ${badge.code.required}${if (badge.preliminary) " · wstępnie" else ""}",
                Modifier.testTag("badge-progress-${badge.code.wire}"), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            LinearProgressIndicator(progress = { badge.progress.toFloat() / badge.code.required }, modifier = Modifier.fillMaxWidth())
            if (badge.preliminary) Text("Zamknięte dni: ${badge.closedProgress} / ${badge.code.required}", style = MaterialTheme.typography.bodySmall)
            if (badge.satisfied) {
                TextButton(onClick = { expanded = !expanded }, modifier = Modifier.testTag("badge-dates-${badge.code.wire}")) {
                    Text(if (expanded) "Ukryj dni spełnienia" else "Pokaż dni spełnienia")
                }
                if (expanded) Text(badge.witness.joinToString(" · ") { it.format(DateTimeFormatter.ofPattern("dd.MM.yyyy", Locale.forLanguageTag("pl"))) },
                    Modifier.testTag("badge-witness-${badge.code.wire}"), style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
