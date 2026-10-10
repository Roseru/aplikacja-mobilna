package pl.roseru.kalorie.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.ProfileEntity
import pl.roseru.kalorie.data.WeightEntity
import java.time.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun ProfileScreen(model: DiaryViewModel) {
    val profile by model.profile.collectAsStateWithLifecycle()
    val weights by model.weights.collectAsStateWithLifecycle()
    val busy by model.busy.collectAsStateWithLifecycle()
    val weightSaveVersion by model.weightSaveVersion.collectAsStateWithLifecycle()
    var kgText by rememberSaveable { mutableStateOf("") }
    var seenWeightSaveVersion by rememberSaveable { mutableStateOf(weightSaveVersion) }
    LaunchedEffect(weightSaveVersion) {
        if (weightSaveVersion > seenWeightSaveVersion) kgText = ""
        seenWeightSaveVersion = weightSaveVersion
    }
    var dateText by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    var datePicker by rememberSaveable { mutableStateOf(false) }
    var editing by remember { mutableStateOf<WeightEntity?>(null) }
    var deleting by remember { mutableStateOf<WeightEntity?>(null) }
    val date = LocalDate.parse(dateText)
    val kg = parseNumber(kgText)?.takeIf { it in 20.0..400.0 }
    LazyColumn(Modifier.fillMaxSize().imePadding().testTag("profile-content"), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        item(key = "profile-header") {
            Text("Profil", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
            Text("Profil i pomiary zapisane na tym urządzeniu", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        weights.firstOrNull()?.let { latest -> item(key = "latest-weight") {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer), shape = RoundedCornerShape(16.dp)) {
                Column(Modifier.fillMaxWidth().padding(20.dp)) {
                    Text("Ostatni pomiar · ${latest.localDate}", style = MaterialTheme.typography.labelLarge)
                    Text("${decimal(latest.kg)} kg", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                }
            }
        } }
        item(key = "profile-editor") { key(profile?.id) { ProfileEditor(profile, busy, onSave = model::setProfile) } }
        item(key = "weight-form") {
            HorizontalDivider()
            SectionTitle("Dodaj pomiar wagi", Modifier.padding(top = 16.dp))
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                TextButton(onClick = { datePicker = true }, enabled = !busy) { Text("Data pomiaru: $date") }
                NumericField("Masa ciała", "kg", kgText, { kgText = it }, kgText.isNotBlank() && kg == null, "weight-kg", busy)
                Text("Zakres: 20–400 kg. Możesz dodać więcej niż jeden pomiar w danym dniu.", style = MaterialTheme.typography.bodySmall)
                if (date > LocalDate.now()) Text("Wybierz dzień dzisiejszy albo wcześniejszy.", color = MaterialTheme.colorScheme.error)
                Button(onClick = { kg?.let { model.addWeight(it, date) } }, enabled = kg != null && date <= LocalDate.now() && !busy,
                    modifier = Modifier.fillMaxWidth().testTag("confirm-weight")) { Text(if (busy) "Zapisuję…" else "Zapisz pomiar") }
            }
        }
        item(key = "weight-history-header") { SectionTitle("Historia pomiarów") }
        if (weights.isEmpty()) item(key = "weight-history-empty") { Text("Brak pomiarów. Dodaj pierwszy, aby śledzić zmianę masy.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        items(weights, key = { it.id }) { point ->
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(14.dp)) {
                Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("${decimal(point.kg)} kg", fontWeight = FontWeight.SemiBold)
                        Text(point.localDate, style = MaterialTheme.typography.bodySmall)
                    }
                    IconButton(onClick = { editing = point }, enabled = !busy) { Icon(Icons.Outlined.Edit, "Popraw pomiar ${point.localDate}") }
                    IconButton(onClick = { deleting = point }, enabled = !busy) { Icon(Icons.Outlined.DeleteOutline, "Usuń pomiar ${point.localDate}") }
                }
            }
        }
    }
    if (datePicker) {
        val picker = rememberDatePickerState(initialSelectedDateMillis = date.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
        DatePickerDialog(onDismissRequest = { datePicker = false }, confirmButton = { TextButton(onClick = {
            picker.selectedDateMillis?.let { dateText = Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString() }; datePicker = false
        }) { Text("Wybierz") } }, dismissButton = { TextButton(onClick = { datePicker = false }) { Text("Anuluj") } }) { DatePicker(picker) }
    }
    editing?.let { point -> WeightDialog(point, busy, onDismiss = { editing = null }, onSave = { model.editWeight(point.id, it); editing = null }) }
    deleting?.let { point -> AlertDialog(onDismissRequest = { deleting = null }, title = { Text("Usunąć pomiar?") },
        text = { Text("${decimal(point.kg)} kg · ${point.localDate}") }, confirmButton = { TextButton(onClick = { model.deleteWeight(point.id); deleting = null }, enabled = !busy) { Text("Usuń") } },
        dismissButton = { TextButton(onClick = { deleting = null }) { Text("Anuluj") } }) }
}

@Composable private fun ProfileEditor(profile: ProfileEntity?, busy: Boolean, onSave: (String, Double, ActivityClass, DietAim) -> Unit) {
    var nickname by rememberSaveable { mutableStateOf(profile?.nickname ?: "") }
    var height by rememberSaveable { mutableStateOf(profile?.heightCm?.let(::decimal) ?: "") }
    var activityName by rememberSaveable { mutableStateOf(profile?.activityClass ?: ActivityClass.GARRISON.name) }
    var aimName by rememberSaveable { mutableStateOf(profile?.dietAim ?: DietAim.MAINTAIN.name) }
    val cm = parseNumber(height)?.takeIf { it in 80.0..250.0 }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        SectionTitle("Twój profil")
        OutlinedTextField(nickname, onValueChange = { nickname = it }, label = { Text("Pseudonim (2–40 znaków)") }, singleLine = true,
            enabled = !busy, modifier = Modifier.fillMaxWidth().testTag("profile-nickname"))
        NumericField("Wzrost (80–250 cm)", "cm", height, { height = it }, height.isNotBlank() && cm == null, "profile-height", busy)
        Text("Klasa aktywności", style = MaterialTheme.typography.titleSmall)
        ActivityClass.entries.forEach { option -> FilterChip(selected = activityName == option.name, onClick = { activityName = option.name },
            label = { Text(option.label) }, enabled = !busy, modifier = Modifier.fillMaxWidth()) }
        Text("Cel użytkownika", style = MaterialTheme.typography.titleSmall)
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            DietAim.entries.forEach { option -> FilterChip(selected = aimName == option.name, onClick = { aimName = option.name },
                label = { Text(option.label) }, enabled = !busy) }
        }
        Text("Dzienne kcal i B/T/W ustawisz oddzielnie w Ustawieniach.", style = MaterialTheme.typography.bodySmall)
        Button(onClick = { cm?.let { onSave(nickname, it, ActivityClass.valueOf(activityName), DietAim.valueOf(aimName)) } },
            enabled = nickname.trim().length in 2..40 && cm != null && !busy, modifier = Modifier.fillMaxWidth().testTag("confirm-profile")) {
            Text(if (busy) "Zapisuję…" else "Zapisz profil")
        }
    }
}

@Composable private fun WeightDialog(point: WeightEntity, busy: Boolean, onDismiss: () -> Unit, onSave: (Double) -> Unit) {
    var text by rememberSaveable(point.id) { mutableStateOf(decimal(point.kg)) }
    val kg = parseNumber(text)?.takeIf { it in 20.0..400.0 }
    AlertDialog(onDismissRequest = onDismiss, title = { Text("Pomiar · ${point.localDate}") }, text = {
        NumericField("Masa ciała (20–400 kg)", "kg", text, { text = it }, kg == null, "edit-weight-kg", busy)
    }, confirmButton = { TextButton(onClick = { kg?.let(onSave) }, enabled = kg != null && !busy) { Text("Zapisz") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Anuluj") } })
}
