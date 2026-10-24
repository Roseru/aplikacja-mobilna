package pl.roseru.kalorie.sync

import pl.roseru.kalorie.data.SyncWorkState
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

/** A queued job is distinct from completed server confirmation. No private context in UI text. */
fun SyncWorkState.userStatus():String=when(status) {
    "idle"->"Synchronizacja zakończona. Potwierdzone: $acknowledged. Odmowy: $refused."
    "ready"->"Synchronizacja oczekuje na wykonanie."
    "running"->when(phase) {"push"->"Wysyłam kolejkę konta…";"pull_after"->"Sprawdzam pełną kopię po wysłaniu…";else->"Pobieram pełną kopię przed wysłaniem…"}
    "deferred"->"Ponowienie nie wcześniej niż "+DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT).withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(retryAtMillis))+". Kolejka pozostaje zapisana."
    "login"->"Synchronizacja czeka na ponowne logowanie. Dziennik działa offline."
    "reconciliation"->"Synchronizacja czeka na świadome uzgodnienie danych konta."
    "not_configured"->"Synchronizacja serwera nie jest skonfigurowana. Kolejka pozostaje zapisana."
    "storage"->"Brak miejsca na bezpieczną kopię. Dotychczasowa kopia i dane pozostają zapisane."
    else->"Synchronizacja wymaga ponownego sprawdzenia stanu. Dane pozostają zapisane."
}
