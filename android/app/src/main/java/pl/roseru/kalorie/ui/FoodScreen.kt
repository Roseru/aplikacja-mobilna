package pl.roseru.kalorie.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.ProductEntity
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun FoodScreen(model: DiaryViewModel, onBack: () -> Unit, onRations: () -> Unit) {
    val products by model.products.collectAsStateWithLifecycle()
    val recent by model.recent.collectAsStateWithLifecycle()
    val day by model.day.collectAsStateWithLifecycle()
    val busy by model.busy.collectAsStateWithLifecycle()
    var query by rememberSaveable { mutableStateOf("") }
    var recentOnly by rememberSaveable { mutableStateOf(false) }
    var selectedId by rememberSaveable { mutableStateOf<String?>(null) }
    var mealTypeName by rememberSaveable { mutableStateOf(MealType.LUNCH.name) }
    val type = MealType.valueOf(mealTypeName)
    val selected = products.firstOrNull { it.id == selectedId }
    val keyboard = LocalSoftwareKeyboardController.current
    val normalized = normalizeSearch(query)
    val results = products.filter { (!recentOnly || it.id in recent) && it.searchName.contains(normalized) }
        .sortedWith(compareBy<ProductEntity> { if (it.id in recent) recent.indexOf(it.id) else Int.MAX_VALUE }.thenBy { it.name })
    Scaffold(
        topBar = { TopAppBar(title = { Column { Text("Dodaj posiłek", fontWeight = FontWeight.SemiBold); Text(day.date.toString(), style = MaterialTheme.typography.bodySmall) } },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Wróć do dziennika") } },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background)) },
        bottomBar = {
            selected?.let { product ->
                key(product.id) {
                    PortionEditor(product, type, busy, onAdd = { grams -> keyboard?.hide(); model.add(product.id, grams, type) })
                }
            }
        }
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedTextField(query, onValueChange = { query = it }, placeholder = { Text("Szukaj produktu lub potrawy") },
                leadingIcon = { Icon(Icons.Outlined.Search, null) }, trailingIcon = { if (query.isNotEmpty()) IconButton(onClick = { query = "" }) { Icon(Icons.Outlined.Close, "Wyczyść wyszukiwanie") } },
                singleLine = true, modifier = Modifier.fillMaxWidth().testTag("product-search"), shape = RoundedCornerShape(14.dp))
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = !recentOnly, onClick = { recentOnly = false }, label = { Text("Produkty") })
                FilterChip(selected = recentOnly, onClick = { recentOnly = true }, label = { Text("Ostatnie") })
                FilterChip(selected = false, onClick = { keyboard?.hide(); onRations() }, label = { Text("Racje") }, modifier = Modifier.testTag("open-rations"))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.Storage, null, tint = MaterialTheme.colorScheme.primary)
                Text("Baza lokalna dostępna offline", style = MaterialTheme.typography.bodySmall)
            }
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                MealType.entries.forEach { option ->
                    FilterChip(selected = type == option, onClick = { mealTypeName = option.name }, label = { Text(option.label) })
                }
            }
            SectionTitle(if (recentOnly) "Ostatnio używane" else "Wybierz produkt")
            if (results.isEmpty()) {
                Text(if (recentOnly && query.isBlank()) "Dodane produkty pojawią się tutaj." else "Brak wyników. Spróbuj innej nazwy.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp), contentPadding = PaddingValues(bottom = 16.dp)) {
                items(results, key = { it.id }) { product ->
                    ProductRow(product, selectedId == product.id, enabled = !busy, onSelect = { selectedId = product.id; keyboard?.hide() })
                }
            }
        }
    }
}

@Composable private fun ProductRow(product: ProductEntity, selected: Boolean, enabled: Boolean, onSelect: () -> Unit) {
    Surface(color = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth().testTag("product-${product.id}").clickable(enabled = enabled, onClick = onSelect)) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            Icon(if (product.category == "Owoc" || product.category == "Warzywo") Icons.Outlined.Eco else Icons.Outlined.Restaurant,
                contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(28.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(product.name, fontWeight = FontWeight.Medium)
                Text("${product.kcal.roundToInt()} kcal / 100 g", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Icon(if (selected) Icons.Outlined.CheckCircle else Icons.Outlined.AddCircleOutline,
                contentDescription = if (selected) "Wybrano ${product.name}" else "Wybierz ${product.name}", tint = MaterialTheme.colorScheme.primary)
        }
    }
}

@Composable private fun PortionEditor(product: ProductEntity, type: MealType, busy: Boolean, onAdd: (Double) -> Unit) {
    var grams by rememberSaveable(product.id) { mutableStateOf(decimal(product.defaultGrams)) }
    val amount = parseAmount(grams)
    Surface(color = MaterialTheme.colorScheme.surface, shadowElevation = 8.dp, shape = RoundedCornerShape(topStart = 22.dp, topEnd = 22.dp)) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(product.name, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                Text(amount?.let { "${product.nutrients().portion(it).kcal.roundToInt()} kcal" } ?: "— kcal", fontWeight = FontWeight.SemiBold)
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedIconButton(onClick = { grams = decimal(((amount ?: product.defaultGrams) - 10).coerceAtLeast(1.0)) }, enabled = !busy) { Icon(Icons.Outlined.Remove, "Zmniejsz o 10 g") }
                OutlinedTextField(grams, onValueChange = { grams = it }, modifier = Modifier.weight(1f).testTag("portion-grams"), label = { Text("Gramatura") }, suffix = { Text("g") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true, isError = amount == null, enabled = !busy)
                OutlinedIconButton(onClick = { grams = decimal(((amount ?: product.defaultGrams) + 10).coerceAtMost(Nutrients.MAX_GRAMS)) }, enabled = !busy) { Icon(Icons.Outlined.Add, "Zwiększ o 10 g") }
            }
            if (amount == null) Text("Podaj dodatnią ilość, najwyżej 10 000 g.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            Button(onClick = { amount?.let(onAdd) }, enabled = amount != null && !busy, modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp).testTag("confirm-food"), shape = RoundedCornerShape(14.dp)) {
                Text(if (busy) "Zapisuję…" else "Dodaj · ${type.label}", style = MaterialTheme.typography.titleMedium)
            }
        }
    }
}
