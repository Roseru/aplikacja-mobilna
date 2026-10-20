package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.session.*

@Composable fun PhotoAnalysisPanel(preview:PhotoAnalysisPreview?) {
    val result=preview?:return
    Card(Modifier.fillMaxWidth().testTag("photo-analysis-result")) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
            Text("Zapisany wynik analizy",style=MaterialTheme.typography.titleMedium)
            Text(if(result.provider=="mock") "Wynik testowy serwera — bez rozpoznawania zdjęcia."
                else "Szacunek AI · ${result.model}. Sprawdź skład i porcje.")
            Text(when {
                result.decision=="cancelled"->"Analiza została anulowana. Możesz dodać posiłek ręcznie."
                result.decision=="confirmed"->"Propozycja zatwierdzona na serwerze. Sam odczyt nie dodaje jej do lokalnego dziennika."
                result.state=="queued"->"Zdjęcie czeka na analizę."
                result.state=="running"->"Serwer analizuje zdjęcie."
                result.state=="failed"->"Nie udało się przygotować propozycji. Ręczne dodawanie posiłków jest dostępne."
                else->"Propozycja do sprawdzenia. Posiłek nie został jeszcze zapisany."
            },Modifier.testTag("photo-analysis-state"))
            Text("To ostatnio zapisany stan. Przycisk „Sprawdź wynik” pobiera aktualizację.",style=MaterialTheme.typography.bodySmall)
            result.nutrition?.let { totals->
                Text("${if(totals.energy.missingCount>0) "Znana suma" else "Razem"} · ${nutrient(totals.energy,"kcal")}",style=MaterialTheme.typography.titleMedium,
                    modifier=Modifier.testTag("photo-analysis-total"))
                Text("B: ${nutrient(totals.protein,"g")} · T: ${nutrient(totals.fat,"g")} · W: ${nutrient(totals.carbs,"g")}")
                if(listOf(totals.energy,totals.protein,totals.fat,totals.carbs).any {it.missingCount>0})
                    Text("Niepełne wartości obejmują tylko znane składniki; brak danych nie oznacza zera.")
            }
            result.items.forEachIndexed { index,item->
                HorizontalDivider()
                Column(verticalArrangement=Arrangement.spacedBy(4.dp),modifier=Modifier.testTag("photo-analysis-item-$index")) {
                    Text(item.name,style=MaterialTheme.typography.titleSmall,maxLines=3,overflow=TextOverflow.Ellipsis)
                    Text("${item.amount} ${item.unit} · ${if(item.nutrition.energy.missingCount>0) "brak danych kcal" else nutrient(item.nutrition.energy,"kcal")}")
                    Text("B: ${itemNutrient(item.nutrition.protein)} · T: ${itemNutrient(item.nutrition.fat)} · W: ${itemNutrient(item.nutrition.carbs)}",
                        style=MaterialTheme.typography.bodySmall)
                    Text(when(item.uncertainty){"low"->"Niska niepewność";"high"->"Wysoka niepewność — sprawdź porcję i skład";else->"Umiarkowana niepewność"},
                        style=MaterialTheme.typography.bodySmall)
                    item.notes.forEach {Text(it,style=MaterialTheme.typography.bodySmall,maxLines=3,overflow=TextOverflow.Ellipsis)}
                }
            }
            result.notes.forEach {Text(it,style=MaterialTheme.typography.bodySmall,maxLines=4,overflow=TextOverflow.Ellipsis)}
        }
    }
}

private fun nutrient(value:PhotoNutrientPreview,unit:String)=
    "${value.display} $unit"+if(value.missingCount>0) " (niepełne)" else ""
private fun itemNutrient(value:PhotoNutrientPreview)=if(value.missingCount>0) "brak danych" else "${value.display} g"
