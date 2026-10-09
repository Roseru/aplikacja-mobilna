package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.outlined.KeyboardArrowRight
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.MealWithItems
import pl.roseru.kalorie.data.MealItemEntity
import java.time.*
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun DiaryScreen(model: DiaryViewModel, onAdd: () -> Unit, onSettings: () -> Unit) {
    val day by model.day.collectAsStateWithLifecycle()
    val pending by model.pending.collectAsStateWithLifecycle()
    val busy by model.busy.collectAsStateWithLifecycle()
    var editing by remember { mutableStateOf<EditingItem?>(null) }
    var deleting by remember { mutableStateOf<EditingItem?>(null) }
    var deletingRation by remember { mutableStateOf<MealWithItems?>(null) }
    var datePicker by rememberSaveable { mutableStateOf(false) }
    val formatter = remember { DateTimeFormatter.ofPattern("d MMMM", Locale.forLanguageTag("pl-PL")) }
    Column(Modifier.fillMaxSize()) {
    LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("Dziennik", modifier = Modifier.weight(1f), style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
                IconButton(onClick = onSettings) { Icon(Icons.Outlined.Tune, contentDescription = "Ustawienia celu i wyglądu") }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                IconButton(onClick = { model.changeDay(-1) }) { Icon(Icons.AutoMirrored.Outlined.KeyboardArrowLeft, "Poprzedni dzień") }
                TextButton(onClick = { datePicker = true }) {
                    Text((if (day.date == LocalDate.now()) "Dzisiaj, " else "") + day.date.format(formatter), style = MaterialTheme.typography.titleMedium)
                }
                IconButton(onClick = { model.changeDay(1) }) { Icon(Icons.AutoMirrored.Outlined.KeyboardArrowRight, "Następny dzień") }
            }
        }
        item {
            Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(14.dp)) {
                Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Icon(Icons.Outlined.CloudOff, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Column {
                        Text("Tryb poligonowy · zapis lokalny", style = MaterialTheme.typography.labelLarge)
                        Text("${pending} zmian w kolejce · dane na tym urządzeniu", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        item { NutritionCard(day.totals, day.goal) }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(16.dp)) {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text(if (day.complete) "Dzień kompletny" else "Dziennik niekompletny", style = MaterialTheme.typography.titleSmall)
                        Text(if (day.meals.isEmpty() || day.totals.kcal <= 0) "Dodaj posiłki, aby potwierdzić kompletność." else "Potwierdź, gdy zapisałeś wszystkie posiłki.",
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Switch(checked = day.status?.declaredComplete == true, onCheckedChange = model::setDayComplete,
                        enabled = !busy && day.date <= LocalDate.now() && (day.status?.declaredComplete == true || day.totals.kcal > 0),
                        modifier = Modifier.semantics { contentDescription = "Deklaracja kompletności dnia" }.testTag("day-complete"))
                }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                SectionTitle("Twoje posiłki", Modifier.weight(1f))
                TextButton(onClick = onAdd) { Icon(Icons.Outlined.Add, null); Text("Dodaj") }
            }
        }
        if (day.meals.isEmpty()) {
            item {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(18.dp)) {
                    Column(Modifier.fillMaxWidth().padding(24.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Icon(Icons.Outlined.Restaurant, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(32.dp))
                        Text("Pierwszy posiłek tego dnia", style = MaterialTheme.typography.titleMedium)
                        Text("Wybierz produkt i podaj zjedzoną ilość. Zapis działa bez internetu.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        MealType.entries.forEach { type ->
            val meals = day.meals.filter { it.meal.mealType == type.name }
            if (meals.isNotEmpty()) item(key = type.name) {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(18.dp)) {
                    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Text(type.label, Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                            Text("${meals.flatMap { it.items }.sumOf { it.consumed().kcal }.roundToInt()} kcal", fontWeight = FontWeight.SemiBold)
                        }
                        meals.forEach { meal ->
                            meal.meal.rationName?.let { name ->
                                HorizontalDivider(Modifier.padding(top = 8.dp))
                                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                    Column(Modifier.weight(1f)) {
                                        Text(name, style = MaterialTheme.typography.titleSmall)
                                        Text("${meal.items.size} zjedzone składniki · ${meal.items.sumOf { it.consumed().kcal }.roundToInt()} kcal", style = MaterialTheme.typography.bodySmall)
                                    }
                                    IconButton(onClick = { deletingRation = meal }, enabled = !busy) { Icon(Icons.Outlined.DeleteOutline, "Usuń rację") }
                                }
                            }
                            meal.items.forEach { product ->
                            TextButton(onClick = { editing = EditingItem(meal, product) }, enabled = !busy, contentPadding = PaddingValues(vertical = 8.dp, horizontal = 0.dp)) {
                                Column(Modifier.weight(1f), horizontalAlignment = Alignment.Start) {
                                    Text(product.productName, color = MaterialTheme.colorScheme.onSurface)
                                    Text("${decimal(product.grams)} g · ${product.consumed().kcal.roundToInt()} kcal", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                Icon(Icons.Outlined.Edit, "Popraw ${product.productName}", modifier = Modifier.size(18.dp))
                            }
                            }
                        }
                    }
                }
            }
        }
        item { Text("Katalog demonstracyjny. Zweryfikuj wartości przed użyciem do prowadzenia diety.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
    Button(onClick = onAdd, modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp).fillMaxWidth().heightIn(min = 56.dp), shape = RoundedCornerShape(16.dp)) {
        Icon(Icons.Outlined.Add, null); Spacer(Modifier.width(8.dp)); Text("Dodaj posiłek", style = MaterialTheme.typography.titleMedium)
    }
    }
    editing?.let { target ->
        EditMealDialog(target.item, busy, onDismiss = { editing = null }, onSave = { grams -> model.editItem(target.meal.meal.id, target.item.id, grams); editing = null },
            onDelete = { editing = null; deleting = target })
    }
    deleting?.let { target ->
        AlertDialog(onDismissRequest = { deleting = null }, title = { Text("Usunąć składnik?") }, text = { Text(target.item.productName) },
            confirmButton = { TextButton(onClick = { model.removeItem(target.meal.meal.id, target.item.id); deleting = null }, enabled = !busy) { Text("Usuń") } },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text("Anuluj") } })
    }
    deletingRation?.let { meal ->
        AlertDialog(onDismissRequest = { deletingRation = null }, title = { Text("Usunąć całą rację?") },
            text = { Text("${meal.meal.rationName}\nWszystkie jej składniki zostaną usunięte z dziennika.") },
            confirmButton = { TextButton(onClick = { model.delete(meal.meal.id); deletingRation = null }, enabled = !busy) { Text("Usuń rację") } },
            dismissButton = { TextButton(onClick = { deletingRation = null }) { Text("Anuluj") } })
    }
    if (datePicker) {
        val picker = rememberDatePickerState(initialSelectedDateMillis = day.date.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
        DatePickerDialog(onDismissRequest = { datePicker = false },
            confirmButton = { TextButton(onClick = {
                picker.selectedDateMillis?.let { model.selectDate(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate()) }; datePicker = false
            }) { Text("Wybierz") } }, dismissButton = { TextButton(onClick = { datePicker = false }) { Text("Anuluj") } }) {
            DatePicker(picker)
        }
    }
}

private data class EditingItem(val meal: MealWithItems, val item: MealItemEntity)

@Composable private fun EditMealDialog(item: MealItemEntity, busy: Boolean, onDismiss: () -> Unit, onSave: (Double) -> Unit, onDelete: () -> Unit) {
    var grams by rememberSaveable(item.id) { mutableStateOf(decimal(item.grams)) }
    val amount = parseAmount(grams)
    AlertDialog(onDismissRequest = onDismiss, title = { Text(item.productName) }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            OutlinedTextField(grams, onValueChange = { grams = it }, label = { Text("Zjedzona ilość") }, suffix = { Text("g") }, singleLine = true,
                isError = amount == null, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
            Text(amount?.let { "${item.copy(grams = it).consumed().kcal.roundToInt()} kcal" } ?: "Podaj ilość od 0 do 10 000 g (większą od zera)")
        }
    }, confirmButton = { TextButton(onClick = { amount?.let(onSave) }, enabled = amount != null && !busy) { Text("Zapisz") } },
        dismissButton = { Row { TextButton(onClick = onDelete, enabled = !busy) { Text("Usuń") }; TextButton(onClick = onDismiss) { Text("Anuluj") } } })
}
