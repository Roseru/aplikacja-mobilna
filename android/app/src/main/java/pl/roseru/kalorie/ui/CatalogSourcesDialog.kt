package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.catalogupdate.*
import pl.roseru.kalorie.core.catalog.CatalogManifest

@Composable internal fun CatalogSourcesDialog(state:CatalogSourcesState,onPage:(CatalogManifest,Int)->Unit,onClose:()->Unit) {
    if(state is CatalogSourcesState.Closed)return
    val manifest=when(state) {
        is CatalogSourcesState.Loading->state.manifest
        is CatalogSourcesState.Failed->state.manifest
        is CatalogSourcesState.Ready->state.value.manifest
        CatalogSourcesState.Closed->return
    }
    var selectedId by rememberSaveable(manifest.packageId,manifest.release){mutableStateOf<String?>(null)}
    val selected=(state as? CatalogSourcesState.Ready)?.value?.entries?.firstOrNull{it.id==selectedId}
    if(selected!=null) {
        CatalogSourceDetail(selected,onBack={selectedId=null})
        return
    }
    AlertDialog(onDismissRequest=onClose,title={Text("Źródła bazy v${manifest.release}")},
        modifier=Modifier.testTag("catalog-sources-dialog"),
        text={when(state) {
            is CatalogSourcesState.Loading->Row(horizontalArrangement=Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator(Modifier.size(22.dp),strokeWidth=2.dp);Text("Otwieram zapisane źródła…")
            }
            is CatalogSourcesState.Failed->Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
                Text("Nie udało się odczytać źródeł tej wersji. Baza nie została zmieniona.")
                TextButton(onClick={onPage(state.manifest,state.page)}){Text("Spróbuj ponownie")}
            }
            is CatalogSourcesState.Ready->{
                val page=state.value
                LazyColumn(Modifier.heightIn(max=460.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
                    items(page.entries,key={it.id}) {source->
                        OutlinedCard(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp),verticalArrangement=Arrangement.spacedBy(6.dp)) {
                                Text(source.document,maxLines=3,overflow=TextOverflow.Ellipsis,fontWeight=FontWeight.SemiBold)
                                Text(if(source.verified)"Zweryfikowane · ${source.checkedOn}" else "DEMO / niezweryfikowane · ${source.checkedOn}")
                                Text("Uwagi: ${source.notes.size} · braki danych: ${source.missing.size}",style=MaterialTheme.typography.bodySmall)
                                TextButton(onClick={selectedId=source.id},modifier=Modifier.testTag("catalog-source-detail-${source.id}")){Text("Szczegóły źródła")}
                            }
                        }
                    }
                    item {
                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                            TextButton(onClick={selectedId=null;onPage(manifest,page.page-1)},enabled=page.hasPrevious){Text("Poprzednie")}
                            TextButton(onClick={selectedId=null;onPage(manifest,page.page+1)},enabled=page.hasNext){Text("Następne")}
                        }
                        Text("${page.page*CatalogSourcePage.SIZE+1}–${page.page*CatalogSourcePage.SIZE+page.entries.size} z ${manifest.sources}",style=MaterialTheme.typography.bodySmall)
                    }
                }
            }
            CatalogSourcesState.Closed->Unit
        }},confirmButton={TextButton(onClick=onClose){Text("Zamknij źródła")}})
}

@Composable private fun CatalogSourceDetail(source:CatalogSource,onBack:()->Unit) {
    AlertDialog(onDismissRequest=onBack,title={Text("Szczegóły źródła")},modifier=Modifier.testTag("catalog-source-detail"),text={
        LazyColumn(Modifier.heightIn(max=460.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
            item{SelectionContainer{Text(source.document,fontWeight=FontWeight.SemiBold)}}
            item{Text(if(source.verified)"Źródło zweryfikowane" else "Dane demonstracyjne lub niezweryfikowane")}
            item{Text("Sprawdzono: ${source.checkedOn}")}
            source.manufacturer?.let{manufacturer->item{Text("Producent: $manufacturer")}}
            source.market?.let{market->item{Text("Rynek: $market")}}
            source.variant?.let{variant->item{Text("Wariant: $variant")}}
            item{Text(when(source.basis) {
                "per_100_g"->"Wartości na 100 g"
                "per_100_ml"->"Wartości na 100 ml"
                "label_serving"->"Wartości dla porcji z etykiety"
                "mixed_labels"->"Wartości z zestawu etykiet"
                else->"Przyjęta ilość wymaga weryfikacji"
            })}
            source.url?.let{url->item{SelectionContainer{Text(url)}}}
            if(source.missing.isNotEmpty()) {
                item{Text("Brakujące dane",fontWeight=FontWeight.SemiBold)}
                items(source.missing){Text(it)}
            }
            if(source.notes.isNotEmpty()) {
                item{Text("Uwagi do danych",fontWeight=FontWeight.SemiBold)}
                items(source.notes){Text(it)}
            }
        }
    },confirmButton={TextButton(onClick=onBack){Text("Wróć do listy źródeł")}})
}
