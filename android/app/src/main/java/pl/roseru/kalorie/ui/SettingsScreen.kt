package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.decimal
import pl.roseru.kalorie.data.GoalEntity
import pl.roseru.kalorie.data.ThemeMode

@Composable fun SettingsScreen(model: DiaryViewModel) {
    val theme by model.theme.collectAsStateWithLifecycle()
    val goal by model.todayGoal.collectAsStateWithLifecycle()
    val busy by model.busy.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Text("Ustawienia", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
        SectionTitle("Wygląd aplikacji")
        ThemeMode.entries.forEach { option ->
            FilterChip(selected = theme == option, onClick = { model.setTheme(option) }, label = { Text(option.label) }, modifier = Modifier.fillMaxWidth())
        }
        HorizontalDivider()
        SectionTitle("Dzienny cel")
        Text("Nowe ustawienia obowiązują od dzisiaj. Cele wcześniejszych dni pozostają zapisane.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        goal?.let { current -> GoalEditor(current, busy, onSave = model::setGoal) }
        HorizontalDivider()
        SectionTitle("Dane na urządzeniu")
        Text("Korzystasz bez konta. Posiłki i ustawienia są zapisywane lokalnie. Odinstalowanie aplikacji usuwa tę kopię danych.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text("Baza demonstracyjna v1. Wartości produktów i początkowy cel służą do sprawdzenia aplikacji. Ustaw własny cel i zweryfikuj dane przed użytkowaniem.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable private fun GoalEditor(goal: GoalEntity, busy: Boolean, onSave: (Double, Double?, Double?, Double?) -> Unit) {
    var kcal by rememberSaveable { mutableStateOf(decimal(goal.kcal)) }
    var protein by rememberSaveable { mutableStateOf(goal.protein?.let(::decimal) ?: "") }
    var fat by rememberSaveable { mutableStateOf(goal.fat?.let(::decimal) ?: "") }
    var carbs by rememberSaveable { mutableStateOf(goal.carbs?.let(::decimal) ?: "") }
    fun parse(text: String) = text.trim().replace(',', '.').toDoubleOrNull()?.takeIf { it.isFinite() }
    val energy = parse(kcal)?.takeIf { it > 0 && it <= 20_000 }
    fun validMacro(text: String) = text.isBlank() || parse(text)?.let { it >= 0 && it <= 5000 } == true
    val valid = energy != null && validMacro(protein) && validMacro(fat) && validMacro(carbs)
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        GoalField("Kalorie", "kcal", kcal, { kcal = it }, energy == null)
        GoalField("Białko (opcjonalnie)", "g", protein, { protein = it }, !validMacro(protein))
        GoalField("Tłuszcze (opcjonalnie)", "g", fat, { fat = it }, !validMacro(fat))
        GoalField("Węglowodany (opcjonalnie)", "g", carbs, { carbs = it }, !validMacro(carbs))
        Button(onClick = { energy?.let { onSave(it, parse(protein), parse(fat), parse(carbs)) } }, enabled = valid && !busy, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)) {
            Text(if (busy) "Zapisuję…" else "Zapisz cel")
        }
    }
}

@Composable private fun GoalField(label: String, unit: String, value: String, change: (String) -> Unit, error: Boolean) {
    OutlinedTextField(value, onValueChange = change, label = { Text(label) }, suffix = { Text(unit) }, singleLine = true, isError = error,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth())
}
