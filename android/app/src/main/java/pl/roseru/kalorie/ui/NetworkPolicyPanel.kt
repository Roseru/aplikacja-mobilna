package pl.roseru.kalorie.ui

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.foundation.selection.toggleable
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.roseru.kalorie.core.network.*

@Composable fun NetworkPolicyPanel(model:NetworkPolicyViewModel) {
    val state by model.state.collectAsStateWithLifecycle()
    Column(Modifier.fillMaxWidth().testTag("network-policy-panel"),verticalArrangement=Arrangement.spacedBy(10.dp)) {
        SectionTitle("Tryb poligonowy")
        Text("Blokuje połączenia tej aplikacji. Dziennik oraz zapisana baza produktów i racji działają dalej bez internetu i logowania.")
        if(state.access==NetworkAccessState.Unavailable && !state.saving) {
            Text("Do potwierdzenia ustawień sieć aplikacji jest wstrzymana.")
            OutlinedButton(onClick={model.setBlocked(true)},modifier=Modifier.fillMaxWidth().testTag("network-policy-block")){Text("Włącz tryb poligonowy")}
            TextButton(onClick={model.setBlocked(false)},modifier=Modifier.fillMaxWidth().testTag("network-policy-allow")){Text("Zezwól aplikacji na internet")}
        } else {
            Row(Modifier.fillMaxWidth().toggleable(state.checked,enabled=!state.saving,role=Role.Switch,onValueChange=model::setBlocked)
                .testTag("field-mode-switch"),horizontalArrangement=Arrangement.SpaceBetween) {
                Text(if(state.checked)"Bez połączeń z serwerem" else "Połączenia z serwerem dozwolone",Modifier.weight(1f).padding(end=12.dp))
                Switch(checked=state.checked,onCheckedChange=null,enabled=!state.saving)
            }
        }
        if(state.saving)Text("Zapisuję ustawienie…")
        if(state.saveFailed)Text("Nie udało się zapisać ustawienia. Sieć aplikacji pozostaje wstrzymana. Spróbuj ponownie.",color=MaterialTheme.colorScheme.error)
    }
}
