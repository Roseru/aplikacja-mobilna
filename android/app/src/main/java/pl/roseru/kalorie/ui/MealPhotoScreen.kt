package pl.roseru.kalorie.ui

import android.graphics.Bitmap
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CameraAlt
import androidx.compose.material.icons.outlined.PhotoLibrary
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.photo.MealPhotoViewModel
import java.time.LocalDate

@Composable fun MealPhotoScreen(model: MealPhotoViewModel, date: LocalDate, onBack: () -> Unit, onManual: () -> Unit) {
    val drafts by model.drafts.collectAsStateWithLifecycle()
    val busy by model.busy.collectAsStateWithLifecycle()
    val message by model.message.collectAsStateWithLifecycle()
    val selectionPending by model.selectionPending.collectAsStateWithLifecycle()
    var selected by rememberSaveable { mutableStateOf<String?>(null) }
    var removal by remember { mutableStateOf<String?>(null) }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia(), model::galleryResult)
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture(), model::cameraResult)
    val preview by produceState<Bitmap?>(null, selected, model) {
        value = null
        selected?.let { value = runCatching { model.preview(it) }.getOrNull() }
    }
    LazyColumn(Modifier.fillMaxSize().testTag("photo-content"), contentPadding=PaddingValues(16.dp), verticalArrangement=Arrangement.spacedBy(12.dp)) {
        item {
            TextButton(onClick=onBack, modifier=Modifier.testTag("photo-back")) { Text("Wróć do wyboru posiłku") }
            Text("Zdjęcie posiłku", style=MaterialTheme.typography.headlineLarge)
            Text("Zachowaj zdjęcie, nawet bez internetu.", color=MaterialTheme.colorScheme.onSurfaceVariant)
        }
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement=Arrangement.spacedBy(8.dp)) {
                    Text("Na Twoim telefonie", style=MaterialTheme.typography.titleMedium)
                    Text("Wybór lub wykonanie zdjęcia nie wysyła go do serwera. Analiza jedzenia wymaga osobnej zgody.", style=MaterialTheme.typography.bodyMedium)
                    Text("Zdjęcie przypiszemy do dnia $date. Sam obraz nie jest jeszcze wpisem posiłku.", style=MaterialTheme.typography.bodySmall)
                    OutlinedButton(onClick={model.beginGallery(date) { gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }},
                        enabled=!busy, modifier=Modifier.fillMaxWidth().testTag("photo-gallery")) {
                        Icon(Icons.Outlined.PhotoLibrary,null); Spacer(Modifier.width(8.dp)); Text("Wybierz z galerii")
                    }
                    OutlinedButton(onClick={model.beginCamera(date,camera::launch)}, enabled=!busy, modifier=Modifier.fillMaxWidth().testTag("photo-camera")) {
                        Icon(Icons.Outlined.CameraAlt,null); Spacer(Modifier.width(8.dp)); Text("Zrób zdjęcie")
                    }
                }
            }
        }
        item {
            if (busy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Wybór lub przygotowanie zdjęcia…") }
            if (selectionPending) TextButton(onClick=model::cancelSelection, modifier=Modifier.testTag("photo-cancel-selection")) { Text("Anuluj wybór zdjęcia") }
            message?.let { Text(it,Modifier.testTag("photo-message")) }
            TextButton(onClick=onManual, modifier=Modifier.testTag("photo-manual")) { Text("Dodaj posiłek ręcznie") }
        }
        item { Text("Zapisane zdjęcia · ${drafts.size}", style=MaterialTheme.typography.titleMedium, modifier=Modifier.testTag("photo-count")) }
        if (drafts.isEmpty()) item { Text("Nie ma jeszcze zapisanych zdjęć.", Modifier.testTag("photo-empty")) }
        items(drafts,key={it.id}) { row ->
            OutlinedCard(Modifier.fillMaxWidth().testTag("photo-draft-${row.id}")) {
                Column(Modifier.padding(12.dp), verticalArrangement=Arrangement.spacedBy(4.dp)) {
                    Text(row.localDate,style=MaterialTheme.typography.titleMedium)
                    Text("${if(row.source=="camera") "Aparat" else "Galeria"} · ${(row.byteCount/1024).coerceAtLeast(1)} KB · tylko lokalnie",style=MaterialTheme.typography.bodySmall)
                    Row {
                        TextButton(onClick={selected=if(selected==row.id) null else row.id}, modifier=Modifier.testTag("photo-preview-${row.id}")) { Text(if(selected==row.id) "Zwiń" else "Pokaż zdjęcie") }
                        TextButton(onClick={removal=row.id}, enabled=!busy) { Text("Usuń") }
                    }
                    if(selected==row.id) {
                        preview?.let { Image(it.asImageBitmap(),"Zapisane zdjęcie posiłku",Modifier.fillMaxWidth().heightIn(max=280.dp).testTag("photo-preview"), contentScale=ContentScale.Fit) }
                            ?: Text("Otwieranie zdjęcia…")
                    }
                }
            }
        }
    }
    removal?.let { id -> AlertDialog(onDismissRequest={removal=null}, title={Text("Usunąć lokalne zdjęcie?")},
        text={Text("Usuniemy obraz z aplikacji. Oryginał w galerii oraz zapisane posiłki pozostaną zachowane.")},
        confirmButton={TextButton(onClick={removal=null;if(selected==id) selected=null;model.delete(id)},enabled=!busy,modifier=Modifier.testTag("photo-confirm-delete")) { Text("Usuń") }},
        dismissButton={TextButton(onClick={removal=null}) { Text("Wróć") }}) }
}
