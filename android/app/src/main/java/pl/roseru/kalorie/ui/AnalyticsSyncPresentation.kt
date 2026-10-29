package pl.roseru.kalorie.ui

import pl.roseru.kalorie.core.network.NetworkAccessState
import pl.roseru.kalorie.data.AnalyticsSyncState
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

internal data class AnalyticsSyncNotice(val scope: String, val lines: List<String>)

/** Presentation only: an allowed network policy is neither connectivity nor a server receipt. */
internal fun analyticsSyncNotice(state: AnalyticsSyncState, network: NetworkAccessState?,
    zone: ZoneId = ZoneId.systemDefault()): AnalyticsSyncNotice {
    val local = "Lokalny raport · obejmuje dziennik na tym urządzeniu"
    fun time(value: String): String = try {
        DateTimeFormatter.ofPattern("d.MM.yyyy, HH:mm z", Locale.forLanguageTag("pl-PL"))
            .withZone(zone).format(Instant.parse(value))
    } catch (_: Exception) { "czas niedostępny" }
    val lines = when (state) {
        AnalyticsSyncState.Guest -> listOf("Gość · dane tylko na tym urządzeniu. Bez kopii konta i potwierdzenia serwera.")
        AnalyticsSyncState.Loading -> listOf("Odczytuję zapisany stan synchronizacji…")
        AnalyticsSyncState.Stale -> listOf("Wybrany profil się zmienił. Otwórz ponownie Postępy dla aktywnego profilu.")
        AnalyticsSyncState.Unavailable -> listOf("Aktualność synchronizacji jest niedostępna. Raport pokazuje dane lokalne.")
        is AnalyticsSyncState.Account -> buildList {
            add("Zakres: lokalne posiłki, cele, kompletność dni i waga tego konta.")
            if (state.lastAppliedAt == null) add("Nie ukończono jeszcze pobrania i zastosowania kopii w bieżącym połączeniu konta. Historia konta może być niepełna.")
            else {
                add("Ostatnie ukończone pobranie i zastosowanie: ${time(state.lastAppliedAt)}.")
                state.serverTime?.let { add("Stan serwera w tej kopii: ${time(it)}. Późniejsze zmiany mogą wymagać pobrania.") }
            }
            add("Oczekujące: ${state.pendingOperations} · Odrzucone: ${state.rejectedOperations} · Konflikty: ${state.conflictedOperations}. Kolejka dotyczy całego konta, także poza tym okresem.")
            if (state.legacyOperations > 0) add("Do przygotowania lub importu: ${state.legacyOperations} (wliczone powyżej).")
            if (state.unconfirmedWrite) add("Wysłana próba nie ma końcowego potwierdzenia.")
            if (state.heldServerRecords > 0) add("Niezastosowane rekordy z ostatniej kopii: ${state.heldServerRecords}. Raport zachowuje lokalne wersje.")
            if (state.copyAwaitingApplication) add("Ukończona kopia czeka na zastosowanie. Raport korzysta z dotychczas zapisanych danych.")
            if (state.requiresRecovery) add("Dane konta wymagają uzgodnienia. Raport pozostaje lokalny.")
            when (state.syncStatus) {
                "running" -> add("Trwa aktualizacja danych konta.")
                "deferred" -> add("Aktualizacja czeka na ponowienie.")
                "login" -> add("Aktualizacja czeka na ponowne logowanie.")
                "not_configured" -> add("Synchronizacja konta nie jest skonfigurowana.")
            }
            add("Czas kopii i dostęp do sieci nie potwierdzają całej kolejki.")
        }
    }
    val connection = when (network) {
        NetworkAccessState.Blocked -> "Tryb offline · ruch sieciowy zablokowany. Zapisany raport pozostaje dostępny."
        NetworkAccessState.Unavailable -> "Ruch sieciowy wstrzymany · ustawienie sieci jest niedostępne. Raport działa offline."
        else -> "Raport dostępny także offline."
    }
    return AnalyticsSyncNotice(local, lines + connection)
}
