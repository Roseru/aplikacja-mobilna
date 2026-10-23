package pl.roseru.kalorie.session

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import pl.roseru.kalorie.core.sync.MealWire
import pl.roseru.kalorie.core.FieldAggregate
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import pl.roseru.kalorie.core.catalog.StrictJson
import pl.roseru.kalorie.core.sync.ConflictServerState
import pl.roseru.kalorie.data.*

data class ConflictListEntry(val key: String, val label: String)
data class ConflictVersionView(val title: String, val lines: List<String>, val deleted: Boolean = false)
data class ConflictPreviewView(val key: String, val local: ConflictVersionView, val server: ConflictVersionView,
    val canChoose: Boolean, val restoresAsCopy: Boolean, val needsRefresh: Boolean)
data class ConflictListView(val entries: List<ConflictListEntry> = emptyList(), val hasMore: Boolean = false,
    val loaded: Boolean = false, val preview: ConflictPreviewView? = null, val message: String? = null, val page: Int = 0)

/** Only user-facing values leave the private ticket map; never an epoch, receipt or checkpoint. */
internal fun conflictPreview(key: String, ticket: ConflictTicket): ConflictPreviewView {
    fun version(payload: String?, deleted: Boolean, unavailable: Boolean = false): ConflictVersionView {
        if (unavailable) return ConflictVersionView("Potrzebna świeża kopia", listOf("Pobierz aktualne dane serwera i otwórz porównanie ponownie."))
        if (deleted) return ConflictVersionView("Wpis usunięty", listOf("Ta wersja oznacza usunięcie wpisu."), true)
        val value = StrictJson.read(checkNotNull(payload).toByteArray(Charsets.UTF_8))
        val date = value.getString("local_date")
        val time = Instant.parse(value.getString("occurred_at")).atZone(ZoneId.of(value.getString("time_zone")))
            .format(DateTimeFormatter.ofPattern("HH:mm"))
        if (ticket.evidence.entityType == "weight") return ConflictVersionView("Pomiar wagi", listOf("$date · $time", "${value.getString("weight_kg")} kg"))
        val items = value.getJSONArray("items")
        fun number(field: FieldAggregate) = if (field.complete) field.knownSum.stripTrailingZeros().toPlainString() else "brak danych"
        val lines = mutableListOf("$date · $time")
        for (i in 0 until items.length()) {
            val item = items.getJSONObject(i); val amount = item.getJSONObject("quantity")
            lines += "${item.getString("name")} · ${amount.getString("amount")} ${amount.getString("unit")}"
            val fields = MealWire.consumed(StrictJson.canonical(item)).asExact().fields()
            lines += "${number(fields[0])} kcal · B ${number(fields[1])} g · T ${number(fields[2])} g · W ${number(fields[3])} g"
        }
        val title = value.optString("title").takeUnless { it.isBlank() || it == "null" } ?: "Posiłek"
        return ConflictVersionView(title, lines)
    }
    return ConflictPreviewView(key, version(ticket.localPayload, ticket.localDeleted),
        version(ticket.serverPayload, ticket.serverState == ConflictServerState.DELETED, ticket.serverState == ConflictServerState.UNAVAILABLE),
        ticket.canChoose, ticket.restoresAsCopy, ticket.serverState == ConflictServerState.UNAVAILABLE)
}

@Composable internal fun SyncConflictPanel(view: SessionView, actions: SessionActions) {
    val lease = view.binding?.takeIf { it.owner.kind == "account" }?.lease ?: return
    val state = view.conflicts
    val busy = view.conflictBusy || view.busy || view.pendingLogin || view.bootstrapBusy || view.snapshotBusy || view.mealPushBusy
    var confirmation by remember(state.preview?.key) { mutableStateOf<ConflictChoice?>(null) }
    Card(Modifier.fillMaxWidth().testTag("sync-conflicts-panel")) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Zmiany do uzgodnienia", style = MaterialTheme.typography.titleMedium)
            Text("Porównaj zapis na urządzeniu z wersją serwera. Przed wyborem zachowujemy obie wersje.")
            state.message?.let { Text(it, Modifier.testTag("sync-conflicts-message")) }
            if (view.conflictBusy) LinearProgressIndicator(Modifier.fillMaxWidth())
            OutlinedButton(onClick = { actions.loadConflicts(lease) }, enabled = !busy,
                modifier = Modifier.fillMaxWidth().testTag("sync-conflicts-load")) { Text("Pokaż wpisy do uzgodnienia") }
            if (state.loaded && state.entries.isEmpty()) Text("Brak wpisów wymagających decyzji.")
            state.entries.forEachIndexed { index, row ->
                OutlinedButton(onClick = { actions.openConflict(lease, row.key) }, enabled = !busy,
                    modifier = Modifier.fillMaxWidth().testTag("sync-conflict-open-$index")) { Text(row.label) }
            }
            if (state.page > 0) OutlinedButton(onClick = { actions.previousConflicts(lease) }, enabled = !busy,
                modifier = Modifier.fillMaxWidth().testTag("sync-conflicts-previous")) { Text("Poprzednie wpisy") }
            if (state.hasMore) OutlinedButton(onClick = { actions.nextConflicts(lease) }, enabled = !busy,
                modifier = Modifier.fillMaxWidth().testTag("sync-conflicts-next")) { Text("Kolejne wpisy") }
        }
    }
    state.preview?.let { preview ->
        AlertDialog(onDismissRequest = { if (!busy) actions.closeConflict(lease) },
            title = { Text("Porównaj wersje") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    ConflictVersionCard("Na urządzeniu", preview.local, "conflict-local")
                    ConflictVersionCard("Na serwerze", preview.server, "conflict-server")
                    if (preview.restoresAsCopy) Text("Wersja lokalna zostanie odtworzona jako nowy wpis. Usunięty wpis serwera pozostanie usunięty.")
                    if (!preview.canChoose && !preview.needsRefresh) Text("Ten wpis wymaga poprawy danych lub połączenia z serwerem. Zapisane wersje pozostają zachowane.")
                    if (preview.needsRefresh) OutlinedButton(onClick = { actions.closeConflict(lease); actions.downloadSnapshot() },
                        enabled = !busy && view.apiConfigured && view.hasSession,
                        modifier = Modifier.testTag("conflict-download-fresh")) { Text("Pobierz świeżą kopię") }
                    Button(onClick = { confirmation = ConflictChoice.LOCAL }, enabled = !busy && preview.canChoose,
                        modifier = Modifier.fillMaxWidth().testTag("conflict-keep-local")) {
                        Text(if (preview.restoresAsCopy) "Odtwórz lokalną wersję" else "Zachowaj wersję lokalną")
                    }
                    OutlinedButton(onClick = { confirmation = ConflictChoice.SERVER }, enabled = !busy && preview.canChoose,
                        modifier = Modifier.fillMaxWidth().testTag("conflict-keep-server")) { Text("Przyjmij wersję serwera") }
                }
            }, confirmButton = { TextButton(onClick = { actions.closeConflict(lease) }, enabled = !busy) { Text("Zamknij") } })
        confirmation?.let { choice ->
            AlertDialog(onDismissRequest = { confirmation = null }, title = { Text("Potwierdź wybór wersji") },
                text = { Text(if (choice == ConflictChoice.LOCAL) "Zapisz lokalny wynik i przygotuj go do wysłania przy najbliższej synchronizacji?"
                    else "Zastąp bieżący lokalny wpis wersją serwera? Obie porównane wersje pozostaną w historii decyzji.") },
                confirmButton = { TextButton(onClick = { confirmation = null; actions.resolveConflict(lease, preview.key, choice) },
                    enabled = !busy, modifier = Modifier.testTag("conflict-confirm-choice")) { Text("Zapisz wybór") } },
                dismissButton = { TextButton(onClick = { confirmation = null }) { Text("Wróć do porównania") } })
        }
    }
}

@Composable private fun ConflictVersionCard(label: String, version: ConflictVersionView, tag: String) {
    OutlinedCard(Modifier.fillMaxWidth().testTag(tag)) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(label, style = MaterialTheme.typography.labelLarge)
            Text(version.title, style = MaterialTheme.typography.titleSmall)
            version.lines.forEach { Text(it) }
        }
    }
}
