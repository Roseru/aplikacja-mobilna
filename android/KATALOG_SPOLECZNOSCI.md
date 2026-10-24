# Katalog społeczności — Android WF-07/08

Stan 24.10.2026: duży przepływ jest napisany i podłączony do aplikacji.
Build/lint oraz pięć nowych unikalnych przypadków natywnych zaliczono
w opisanych niżej zakresach. Nie jest to skonfigurowane wydanie live,
scalony PR lub potwierdzenie pełnego v1. Wersja0.8.32/code43/validation1043,
Room23. Kod czeka na integrację wspólnego runtime O2 i końcowe CI.

## Baza i podział pracy

- Gałąź `codex/android-katalog-spolecznosci` zależy od własnego opublikowanego
  pina `4f6bb841818daa5b0823132a2120106dd97c3c61` gałęzi
  `codex/android-katalog-do-pobrania`. To jawna zależność od jeszcze
  niescalonego wspólnego providera/fabryki sieci; nie należy scalać dziecka
  do rodzica. Końcowy odbiór wymaga aktualnego main i integracji rodzica.
- O1 prowadzi nowy moduł `community`, widok, addytywne DI/nawigację,
  zapis porcji i migrację22→23. O2 nadal prowadzi konsument gate w
  SyncWork/SyncCoordinator/SyncWorkPresentation. Te pliki nie są zmieniane.
  Dodatkowo [O1 przekazał O2 dwa wydzielone porty](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6386626395)
  sesji/SyncExecution i obserwowalnej generacji gate. O1 zamroził te pliki
  do dostawy O2; własne wcześniejsze metody community przy apiSession
  pozostają zachowane do zwykłego merge.
- Rezerwacja migracji i granice przekazane do O2/O3 w
  [komentarzu6379040261](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6379040261).
  Potwierdzenie odbiorców nie jest domniemane.
- Nie powstaje mały PR statusowy. Cały nowy przepływ, testy, poprawki
  i wymagane CI poprzedzają funkcjonalne scalenie.

## Zachowanie użytkownika

Z ekranu wyboru posiłku przycisk „Katalog społeczności” otwiera wyszukiwanie.
Serwer zwraca strony po10 pozycji; pamięć ekranu obejmuje jedną stronę.
Osobny przycisk pokazuje zapisany fragment, z jawnym oznaczeniem jego
możliwej nieaktualności. Nowe odczyty i działania wymagają konta, bootstrapu,
ważnej sesji i dozwolonej sieci. Gość może przejść do konta lub prywatnego
produktu; podstawowy katalog i dziennik zachowują swoją obsługę offline.

Szczegóły pokazują źródło, status weryfikacji, osobne plusy/minusy,
braki odżywcze i ilość g/ml. Brak gęstości blokuje wyłącznie konwersję
między jednostkami. Zapis porcji działa lokalnie bez ważnego JWT.
Produkt po scaleniu zachowuje oryginalny publiczny identyfikator/rewizję,
makra i snapshot użytego źródła. `canonical_ref` służy do nawigacji i ocen;
nie zastępuje oryginalnych wartości w historii. Braków B/T/W nie zapisuje
się jako zera. Długa nazwa jest skracana do limitu200 znaków kontraktu
dziennika; pełna nazwa pozostaje w lokalnym snapshotcie.

Publikować można własny żywy szkic z potwierdzoną rewizją serwera,
bez niewysłanych zmian tej encji. Formularz rozróżnia znaną, nieznaną
i niepasującą markę/wariant oraz nieznany skład. Opisuje rodzaj źródła,
aliasy, porcję i opcjonalną udokumentowaną gęstość. Użytkownik wyraźnie
akceptuje udostępnienie danych. `matches` pokazuje kandydatów i ich dane;
można wybrać istniejący produkt albo potwierdzić nowy wariant. Backend
ponownie sprawdza zgodność przy publikacji. Prywatny szkic pozostaje
osobną encją; samo zjedzenie lub zapisanie produktu nie publikuje go.

Ocena jest jednym własnym głosem1/−1 z rewizją `If-Match`; można ją
zastąpić lub wycofać przez DELETE bez body. Autor nie głosuje na swój
produkt. Zgłoszenie zawiera dokładną referencję produktu, powód i opis.
Ekran pokazuje wynik z serwera; liczników nie zwiększa optymistycznie.

## Trwałość i sieć

Room23 dodaje wyłącznie `community_cache`, `community_attempts` i
`community_backoff`. Istniejące schematy1–22 i tabele nie są zastępowane.
Rejestracje 15 wcześniejszych testów migracji otrzymują wyłącznie nowy
ostatni krok i bieżący oczekiwany numer schematu; historycznych liczb
rekordów ani zamrożonego drivera E4 nie zmienia się.

Cache jest odseparowany kontem i kontekstem serwera; przechowuje maksymalnie
100 wersji/4MiB na kontekst. Nie jest pełnym pakietem publicznego katalogu.
Przełączenie konta nie udostępnia cudzych ocen lub oznaczeń autorstwa.
Nowa sesja tego samego konta może odczytać własną trwałą kopię.

Przed wysłaniem mutacji zapisywane są UUID, metoda, ścieżka, dokładne
body, If-Match i odcisk żądania. `attempted` jest utrwalone przed fizycznym
wywołaniem. Utrata odpowiedzi zachowuje ten sam klucz i body; po restarcie
użytkownik ponawia zapisane żądanie. Usunąć można wyłącznie niewysłane.
Nieznane wyniki nie są wyrzucane przez limit historii. Poprzedni kontekst
konta pozostaje widoczny jako wymagający wyjaśnienia i nie jest wysyłany
z nową epoką. Wygaśnięcie odpowiedzi idempotencji nie tworzy automatycznie
nowego UUID. Zakończona historia ma ograniczenie100; nieznanych bieżących
żądań może być najwyżej64.

Moduł używa istniejącej sesji i odświeżania z pełnym fence konta,
generacji/epoki, lease i wersji sesji. Każda operacja ma permit wspólnego
NetworkAccessGate i używa tej samej PolicyConnectionFactory co API,
AppAuth i oficjalny katalog. Nie ma drugiej preferencji ani magazynu
tokenów. API tylko HTTPS; przekierowania są odrzucane, odpowiedzi są
ograniczone, a watchdog rozłącza socket po30s. Retry-After jest zapisany
i współdzielony z istniejącą przerwą sesji/API, bez skracania poprawnego
Retry-After. 401 dopuszcza jedno odświeżenie z tym samym
kontekstem i zapisanym żądaniem. Surowe błędy i tokeny nie trafiają do UI.

## Kwalifikacja i pozostałe wejścia

Po całym przepływie przeprowadzono build validation/testAPK/standard Kotlin/
lint. Pierwszy build PASS726,437s; po rzeczywistych poprawkach odpowiedzi,
Retry-After i podglądu publikacji końcowy build PASS588,453s,
20executed/68up-to-date,0error/fatal,8warnings/1info. Log końcowy SHA256
`835df8ef92e2252076124f5cf0132aa2162a18970468d34064d7ded2f74e6d39`.
To kompilacja i lint, bez uruchamiania testów JVM lub wcześniejszych A/B/C.

Pięć nowych unikalnych przypadków native API35 jest zaliczonych:

| Przypadek | Zakres rzeczywistego wykonania |
|---|---|
| Cache/konta i Meal | Room, lease/ABA konta, prywatny cache, oryginalna rewizja po merge,100ml×gęstość1,1 z200kcal/100g daje220kcal, brak W pozostaje brakiem |
| Nieznane żądanie | Zapis przed wysyłką, reopen plikowej Room, te same UUID/body/fingerprint, brak kasowania attempted, zachowany RetryAfter, brak ponowienia w nowej epoce |
| Adapter HTTP | Rzeczywisty HttpsCommunityGateway i PolicyConnectionFactory, syntetyczny socket, metoda/ścieżka/key/body/epoch/If-Match, DELETE bez body i odmowa po blokadzie |
| Migracja22→23 | Prawdziwy plik22 z niezmienionego eksportu, wszystkie dawne wiersze i rowid zachowane, kontrola FK, trzy nowe puste tabele i zgodność z wygenerowanym schematem23 |
| Nawigacja | Rzeczywiste Application/MainActivity/root, gość bez dostępu do nowych operacji online, odtworzenie Activity i przejście do prywatnego produktu |

Pierwsza instrumentacja17,683s: **4PASS/1FAIL**, bez skip. Błąd był w
przygotowaniu starej testowej bazy:22 nie zawsze zawiera opcjonalne
`indices`; migrowanie nie zostało wtedy osiągnięte. Log SHA256
`2424b8a9d58381fbf3645b3be7fa218769838d4e450005d19874cc298b752be6`.
Poprawiono wyłącznie ten fixture; sam pakiet testowy przebudowano200,469s,
5executed/41up-to-date. APK aplikacji pozostał identyczny bajtowo.
Powtórzono wyłącznie migrację: **1PASS/0FAIL/0SKIP**,4,127s;
log SHA256 `4f757f3934995d78fd751d2772394cbbb2eddf897d3228e2433d7ebf6452ae95`.
Pierwszy FAIL pozostaje zachowany; nie jest to jeden nowy pełny przebieg5/5.

Zainstalowane izolowane pakiety zweryfikowano z binarnym manifestem i SHA:

- `pl.roseru.kalorie.validation.communitycheck`,1043/0.8.32.validation,
  22919441B, SHA256 `84b70ec4ffb7ffa785ea55eb0874e4f37e3f218c7e48c2d185637963cc57fb65`;
- końcowy testAPK `pl.roseru.kalorie.validation.communitycheck.test`,
  4810296B, SHA256 `adbb18975bd561e209275babc65d1360a865906baaadf828e3f2a8082038e73f`;
- schemat23 SHA256 `8b7df6d9d4d4653ec3b8e85fbf53ba353e8621cf89c4a573ce0a97cfd90936b2`.

Przed i po obu instrumentacjach było airplane1/wifiOFF/brak aktywnej sieci.
Oryginalne APK i pliki DB zachowały SHA również podczas cleanup.
Usunięto tylko zweryfikowane syntetyczne pakiety; własny O1Session35/5564
zatrzymano bezwipe. Nie restartowano komputera lub normalnego emulatora.
Logi są lokalne i niewersjonowane; APK nie są publikowane w źródłach.

Do odbioru nadal potrzebne są funkcjonalna integracja portów/gate od O2,
zachowanie obu fragmentów SessionController podczas zwykłego merge i końcowy CI.
Live API/OIDC, wspólne E4 z O3, nowy skonfigurowany APK oraz wdrożenie
pozostają osobnymi wejściami. Zamrożona dostawa0.8.29/Room20 jest zachowana;
driver nie otrzymał automatycznego dopuszczenia nowego schematu23.
