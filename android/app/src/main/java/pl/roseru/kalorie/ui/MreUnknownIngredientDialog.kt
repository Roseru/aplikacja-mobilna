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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.ExactNutrition
import pl.roseru.kalorie.core.catalog.MreManualInput
import pl.roseru.kalorie.core.catalog.MreMissingIngredient

@Composable internal fun MreUnknownIngredientDialog(ingredient: MreMissingIngredient, busy: Boolean,
    onSave: (MreManualInput) -> Unit, onClose: () -> Unit) {
    var grams by rememberSaveable(ingredient.locator) { mutableStateOf("") }
    var kcal by rememberSaveable(ingredient.locator) { mutableStateOf("") }
    var protein by rememberSaveable(ingredient.locator) { mutableStateOf("") }
    var fat by rememberSaveable(ingredient.locator) { mutableStateOf("") }
    var carbs by rememberSaveable(ingredient.locator) { mutableStateOf("") }
    val input = runCatching { MreManualInput.read(grams,
        ExactNutrition.fields.zip(listOf(kcal, protein, fat, carbs)).toMap()) }.getOrNull()
    AlertDialog(onDismissRequest = { if (!busy) onClose() }, title = { Text(ingredient.name) },
        dismissButton = { TextButton(onClick = onClose, enabled = !busy) { Text("Anuluj") } },
        confirmButton = { TextButton(onClick = { input?.let(onSave) }, enabled = !busy && input != null,
            modifier = Modifier.testTag("mre-unknown-save")) { Text(if (busy) "Zapisuję…" else "Zapisz osobny wpis") } },
        text = { Column(Modifier.fillMaxWidth().heightIn(max = 480.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Ten składnik nie ma potwierdzonego profilu. Nie uzupełniamy go wartościami podobnego produktu.")
            ingredient.reasons.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
            OutlinedTextField(grams, { grams = it }, label = { Text("Zjedzona masa") }, suffix = { Text("g") },
                singleLine = true, enabled = !busy, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal, imeAction = ImeAction.Done),
                keyboardActions = doneKeyboardActions(),
                modifier = Modifier.fillMaxWidth().testTag("mre-unknown-grams"),
                supportingText = { Text("Podaj więcej niż 0 i najwyżej 10000g.") })
            Text("Dane z etykiety na 100g — opcjonalne. Puste pole oznacza brak danych; wpisane 0 oznacza znane zero.")
            listOf(Triple("Energia [kcal]", kcal, { value: String -> kcal = value }),
                Triple("Białko [g]", protein, { value: String -> protein = value }),
                Triple("Tłuszcz [g]", fat, { value: String -> fat = value }),
                Triple("Węglowodany [g]", carbs, { value: String -> carbs = value })).forEachIndexed { index, (label, value, update) ->
                OutlinedTextField(value, update, label = { Text(label) }, singleLine = true, enabled = !busy,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    modifier = Modifier.fillMaxWidth().testTag("mre-unknown-nutrient-$index"))
            }
            if (grams.isNotBlank() && input == null) Text("Sprawdź ilość i wartości/100g: 0–1000kcal oraz 0–100g makra, najwyżej 6 miejsc po przecinku.",
                color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            Text("Wpis pojawi się osobno w dzienniku. Przy nieznanej energii dzień pozostanie niekompletny. Wybór średniej pakietu dodatków jest odznaczany, aby nie doliczyć go ponownie.",
                style = MaterialTheme.typography.bodySmall)
        } })
}
