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
  Znana odmowa dostępu usuwa odpowiednią kopię; błąd przejściowy może pokazać
  poprzedni podgląd z datą i ostrzeżeniem.
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
32 wpisy i8MiB na konto; starsze szczegóły mogą zostać usunięte z cache.
Zmieniony kontekst nie przywraca starej kopii. To pamięć podręczna,
nie alternatywny dziennik lub protokół serwera.

Migracja26→27 zachowuje stare eksporty1–26. Eksport27: SHA256
`5cdf7ce9090e8f93628ccc485938fb73cc507bb1b360085d1523b205a77f3d2b`,
identity `81bce45e330bbf3f75444d0b4ea690a0`. Jawny guard validation obejmuje
Room27 i nową tabelę; Room28 oraz brak wymaganej izolacji nadal są odrzucane.
W istniejących testach migracji dopisano wyłącznie kolejne przejście do
bieżącej bazy. Backend, kontrakt HTTP, driver O2 i zamrożony Room23 bez zmian.

## Faktyczny odbiór

- Po złożeniu przepływu: oba warianty i APK testów skompilowane; końcowy
  build/lint924,891s, logSHA256
  `b11e93898a9294cf0929e9a10b66c8e248d9c3084f9fdb2fe010170e02c6f961`.
  Lint0Fatal/0Error/7Warning/2Information.
- Tylko sześć testów zmienionego guardu fingerprint:6PASS/0FAIL/0ERROR/0SKIP.
  Wykonane raz we wcześniejszym odbiorze723,844s; źródła komponentu i testu
  zachowane identycznie w końcowym buildzie. Nie ponawiano całego JVM.
- Pierwszy ograniczony native:4PASS/2FAIL/0SKIP,52,516s z instalacją/kontrolą,
  logSHA256 `182b23b642dee79c0136aa5a8e3d11f9604a1738c19f65b53d3470191eef7fa0`.
  PASS: migracja wszystkich54 poprzednich tabel wraz z rowid/treścią,
  budżet/korupcja/prywatność cache, trzy ekrany oraz istniejący powrót Nemesis.
  Dwa nowe testy sesji zatrzymały się przy celowo nieobsługiwanym fizycznym
  applicationId izolowanego APK, przed odczytem danych.
- Poprawiono tylko te dwa testy, korzystając z istniejącego parametru
  logicznego klienta OIDC `pl.roseru.kalorie.validation`. Reguła produkcyjna
  dopuszczalnych callbacków nie została rozszerzona. Przebudowano tylko
  APK testów259,015s; aplikacja identyczna. Ponowiono tylko te dwa przypadki:
  2PASS/0FAIL/0SKIP,17,063s z kontrolą, logSHA256
  `82fb5a83feb2d57443eb1b47c4d8b514e4bd98f09edb0ec0349db9391c4d0d14`.
  Obejmują rzeczywisty restart SQLite/kontrolera, wygasłą sesję bez HTTP,
  brak kontynuacji/nowych decyzji oraz izolację kont i kontekstów.
- Łącznie sześć unikalnych scenariuszy ma wynik pozytywny w dwóch zakresach
  4+2; nie jest to nowe wspólne6/6. Pliki dwóch klas zawierających wcześniejsze
  cztery PASS są identyczne. Nie ponawiano tych czterech ani całego native.
- Oryginalny APK, jego test APK i trzy pliki dziennika identyczne przed/po
  obu zakresach. Tryb samolotowy1, Wi-Fi wyłączone, brak aktywnej sieci.
  Izolowany `privatepreviewcheck` otwarto do prób offline.

Aplikacja: SHA256 `aee02f8ff8f4763c6fad6995c10d1f0545517e96e01b176c90e2c0cc33aaab19`.
Końcowy test APK: `fd1c8e7e7875255cec97b779774893397697ae4c2002aec725162625bdec6904`.
Buildy i prywatne logi pozostają poza Git. Nie wykonano tu nowych prób
TLS/PKCE/Gemini/E4 lub odbioru1.0. Cztery skonfigurowane APK Room23 dla O3
są odrębną, przypiętą dostawą opisaną w jedynym dzienniku zespołu.
