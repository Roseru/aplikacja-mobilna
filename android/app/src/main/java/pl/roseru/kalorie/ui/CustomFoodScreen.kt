package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.*
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun CustomFoodScreen(model: DiaryViewModel, onBack: () -> Unit) {
    val busy by model.busy.collectAsStateWithLifecycle()
    val day by model.day.collectAsStateWithLifecycle()
    var name by rememberSaveable { mutableStateOf("") }
    var source by rememberSaveable { mutableStateOf("") }
    var kcal by rememberSaveable { mutableStateOf("") }
    var protein by rememberSaveable { mutableStateOf("") }
    var fat by rememberSaveable { mutableStateOf("") }
    var carbs by rememberSaveable { mutableStateOf("") }
    var grams by rememberSaveable { mutableStateOf("100") }
    var typeName by rememberSaveable { mutableStateOf(MealType.LUNCH.name) }
    val energy = parseNumber(kcal)?.takeIf { it in 0.0..1000.0 }
    val amount = parseAmount(grams)
    fun macroValid(text: String) = text.isBlank() || parseNumber(text)?.let { it in 0.0..100.0 } == true
    val valid = name.trim().length in 2..100 && source.trim().length in 3..250 && energy != null && amount != null &&
        listOf(protein, fat, carbs).all(::macroValid)
    val keyboard = LocalSoftwareKeyboardController.current
    Scaffold(topBar = { TopAppBar(title = { Text("Własny produkt") }, navigationIcon = {
        IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Wróć") }
    }, colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background)) },
        bottomBar = { Surface(color = MaterialTheme.colorScheme.surface, shadowElevation = 8.dp) {
            Column(Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (energy != null && amount != null) "Zjedzona porcja: ${(energy * amount / 100).roundToInt()} kcal" else "Uzupełnij nazwę, źródło, kcal i gramaturę.")
                Button(onClick = {
                    keyboard?.hide()
                    model.addCustom(CustomProductDraft(name, requireNotNull(energy), parseNumber(protein), parseNumber(fat), parseNumber(carbs), source),
                        requireNotNull(amount), MealType.valueOf(typeName))
                }, enabled = valid && !busy, modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp).testTag("confirm-custom-food"), shape = RoundedCornerShape(14.dp)) {
                    Text(if (busy) "Zapisuję…" else "Zapisz produkt i dodaj")
                }
            }
        } }
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding).verticalScroll(rememberScrollState()).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("Prywatny wpis dostępny offline. Będzie można wybrać go ponownie z listy produktów.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(name, onValueChange = { name = it }, label = { Text("Nazwa produktu") }, singleLine = true,
                enabled = !busy, modifier = Modifier.fillMaxWidth().testTag("custom-name"))
            OutlinedTextField(source, onValueChange = { source = it }, label = { Text("Źródło: etykieta, przepis lub szacunek") },
                enabled = !busy, modifier = Modifier.fillMaxWidth().testTag("custom-source"))
            SectionTitle("Wartości na 100 g")
            NumericField("Kalorie", "kcal", kcal, { kcal = it }, !kcal.isBlank() && energy == null, "custom-kcal", busy)
            Text("Makra są opcjonalne. Puste pole oznacza brak danych.", style = MaterialTheme.typography.bodySmall)
            NumericField("Białko", "g", protein, { protein = it }, !macroValid(protein), "custom-protein", busy)
            NumericField("Tłuszcze", "g", fat, { fat = it }, !macroValid(fat), "custom-fat", busy)
            NumericField("Węglowodany", "g", carbs, { carbs = it }, !macroValid(carbs), "custom-carbs", busy)
            SectionTitle("Zjedzona porcja · ${day.date}")
            NumericField("Zjedzona ilość", "g", grams, { grams = it }, amount == null, "custom-grams", busy)
            MealType.entries.forEach { type -> FilterChip(selected = typeName == type.name, onClick = { typeName = type.name },
                label = { Text(type.label) }, enabled = !busy) }
            Text("Kcal: 0–1000 / 100 g. Makra: 0–100 g / 100 g. Ilość: więcej niż 0, najwyżej 10 000 g.", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable internal fun NumericField(label: String, unit: String, value: String, onChange: (String) -> Unit, error: Boolean,
    tag: String, busy: Boolean = false) {
    OutlinedTextField(value, onValueChange = onChange, label = { Text(label) }, suffix = { Text(unit) }, singleLine = true,
        isError = error, enabled = !busy, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth().testTag(tag))
}
