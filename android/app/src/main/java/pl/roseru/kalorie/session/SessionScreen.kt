package pl.roseru.kalorie.session

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp

data class SessionActions(val login: () -> Unit, val logout: () -> Unit, val refresh: () -> Unit, val cancel: () -> Unit)

@Composable fun SessionScreen(view: SessionView, actions: SessionActions, back: () -> Unit) {
    val account = view.binding?.owner?.kind == "account"
    var confirmLogout by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        TextButton(onClick = back) { Text("Wróć do profilu") }
        Text("Konto i logowanie", style = MaterialTheme.typography.headlineLarge)
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (account) "Konto · ${view.binding?.owner?.subject?.take(8)}" else "Gość poligonowy",
                    style = MaterialTheme.typography.titleLarge, modifier = Modifier.testTag("session-owner"))
                Text(if (account) "Dziennik tego konta zapisujesz również bez internetu." else "Zapisuj posiłki i wagę bez konta i internetu.")
                if (account) Text(if (view.hasSession) "Sesja dostępna" else "Sesja wymaga odnowienia", Modifier.testTag("session-status"))
            }
        }
        Text("Każde konto ma osobny dziennik. Logowanie nie przenosi wpisów gościa.")
        if (!view.configured) Text("Logowanie będzie dostępne po podłączeniu serwera aplikacji. Możesz dalej korzystać z dziennika offline.")
        view.message?.let { Text(it, modifier = Modifier.testTag("session-message")) }
        if (view.busy) { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("Łączę z dostawcą logowania…") }
        Button(onClick = actions.login, enabled = view.configured && !view.busy && !view.pendingLogin,
            modifier = Modifier.fillMaxWidth().testTag("session-login")) { Text(if (account) "Zaloguj się ponownie / zmień konto" else "Zaloguj się w przeglądarce") }
        if (view.pendingLogin || view.busy) OutlinedButton(onClick = actions.cancel, modifier = Modifier.fillMaxWidth()) { Text("Anuluj logowanie") }
        if (account) {
            OutlinedButton(onClick = actions.refresh, enabled = view.configured && !view.busy && !view.pendingLogin,
                modifier = Modifier.fillMaxWidth().testTag("session-refresh")) { Text("Odnów sesję") }
            OutlinedButton(onClick = { confirmLogout = true }, modifier = Modifier.fillMaxWidth().testTag("session-logout")) { Text("Wyloguj i otwórz gościa") }
        }
    }
    if (confirmLogout) AlertDialog(onDismissRequest = { confirmLogout = false }, title = { Text("Wylogować z aplikacji?") },
        text = { Text("Sesja na tym urządzeniu zostanie usunięta. Dzienniki konta i gościa pozostaną zapisane osobno. Sesja w przeglądarce pozostaje u dostawcy logowania.") },
        confirmButton = { TextButton(onClick = { confirmLogout = false; actions.logout() }, modifier = Modifier.testTag("confirm-session-logout")) { Text("Wyloguj") } },
        dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text("Anuluj") } })
}
