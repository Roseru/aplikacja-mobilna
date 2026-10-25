# Korekty zapotrzebowania — etap klienta E9

25.10.2026, Agent1. Gałąź `codex/android-korekty-energii`, baza
`17c388edfd915355d398d7b33deb65a1f7a0d5d3`. To dalsza implementacja,
nie ukończony odbiór E9. Kontrakt: [O1](../docs/e9/INTEGRACJA_O1.md),
[wymagania11.5](../WYMAGANIA_PROJEKTOWE.md#115-zapotrzebowanie-i-korekty).

Status: REST/cache/UI i migracja Room25 mają lokalne wyniki PASS opisane
poniżej. Pełne E9 nadal wymaga integracji opt-in synchronizacji i odbioru
z rzeczywistym serwerem. Zbudowany APK używa osobnego pakietu energycheck
i syntetycznej granicy API/sesji w instrumentacji.

## Zakres do ukończenia

- Własny ekran stanu E, historii niezmiennych wersji oraz analiz i ich
  przyczyn odmowy. Oszacowanie E pozostaje odrębne od celu kcal/B/T/W.
- Świadome zlecenie analizy online: aktualny provider z capabilities,
  notice o minimalnych agregatach oraz osobne potwierdzenie zakresu v1.
  Odczyt/cache nie zaznacza checkboxów ani nie wysyła modelowi danych.
- Przegląd propozycji, expiry i niezmiennego source_context. Przyjęcie,
  odrzucenie i cofnięcie tworzą własne trwałe próby z kluczem i dokładnym
  body; niepewnego ACK nie zastępujemy nowym UUID. Nowa decyzja od
  następnego dnia nie przestawia celu posiłków ani klasy profilu.
- Requested i effective automatu pokazujemy osobno. Zgoda zachowuje
  pozostałe ustawienia, a afirmacja jest osobną świadomą operacją
  z aktualnym E/revision/provider/notice. Zmiana rankingu lub ponowny
  odczyt nie wykonują afirmacji w tle.
- Trwały cache i próby są związane z właścicielem, lease i kontekstem
  serwera. Offline udostępnia ostatni własny odczyt z oznaczeniem wieku;
  nie obiecuje nowej analizy lub przyjęcia bez aktualnego serwera.
- Integracja encji energy_estimate i jawnego capability
  energy_estimates_v1 pozostaje częścią pełnego etapu. Zmiana scope
  wymaga pełnego snapshotu z zachowaniem istniejących operacji; nie
  włączamy jej przez sam nagłówek w dotychczasowym konsumencie O2.

## Implementacja REST, pamięci i UI

EnergySchema używa kopii wygenerowanego energy.schema.json z przypiętym
SHA256 reprezentacji LF
`54baca27ddc062b8de98386dde964cd8259998e1c30cdb3e44ab4de9b0cb7764`.
Wyłącznie konfiguracja schematu dopuszcza zamianę CRLF na LF, żeby checkout
Windows i Linux ładowały ten sam dokument. Pierwotny plik Windows CRLF ma
surowy SHA256 `0ab9b9a795151e16989b131d9f64947150b0907916ee6339b79c8e76bb2187d4`.
Zaufana konfiguracja zawiera granice liczbowe0.0 i po kontroli pina używa
JSONObject. Odpowiedzi, requesty i audyt nadal przechodzą StrictJson;
nie normalizujemy ich oryginalnych bajtów ani nie dopuszczamy koercji typów.
Obsługuje jego alternatywy, warunki, typy, ograniczenia i daty; nieznane
keywords lub zewnętrzne odwołania są odrzucane. Nie używamy interpretatora
katalogu ignorującego warunki wymagane przez ten kontrakt.

EnergyProtocol ma typowane odczyty stanu, osi i analiz, BigDecimal,
powiązanie notice/snapshot oraz budowanie kanonicznych requestów.
Historia używa rzeczywistego kontraktu: pusta strona zwraca poprzednie
after_revision, a nie null. Pierwotny wire/audyt pozostaje niezmienny.
DTO nie zawierają tokenów i mają redagowane toString.

EnergyStore dodaje3własne tabele: energy_cache, energy_attempts i energy_backoff.
Zapis jest związany z captured lease i istniejącym kontekstem konta. Wersje E
są niezmienne, a próby utrwalają oryginalny leaseGeneration, UUID, body,
If-Match i fingerprint przed I/O. SQL guard blokuje zmianę tych pól oraz
usunięcie nierozstrzygniętej wysłanej próby. Jawne ponowienie po ponownym
logowaniu do tego samego kontekstu zachowuje pierwotne dane operacji;
stary callback nie może zastosować wyniku pod nowym lease lub innym kontem.
Epoka/generacja innego kontekstu nie jest automatycznie przepisywana.

Transport używa tego samego PolicyConnectionFactory i jednej sesji przez
EnergySessionAccess/SessionController. Nie zakłada drugiego token vault.
Ma ścisłe ścieżki, no-store, limity odpowiedzi, brak przekierowań, deadline
oraz disconnect blokującego I/O przy anulowaniu. Wszystkie późne wyniki
przechodzą ponownie gate/ticket/owner/context przed transakcją.

Repozytorium odczytuje aktualne state/me/capabilities przed nowym zleceniem
i afirmacją. Zmiana przeglądanego kontekstu wymaga ponownej decyzji; nie
podmienia po cichu body poprzedniej próby. 401 może odświeżyć tę samą sesję;
429/503 zapisują wspólny backoff. Niepewna odpowiedź zachowuje próbę do
retry, a utracony receipt lub ponownie użyty klucz wymagają uzgodnienia.
Przyjęcie/revert zapisuje wyłącznie oś E i odświeża podgląd; nie przepisuje
celu, profilu albo dotychczasowego outboxu sześciu domen.

Ustawienia otwierają ekran E i celu posiłków, analiz i historii. W UI są
osobne potwierdzenia zakresu jednej analizy i przyszłego automatu. Odczyt,
cache i odtworzenie ekranu nie zaznaczają zgód. Niepewna/nowa zmiana zgód
rankingu wstrzymuje oznaczenie effective; żaden ranking PUT nie afirmuje
energii. Revert planu na jutro wymaga jawnego wskazania i zatwierdzenia
zastępowanej wersji. Operacje pokazują rozdzielnie niewysłane, niepewne,
potwierdzone, odrzucone i pochodzące z wcześniejszego kontekstu.

Robocze0.8.34/code45/validation1045/Room25. Zgodnie z decyzją właściciela
cały przepływ powstał przed kontrolami. Końcowy build validation/testAPK,
standard Kotlin, lint i tylko4nowe JVM protokołu+6zmienionych odcisków
został uruchomiony. Pierwszy build FAIL na konflikcie nazwy wyjątku z DTO
EnergyUnavailable;314,469s, wejścia niezmienione. JVM/lint/native nie
zostały w nim wykonane. Wyjątek otrzymał osobną nazwę EnergyAccessFailure.
Drugi build skompilował oba warianty i źródła testów, lecz zakończył się
FAIL631,359s:6zmienionych testów odcisków PASS,4nowe protokołu FAIL przy
ładowaniu statycznego schematu z granicą0.0. Surowe odpowiedzi nadal muszą
spełniać StrictJson. Wyniki sześciu PASS zachowano i nie ponawiano.

Po oddzieleniu przypiętej konfiguracji od parsera odpowiedzi trzeci build
PASS895,281s: validation/testAPK, standard Kotlin,4JVM protokołu PASS,
lint0Error/0Fatal/8Warning/2Information. LogSHA256
`c5aa8ecce7e4cbab8088c9288c890d72898ac991995f1fb8533326ec4b3ced28`.
Wejścia pozostały niezmienione. Eksport25 ma52encje, identityHash
`bebca9f9db0ceb7b48ac008643af5fb4`, surowy SHA256
`3db2ff20015bde08082fbcf8cdda8d25aa845be4a01c93137c272ae66f014265`.

Przegląd przed publikacją wykrył zależność surowego pina konfiguracji od
CRLF/LF. Wprowadzono opisany powyżej pin reprezentacji LF i rozszerzono
istniejący przypadek o oba warianty. Czwarty build PASS618,172s: oba
warianty Kotlin, validation/testAPK,4JVM protokołu PASS i lint bez błędów
(8Warning/2Information), wejścia niezmienione. Sześciu zamkniętych testów
odcisków nie powtarzano. LogSHA256
`a850572311b35852c1882b8845c93fdad864fba1b8006e7e9594b349b8c7b23b`.

Na jego APK wykonano6przypadków urządzenia, wszystkie PASS/0FAIL/0SKIP:
reopen/replay utraconej odpowiedzi/obce konto, actual24→25, HTTP headers
i anulowanie, świadoma ścieżka Compose create→accept bez zmiany celu,
trwałe oznaczenie niepewnej zgody przez restart i równoległy odczyt,
oraz actual eksporty Room25 i ścisły zakres drivera. Instrumentacja28,357s,
receipt44,703s; logSHA256
`04b1e48ee2b9ea37aadd9dbf3e1a4d359c035a8dab20c658ee7aabbe3d07ad3a`.
Oryginalne APK/testAPK i3pliki bazy zachowały hashe. Własny AVD5564
pozostał offline; osobny energycheck zostaje zainstalowany do podglądu.
App23397089B/SHA256
`3607ac057bb251665d9cca140fa2c4433b8463554c09fa08d77f2edc1f5c90a5`,
test3177974B/SHA256
`6cc7185acd0700c3077b056773ee6d51facb3e1f44456fc51dc047823332a8ae`.
Granica API/sesji była syntetyczna; nie wykonano rzeczywistego
Keycloak/Gemini/HTTPS lub odbioru pełnego E9. E0 PASS11schemas/98valid/
35invalid/18scenarios/16Decimal/5day/72normalizations/894local-links.

Odczyt podczas zmiany zgód nie kasuje jej trwałego znacznika. Root zaznacza
go przed istniejącym ranking PUT/retry, bez edycji SessionController.
Stan aktywności w pamięci rozróżnia GET rozpoczęty podczas mutacji od GET
wykonanego po jej zakończeniu; nonce chroni przed skasowaniem nowszego
sygnału. Po restarcie znacznik nadal wyłącza oznaczenie effective do
nowego potwierdzonego odczytu poza zmianą zgód. Własna nierozstrzygnięta
próba PUT zgód też trwale blokuje takie oznaczenie i nowe potwierdzenie.
Nadal jest to ostatni pobrany stan, nie obietnica bieżącego stanu serwera.

Integracja capability/encji energy_estimates_v1 z synchronizacją pozostaje
**DO WYKONANIA** po dostawie O2. Ten etap nie uznaje samego REST/cache za
pełne E9 ani za nowe liveE4, configuredAPK lub android_acceptance.

## Współpraca

O1 napisał addytywną migrację24→25 dla3lokalnych tabel tego modułu;
została zarejestrowana w18miejscach, bez zmiany dawnych migracji. Jej
kwalifikacja actual24→25 i eksport25 przeszły opisane kontrole.
Siedem plików O2 z AGENTS pozostaje zamrożone. Nie powstaje drugi gate,
sesja lub magazyn tokenów. O2 nadal oddaje porty/runtime/admission na
własnej bazie be6/4f+be21; końcowy merge i odbiór po jego finalnym pinie.
Ukończony kalkulator17c388e i driverccb614e pozostają osobnymi gałęziami.

Przed włączeniem EnergyPullResponse w kolejnym etapie trzeba przenieść
jego wzorzec UnicodeText na istniejącą iteracyjną kontrolę znaków.
Reprodukcja wzorca JVM:1024znaki PASS,2048i4096 StackOverflowError.
Dotyczy m.in. tokenów4096znaków nowej synchronizacji. Bieżący EnergyProtocol
wywołuje wyłącznie definicje REST, a transport nie dopuszcza ścieżki sync;
wyników powyżej nie rozszerzamy na jeszcze niewłączoną definicję sync.
