package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.core.*
import java.math.BigDecimal

@Composable fun MaintenanceScreen(model: DiaryViewModel, onBack: () -> Unit) {
    val profile by model.profile.collectAsStateWithLifecycle()
    val weights by model.weights.collectAsStateWithLifecycle()
    val goal by model.todayGoal.collectAsStateWithLifecycle()
    val busy by model.busy.collectAsStateWithLifecycle()
    val saveVersion by model.calculatedGoalSaveVersion.collectAsStateWithLifecycle()
    var seenSave by rememberSaveable(model) {mutableStateOf(saveVersion)}
    LaunchedEffect(saveVersion) {if(saveVersion>seenSave){seenSave=saveVersion;onBack()}}
    var age by rememberSaveable(model) {mutableStateOf("")}
    var height by rememberSaveable(model) {mutableStateOf("")}
    var weight by rememberSaveable(model) {mutableStateOf("")}
    var activityName by rememberSaveable(model) {mutableStateOf(ActivityClass.GARRISON.name)}
    var variantName by rememberSaveable(model) {mutableStateOf<String?>(null)}
    var touched by rememberSaveable(model) {mutableStateOf(false)}
    var seeded by rememberSaveable(model) {mutableStateOf(false)}
    var qualified by remember(model) {mutableStateOf(false)}
    var computed by rememberSaveable(model) {mutableStateOf<String?>(null)}
    var kcal by rememberSaveable(model) {mutableStateOf("")}
    var protein by rememberSaveable(model) {mutableStateOf("")}
    var fat by rememberSaveable(model) {mutableStateOf("")}
    var carbs by rememberSaveable(model) {mutableStateOf("")}
    var aimName by rememberSaveable(model) {mutableStateOf(DietAim.MAINTAIN.name)}
    var confirm by remember(model) {mutableStateOf(false)}
    LaunchedEffect(profile,weights,goal) {
        if(!seeded && !touched && (profile!=null || weights.isNotEmpty())) {
            height=profile?.heightCm?.let(::formDecimal) ?: ""
            weight=weights.firstOrNull()?.kg?.let(::formDecimal) ?: ""
            activityName=profile?.activityClass ?: ActivityClass.GARRISON.name
            aimName=profile?.dietAim ?: DietAim.MAINTAIN.name
            protein=goal?.protein?.let(::formDecimal) ?: "";fat=goal?.fat?.let(::formDecimal) ?: "";carbs=goal?.carbs?.let(::formDecimal) ?: ""
            seeded=true
        }
    }
    val activity=ActivityClass.entries.firstOrNull {it.name==activityName} ?: ActivityClass.GARRISON
    val variant=EquationVariant.entries.firstOrNull {it.name==variantName}
    val ageNumber=age.takeIf {Regex("[0-9]{1,3}").matches(it)}?.toIntOrNull()?.takeIf {it in 18..120}
    val h=MaintenanceEstimate.inputDecimal(height)?.takeIf {it<=BigDecimal("300")}
    val w=MaintenanceEstimate.inputDecimal(weight)?.takeIf {it<=BigDecimal("1000")}
    val input=if(ageNumber!=null && h!=null && w!=null && variant!=null)MaintenanceInput(ageNumber,h,w,variant,activity) else null
    val candidate=remember(input) {input?.let {runCatching {MaintenanceEstimate.calculate(it)}.getOrNull()}}
    val result=remember(computed) {computed?.let {runCatching {MaintenanceEstimate.read(it)}.getOrNull()}}
    fun edited() {touched=true;computed=null;confirm=false}
    fun macro(text:String):BigDecimal? = if(text.isBlank())null else MaintenanceEstimate.inputDecimal(text)
        ?: text.trim().replace(',','.').takeIf {Regex("0(\\.0{1,6})?").matches(it)}?.let {BigDecimal.ZERO}
    fun macroValid(text:String)=text.isBlank() || macro(text)?.let {it<=BigDecimal("5000")}==true
    val target=MaintenanceEstimate.inputDecimal(kcal)?.takeIf {it<=BigDecimal("20000")}
    val targetValid=target!=null && listOf(protein,fat,carbs).all(::macroValid)
    val aim=DietAim.entries.first {it.name==aimName}
    LazyColumn(Modifier.fillMaxSize().imePadding().testTag("maintenance-screen"),contentPadding=PaddingValues(20.dp),verticalArrangement=Arrangement.spacedBy(16.dp)) {
        item {
            TextButton(onClick=onBack,enabled=!busy){Text("Wróć")}
            Text("Zapotrzebowanie",style=MaterialTheme.typography.headlineLarge,fontWeight=FontWeight.Bold)
            Text("Oblicz orientacyjną energię do utrzymania masy, a następnie wybierz własny cel spożycia.")
        }
        item {
            Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
                EstimateField("Wiek w pełnych latach","lat",age,{age=it;edited()},age.isNotBlank() && ageNumber==null,"maintenance-age",busy)
                EstimateField("Wzrost","cm",height,{height=it;edited()},height.isNotBlank() && h==null,"maintenance-height",busy)
                EstimateField("Masa do obliczenia","kg",weight,{weight=it;edited()},weight.isNotBlank() && w==null,"maintenance-weight",busy)
                Text("Wzrost: dodatni do 300 cm, masa: dodatnia do 1000 kg; do 6 miejsc po przecinku.",style=MaterialTheme.typography.bodySmall)
                Text("Wybierz wariant równania",style=MaterialTheme.typography.titleMedium)
                EquationVariant.entries.forEach {option ->
                    FilterChip(selected=variant==option,onClick={variantName=option.name;edited()},enabled=!busy,
                        label={Text(option.label)},modifier=Modifier.fillMaxWidth().testTag("equation-${option.wire}"))
                }
                Text("Klasa użyta w oszacowaniu",style=MaterialTheme.typography.titleMedium)
                ActivityClass.entries.forEach {option ->
                    FilterChip(selected=activity==option,onClick={activityName=option.name;edited()},enabled=!busy,
                        label={Text(option.label)},leadingIcon={SoldierIcon(option)},modifier=Modifier.fillMaxWidth().testTag("maintenance-activity-${option.name}"))
                }
                Text("Wersja v1 jest przeznaczona dla dorosłych 18–120 lat. Przy ciąży, karmieniu lub potrzebie specjalistycznego ustalenia diety dostępny jest ręczny cel.",
                    style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
                Row {
                    Checkbox(checked=qualified,onCheckedChange={qualified=it;computed=null;confirm=false},enabled=!busy,modifier=Modifier.testTag("maintenance-qualified"))
                    Text("Potwierdzam dane i zakres kalkulatora v1.",Modifier.padding(top=12.dp))
                }
                if(input!=null && candidate==null)Text("Te dane nie dają dodatniego wyniku. Sprawdź pola lub ustaw cel ręcznie.",color=MaterialTheme.colorScheme.error)
                Button(onClick={candidate?.let {
                    computed=it.stored();kcal=it.suggestedGoal.toPlainString()
                    protein=goal?.protein?.let(::formDecimal) ?: "";fat=goal?.fat?.let(::formDecimal) ?: "";carbs=goal?.carbs?.let(::formDecimal) ?: ""
                }},enabled=candidate!=null && qualified && !busy,modifier=Modifier.fillMaxWidth().testTag("calculate-maintenance")){Text("Oblicz szacunek")}
            }
        }
        if(result!=null && qualified)item {
            Card(colors=CardDefaults.cardColors(containerColor=MaterialTheme.colorScheme.primaryContainer)) {
                Column(Modifier.padding(18.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                    Text("Szacowane utrzymanie masy",style=MaterialTheme.typography.titleMedium)
                    Text("${displayEnergy(result.maintenance)} kcal / dzień",style=MaterialTheme.typography.headlineMedium,modifier=Modifier.testTag("maintenance-result"))
                    Text("Spoczynkowe: ${displayEnergy(result.resting)} kcal · PAL ${result.pal.toPlainString()}")
                    Text("Metoda Mifflina–St Jeora. Wynik jest szacunkiem na podstawie wpisanych danych.",style=MaterialTheme.typography.bodySmall)
                }
            }
            Column(Modifier.padding(top=16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
                SectionTitle("Wybierz dzienny cel")
                Text("Możesz wpisać inną liczbę kcal. Zapis nastąpi dopiero po zatwierdzeniu; kalkulator nie dobiera deficytu ani nadwyżki.")
                DietAim.entries.forEach {option->FilterChip(selected=aim==option,onClick={aimName=option.name},label={Text(option.label)},enabled=!busy,
                    modifier=Modifier.fillMaxWidth().testTag("maintenance-aim-${option.name}"))}
                EstimateField("Twój cel spożycia","kcal",kcal,{kcal=it},kcal.isNotBlank() && target==null,"maintenance-goal",busy)
                EstimateField("Białko (opcjonalnie)","g",protein,{protein=it},!macroValid(protein),"maintenance-protein",busy)
                EstimateField("Tłuszcze (opcjonalnie)","g",fat,{fat=it},!macroValid(fat),"maintenance-fat",busy)
                EstimateField("Węglowodany (opcjonalnie)","g",carbs,{carbs=it},!macroValid(carbs),"maintenance-carbs",busy)
                Button(onClick={confirm=true},enabled=targetValid && !busy,modifier=Modifier.fillMaxWidth().testTag("review-calculated-goal")){Text("Sprawdź przed zapisem")}
            }
        }
    }
    if(confirm && result!=null && qualified && targetValid)AlertDialog(onDismissRequest={confirm=false},title={Text("Zapisać cel od dzisiaj?")},
        text={Column(verticalArrangement=Arrangement.spacedBy(8.dp)) {
            Text("Szacunek utrzymania: ${displayEnergy(result.maintenance)} kcal")
            Text("Twój cel: ${target!!.toPlainString()} kcal · ${aim.label}",fontWeight=FontWeight.Bold)
            Text("B/T/W: ${protein.ifBlank {"brak"}} / ${fat.ifBlank {"brak"}} / ${carbs.ifBlank {"brak"}} g")
            Text("Dane: ${result.input.age} lat · ${result.input.height.toPlainString()} cm · ${result.input.weight.toPlainString()} kg · ${result.input.variant.label}")
            Text("${result.input.activity.label}. Wcześniejsze cele i dane profilu pozostaną zapisane.")
        }},confirmButton={TextButton(onClick={
            model.setCalculatedGoal(result,target!!.toDouble(),macro(protein)?.toDouble(),macro(fat)?.toDouble(),macro(carbs)?.toDouble(),aim,qualified)
            confirm=false
        },enabled=!busy,modifier=Modifier.testTag("confirm-calculated-goal")){Text("Zapisz cel i oszacowanie")}},
        dismissButton={TextButton(onClick={confirm=false}){Text("Wróć do edycji")}})
}

private fun displayEnergy(value:BigDecimal)=value.setScale(2,java.math.RoundingMode.HALF_UP).stripTrailingZeros().toPlainString()
private fun formDecimal(value:Double)=BigDecimal.valueOf(value).stripTrailingZeros().toPlainString().replace('.',',')

@Composable private fun EstimateField(label:String,unit:String,value:String,change:(String)->Unit,error:Boolean,tag:String,busy:Boolean) {
    OutlinedTextField(value,onValueChange=change,label={Text(label)},suffix={Text(unit)},singleLine=true,isError=error,enabled=!busy,
        keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth().testTag(tag))
}

@Composable fun SavedMaintenanceEstimate(estimateJson:String?) {
    if(estimateJson==null)return
    val estimate=remember(estimateJson){runCatching {MaintenanceEstimate.read(estimateJson)}.getOrNull()}
    Card(Modifier.fillMaxWidth().testTag("saved-maintenance")) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
            if(estimate==null)Text("Zapisane oszacowanie wymaga sprawdzenia. Nie przeliczono go z celu spożycia.")
            else {
                Text("Szacunek zapisany przy tej wersji celu",style=MaterialTheme.typography.titleSmall)
                Text("${displayEnergy(estimate.maintenance)} kcal / dzień",style=MaterialTheme.typography.titleLarge)
                Text("${estimate.input.age} lat · ${estimate.input.height.toPlainString()} cm · ${estimate.input.weight.toPlainString()} kg · ${estimate.input.variant.label}",style=MaterialTheme.typography.bodySmall)
                Text("${estimate.input.activity.label} · PAL ${estimate.pal.toPlainString()}",style=MaterialTheme.typography.bodySmall)
                Text("Obliczono ${estimate.estimatedAt.atZone(java.time.ZoneId.systemDefault()).toLocalDate()} · Mifflin–St Jeor",style=MaterialTheme.typography.bodySmall)
            }
        }
    }
}
