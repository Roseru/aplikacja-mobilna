package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.data.MealItemEntity
import pl.roseru.kalorie.data.ingredientInput

@Composable internal fun MealIngredientDialog(item:MealItemEntity?,busy:Boolean,onDismiss:()->Unit,
    onSave:(MealIngredientInput)->Unit) {
    val original=remember(item){item?.ingredientInput()}
    var name by rememberSaveable(item?.id){mutableStateOf(original?.name?:"")}
    var amount by rememberSaveable(item?.id){mutableStateOf(original?.amount?:"100")}
    var unit by rememberSaveable(item?.id){mutableStateOf(original?.unit?.wire?:"g")}
    var basis by rememberSaveable(item?.id){mutableStateOf(original?.basisUnit?.wire?:"g")}
    val initial=original?.nutrition?.values()?.map {it?.let(ContractDecimal::canonical)?:""}?:List(4){""}
    var energy by rememberSaveable(item?.id){mutableStateOf(initial[0])}
    var protein by rememberSaveable(item?.id){mutableStateOf(initial[1])}
    var fat by rememberSaveable(item?.id){mutableStateOf(initial[2])}
    var carbs by rememberSaveable(item?.id){mutableStateOf(initial[3])}
    val density=original?.density?.takeIf {name.trim()==original.name}
    val input=MealIngredientInput.parse(name,amount,unit,basis,listOf(energy,protein,fat,carbs),density)
    AlertDialog(onDismissRequest=onDismiss,title={Text(if(item==null)"Dodaj składnik" else "Popraw składnik")},text={
        Column(Modifier.heightIn(max=440.dp).verticalScroll(rememberScrollState()).testTag("ingredient-form"),
            verticalArrangement=Arrangement.spacedBy(12.dp)) {
            Text("Własne wartości tego spożycia. Puste pole oznacza brak danych; 0 oznacza znane zero.")
            OutlinedTextField(name,{name=it},label={Text("Nazwa składnika")},singleLine=true,
                modifier=Modifier.fillMaxWidth().testTag("ingredient-name"))
            if(item!=null)Text("Zmiana nazwy zastępuje składnik własnym wpisem. Źródło pozostaje zachowane.",style=MaterialTheme.typography.bodySmall)
            OutlinedTextField(amount,{amount=it},label={Text("Zjedzona ilość")},singleLine=true,
                keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),
                modifier=Modifier.fillMaxWidth().testTag("ingredient-amount"))
            IngredientUnit("Jednostka ilości",unit,"quantity-unit"){unit=it}
            IngredientUnit("Wartości poniżej na 100",basis,"basis-unit"){basis=it}
            Text("Ilość skaluje spożycie. Wartości na 100 $basis zmieniasz osobno; zmiana jednostki nie przelicza ich automatycznie.",style=MaterialTheme.typography.bodySmall)
            listOf(Triple("Energia (kcal)",energy,"energy"),Triple("Białko (g)",protein,"protein"),
                Triple("Tłuszcz (g)",fat,"fat"),Triple("Węglowodany (g)",carbs,"carbs")).forEachIndexed {index,(label,value,tag)->
                OutlinedTextField(value,{when(index){0->energy=it;1->protein=it;2->fat=it;else->carbs=it}},
                    label={Text("$label / 100 $basis")},singleLine=true,keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),
                    modifier=Modifier.fillMaxWidth().testTag("ingredient-$tag"))
            }
            if(unit!=basis)Text(density?.let {"Przeliczenie g/ml: ${ContractDecimal.canonical(it.gramsPerMl)} g/ml · ${it.sourceId}"}
                ?:"Różne jednostki wymagają zapisanej gęstości. Wybierz tę samą jednostkę ilości i podstawy.",style=MaterialTheme.typography.bodySmall)
            if(input!=null) {
                val total=NutritionV1.calculate(listOf(input.portion()))
                Text("Spożycie: ${if(total.energy.complete)total.energy.display else "brak"} kcal · B ${if(total.protein.complete)total.protein.display else "brak"} g · T ${if(total.fat.complete)total.fat.display else "brak"} g · W ${if(total.carbs.complete)total.carbs.display else "brak"} g",
                    modifier=Modifier.testTag("ingredient-preview"))
            } else Text("Podaj nazwę, ilość 0–10 000 (większą od zera) i nieujemne wartości, do 6 miejsc po przecinku.",style=MaterialTheme.typography.bodySmall)
            Text("Zapis działa offline. Oczekujące zmiany i konflikty sprawdzisz na ekranie konta.",style=MaterialTheme.typography.bodySmall)
        }
    },confirmButton={TextButton(onClick={input?.let(onSave)},enabled=input!=null && !busy,
        modifier=Modifier.testTag("confirm-ingredient")){Text("Zapisz")}},
        dismissButton={TextButton(onClick=onDismiss){Text("Anuluj")}})
}

@Composable private fun IngredientUnit(label:String,value:String,tag:String,onChange:(String)->Unit) {
    Column {
        Text(label,style=MaterialTheme.typography.labelLarge)
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            listOf("g","ml").forEach {unit->FilterChip(selected=value==unit,onClick={onChange(unit)},label={Text(unit)},
                modifier=Modifier.testTag("$tag-$unit"))}
        }
    }
}
