# Android 0.8.3 — trwała kopia danych serwera

Data: 11 października 2026. Autor: **agent 1 / O1**. Gałąź: `codex/android-sync-pull`. Końcowy kod `d782a2e546667f5ddf74f172bb6c980c3a8d591b`; początek `f2527a5356f64148201d18804cfb95efa0db8a44`, zwykłe merge main E7 `ba9704a` i instrukcji E8 `af8df9a`. Merge nie zmieniły źródeł Androida ani trzech użytych schematów sync.

## Wynik i granice

Jawny GET sync/pull po sesji/bootstrapie pobiera pełną kopię do osobnych tabel Room 7. Strona i następny token zapisują się atomowo; dopiero finał aktywuje kopię/checkpoint. Restart w tym samym lease/kontekście wznawia pobieranie. Powtórki nie dodają stron; niespójności, stare konto/sesja, cykle lub brak miejsca nie przesuwają postępu. Przed poprawnym nowym bootstrapem błąd kontekstu blokuje kolejny odczyt. Recovery pozostaje trwałe, a account_deleting odcina kolejne pobrania.

To archiwum odpowiedzi wire, bez zmiany lokalnego dziennika/goals/profilu/outbox i bez ACK. Semantyczna projekcja, push, inkrementalny pull, import gościa, zakończenie recovery i WorkManager pozostają kolejnymi etapami. Szczegóły i granice magazynu są w [opisie pull](SYNCHRONIZACJA_PULL.md).

## Lokalna walidacja

- JVM: **103 PASS**, zero failures/errors/skips. 16 nowych przypadków: dziewięć walidatora przypiętych schematów, pięć protokołu snapshotu, dwa transportu. Korzystają z prawdziwych normatywnych schematów i przykładów O2; trzy schematy w assets/test resources porównane byte-for-byte z contracts.
- Lint: **0 błędów / 4 ostrzeżenia / 1 informacja**. Bez suppressions lub baseline.
- Pełne urządzenie: **104/104 PASS**, zero failures/errors/skips. Końcowy pełny build/JVM/lint/device zakończył się sukcesem w **9m13s**. API35/Android15, 1080×2400, density420/font1, offline, emulowane AC/StayOn/Awake. Osobny pakiet validation, bez czyszczenia aplikacji użytkownika.
- 18 nowych przypadków urządzenia: dziewięć magazynu/Room, siedem kontrolera sesji i dwa Compose. Obejmują trwałą kontynuację/reopen, atomowy finał, idempotencję/zmieniony replay, duplikaty UUID, zmianę timeline/token/cykl, A→B→A, recovery, nowy potwierdzony bootstrap, expiry, deleting i budżet zachowanych prób. Ponadto rzeczywisty SQLITE_FULL oraz migrację 6→7 z porównaniem wszystkich kolumn wszystkich 18 wcześniejszych tabel.
- HTTP/OIDC są zastępczym transportem, nie dowodem rzeczywistego TLS/Keycloak/API. Room, SQLite, Keystore i Compose pracują na emulatorze. Rzeczywisty odbiór nadal wymaga istniejącego środowiska O3 zgodnie z O1-015.

Wykonywane polecenie: `:app:assembleDebug :app:testDebugUnitTest :app:lintDebug :app:connectedValidationAndroidTest --max-workers=1 --offline --console=plain`. Wybrano jeden worker dla zapisu nowego wspólnego schematu debug/validation.

## Pierwsze nieudane próby

Pierwsza równoległa kompilacja debug/validation przerwała się w KSP przy odczycie częściowego JSON nowego schematu7. Najbardziej prawdopodobna przyczyna to jednoczesny export/read tego samego pliku. Plik następnie przeszedł parser JSON; sekwencyjna kompilacja zakończyła się sukcesem. Nie zmieniano workflow O3 lub starszych schematów1–6.

Pierwszy pełny run urządzenia: **101/104 PASS, 3 failures**, zero skips. Nowa asercja UI wymagała całego tekstu zamiast substring; nowy fixture migracji wymagał `indices` także dla tabel bez indeksów; fixture `sync_epoch_changed` pomijał obowiązkowe `current_sync_epoch/requested_sync_epoch/recovery_required`. Parser poprawnie odrzucał tę odpowiedź przed mutacją. Naprawiono fixtures/asercję oraz czytelność tekstu liczników; dodano JVM sprawdzający wymagany kontekst błędu. Zachowano oryginalny raport prywatnie. Nie poluzowano kontraktu, reguł magazynu, asercji danych, timeoutów lub zestawu; nie ma automatycznego retry/skip.

## APK i zachowanie danych

Wersja `0.8.3` / versionCode14 / Room7, SHA-256 `e892cf1ef65e4b4d808b99c6dfd124bce4e290e38838307f504ab181adf8b901`. APK pozostaje poza Git. Rzeczywista aktualizacja zainstalowanej0.8.2→0.8.3 zachowała wszystkie kolumny18wcześniejszych tabel i5posiłków/outbox. Sprawdzenie przed instalacją, po install-r przed pierwszym startem (Room6) i po rzeczywistym pierwszym uruchomieniu (Room7) porównało prywatny punkt odniesienia; foreign_key_check pusty. Aplikacja została ponownie otwarta do testów manualnych. Prywatny punkt odniesienia pobrano przed zmianą pakietu; treść dziennika nie jest publikowana.

## GitHub i następny etap

PR26/31 scalono po własnym odczycie ośmiu wymaganych kontroli. Odczytano scalony E7/PR28 oraz instrukcje E8/PR33, O2-022–024; nie przypisujemy sobie testów O2. Oddzielny [PR32](https://github.com/Roseru/aplikacja-mobilna/pull/32) poprawia wire base_revision=null w instrukcji E7; skierowany na main, scalony normalnym merge0ed58d6610f827de08ad9b10b1d6eda87ccbf45c po własnym odczycie ośmiu success dla00b2876/baseaf8df9a, [CI38176933888](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38176933888); reviews/comments0. Jego merge do tej gałęzi zachował dziennik oraz nie zmienił źródeł Androida. Ten etap ma własne CI po publikacji PR do main.

Priorytety właściciela zapisano w [planie Androida](../PLAN_IMPLEMENTACJI_ANDROID.md): dopracowana analityka7/30/90, osiągnięcia z jawnym statusem lokalnym/serwerowym, dalsze E4 i NEMESIS na odebranych E8.3/E8.4. Instrukcje/master E8 nie są gotowym runtime; wyniki/ranking wymagają świadomej zgody i potwierdzonej aktualności. Większy deficyt nie daje dodatkowych punktów.
