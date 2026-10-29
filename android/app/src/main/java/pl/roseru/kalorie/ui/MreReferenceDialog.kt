package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.catalog.MreIngredientSource
import pl.roseru.kalorie.core.catalog.MreRationSelection

@Composable internal fun MreReferenceDialog(selection: MreRationSelection, ingredient: MreIngredientSource?, onClose: () -> Unit) {
    AlertDialog(onDismissRequest = onClose, title = { Text(ingredient?.name ?: selection.menu) },
        confirmButton = { TextButton(onClick = onClose) { Text("Zamknij") } },
        text = { Column(Modifier.fillMaxWidth().heightIn(max = 530.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (ingredient == null) {
                Text("Opracowanie DLA/HPRC COMRAD 2026. Dane konkretnej paczki mogą się różnić. Ten zbiór nie jest oficjalnym katalogiem wydania.")
                selection.warnings.forEach { Text(it) }
                Text("Masa w aplikacji oznacza porcję COMRAD, a nie potwierdzoną liczbę sztuk. Dla proszków nie doliczaj dodanej wody.")
                Text("Składniki bez potwierdzonych danych", fontWeight = FontWeight.SemiBold)
                val foods = selection.missing.filterNot { it.equipment }
                if (foods.isEmpty()) Text("Brak dodatkowych zgłoszonych składników jadalnych.")
                foods.forEach { row -> Column {
                    Text(row.name, fontWeight = FontWeight.Medium)
                    row.reasons.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                } }
                val equipment = selection.missing.filter { it.equipment }
                if (equipment.isNotEmpty()) {
                    Text("Akcesoria niejadalne", fontWeight = FontWeight.SemiBold)
                    Text(equipment.joinToString { it.name })
                }
                Text("Lista DLA została zebrana z indeksowanego tekstu; PDF DLA zwracał HTTP403. Oryginalny PDF COMRAD i uwagi źródłowe zachowano w materiałach projektu.",
                    style = MaterialTheme.typography.bodySmall)
            } else {
                Text("Porcja źródłowa: ${ingredient.portionGrams.replace('.', ',')} g · COMRAD, strona ${ingredient.page}")
                Text(ingredient.sourceLocator, style = MaterialTheme.typography.bodySmall)
                if (ingredient.flavours.isNotEmpty()) Text("Warianty: ${ingredient.flavours.joinToString()}. Profil ogólny nie potwierdza osobnych wartości każdego smaku.")
                if (ingredient.nutritionStatus == "source_packet_average") Text("Średnia zbiorcza pakietu z MRE42. Nie jest pomiarem konkretnego pakietu2026 i nie może być dodana ponownie do jego składników.")
                ingredient.notes.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                Text("Wartości na porcję ze źródła", fontWeight = FontWeight.SemiBold)
                val labels = mapOf("weight_g" to "Masa [g]", "energy_kcal" to "Energia [kcal]", "protein_g" to "Białko [g]",
                    "fat_g" to "Tłuszcz [g]", "carbohydrate_g" to "Węglowodany [g]", "fiber_g" to "Błonnik [g]",
                    "caffeine_mg" to "Kofeina [mg]", "sugars_g" to "Cukry [g]")
                ingredient.values.forEach { (field, value) ->
                    val label = labels[field] ?: field
                    Text("$label: ${value?.replace('.', ',') ?: "brak danych"}", style = MaterialTheme.typography.bodySmall)
                    if (field.endsWith("source_unit")) Text("Jednostka źródłowa wymaga potwierdzenia; wartości nie przeliczono.", style = MaterialTheme.typography.bodySmall)
                }
                Text("Wartości/100g są przeliczeniem porcji do6miejsc, z ROUND_HALF_UP. Brak danych pozostaje brakiem, nie zerem.", style = MaterialTheme.typography.bodySmall)
                Text(ingredient.url, style = MaterialTheme.typography.bodySmall)
            }
        } })
}
