# Android 0.7.0 — bootstrap i niezmienne cele

Agent 1 / O1, 10 października 2026 r. Gałąź `codex/android-bootstrap-cele` od `ad8c0a6` / [PR #7](https://github.com/Roseru/aplikacja-mobilna/pull/7); baza PR: `codex/android-izolacja-kont`. Odbiór kolejno #1 → #6 → #7 → bootstrap, z retargetowaniem po odebraniu poprzedniego etapu i kontrolą integracji. Nie scalono własnych PR-ów.

## Zakres

- Room 6 dodaje trwałe żądanie bootstrapu i powiązanie lokalnego właściciela z serwerowym kontem, generacją i epoką. Lokalny lease i kontekst serwerowy mają osobne liczniki. Powiązanie nie uwierzytelnia ani nie wybiera konta.
- Klucz niezakończonego żądania przetrwa restart. Przyjęcie wyniku i zapis potwierdzenia są atomowe; identyczne ponowienie jest no-op. Spóźnione odpowiedzi, inne konto lub konflikt wyniku są odrzucane. Unikalne account_id nie może zostać przypisane dwóm lokalnym właścicielom. Użyto jawnego INSERT/UPDATE, aby konflikt unikalności nie został zamieniony w pozorny upsert.
- Zmiana epoki/generacji serwera trwale blokuje gotowość synchronizacji, bez kasowania prywatnych danych. Ponowny bootstrap nie usuwa blokady; uzgodnienie odzyskania wymaga E4.
- Cel dostaje nowy ID, lokalną sekwencję, czas/strefę decyzji i referencję poprzedniej wersji z tego dnia. SQLite wymusza właściciela korekty i chroni wersje przed UPDATE/DELETE oraz zmieniającym REPLACE. Cel i outbox zapisują się razem. Odczyt dnia/analityki wybiera najnowszą wersję.
- Migracja 5→6 przebudowuje tabelę celów z zachowaniem starych kolumn i ID; metadane starych wersji mają sekwencję 0 i reason=legacy. Nie odzyskuje decyzji nadpisanych przez starsze APK. Poprzednie schematy, snapshoty i payloady pozostają niezmienione.
- [Przekazanie E3](INTEGRACJA_E3.md) utrwala parametry przyszłego klienta i odpowiedź na pytania O2. APK nadal jest gościem offline; nie ma OIDC, handlera callbacku, uprawnienia INTERNET ani HTTP.

## Weryfikacja

- Końcowy pełny przebieg `:app:assembleDebug :app:testDebugUnitTest :app:lintDebug :app:connectedValidationAndroidTest`: BUILD SUCCESSFUL. 59 testów JVM i 47/47 testów urządzenia API 35, zero błędów i pominięć. Lint: 0 błędów, 26 ostrzeżeń, 1 informacja.
- JVM: normatywny bootstrap E0, ścisły JSON/UTF-8/UUID/generacja/czas, limit odpowiedzi, callbacki oraz kolejność wersji celów, niezależna od kolejności wejścia.
- Osiem nowych prób urządzenia obejmuje trwały klucz/powiązanie, restart, zmianę właściciela i powrót, odnowienie żądania, zmianę kontekstu serwera, konflikt i atomowy rollback potwierdzenia, niezmienne cele/REPLACE/FK/rollback kolejki, równoległe decyzje oraz rzeczywistą migrację schematu 5. Wcześniejsze migracje 1/2/3/4 także dochodzą do 6.
- Pierwszy przebieg 47 testów miał sześć niepowodzeń: pięć migracji z niezmienioną nazwą self-FK po rename SQLite oraz kolizję account_id ukrytą przez Upsert. Poprawiono tworzenie tabeli pod docelową nazwą i jawne INSERT/UPDATE. Powyższy wynik pochodzi z ponowionego całego zestawu po poprawkach, nie sumowania osobnych prób.
- APK zainstalowano jako aktualizację 0.6→0.7 bez kasowania danych. Przed/po porównano wszystkie stare kolumny 16 tabel rzeczywiście zainstalowanej bazy. Zachowano dziennik, właścicieli i kolejkę; foreign_key_check pusty. Uruchomiono Dziennik w trybie samolotowym; versionCode 7 / 0.7.0. Testy korzystają z oddzielnej instalacji validation.

Lokalne raporty są w `app/build/test-results/`, `app/build/reports/` i `app/build/outputs/androidTest-results/`. APK poza Git: `output-apk/Racje-i-kalorie-0.7.0-debug.apk`; SHA-256 `f0da5c1af3223cbbd548b22f40ab6c51edf60397cf42c17fa7a03ca5c8fe62b4`. To walidacja lokalna; nie potwierdza mobilnego CI ani rzeczywistego E3.

## Granice i kolejne kroki

Odczytano recenzje O2 do #1/#6/#7 oraz nowe przekazanie O3-001/O3-002 na `53ff675`. #1 wymaga poprawki kompletności w swoim zakresie, mimo że kolejne wersje mają już poprawną wspólną regułę. #6 wymaga rozdzielenia bieżącego dnia od wyników zamkniętych i odświeżenia po północy. Te uwagi pozostają do osobnego domknięcia właściwych PR-ów; ten etap bootstrapu nie deklaruje ich naprawy. O3 przygotowuje rzeczywiste CI Androida i testowe środowisko. Żaden PR nie jest uznany za odebrany na podstawie samych testów autora.

Potrzebne są klient potwierdzonej sesji, odtwarzanie ViewModel, HTTP/bootstrap na E3, mapowanie server revisions/Decimal, pełne klucze encji z właścicielem i procedura E4/WorkManager. Roboczy outbox nie jest payloadem HTTP. Import gościa wymaga jawnej zgody oraz trwałego potwierdzenia. Nie przypisano ani nie wysłano danych gościa.
