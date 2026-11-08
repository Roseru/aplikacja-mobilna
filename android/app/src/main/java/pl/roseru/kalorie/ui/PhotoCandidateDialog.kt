package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import pl.roseru.kalorie.community.CandidatePreview
import pl.roseru.kalorie.community.CommunityCandidate
import pl.roseru.kalorie.community.PublicProductRef
import pl.roseru.kalorie.session.PhotoDraftItemPreview

@Composable
internal fun PhotoCandidateDialog(
    item: PhotoDraftItemPreview,
    lookup: (suspend (CommunityCandidate) -> CandidatePreview)?,
    editable: Boolean,
    connected: Boolean,
    onDismiss: () -> Unit,
    onChoose: (PublicProductRef) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val previews = remember { mutableStateMapOf<PublicProductRef, CandidatePreview>() }
    val failed = remember { mutableStateMapOf<PublicProductRef, Boolean>() }
    var loading by remember { mutableStateOf<PublicProductRef?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Porównaj produkty") },
        text = {
            Column(Modifier.heightIn(max = 400.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Rozpoznany składnik · ${item.input.name}")
                Text("Powiązanie zachowuje ilość i wartości, które wpiszesz w tym posiłku.")
                if (lookup == null || !connected) Text("Połącz konto, aby pobrać szczegóły katalogowe.")
                if (item.candidatesTruncated) Text("Pokazano część możliwych dopasowań.")
                item.candidates.forEachIndexed { index, candidate ->
                    val ref = candidate.product
                    val preview = previews[ref]
                    HorizontalDivider()
                    Text(preview?.name ?: "Dopasowanie ${index + 1}", style = MaterialTheme.typography.titleSmall)
                    Text(if (candidate.provenance == "official") "Katalog oficjalny" else "Katalog społeczności",
                        style = MaterialTheme.typography.bodySmall)
                    if (preview == null) {
                        if (failed[ref] == true) Text("Szczegóły produktu są teraz niedostępne.")
                        TextButton(
                            onClick = {
                                val read = lookup ?: return@TextButton
                                if (loading != null) return@TextButton
                                loading = ref
                                failed.remove(ref)
                                scope.launch {
                                    try {
                                        val result = read(candidate)
                                        check(result.ref == ref)
                                        previews[ref] = result
                                    } catch (error: CancellationException) {
                                        throw error
                                    } catch (_: Exception) {
                                        failed[ref] = true
                                    } finally {
                                        loading = null
                                    }
                                }
                            },
                            enabled = editable && connected && lookup != null && loading == null,
                            modifier = Modifier.testTag("photo-candidate-detail-$index"),
                        ) { Text(if (loading == ref) "Pobieram szczegóły…" else "Pobierz szczegóły") }
                    } else {
                        val identity = listOfNotNull(preview.brand, preview.variant)
                        if (identity.isNotEmpty()) Text(identity.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                        Text(preview.energy?.let { "$it kcal na 100 ${preview.unit}" } ?: "Brak danych o energii",
                            style = MaterialTheme.typography.bodySmall)
                        TextButton(
                            onClick = { onChoose(ref) },
                            enabled = editable && loading == null && item.input.product != ref,
                            modifier = Modifier.testTag("photo-candidate-select-$index"),
                        ) { Text(if (item.input.product == ref) "Wybrany produkt" else "Wybierz ten produkt") }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Wróć") } },
    )
}
