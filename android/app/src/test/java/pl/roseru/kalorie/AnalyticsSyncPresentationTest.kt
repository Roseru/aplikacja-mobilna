package pl.roseru.kalorie

import org.junit.Assert.*
import org.junit.Test
import pl.roseru.kalorie.core.network.NetworkAccessState
import pl.roseru.kalorie.data.AnalyticsSyncState
import pl.roseru.kalorie.ui.analyticsSyncNotice
import java.time.ZoneId

class AnalyticsSyncPresentationTest {
    private val utc = ZoneId.of("UTC")
    private fun account() = AnalyticsSyncState.Account(null, null, 0, 0, 0, 0, false, 0, false, false, null)
    private fun text(state: AnalyticsSyncState, network: NetworkAccessState? = NetworkAccessState.Allowed(1)) =
        analyticsSyncNotice(state, network, utc).lines.joinToString("\n")

    @Test fun guestAndNeverFetchedAccountAreDifferentEvenWithAllowedNetworkAndEmptyQueue() {
        val guest = text(AnalyticsSyncState.Guest)
        assertTrue(guest.contains("Gość · dane tylko na tym urządzeniu"))
        assertFalse(guest.contains("Ostatnie ukończone pobranie"))
        val account = text(account())
        assertTrue(account.contains("Nie ukończono jeszcze pobrania i zastosowania kopii"))
        assertTrue(account.contains("Historia konta może być niepełna"))
        assertTrue(account.contains("Oczekujące: 0 · Odrzucone: 0 · Konflikty: 0"))
        assertFalse(account.contains("Synchronizacja zakończona"))
        assertFalse(account.contains("online", ignoreCase = true))
    }

    @Test fun appliedCopyShowsBothTimesButPendingRejectedAndUnknownWriteStayUnconfirmed() {
        val result = text(account().copy(lastAppliedAt = "2026-10-29T12:15:00Z", serverTime = "2026-10-29T12:00:00Z",
            pendingOperations = 3, rejectedOperations = 2, conflictedOperations = 1, legacyOperations = 1,
            unconfirmedWrite = true, heldServerRecords = 2, copyAwaitingApplication = true, syncStatus = "idle"))
        assertTrue(result.contains("Ostatnie ukończone pobranie i zastosowanie: 29.10.2026, 12:15 UTC"))
        assertTrue(result.contains("Stan serwera w tej kopii: 29.10.2026, 12:00 UTC"))
        assertTrue(result.contains("Oczekujące: 3 · Odrzucone: 2 · Konflikty: 1"))
        assertTrue(result.contains("także poza tym okresem"))
        assertTrue(result.contains("Wysłana próba nie ma końcowego potwierdzenia"))
        assertTrue(result.contains("Niezastosowane rekordy z ostatniej kopii: 2"))
        assertTrue(result.contains("kopia czeka na zastosowanie"))
        assertTrue(result.contains("Czas kopii i dostęp do sieci nie potwierdzają całej kolejki"))
        assertFalse(result.contains("Synchronizacja zakończona"))
    }

    @Test fun offlineAndRecoveryRetainCopyEvidenceInsteadOfInventingNewFreshness() {
        val account = account().copy(lastAppliedAt = "2026-10-20T10:00:00Z", serverTime = "2026-10-20T09:59:00Z", requiresRecovery = true)
        val blocked = text(account, NetworkAccessState.Blocked)
        assertTrue(blocked.contains("Tryb offline · ruch sieciowy zablokowany"))
        assertTrue(blocked.contains("20.10.2026, 10:00 UTC"))
        assertTrue(blocked.contains("Dane konta wymagają uzgodnienia"))
        val unavailable = text(account, NetworkAccessState.Unavailable)
        assertTrue(unavailable.contains("ustawienie sieci jest niedostępne"))
        assertTrue(unavailable.contains("Raport działa offline"))
        assertFalse(text(AnalyticsSyncState.Stale).contains("20.10.2026"))
        assertTrue(text(AnalyticsSyncState.Unavailable).contains("Aktualność synchronizacji jest niedostępna"))
    }
}
