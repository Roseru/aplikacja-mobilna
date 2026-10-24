package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.decimal
import pl.roseru.kalorie.data.GoalEntity
import pl.roseru.kalorie.data.ThemeMode

@Composable fun SettingsScreen(model: DiaryViewModel,catalogModel:pl.roseru.kalorie.catalogupdate.CatalogUpdateViewModel?=null,
    networkModel:pl.roseru.kalorie.core.network.NetworkPolicyViewModel?=null) {
    val theme by model.theme.collectAsStateWithLifecycle()
    val goal by model.todayGoal.collectAsStateWithLifecycle()
    val busy by model.busy.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(20.dp).testTag("settings-content"), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Text("Ustawienia", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
        SectionTitle("Wygląd aplikacji")
        ThemeMode.entries.forEach { option ->
            FilterChip(selected = theme == option, onClick = { model.setTheme(option) }, label = { Text(option.label) }, modifier = Modifier.fillMaxWidth())
        }
        HorizontalDivider()
        SectionTitle("Dzienny cel")
        Text("Nowe ustawienia obowiązują od dzisiaj. Cele wcześniejszych dni pozostają zapisane.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        if(goal==null) Text("Nie masz jeszcze celu. Wpisz własną liczbę kcal; B/T/W możesz pozostawić puste.",
            modifier=Modifier.testTag("first-goal-hint"),color=MaterialTheme.colorScheme.onSurfaceVariant)
        GoalEditor(goal, busy, onSave = model::setGoal)
        HorizontalDivider()
        if(networkModel!=null) {
            NetworkPolicyPanel(networkModel)
            HorizontalDivider()
        }
        if(catalogModel!=null) {
            CatalogUpdatePanel(catalogModel)
            HorizontalDivider()
        }
        SectionTitle("Dane na urządzeniu")
        Text(if(model.isGuest) "Korzystasz bez konta. Posiłki i ustawienia są zapisywane lokalnie. Odinstalowanie aplikacji usuwa tę kopię danych."
            else "Korzystasz z profilu konta. Zmiany zapisujemy najpierw na urządzeniu, a synchronizacja odbywa się osobno. Odinstalowanie aplikacji usuwa lokalną kopię danych.",
            modifier=Modifier.testTag("settings-owner-info"),color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(if(model.isGuest) "Baza demonstracyjna v1. Wartości produktów i początkowy cel służą do sprawdzenia aplikacji. Ustaw własny cel i zweryfikuj dane przed użytkowaniem."
            else "Baza demonstracyjna v1. Wartości produktów służą do sprawdzenia aplikacji. Cel konta ustawiasz samodzielnie; zweryfikuj dane przed użytkowaniem.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable private fun GoalEditor(goal: GoalEntity?, busy: Boolean, onSave: (Double, Double?, Double?, Double?) -> Unit) {
    var kcal by rememberSaveable(goal?.id) { mutableStateOf(goal?.kcal?.let(::decimal) ?: "") }
    var protein by rememberSaveable(goal?.id) { mutableStateOf(goal?.protein?.let(::decimal) ?: "") }
    var fat by rememberSaveable(goal?.id) { mutableStateOf(goal?.fat?.let(::decimal) ?: "") }
    var carbs by rememberSaveable(goal?.id) { mutableStateOf(goal?.carbs?.let(::decimal) ?: "") }
    fun parse(text: String) = text.trim().replace(',', '.').toDoubleOrNull()?.takeIf { it.isFinite() }
    val energy = parse(kcal)?.takeIf { it > 0 && it <= 20_000 }
    fun validMacro(text: String) = text.isBlank() || parse(text)?.let { it >= 0 && it <= 5000 } == true
    val valid = energy != null && validMacro(protein) && validMacro(fat) && validMacro(carbs)
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        GoalField("Kalorie", "kcal", kcal, { kcal = it }, kcal.isNotBlank() && energy == null,"goal-kcal")
        GoalField("Białko (opcjonalnie)", "g", protein, { protein = it }, !validMacro(protein),"goal-protein")
        GoalField("Tłuszcze (opcjonalnie)", "g", fat, { fat = it }, !validMacro(fat),"goal-fat")
        GoalField("Węglowodany (opcjonalnie)", "g", carbs, { carbs = it }, !validMacro(carbs),"goal-carbs")
        Button(onClick = { energy?.let { onSave(it, parse(protein), parse(fat), parse(carbs)) } }, enabled = valid && !busy, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("confirm-goal")) {
            Text(if (busy) "Zapisuję…" else "Zapisz cel")
        }
    }
}

@Composable private fun GoalField(label: String, unit: String, value: String, change: (String) -> Unit, error: Boolean, tag:String) {
    OutlinedTextField(value, onValueChange = change, label = { Text(label) }, suffix = { Text(unit) }, singleLine = true, isError = error,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth().testTag(tag))
}
