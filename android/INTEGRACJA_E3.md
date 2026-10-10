# Przekazanie mobilne E3 — Agent 1 / O1

Punkt odniesienia: Android 0.7.0 / Room 6, gałąź `codex/android-bootstrap-cele`, zależna od `ad8c0a6` / [PR #7](https://github.com/Roseru/aplikacja-mobilna/pull/7). Przeczytano [plan O2, PR #8](https://github.com/Roseru/aplikacja-mobilna/pull/8), commit `1908c9b`; potwierdzenie i parametry wysłano [w PR #5](https://github.com/Roseru/aplikacja-mobilna/pull/5#issuecomment-6099166765) na polecenie użytkownika. Ten etap przygotowuje lokalny protokół, nie wdraża OIDC/HTTP.

## Parametry klienta

| Parametr | Wartość |
|---|---|
| applicationId zwykłego APK | `pl.roseru.kalorie` |
| applicationId testów urządzenia | `pl.roseru.kalorie.validation` |
| Ustalony przyszły redirect APK | `pl.roseru.kalorie:/oauth2redirect` |
| Ustalony przyszły redirect instalacji testowej | `pl.roseru.kalorie.validation:/oauth2redirect` |
| Publiczny klient z planu O2 | `calorie-android`, bez sekretu w APK |
| Planowany przepływ | przeglądarka systemowa, Authorization Code + PKCE S256 |

Adresy są dokładną allowlistą do przyszłego klienta, bez wildcardów. `AuthReturn` utrwala je w kodzie i testach; **APK 0.7 nie ma jeszcze handlera powrotu, OIDC ani uprawnienia INTERNET**. Redirect harnessu backendu jest osobny. O3 ustala osiągalny identyczny issuer dla backendu i emulatora, adres API/JWKS oraz parametry środowiska. Nie wpisano fikcyjnych adresów ani tokenów.

## Tożsamość i bootstrap

1. Przyszły klient potwierdza sesję OIDC i wiąże dokładne `(issuer, sub)` z rejestrem O1. Rejestr metadanych sam nie uwierzytelnia. Token użyty do żądania musi należeć do przechwyconej tożsamości; późniejsza zmiana sesji nie podstawia tokenu innego konta.
2. Dla aktualnego `OwnerLease` `AccountBootstrapStore.begin()` utrwala UUID Idempotency-Key przed przyszłym wywołaniem `POST /me/bootstrap`, bez body. Utrata odpowiedzi lub restart zachowuje klucz niezakończonego żądania w tej generacji lease.
3. `BootstrapProtocol` sprawdza ograniczony do 64 KiB, ścisły UTF-8/JSON wynik E0: dokładnie cztery pola, kanoniczne UUID, integer generation 1..2147483647, semantyczny UTC timestamp z maksymalnie sześcioma cyframi ułamka. Zachowuje oryginalną pisownię czasu.
4. `apply()` sprawdza aktywny zakres/generację oraz klucz żądania w transakcji. Atomowo utrwala powiązanie i wynik żądania. Powtórzenie tego samego wyniku jest no-op; inny wynik dla tego klucza, inne account_id, niższa generacja w tej samej epoce, obcy właściciel lub stare żądanie są odrzucane. Jedno account_id nie może zostać przypisane do dwóch lokalnych właścicieli.
5. Żądanie zakończone dostaje nowy klucz przy kolejnym `begin()`. Po błędzie E3 `sync_epoch_changed` / `account_generation_changed` przyszły adapter może użyć `renew()` do niezakończonego żądania; późniejsza odpowiedź starego klucza jest odrzucana. Nie resetujemy danych ani poprzedniego powiązania.
6. Po pierwszym bootstrapie chronione odczyty mogą korzystać z tego powiązania i potwierdzonej sesji. Sama obecność wiersza nie dowodzi aktualnego tokenu lub aktywności konta na serwerze. Obsługa 401/403 i blokady konta pozostaje obowiązkiem przyszłego klienta.

| Wartość | Znaczenie |
|---|---|
| local owner UUID / storageScope | trwały zakres danych urządzenia; gość nadal używa dawnego aliasu `guest` |
| lease generation | lokalny licznik zmiany aktywnego właściciela |
| account_id | UUID konta zwrócony przez backend |
| account_generation | generacja serwerowego konta, niezależna od lease |
| sync_epoch | epoka instalacji/odzyskania backendu |
| contextRevision | lokalny licznik zmian zaakceptowanej epoki/generacji serwera |

Zmiana epoki lub generacji ustawia trwałe `requiresRecovery`. Zmieniona epoka dopuszcza niższą generację po odtworzeniu backendu, lecz zawsze blokuje gotowość sync. `requireReady()` sprawdza lease i kontekst; przyszły worker wywołuje kontrolę przed wysyłką i wewnątrz transakcji zapisu odpowiedzi. Powtórny bootstrap nie czyści tej blokady. Jej bezpieczne rozwiązanie wymaga procedury E4; w 0.7 nie ma drogi automatycznego skasowania flagi.

Powiązanie nie wybiera konta, nie przenosi danych gościa i nie tworzy profilu/celu/posiłku. Przed włączeniem kont w UI O1 musi odtwarzać repozytorium i ViewModel oraz anulować odczyty/czyścić pamięć ekranów. Testy lokalne nie zastępują tokenów ani integracji APK z rzeczywistym E3.

## Cele i adapter prywatnych zapisów

Każdy nowy lokalny zapis celu ma nowy UUID, czas decyzji, strefę i sekwencję właściciela. Następna zmiana tego samego dnia wskazuje poprzednią wersję jako `correctionOf`; SQLite wymusza własność tej referencji. Odczyt daty i analityka wybierają największą datę obowiązywania, następnie sekwencję i ID. Historyczne daty pozostają zgodne z wcześniejszymi celami.

Wersji nie aktualizujemy ani nie usuwamy; callback i migracja instalują ochronę przed UPDATE/DELETE oraz zmieniającym treść INSERT OR REPLACE. Ponowienie `setGoal()` z tym samym ID i wejściem nie tworzy wersji/operacji; inna treść jest konfliktem. Cel i outbox zapisują się razem. Lokalna sekwencja nie jest serwerowym `goal_timeline_revision`.

Migracja 5→6 zachowuje wszystkie stare pola celu, właścicieli i payloady, dodając metadane `localSequence=0`, `reason=legacy`, pozostałe nullable. Nie odtwarza decyzji nadpisanych przez dawne wersje aplikacji. Zmiana dawnego celu tworzy nową wersję; nie przepisuje starej kolejki.

O2 nie dodaje `PATCH /me` ani `POST /me/goals`; prywatne zapisy telefonu będą wysyłane przez E4. Obecny outbox nadal ma lokalny format i **nie jest wysyłany**. Adapter musi obsłużyć stare ID, pełne snapshoty i Decimal (E0 wejście do 6 miejsc, lokalne porcje do 12) oraz server base revisions/epokę bez cichego obcinania oryginałów. Uzgodnienie celu z serwerową osią i pełne klucze encji z właścicielem pozostają do wykonania; złożony FK korekty celu nie oznacza zakończenia całej migracji izolacji.

## Dalszy odbiór

O2: dostarcza wdrożone E3, aktualne OpenAPI/przykłady i błędy. O3: udostępnia konfigurację środowiska/klienta, CI Androida i dostawę APK. O1: klient sesji/HTTP, bootstrap na rzeczywistym E3 i odczyty, a potem uzgodnienie E4, mapowanie encji i WorkManager. Gość nadal musi działać bez sieci, a jego import wymaga jawnej zgody i trwałego potwierdzenia.
