package pl.roseru.kalorie.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Inventory2
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.mapSaver
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
import pl.roseru.kalorie.data.*
import java.math.BigDecimal

private val QuantitySaver = mapSaver<Map<String, String>>(
    save = { it }, restore = { values -> values.mapValues { it.value as String } }
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun RationScreen(model: DiaryViewModel, onBack: () -> Unit) {
    val rations by model.rations.collectAsStateWithLifecycle()
    val products by model.products.collectAsStateWithLifecycle()
    val day by model.day.collectAsStateWithLifecycle()
    val busy by model.busy.collectAsStateWithLifecycle()
    var selectedId by rememberSaveable { mutableStateOf<String?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    var typeName by rememberSaveable { mutableStateOf(MealType.LUNCH.name) }
    var quantities by rememberSaveable(stateSaver = QuantitySaver) { mutableStateOf(emptyMap<String, String>()) }
    val type = MealType.valueOf(typeName)
    val selected = rations.firstOrNull { it.ration.id == selectedId }
    val components = selected?.components?.sortedBy { it.position }.orEmpty()
    val productMap = remember(products) { products.associateBy { it.id } }
    val amounts = quantities.mapValues { (id, text) ->
        ContractDecimal.userQuantity(text, 12)?.takeIf { amount -> components.any { it.id == id && amount <= BigDecimal(it.quantityText ?: ContractDecimal.canonical(BigDecimal.valueOf(it.packageGrams))) } }
    }
    val valid = amounts.isNotEmpty() && amounts.values.all { it != null } &&
        amounts.keys.all { id -> components.any { it.id == id && productMap[it.productId] != null } }
    val total = if (valid) components.mapNotNull { part ->
        amounts[part.id]?.let { productMap[part.productId]?.portion(ContractDecimal.canonical(it), part.quantityUnit) }
    }.total() else null
    val keyboard = LocalSoftwareKeyboardController.current
    fun back() { if (selectedId != null) { selectedId = null; quantities = emptyMap() } else onBack() }
    BackHandler { back() }
    Scaffold(
        topBar = { TopAppBar(title = { Column {
            Text(if (selected == null) "Racje" else "Składniki racji", fontWeight = FontWeight.SemiBold)
            Text(day.date.toString(), style = MaterialTheme.typography.bodySmall)
        } }, navigationIcon = { IconButton(onClick = { back() }, enabled = !busy) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Wróć") } },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background)) },
        bottomBar = { if (selected != null) Surface(color = MaterialTheme.colorScheme.surface, shadowElevation = 8.dp) {
            Column(Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Wybrano: ${quantities.size}/${components.size}")
                    Text(total?.let { "${it.energyText()} kcal" } ?: "— kcal", fontWeight = FontWeight.SemiBold)
                }
                if (total != null) {
                    fun field(value: FieldAggregate) = (if (value.complete) "" else "≥ ") + quantityText(value.display) +
                        if (value.complete) "" else " (brak: ${value.missingCount})"
                    val exact = total.asExact()
                    Text("B: ${field(exact.protein)} · T: ${field(exact.fat)} · W: ${field(exact.carbs)} g",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Button(onClick = {
                    keyboard?.hide()
                    model.addRation(selected.ration.id, amounts.mapValues { requireNotNull(it.value).toDouble() }, type,
                        amounts.mapValues { ContractDecimal.canonical(requireNotNull(it.value)) })
                }, enabled = valid && !busy, modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp).testTag("confirm-ration"), shape = RoundedCornerShape(14.dp)) {
                    Text(if (busy) "Zapisuję…" else "Zapisz zjedzone składniki")
                }
            }
        } }
    ) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding).testTag("ration-content"),
            contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (selected == null) {
                item { OutlinedTextField(query, onValueChange = { query = it }, label = { Text("Szukaj racji") },
                    singleLine = true, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp)) }
                item { Text("Zestawy demonstracyjne · dostępne offline", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall) }
                val results = rations.filter { normalizeSearch(it.ration.name).contains(normalizeSearch(query)) }
                if (results.isEmpty()) item { Text("Brak racji pasujących do wyszukiwania.") }
                items(results, key = { it.ration.id }) { ration ->
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(16.dp),
                        modifier = Modifier.fillMaxWidth().testTag("ration-${ration.ration.id}").clickable {
                            selectedId = ration.ration.id; quantities = emptyMap(); keyboard?.hide()
                        }) {
                        Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            Icon(Icons.Outlined.Inventory2, null, tint = MaterialTheme.colorScheme.primary)
                            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text(ration.ration.name, fontWeight = FontWeight.SemiBold)
                                Text("${ration.components.size} składniki · wybierz zjedzoną część", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            } else {
                item {
                    Text(selected.ration.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                    Text(selected.ration.description, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 8.dp))
                }
                item { Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    MealType.entries.forEach { option -> FilterChip(selected = type == option, onClick = { typeName = option.name },
                        enabled = !busy, label = { Text(option.label) }) }
                } }
                item {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        TextButton(onClick = { quantities = components.associate { it.id to (it.quantityText ?: ContractDecimal.canonical(BigDecimal.valueOf(it.packageGrams))) } }, enabled = !busy) { Text("Zaznacz całą rację") }
                        TextButton(onClick = { quantities = emptyMap() }, enabled = !busy && quantities.isNotEmpty()) { Text("Wyczyść") }
                    }
                    Text("Zaznacz tylko zjedzone produkty. Dla części opakowania podaj gramaturę.", style = MaterialTheme.typography.bodySmall)
                }
                items(components, key = { it.id }) { part ->
                    val product = productMap[part.productId]
                    if (product != null) RationComponent(part, product, quantities[part.id], busy,
                        onChecked = { checked -> quantities = if (checked) quantities + (part.id to (part.quantityText ?: ContractDecimal.canonical(BigDecimal.valueOf(part.packageGrams)))) else quantities - part.id },
                        onAmount = { quantities = quantities + (part.id to it) })
                    else Text("Nie można odczytać składnika. Otwórz rację ponownie.", color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}

@Composable private fun RationComponent(part: RationComponentEntity, product: ProductEntity, text: String?, busy: Boolean,
    onChecked: (Boolean) -> Unit, onAmount: (String) -> Unit) {
    val packageAmount = BigDecimal(part.quantityText ?: ContractDecimal.canonical(BigDecimal.valueOf(part.packageGrams)))
    val amount = text?.let { ContractDecimal.userQuantity(it, 12) }?.takeIf { it <= packageAmount }
    Card(colors = CardDefaults.cardColors(containerColor = if (text != null) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = text != null, onCheckedChange = onChecked, enabled = !busy, modifier = Modifier.testTag("ration-check-${part.id}"))
                Column(Modifier.weight(1f)) {
                    Text(product.name, fontWeight = FontWeight.Medium)
                    Text("Opakowanie: ${quantityText(ContractDecimal.canonical(packageAmount))} ${part.quantityUnit}", style = MaterialTheme.typography.bodySmall)
                }
                Text(if (packageAmount <= BigDecimal("10000")) "${product.portion(ContractDecimal.canonical(packageAmount), part.quantityUnit).energyText()} kcal" else "Podaj zjedzoną ilość", style = MaterialTheme.typography.bodySmall)
            }
            if (text != null) {
                OutlinedTextField(text, onValueChange = onAmount, label = { Text("Zjedzona ilość") }, suffix = { Text(part.quantityUnit) }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), enabled = !busy, isError = amount == null,
                    modifier = Modifier.fillMaxWidth().testTag("ration-grams-${part.id}"),
                    supportingText = { Text(amount?.let { "${product.portion(ContractDecimal.canonical(it), part.quantityUnit).energyText()} kcal · zjedzona część" }
                        ?: "Podaj ilość większą od 0, najwyżej ${quantityText(ContractDecimal.canonical(packageAmount.min(BigDecimal("10000"))))} ${part.quantityUnit}.") })
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(0.25 to "¼", 0.5 to "½", 1.0 to "Całość").forEach { (fraction, label) ->
                        OutlinedButton(onClick = { onAmount(quantityText(ContractDecimal.canonical(packageAmount.multiply(BigDecimal.valueOf(fraction))))) }, enabled = !busy) { Text(label) }
                    }
                }
            }
        }
    }
}
