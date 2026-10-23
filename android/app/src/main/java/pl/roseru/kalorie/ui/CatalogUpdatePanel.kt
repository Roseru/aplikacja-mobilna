package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import pl.roseru.kalorie.catalogupdate.*
import pl.roseru.kalorie.core.catalog.CatalogManifest
import java.math.RoundingMode
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

@Composable fun CatalogUpdatePanel(model:CatalogUpdateViewModel) {
    val state by model.state.collectAsStateWithLifecycle()
    val sources by model.sources.collectAsStateWithLifecycle()
    CatalogUpdateContent(state,model::check,model::download,model::cancel,onSources={model.showSources(it)},onRetryLocal=model::retryLocalRead)
    CatalogSourcesDialog(sources,onPage=model::showSources,onClose=model::closeSources)
}

@Composable internal fun CatalogUpdateContent(state:CatalogUpdateState,onCheck:()->Unit,onDownload:()->Unit,onCancel:()->Unit,
    onSources:(CatalogManifest)->Unit={},onRetryLocal:()->Unit={}) {
    var now by remember(state.retryAt){mutableLongStateOf(System.currentTimeMillis())}
    LaunchedEffect(state.retryAt) {
        now=System.currentTimeMillis()
        while(state.retryAt>now){delay(1000);now=System.currentTimeMillis()}
    }
    val waiting=state.retryAt>now
    val canUse=state.configured && state.networkAllowed && !state.busy && !waiting
    Column(Modifier.fillMaxWidth().testTag("catalog-update-panel"),verticalArrangement=Arrangement.spacedBy(12.dp)) {
        SectionTitle("Baza produktów i racji")
        Text("Pobraną bazę możesz używać bez internetu i bez logowania. Jej aktualizacja nie zmienia Twoich posiłków.",
            color=MaterialTheme.colorScheme.onSurfaceVariant)
        state.installed.forEach { local->
            when(local) {
                is InstalledCatalog.Ready->CatalogReleaseCard(local.manifest,installed=true,onSources={onSources(local.manifest)})
                is InstalledCatalog.Unreadable->Text("Nie udało się odczytać opisu zapisanej bazy v${local.release}.",color=MaterialTheme.colorScheme.error)
            }
        }
        if(state.localReadFailed) {
            Text("Nie udało się odczytać wersji bazy.",color=MaterialTheme.colorScheme.error)
            TextButton(onClick=onRetryLocal){Text("Ponów odczyt zapisanej bazy")}
        }
        if(!state.configured)Text("Aktualizacje bazy nie są jeszcze dostępne w tej wersji aplikacji.")
        else if(!state.networkAllowed)Text("Blokada sieci jest włączona. Zapisana baza pozostaje dostępna w trybie poligonowym.",
            modifier=Modifier.testTag("catalog-network-blocked"))
        when(state.phase) {
            CatalogUpdatePhase.CHECKING->Text("Sprawdzam dostępną wersję…")
            CatalogUpdatePhase.DOWNLOADING->{
                val progress=if(state.expected>0)(state.received.toDouble()/state.expected).coerceIn(0.0,1.0).toFloat() else 0f
                LinearProgressIndicator(progress={progress},modifier=Modifier.fillMaxWidth().testTag("catalog-download-progress"))
                Text("Pobieram: ${catalogBytes(state.received)} z ${catalogBytes(state.expected)}")
            }
            CatalogUpdatePhase.VERIFYING->Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator(Modifier.size(22.dp),strokeWidth=2.dp);Text("Sprawdzam bazę przed zapisaniem…")
            }
            CatalogUpdatePhase.INSTALLED->Text("Baza jest gotowa do użycia offline.",modifier=Modifier.testTag("catalog-installed"))
            CatalogUpdatePhase.CURRENT->Text(if(state.serverOlder)"Masz nowszą zapisaną bazę. Pozostawiam ją bez zmian." else "Masz aktualną wersję bazy.")
            CatalogUpdatePhase.NOT_PUBLISHED->Text("Zweryfikowana baza nie jest teraz dostępna na serwerze. Możesz dalej używać zapisanej bazy.")
            CatalogUpdatePhase.CANCELLED->Text("Aktualizacja została zatrzymana. Zapisane bazy nadal są dostępne offline.")
            CatalogUpdatePhase.FAILED->Text("Nie udało się pobrać lub zweryfikować aktualizacji. Zapisana baza pozostaje bez zmian. Możesz spróbować ponownie.",
                color=MaterialTheme.colorScheme.error,modifier=Modifier.testTag("catalog-update-error"))
            else->Unit
        }
        if(waiting)Text("Serwer poprosił o przerwę. Możesz ponowić po ${catalogTime(state.retryAt)}.",modifier=Modifier.testTag("catalog-retry-after"))
        state.available?.let { release->
            CatalogReleaseCard(release,installed=false)
            Button(onClick=onDownload,enabled=canUse,modifier=Modifier.fillMaxWidth().testTag("catalog-download")) {
                Text("Pobierz v${release.release} · ${catalogBytes(release.compressedBytes.toLong())}")
            }
        }
        if(state.busy)OutlinedButton(onClick=onCancel,modifier=Modifier.fillMaxWidth().testTag("catalog-cancel")){Text("Anuluj aktualizację")}
        else OutlinedButton(onClick=onCheck,enabled=canUse,modifier=Modifier.fillMaxWidth().testTag("catalog-check")){Text("Sprawdź aktualizacje bazy")}
        state.checkedAt?.let{Text("Sprawdzono: ${catalogTime(it)}",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)}
    }
}

@Composable private fun CatalogReleaseCard(value:CatalogManifest,installed:Boolean,onSources:(()->Unit)?=null) {
    OutlinedCard(Modifier.fillMaxWidth().testTag(if(installed)"catalog-local-${value.kind}" else "catalog-available")) {
        Column(Modifier.padding(14.dp),verticalArrangement=Arrangement.spacedBy(4.dp)) {
            Text((if(installed)"Zapisana" else "Dostępna")+" baza · v${value.release}",fontWeight=FontWeight.SemiBold)
            Text(if(value.kind=="official")"Oficjalna · zweryfikowane źródła" else "DEMO · dane demonstracyjne",color=MaterialTheme.colorScheme.onSurfaceVariant)
            Text("Produkty: ${value.products} · racje: ${value.rations}")
            Text("Składniki racji: ${value.components} · źródła: ${value.sources}",style=MaterialTheme.typography.bodySmall)
            Text("Wydano: ${catalogTime(Instant.parse(value.publishedAt).toEpochMilli())}",style=MaterialTheme.typography.bodySmall)
            if(onSources!=null)TextButton(onClick=onSources,modifier=Modifier.testTag("catalog-sources-${value.kind}")){Text("Przejrzyj źródła")}
        }
    }
}
private fun catalogBytes(bytes:Long):String=if(bytes<1024*1024)"${(bytes+1023)/1024} KB"
    else bytes.toBigDecimal().divide(1_048_576.toBigDecimal(),1,RoundingMode.HALF_UP).toPlainString().replace('.',',')+" MB"
private fun catalogTime(millis:Long):String=DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
    .withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(millis))
