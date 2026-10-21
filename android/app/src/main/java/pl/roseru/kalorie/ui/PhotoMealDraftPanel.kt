package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.session.*
import java.time.LocalDate

@Composable fun PhotoMealDraftPanel(session:SessionView,date:LocalDate,actions:PhotoDraftActions) {
    val row=session.photoUpload?:return
    val draft=session.photoMealDraft
    val idle=!session.photoUploadBusy && !session.busy && !session.pendingLogin && !session.requiresRecovery &&
        !session.bootstrapBusy && !session.profileBusy && !session.snapshotBusy && !session.motivationBusy &&
        !session.rankingConsentBusy && !session.rankingBusy && !session.nemesisBusy && !session.nemesisMutationBusy && !session.photoCapabilitiesBusy
    val editable=session.photoCanEditProposal && !row.blocked && idle
    if(draft==null) {
        val revision=session.photoAnalysis?.revision?:return
        if(session.photoCanEditProposal && !row.blocked) OutlinedButton(onClick={actions.start(row.operationId,revision,date)},enabled=editable,
            modifier=Modifier.fillMaxWidth().testTag("photo-meal-draft-start")){Text("Popraw rozpoznany posiłek")}
        return
    }
    if(draft.operationId!=row.operationId)return
    var edit by remember(session.binding?.lease,draft.operationId,draft.editRevision,session.photoCanEditProposal) {mutableStateOf<String?>(null)}
    var rename by remember(session.binding?.lease,draft.operationId,draft.editRevision,session.photoCanEditProposal) {mutableStateOf(false)}
    var discard by remember(session.binding?.lease,draft.operationId,draft.editRevision,session.photoCanEditProposal) {mutableStateOf(false)}
    val lifecycle=LocalLifecycleOwner.current
    DisposableEffect(lifecycle,session.binding?.lease,draft.operationId,draft.editRevision,session.photoCanEditProposal) {
        val observer=LifecycleEventObserver {_,event->if(event==Lifecycle.Event.ON_STOP){edit=null;rename=false;discard=false}}
        lifecycle.lifecycle.addObserver(observer)
        onDispose {lifecycle.lifecycle.removeObserver(observer)}
    }
    Card(Modifier.fillMaxWidth().testTag("photo-meal-draft-panel")) {
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)) {
            Text("Twoje poprawki",style=MaterialTheme.typography.titleLarge)
            Text(draft.title,style=MaterialTheme.typography.titleMedium,maxLines=3,overflow=TextOverflow.Ellipsis)
            Text(draft.localDate,style=MaterialTheme.typography.bodySmall)
            Text("Szkic zapisany na tym telefonie. Posiłek nie został jeszcze dodany do dziennika.")
            if(!session.photoCanEditProposal)Text("Szkic zachowano do odczytu. Sprawdź stan analizy przed dalszą edycją.")
            val totals=draft.nutrition
            Text("${if(totals.energy.missingCount>0) "Znana suma" else "Razem"}: ${draftNutrient(totals.energy,"kcal")}",
                style=MaterialTheme.typography.titleMedium,modifier=Modifier.testTag("photo-meal-draft-total"))
            Text("B: ${draftNutrient(totals.protein,"g")} · T: ${draftNutrient(totals.fat,"g")} · W: ${draftNutrient(totals.carbs,"g")}")
            if(listOf(totals.energy,totals.protein,totals.fat,totals.carbs).any {it.missingCount>0})Text("Niepełna suma obejmuje tylko znane wartości. Puste pole oznacza brak danych.")
            draft.items.forEach {item->
                HorizontalDivider()
                Column(Modifier.testTag("photo-meal-draft-item-${item.id}"),verticalArrangement=Arrangement.spacedBy(4.dp)) {
                    Text(item.input.name,style=MaterialTheme.typography.titleSmall,maxLines=3,overflow=TextOverflow.Ellipsis)
                    Text("${item.input.amount} ${item.input.unit} · ${if(item.energy.missingCount>0) "brak danych kcal" else draftNutrient(item.energy,"kcal")}")
                    Text(if(item.manuallyAdded) "Składnik dodany ręcznie" else "Szacunek AI z Twoimi poprawkami",style=MaterialTheme.typography.bodySmall)
                    Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick={edit=item.id},enabled=editable,modifier=Modifier.testTag("photo-meal-draft-edit-${item.id}")){Text("Popraw składnik")}
                        TextButton(onClick={actions.remove(draft.operationId,draft.editRevision,item.id)},enabled=editable && draft.items.size>1,
                            modifier=Modifier.testTag("photo-meal-draft-remove-${item.id}")){Text("Usuń")}
                    }
                }
            }
            OutlinedButton(onClick={edit=""},enabled=editable && draft.items.size<30,
                modifier=Modifier.fillMaxWidth().testTag("photo-meal-draft-add")){Text("Dodaj składnik")}
            TextButton(onClick={rename=true},enabled=editable,modifier=Modifier.testTag("photo-meal-draft-rename")){Text("Zmień nazwę posiłku")}
            TextButton(onClick={discard=true},enabled=editable,modifier=Modifier.testTag("photo-meal-draft-discard")){Text("Odrzuć poprawki")}
        }
    }
    edit?.let {target->
        val original=remember(target,draft.operationId,draft.editRevision){if(target.isEmpty())PhotoDraftInput("","100","g","","","","") else draft.items.singleOrNull {it.id==target}?.input}
        if(original!=null && session.photoCanEditProposal) PhotoDraftItemDialog(original,target.isEmpty(),editable,onDismiss={edit=null},onSave={input->
            edit=null
            if(target.isEmpty())actions.add(draft.operationId,draft.editRevision,input)
            else actions.replace(draft.operationId,draft.editRevision,target,input)
        })
    }
    if(rename && session.photoCanEditProposal) {
        var name by remember(draft.operationId,draft.editRevision){mutableStateOf(draft.title)}
        AlertDialog(onDismissRequest={rename=false},title={Text("Nazwa posiłku")},
            text={OutlinedTextField(value=name,onValueChange={name=it},label={Text("Nazwa, do 200 znaków")},modifier=Modifier.testTag("photo-meal-draft-title"))},
            confirmButton={TextButton(onClick={rename=false;actions.rename(draft.operationId,draft.editRevision,name)},
                enabled=editable && name.isNotBlank() && name.codePointCount(0,name.length)<=200,modifier=Modifier.testTag("photo-meal-draft-title-save")){Text("Zapisz nazwę")}},
            dismissButton={TextButton(onClick={rename=false}){Text("Wróć")}})
    }
    if(discard && session.photoCanEditProposal) AlertDialog(onDismissRequest={discard=false},title={Text("Odrzucić poprawki?")},
        text={Text("Usuniemy tylko ten szkic poprawek. Oryginalne rozpoznanie, zdjęcie i dziennik pozostaną zachowane.")},
        confirmButton={TextButton(onClick={discard=false;actions.discard(draft.operationId,draft.editRevision)},enabled=editable,
            modifier=Modifier.testTag("photo-meal-draft-discard-confirm")){Text("Odrzuć poprawki")}},
        dismissButton={TextButton(onClick={discard=false},modifier=Modifier.testTag("photo-meal-draft-discard-dismiss")){Text("Wróć")}})
}

@Composable private fun PhotoDraftItemDialog(initial:PhotoDraftInput,adding:Boolean,enabled:Boolean,onDismiss:()->Unit,onSave:(PhotoDraftInput)->Unit) {
    var name by remember(initial){mutableStateOf(initial.name)}
    var amount by remember(initial){mutableStateOf(initial.amount)}
    var unit by remember(initial){mutableStateOf(initial.unit)}
    var energy by remember(initial){mutableStateOf(initial.energy)}
    var protein by remember(initial){mutableStateOf(initial.protein)}
    var fat by remember(initial){mutableStateOf(initial.fat)}
    var carbs by remember(initial){mutableStateOf(initial.carbs)}
    var error by remember(initial){mutableStateOf(false)}
    AlertDialog(onDismissRequest=onDismiss,title={Text(if(adding) "Dodaj składnik" else "Popraw składnik")},
        text={Column(Modifier.heightIn(max=400.dp).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(value=name,onValueChange={name=it},label={Text("Nazwa składnika")},modifier=Modifier.testTag("photo-draft-input-name"))
            DraftNumberField(amount,{amount=it},"Ilość ($unit)","amount")
            Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {listOf("g","ml").forEach {choice->
                FilterChip(selected=unit==choice,onClick={unit=choice},label={Text(choice)},modifier=Modifier.testTag("photo-draft-unit-$choice"))
            }}
            Text("Wartości na 100 $unit. Zmiana jednostki nie przelicza gęstości — sprawdź wszystkie wartości.")
            DraftNumberField(energy,{energy=it},"Energia (kcal)","energy")
            DraftNumberField(protein,{protein=it},"Białko (g)","protein")
            DraftNumberField(fat,{fat=it},"Tłuszcz (g)","fat")
            DraftNumberField(carbs,{carbs=it},"Węglowodany (g)","carbs")
            Text("Puste pole wartości odżywczej oznacza brak danych; zero wpisz jako 0.")
            if(error)Text("Podaj nazwę do 200 znaków, ilość od ponad 0 do 10 000 oraz nieujemne wartości z najwyżej 6 miejscami po przecinku.",
                color=MaterialTheme.colorScheme.error,modifier=Modifier.testTag("photo-draft-input-error"))
        }},
        confirmButton={TextButton(onClick={
            val input=PhotoDraftInput(name,amount,unit,energy,protein,fat,carbs)
            val valid=runCatching {PhotoMealDraft.validateInput(input);require(name.trim().codePointCount(0,name.trim().length)<=200)}.isSuccess
            if(valid)onSave(input)else error=true
        },enabled=enabled,modifier=Modifier.testTag("photo-draft-input-save")){Text("Zapisz poprawki")}},
        dismissButton={TextButton(onClick=onDismiss,modifier=Modifier.testTag("photo-draft-input-dismiss")){Text("Wróć")}})
}
@Composable private fun DraftNumberField(value:String,changed:(String)->Unit,label:String,tag:String) {
    OutlinedTextField(value=value,onValueChange=changed,label={Text(label)},singleLine=true,
        keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth().testTag("photo-draft-input-$tag"))
}
private fun draftNutrient(value:PhotoNutrientPreview,unit:String)="${value.display} $unit"+if(value.missingCount>0)" (niepełne)" else ""
