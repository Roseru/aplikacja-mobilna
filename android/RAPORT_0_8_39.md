# Android 0.8.39 — trwałe podglądy offline

Stan: cały etap odebrany lokalnie; publikacja i zdalny CI są osobnym odbiorem.
Gałąź `codex/android-podglady-offline`. Wersje: regularna 0.8.39/code50,
validation 0.8.39.validation/1050, Room27/55 encji. Baza prac: abe31e7,
rodzic PR178 został następnie scalony do main db800877.

## Zachowanie

- Własne potwierdzenie osiągnięć, ostatnia strona rankingu oraz lista
  i wcześniej pobrane szczegóły Nemesis przetrwają zamknięcie bazy i procesu.
  Podgląd pokazuje datę pobrania i informację, że wyniki i udostępnianie
  mogły się zmienić. Dostępny jest także po wygaśnięciu tokenu.
- Kopie wymagają aktywnego konta i zgodnego właściciela, dzierżawy oraz
  pełnego kontekstu serwera. Gość, inne konto, stary callback A→B→A,
  recovery i zablokowane konto nie otrzymują cudzych podglądów.
- `Saved` jest osobnym stanem. Nie tworzy źródła zgody lub decyzji Nemesis,
  nagrody lokalnej, checkpointu, ACK ani aktywnego kursora następnej strony.
  Wygasła strona rankingu pozostaje historycznie czytelna; kolejne pobranie
  zaczyna się od świeżego zapytania.
- Przeglądanie rankingu, również zapisanego, nie wymaga publikowania własnego
  wyniku. Własna zgoda pozostaje osobną decyzją, zgodnie z istniejącym API.
  Znana odmowa dostępu usuwa odpowiednią kopię. Po błędzie przejściowym
  można ponowić ten sam odczyt albo osobno wybrać poprzedni podgląd z datą
  i ostrzeżeniem. Otwarcie kopii nie zastępuje automatycznie próby ponowienia.
- Nemesis najpierw przywraca kopię lokalną. Przy jej braku zachowuje odczyt
  wejściowy; świeży szczegół nadal odświeża się na pierwszym planie.
  Zapisane szczegóły otwierają się bez HTTP. Ich widok nie pokazuje panelu
  nowych decyzji. Zakończenie udostępniania usuwa wcześniejsze porównania,
  a pseudonim anulowanego partnera jest usuwany także z utrwalonego JSON.
- Użytkownik może usunąć własne zapisane podglądy. Nie usuwa to dziennika,
  kolejki, historii potwierdzeń ani zapisanej decyzji oczekującej na ACK.

## Pamięć i zgodność

Nowa tabela `private_preview_cache` jest dodatkiem do istniejących54 tabel.
Kopie mają wersjonowaną kopertę klienta, walidację istniejącymi parserami DTO,
hash treści i porządek zapisu niezależny od cofnięcia zegara. Limit wynosi
32 wpisy i8MiB treści JSON na konto; starsze szczegóły mogą zostać usunięte z cache.
Zmieniony kontekst nie przywraca starej kopii. To pamięć podręczna,
nie alternatywny dziennik lub protokół serwera.

Migracja26→27 zachowuje stare eksporty1–26. Eksport27: SHA256
`5cdf7ce9090e8f93628ccc485938fb73cc507bb1b360085d1523b205a77f3d2b`,
identity `81bce45e330bbf3f75444d0b4ea690a0`. Jawny guard validation obejmuje
Room27 i nową tabelę; Room28 oraz brak wymaganej izolacji nadal są odrzucane.
W istniejących testach migracji dopisano wyłącznie kolejne przejście do
bieżącej bazy. Backend, kontrakt HTTP, driver O2 i zamrożony Room23 bez zmian.

## Faktyczny odbiór

- Oba warianty i APK testów skompilowane. Po zachowaniu istniejącej ścieżki
  ponowienia odczytu końcowy build/lint501,766s, logSHA256
  `c319ec6da67ad61c5abdff0effc2a2b9356e2a546c7ac5b853d85b8940a1f242`.
  Lint0Fatal/0Error/7Warning/2Information. Pierwszy kompletny odbiór924,891s
  pozostaje historią poprzedniego wariantu obsługi błędu, nie dowodem nowej ścieżki.
- Tylko sześć testów zmienionego guardu fingerprint:6PASS/0FAIL/0ERROR/0SKIP.
  Wykonane raz podczas odbioru723,844s; źródła tego komponentu i testu
  zachowane identycznie. Nie ponawiano całego JVM.
- Pierwszy ograniczony native:4PASS/2FAIL/0SKIP,52,516s z instalacją/kontrolą,
  logSHA256 `182b23b642dee79c0136aa5a8e3d11f9604a1738c19f65b53d3470191eef7fa0`.
  PASS: migracja wszystkich54 poprzednich tabel wraz z rowid/treścią,
  budżet/korupcja/prywatność cache, trzy ekrany oraz istniejący powrót Nemesis.
  Dwa nowe testy sesji zatrzymały się na nieobsługiwanym fizycznym applicationId
  izolowanego APK, przed odczytem danych. Użyto istniejącego parametru
  logicznego klienta OIDC; reguła produkcyjnych callbacków bez zmian.
  Ponowiono wtedy tylko te dwa:2PASS/0FAIL/0SKIP,17,063s z kontrolą.
- Końcowy przegląd zachował stan Failed/canRetry po utracie odpowiedzi.
  Użytkownik może ponowić tę samą stronę lub osobno otworzyć kopię historyczną.
  Zmieniony kontroler otrzymał nowy właściwy odbiór. Przebudowano tylko test APK
  po jawnym wskazaniu identyfikatora fixture w dwóch istniejących testach
  ponowienia oraz poprawce testu wyciszenia. Test-only build172,516s,
  logSHA256 `82d8440683b22c5a21d1edf289fcfe506729ccbfb92050a65982f857d56bbb3a`.
- Tylko pięć właściwych przypadków kontrolera/runtime:5PASS/0FAIL/0SKIP,
  17,969s z kontrolą (6,928s testów). LogSHA256
  `aea9c7849a5f69dd6d9606130aa6a1819ac5b53eb3619b550983e645f3d0d337`.
  Dwa nowe obejmują restart SQLite/kontrolera, wygasłą sesję bez HTTP,
  brak kontynuacji/nowych decyzji i izolację kont/kontekstów. Dwa istniejące
  sprawdzają utratę odpowiedzi rankingu/Nemesis i ponowienie tego samego odczytu.
  Piąty sprawdza wyciszenie runtime i propagację anulowania.
- Zachowano wcześniejsze cztery niezależne PASS. Całe klasy tych testów,
  magazyn/protokół/Room, UI i jego akcje są identyczne; definicja SessionView
  również identyczna. Zmienione zachowanie kontrolera nie było przypisane
  do dawnych wyników: otrzymało opisany nowy odbiór pięciu przypadków.
  Łącznie dziewięć unikalnych scenariuszy ma pozytywny wynik w zakresach4+5;
  nie jest to nowe wspólne9/9. Nie ponawiano tych czterech ani całego native.
- Oryginalny APK, jego test APK i trzy pliki dziennika identyczne przed/po
  każdym zakresie. Tryb samolotowy1, Wi-Fi wyłączone, brak aktywnej sieci.
  Izolowany privatepreviewcheck otwarto do prób offline. Zamknięty podczas
  przerwy emulator uruchomiono ponownie z zachowaniem userdata, bez wipe
  i bez restartu komputera.

## Osobna porażka main i poprawka fixture

Push/main CI40303186907 dla db800877 miał sześćSUCCESS oraz android-device
121505973910 i gateFAIL. Raport12642400012/SHA256
`44ab52e87630346408c44c3d019678b77984780ba7835dfde561eaf7e08324b3`
wskazał `ReplayRuntimeIsolationTest.kt:62`, odczyt worker.isCancelled.
arm oczekuje na przyjęty blok i jego finally; stan zewnętrznego wywołującego
mógł jeszcze nie odzwierciedlać propagacji anulowania. Test oczekuje teraz
na worker.join przed tą samą asercją. Nie zmieniono timeoutów, asercji
blokady/przedwczesnego arming/writes ani produkcyjnego runtime.
Ta jedna metoda jest piątym przypadkiem końcowego odbioru powyżej.
To nie rerun/naprawa historycznego CI na main; właściwy zdalny CI nowego head
pozostaje do wykonania. Zamrożone źródło2319357 i cztery APK Room23 bez zmian.

Aplikacja: SHA256 `07a273ad9363dbc653a0c08f2f7c432f3deb41b73e044d7ccd9266490afbf923`.
Końcowy test APK: `6c47b623ecbfe1c64e4a2e9847c984bdc92e45b0b1cc737261fbe443181c69a9`.
Buildy i prywatne logi pozostają poza Git. Nie wykonano tu nowych prób
TLS/PKCE/Gemini/E4 lub odbioru1.0. Cztery skonfigurowane APK Room23 dla O3
są odrębną, przypiętą dostawą opisaną w jedynym dzienniku zespołu.
