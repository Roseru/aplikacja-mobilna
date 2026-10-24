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
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.DiaryViewModel
import pl.roseru.kalorie.community.*
import pl.roseru.kalorie.core.*
import pl.roseru.kalorie.core.network.NetworkAccessState
import pl.roseru.kalorie.data.*
import pl.roseru.kalorie.session.SessionView
import java.math.BigDecimal
import java.time.Instant
import java.time.ZoneId

@OptIn(ExperimentalMaterial3Api::class)
@Composable internal fun CommunityScreen(model:CommunityViewModel,diary:DiaryViewModel,session:SessionView,
    network:NetworkAccessState?,onBack:()->Unit,onAccount:()->Unit,onCustom:()->Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    val diaryBusy by diary.busy.collectAsStateWithLifecycle()
    val online=state.configured && session.hasSession && !session.requiresRecovery && network is NetworkAccessState.Allowed
    val enabled=online && !state.busy
    val detail=state.selected
    val publication=state.publication
    LaunchedEffect(model,session.serverLinked,session.requiresRecovery){model.reload()}
    BackHandler(enabled=!state.busy && (detail!=null || publication!=null)){model.close()}
    Scaffold(topBar={TopAppBar(title={Text(if(detail!=null)"Produkt społeczności" else if(publication!=null)"Publikuj produkt" else "Katalog społeczności")},
        navigationIcon={IconButton(onClick={if(detail!=null || publication!=null)model.close() else onBack()},enabled=!state.busy){
            Icon(Icons.AutoMirrored.Outlined.ArrowBack,"Wróć")}})}) {padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding).testTag("community-content"),
            contentPadding=PaddingValues(20.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
            item("status") {
                if(state.busy)LinearProgressIndicator(Modifier.fillMaxWidth())
                if(!online)Text(when {
                    state.scope==null->"Zaloguj się i połącz konto, aby korzystać z katalogu społeczności. Podstawowa baza działa bez konta."
                    !state.configured->"Ten wariant aplikacji nie ma adresu API. Zapisany fragment pozostaje dostępny."
                    session.requiresRecovery->"Najpierw uzgodnij stan konta. Zapisane produkty możesz nadal dodawać do dziennika."
                    !session.hasSession->"Sesja wygasła. Zapisany fragment działa offline; nowe działania wymagają logowania."
                    else->"Sieć jest zablokowana. Zapisany fragment katalogu jest dostępny offline."
                },style=MaterialTheme.typography.bodySmall)
                state.message?.let {Text(it,color=MaterialTheme.colorScheme.primary,modifier=Modifier.testTag("community-message"))}
                if(state.retryAt>System.currentTimeMillis())Text("Przerwa od serwera do ${localTime(state.retryAt)}",style=MaterialTheme.typography.bodySmall)
            }
            if(detail!=null) {
                item("detail") {CommunityDetail(detail,state.feedback,enabled,diaryBusy,state.scope,
                    onRefresh=model::refreshDetail,onVote=model::vote,onReport=model::report,
                    onAdd={amount,unit,type->state.scope?.let {diary.addCommunity(it,detail,amount,unit,type)}})}
            } else if(publication!=null) {
                item("publication") {key(publication.id,publication.revision){PublicationForm(publication,state,enabled,
                    onMatches=model::matches,onPreview=model::preview,onPublish=model::publish)}}
            } else {
                item("search") {
                    OutlinedTextField(state.query,onValueChange=model::query,label={Text("Nazwa produktu lub potrawy")},
                        leadingIcon={Icon(Icons.Outlined.Search,null)},singleLine=true,enabled=!state.busy,
                        modifier=Modifier.fillMaxWidth().testTag("community-query"))
                    Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        Button(onClick={model.search()},enabled=enabled,modifier=Modifier.testTag("community-search")){Text("Szukaj online")}
                        OutlinedButton(onClick=model::reload,enabled=!state.busy){Text("Zapisane offline")}
                    }
                    Text(if(state.remote)"Wyniki z serwera · zapisany podgląd pozostaje na telefonie" else "Zapisany fragment katalogu · stan może być nieaktualny",
                        style=MaterialTheme.typography.bodySmall)
                }
                if(state.scope==null)item("login"){OutlinedButton(onClick=onAccount){Text("Otwórz konto")}}
                if(state.loaded && state.products.isEmpty())item("empty"){Text("Brak produktów w tym widoku. Wyszukaj online lub zmień zapytanie.")}
                items(state.products,key={"community:${it.ref.id}@${it.ref.revision}"}) {product ->
                    Surface(shape=RoundedCornerShape(16.dp),color=MaterialTheme.colorScheme.surface,
                        modifier=Modifier.fillMaxWidth().clickable(enabled=!state.busy){model.select(product)}) {
                        Row(Modifier.padding(16.dp),horizontalArrangement=Arrangement.spacedBy(12.dp),verticalAlignment=Alignment.CenterVertically) {
                            Icon(Icons.Outlined.Restaurant,null,tint=MaterialTheme.colorScheme.primary)
                            Column(Modifier.weight(1f)) {
                                Text(product.name,fontWeight=FontWeight.Medium)
                                Text("${product.nutrition.energy?.let(ContractDecimal::canonical)?:"—"} kcal / 100 ${product.basisUnit}",style=MaterialTheme.typography.bodySmall)
                                Text("${if(product.verified)"Zweryfikowany" else "Wpis użytkownika"} · +${product.positive} / −${product.negative}",style=MaterialTheme.typography.labelSmall)
                            }
                            Icon(Icons.Outlined.ChevronRight,"Pokaż produkt")
                        }
                    }
                }
                if(state.next!=null)item("next"){OutlinedButton(onClick={model.search(true)},enabled=enabled){Text("Następne wyniki")}}
                item("draft-title"){Text("Opublikuj własny produkt",style=MaterialTheme.typography.titleMedium)}
                item("draft-description"){Text("Publikacja jest dobrowolna. Najpierw zapisz i zsynchronizuj prywatny produkt. Sam zapis posiłku nie publikuje go innym.",style=MaterialTheme.typography.bodySmall)}
                items(state.drafts,key={"draft:${it.id}"}) {draft ->
                    OutlinedButton(onClick={model.openDraft(draft)},enabled=!state.busy,modifier=Modifier.fillMaxWidth()) {
                        Text("${draft.name} · wersja ${draft.revision}")
                    }
                }
                item("create"){TextButton(onClick=onCustom){Text("Dodaj prywatny produkt")}}
            }
            val pending=state.attempts.filter {it.state in CommunityStore.pendingStates}
            val history=state.attempts.filter {it.state !in CommunityStore.pendingStates}.take(5)
            if(pending.isNotEmpty() || history.isNotEmpty())item("operations-title") {
                Text("Publikacje i oceny",style=MaterialTheme.typography.titleMedium)
                Text("To osobne operacje online. Wpisy dziennika zapisują się lokalnie i mają własną synchronizację.",style=MaterialTheme.typography.bodySmall)
            }
            items(pending+history,key={"operation:${it.id}"}) {operation ->
                CommunityOperation(operation,enabled,operation.wireContext!=state.scope?.wireContext,
                    onRetry={model.retry(operation.id)},onDiscard={model.discardUnsent(operation.id)})
            }
        }
    }
}

@Composable private fun CommunityDetail(product:CommunityProduct,feedback:CommunityFeedback?,online:Boolean,diaryBusy:Boolean,
    scope:CommunityScope?,onRefresh:()->Unit,onVote:(Int?)->Unit,onReport:(String,String)->Unit,onAdd:(String,String,MealType)->Unit) {
    var amount by rememberSaveable(product.ref){mutableStateOf(product.portionAmount)}
    var unit by rememberSaveable(product.ref){mutableStateOf(product.portionUnit)}
    var type by rememberSaveable(product.ref){mutableStateOf(MealType.BREAKFAST.name)}
    var reporting by rememberSaveable(product.ref){mutableStateOf(false)}
    var reportReason by rememberSaveable(product.ref){mutableStateOf("Nieprawidłowe wartości odżywcze")}
    var description by rememberSaveable(product.ref){mutableStateOf("")}
    val exact=ContractDecimal.userQuantity(amount)
    val totals=exact?.let {runCatching {product.consumed(ContractDecimal.canonical(it),unit)}.getOrNull()}
    Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
        Text(product.name,style=MaterialTheme.typography.headlineSmall)
        Text("${if(product.verified)"Zweryfikowany" else "Niezweryfikowany wpis użytkownika"} · wersja ${product.ref.revision}",style=MaterialTheme.typography.labelMedium)
        if(product.canonicalRef!=product.ref)Text("Produkt połączono z innym wpisem. Ta porcja zachowa oryginalną wersję i wartości.",style=MaterialTheme.typography.bodySmall)
        Text("Źródło: ${product.sourceDescription}",style=MaterialTheme.typography.bodySmall)
        val nutrition=product.nutrition
        Text("Na 100 ${product.basisUnit}: ${nutrition.energy?.let(ContractDecimal::canonical)?:"brak"} kcal · B ${nutrition.protein?.let(ContractDecimal::canonical)?:"brak"} · T ${nutrition.fat?.let(ContractDecimal::canonical)?:"brak"} · W ${nutrition.carbs?.let(ContractDecimal::canonical)?:"brak"}")
        if(!product.complete)Text("Dane są niepełne. Brakujących wartości nie zastępujemy zerem.",style=MaterialTheme.typography.bodySmall)
        val identity=product.json().getJSONObject("identity")
        listOf("brand" to "Marka","variant" to "Wariant").forEach {(key,label)->
            val value=identity.getJSONObject(key)
            Text("$label: ${if(value.isNull("value"))if(value.getString("state")=="not_applicable")"nie dotyczy" else "nie podano" else value.getString("value")}",style=MaterialTheme.typography.bodySmall)
        }
        product.json().optJSONObject("density")?.let {Text("Gęstość: ${it.getString("amount")} g/ml · ${it.getString("source_description")}",style=MaterialTheme.typography.bodySmall)}
        OutlinedButton(onClick=onRefresh,enabled=online){Text("Odśwież szczegóły i oceny")}
        HorizontalDivider()
        OutlinedTextField(amount,onValueChange={amount=it},label={Text("Zjedzona ilość")},singleLine=true,
            keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),isError=totals==null,
            modifier=Modifier.fillMaxWidth().testTag("community-amount"))
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {listOf("g","ml").forEach {option ->
            FilterChip(selected=unit==option,onClick={unit=option},enabled=option==product.basisUnit || product.density!=null,label={Text(option)})
        }}
        Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(8.dp)) {MealType.entries.forEach {option ->
            FilterChip(selected=type==option.name,onClick={type=option.name},label={Text(option.label)})
        }}
        totals?.let {Text("Porcja: ${if(it.energy.complete)it.energy.display else "brak pełnych danych"} kcal · B ${if(it.protein.complete)it.protein.display else "—"} · T ${if(it.fat.complete)it.fat.display else "—"} · W ${if(it.carbs.complete)it.carbs.display else "—"}")}
        Button(onClick={exact?.let {onAdd(ContractDecimal.canonical(it),unit,MealType.valueOf(type))}},
            enabled=totals!=null && scope!=null && !diaryBusy,modifier=Modifier.fillMaxWidth().testTag("community-add")){Text("Dodaj do dziennika")}
        Text("Zapis na telefonie działa bez internetu. Posłuży się tymi wartościami także po aktualizacji produktu.",style=MaterialTheme.typography.bodySmall)
        HorizontalDivider()
        Text("Ocena poprawności wpisu",style=MaterialTheme.typography.titleMedium)
        Text("+${feedback?.positive?:product.positive} / −${feedback?.negative?:product.negative} · ostatni pobrany stan")
        if(product.isMine || feedback?.isMine==true)Text("To Twój produkt. Nie możesz go oceniać.",style=MaterialTheme.typography.bodySmall)
        val canVote=online && feedback!=null && !product.isMine && !feedback.isMine
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            FilterChip(selected=feedback?.mine==1,onClick={onVote(1)},enabled=canVote,label={Text("Poprawny")},leadingIcon={Icon(Icons.Outlined.ThumbUp,null)})
            FilterChip(selected=feedback?.mine== -1,onClick={onVote(-1)},enabled=canVote,label={Text("Nie polecam")},leadingIcon={Icon(Icons.Outlined.ThumbDown,null)})
        }
        if(feedback?.mine!=null)TextButton(onClick={onVote(null)},enabled=canVote){Text("Wycofaj moją ocenę")}
        TextButton(onClick={reporting=!reporting}){Text(if(reporting)"Zamknij zgłoszenie" else "Zgłoś problem")}
        if(reporting) {
            OutlinedTextField(reportReason,onValueChange={reportReason=it},label={Text("Powód")},modifier=Modifier.fillMaxWidth())
            OutlinedTextField(description,onValueChange={description=it},label={Text("Opisz problem")},modifier=Modifier.fillMaxWidth(),minLines=2)
            Button(onClick={onReport(reportReason.trim(),description.trim())},enabled=online && runCatching {CommunityProtocol.text(reportReason.trim());CommunityProtocol.text(description.trim())}.isSuccess){Text("Wyślij zgłoszenie")}
        }
    }
}

@Composable private fun PublicationForm(draft:PublicationDraft,state:CommunityViewState,enabled:Boolean,onMatches:(String)->Unit,
    onPreview:(CommunityCandidate)->Unit,onPublish:(PublicProductRef?,Boolean)->Unit) {
    val payload=remember(draft){CommunityProtocol.read(draft.payload.toByteArray())}
    var source by rememberSaveable(draft.id,draft.revision){mutableStateOf("estimate")}
    var description by rememberSaveable(draft.id,draft.revision){mutableStateOf(payload.optString("source_description",""))}
    var brand by rememberSaveable(draft.id,draft.revision){mutableStateOf(if(payload.isNull("brand"))"" else payload.getString("brand"))}
    var brandState by rememberSaveable(draft.id,draft.revision){mutableStateOf(if(brand.isBlank())"unknown" else "known")}
    var variant by rememberSaveable(draft.id,draft.revision){mutableStateOf(if(payload.isNull("variant"))"" else payload.getString("variant"))}
    var variantState by rememberSaveable(draft.id,draft.revision){mutableStateOf(if(variant.isBlank())"unknown" else "known")}
    var composition by rememberSaveable(draft.id,draft.revision){mutableStateOf("")}
    var aliases by rememberSaveable(draft.id,draft.revision){mutableStateOf("")}
    var portion by rememberSaveable(draft.id,draft.revision){mutableStateOf("")}
    var portionUnit by rememberSaveable(draft.id,draft.revision){mutableStateOf(payload.getString("basis_unit"))}
    var density by rememberSaveable(draft.id,draft.revision){mutableStateOf("")}
    var densitySource by rememberSaveable(draft.id,draft.revision){mutableStateOf("")}
    var consent by rememberSaveable(draft.id,draft.revision){mutableStateOf(false)}
    val body=runCatching {
        CommunityProtocol.publication(draft.id,draft.revision,source,description.trim(),brandState,brand.trim(),variantState,variant.trim(),
            composition.trim(),aliases.split(';').map {it.trim()}.filter {it.isNotEmpty()},
            portion.takeIf {it.isNotBlank()}?.let(::publicationDecimal),portionUnit,
            density.takeIf {it.isNotBlank()}?.let(::publicationDecimal),densitySource.trim())
    }.getOrNull()
    val currentMatches=state.matches.takeIf {body!=null && state.matchBody==body}
    val canPublish=enabled && consent && currentMatches!=null
    Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
        Text(draft.name,style=MaterialTheme.typography.headlineSmall)
        Text("Prywatny szkic · potwierdzona wersja ${draft.revision}",style=MaterialTheme.typography.labelMedium)
        val nutrition=payload.getJSONObject("nutrition_per_100")
        Text("Na 100 ${payload.getString("basis_unit")}: ${if(nutrition.isNull("energy_kcal"))"brak danych" else nutrition.getString("energy_kcal")} kcal · "+
            listOf("protein_g" to "B","fat_g" to "T","carbs_g" to "W").joinToString(" · "){(field,label)->"$label ${if(nutrition.isNull(field))"brak" else nutrition.getString(field)}"})
        Text("Publiczny wpis obejmie nazwę, wartości odżywcze i poniższy opis. Porcje tej samej potrawy pozostają jednym produktem; ilość wybiera się w dzienniku.",style=MaterialTheme.typography.bodySmall)
        Text("Rodzaj źródła")
        Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(6.dp)) {
            listOf("label" to "Etykieta","recipe" to "Przepis","estimate" to "Szacunek","ai" to "AI").forEach {(value,label)->
                FilterChip(selected=source==value,onClick={source=value},label={Text(label)})
            }
        }
        OutlinedTextField(description,onValueChange={description=it},label={Text("Źródło i sposób ustalenia wartości")},modifier=Modifier.fillMaxWidth(),minLines=2)
        IdentityEditor("Marka",brandState,brand,{brandState=it},{brand=it})
        IdentityEditor("Wariant",variantState,variant,{variantState=it},{variant=it})
        OutlinedTextField(composition,onValueChange={composition=it},label={Text("Skład lub przepis (puste = nieznany)")},modifier=Modifier.fillMaxWidth(),minLines=2)
        OutlinedTextField(aliases,onValueChange={aliases=it},label={Text("Inne nazwy, oddzielone średnikiem")},modifier=Modifier.fillMaxWidth())
        OutlinedTextField(portion,onValueChange={portion=it},label={Text("Typowa porcja (opcjonalnie)")},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){listOf("g","ml").forEach {value->FilterChip(selected=portionUnit==value,onClick={portionUnit=value},label={Text(value)})}}
        OutlinedTextField(density,onValueChange={density=it},label={Text("Gęstość g/ml (opcjonalnie)")},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),modifier=Modifier.fillMaxWidth())
        if(density.isNotBlank())OutlinedTextField(densitySource,onValueChange={densitySource=it},label={Text("Źródło gęstości")},modifier=Modifier.fillMaxWidth())
        Row(verticalAlignment=Alignment.CenterVertically) {
            Checkbox(checked=consent,onCheckedChange={consent=it})
            Text("Chcę udostępnić te dane w katalogu innym użytkownikom.",style=MaterialTheme.typography.bodySmall)
        }
        Button(onClick={body?.let(onMatches)},enabled=enabled && body!=null,modifier=Modifier.testTag("community-match")){Text("Sprawdź podobne produkty")}
        currentMatches?.let {matches ->
            Text(when(matches.decision){"existing_variant"->"Znaleziono ten sam wariant produktu.";"manual_candidates"->"Porównaj podobne wpisy przed publikacją.";else->"Nie znaleziono tego wariantu."},fontWeight=FontWeight.Medium)
            if(matches.missing.isNotEmpty())Text("Brak danych do pewnego porównania: ${matches.missing.joinToString {when(it){"brand"->"marka";"variant"->"wariant";"composition"->"skład";else->"kalorie"}}}.",style=MaterialTheme.typography.bodySmall)
            if(matches.truncated)Text("Pokazano część możliwych dopasowań.",style=MaterialTheme.typography.bodySmall)
            matches.candidates.forEach {candidate ->
                val preview=state.previews[candidate.product]
                ElevatedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
                        Text(preview?.name?:if(candidate.provenance=="official")"Produkt oficjalny" else "Produkt społeczności")
                        Text(candidate.reasons.joinToString(" · "),style=MaterialTheme.typography.bodySmall)
                        if(preview!=null)Text("${preview.energy?:"brak danych"} kcal / 100 ${preview.unit} · ${preview.source}",style=MaterialTheme.typography.bodySmall)
                        TextButton(onClick={onPreview(candidate)},enabled=enabled){Text("Pokaż dane produktu")}
                        OutlinedButton(onClick={onPublish(candidate.product,false)},enabled=canPublish && preview!=null){Text("Wybierz ten produkt")}
                    }
                }
            }
            if(matches.decision=="existing_variant")Button(onClick={onPublish(null,false)},enabled=canPublish){Text("Użyj istniejącego wariantu")}
            else Button(onClick={onPublish(null,true)},enabled=canPublish,modifier=Modifier.testTag("community-publish")){Text("Potwierdzam: opublikuj nowy wariant")}
        }
    }
}

@Composable private fun IdentityEditor(label:String,state:String,value:String,onState:(String)->Unit,onValue:(String)->Unit) {
    Column {
        Text(label)
        Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(6.dp)) {
            listOf("known" to "Podaj","unknown" to "Nie wiem","not_applicable" to "Nie dotyczy").forEach {(key,text)->
                FilterChip(selected=state==key,onClick={onState(key)},label={Text(text)})
            }
        }
        if(state=="known")OutlinedTextField(value,onValueChange=onValue,label={Text(label)},modifier=Modifier.fillMaxWidth())
    }
}

@Composable private fun CommunityOperation(row:CommunityAttemptEntity,online:Boolean,archived:Boolean,onRetry:()->Unit,onDiscard:()->Unit) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
            Text("${when(row.kind){"publish"->"Publikacja";"report"->"Zgłoszenie";"withdraw"->"Wycofanie oceny";else->"Ocena"}} · ${localTime(row.createdAt)}",fontWeight=FontWeight.Medium)
            Text(when(row.state){"prepared"->"Zapisano, jeszcze nie wysłano";"unknown"->"Wynik niepotwierdzony — zachowano żądanie";"succeeded"->"Potwierdzone przez serwer";"rejected"->"Serwer odmówił — odśwież dane przed nowym działaniem";else->"Wynik wymaga wyjaśnienia; nie twórz kopii żądania"},style=MaterialTheme.typography.bodySmall)
            if(archived)Text("Żądanie z poprzedniego kontekstu konta. Zachowano do wyjaśnienia; nie zostanie wysłane w nowym kontekście.",style=MaterialTheme.typography.bodySmall)
            if(!archived && row.state in setOf("prepared","unknown"))TextButton(onClick=onRetry,enabled=online && row.retryAt<=System.currentTimeMillis()){Text("Ponów zapisane żądanie")}
            if(!archived && !row.attempted && row.state=="prepared")TextButton(onClick=onDiscard){Text("Usuń niewysłane żądanie")}
        }
    }
}
private fun publicationDecimal(value:String):String=ContractDecimal.canonical(BigDecimal(value.trim().replace(',','.'))).also {
    require(ContractDecimal.read(it)>BigDecimal.ZERO)
}
private fun localTime(millis:Long)=Instant.ofEpochMilli(millis).atZone(ZoneId.systemDefault()).toLocalDateTime().withSecond(0).withNano(0).toString().replace('T',' ')
