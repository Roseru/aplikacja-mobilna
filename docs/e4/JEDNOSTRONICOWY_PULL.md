# Ukończenie małego PULL bez zajmowania kopii kontynuacji

Dwa zwykłe cykle pull → push → pull mogły zajmować cztery sloty konta,
nawet gdy każda odpowiedź mieściła się w jednej stronie. Kolejny odczyt
otrzymywał `503 sync_resources_exhausted` do wygaśnięcia i sprzątnięcia kopii.
Stary test wykonywał cztery puste odczyty i wymagał tej odmowy. To poprawka
cyklu życia pierwszej strony, bez zmiany limitu czterech utrwalonych kopii.

Pierwsze żądanie nadal czyta stan w repeatable read, pod blokadą konta i
licznika, z tym samym H, epoką, generacją, zakresem protokołu i rewizją osi.
Wspólny leniwy iterator obejmuje encje, mapowania i żądane potwierdzenia.
Sonda stosuje wspólny limit elementów, rzeczywisty budżet UTF-8, 512 KiB
pojedynczego elementu i dotychczasowe ograniczenia sesji. Przechowuje jedną
stronę i najwyżej jeden nadmiarowy element; zamyka iterator i wyniki SQL
przed ewentualnym drugim przebiegiem.

Gdy całość mieści się na stronie, serwer wydaje pełny dotychczasowy DTO,
zwykły podpisany checkpoint i `page_token=null`, bez zapisywania wierszy
`SyncSession`/`SyncSessionItem`. Snapshot nadal ma nie-null `snapshot_token`.
Sam ten token nie jest żądaniem kontynuacji. Checkpoint nie zawiera ID sesji
i nadal uprawnia do push oraz rozpoczęcia odczytu przyrostowego.

Gdy potrzeba kolejnej strony, po zamknięciu sondy, przed liczeniem kopii,
działa istniejące `app.admit_read_session(owner)` z E5. Jego pojedynczy marker
w `read_admissions` jest wspólny z prywatnymi odczytami i ograniczony do
jednego wiersza właściciela. `INSERT/ON CONFLICT UPDATE` zapisuje nową wersję wiersza;
samo `FOR UPDATE` pozwalało oczekującej transakcji repeatable read liczyć stary stan
i przekroczyć limit. Błąd serializacji `40001` uruchamia istniejące ponowienie
z nowym `Session` i snapshotem RR, najwyżej trzy próby. Nie zmienia to
`SyncCounter.position`/xmin, historii, checkpointów ani uprawnień.
Kompletna pojedyncza strona i kontynuacje nie zapisują markera admission.

Przy czterech kopiach następuje odmowa bez piątego grafu. Mały kompletny
odczyt może zadziałać przy czterech slotach, bez zmiany istniejących grafów.
Ich wcześniejsze i końcowe strony pozostają dostępne przez dotychczasowe
60 minut; checkpoint zachowuje 30-dniowy okres i wszystkie kontrole kontekstu.
Nie ma nowego endpointu, migracji, wersji wire, skrócenia TTL ani live-prune.

Pierwotna weryfikacja commita `2fa7` na nowym własnym PostgreSQL 17.11:

- Stary kod: oczekiwany FAIL regresji, piąty pusty początkowy PULL dawał 503.
  Po poprawce sześć kolejnych początkowych PULL nie zapisuje grafów.
- 74 wybrane przypadki PASS: 51 integracyjnych PG i 23 jednostkowe tokenów.
  Obejmują cztery prawdziwe wielostronicowe kopie i mały odczyt 200 bez zmiany
  ich fingerprintów lub SQL zapisującego grafy; overflow liczby/bajtów
  zachowuje 503. Sześć cykli z rzeczywistym push i retry zachowuje UUID,
  treść operacji i pojedyncze potwierdzenia.
- Zachowane middle/final retry, expiry, izolacja kontekstu i scope energy,
  requested receipts/mapowania, kontrola wieku po odczycie, UTF-8 oraz
  null/zero i tombstone. Zestaw testów jednostkowych backendu: 1743 PASS; zawiera
  te same 23 testy tokenów, więc łącznie sprawdzono 1794 unikalne przypadki.
- Izolowany mutant przywracający limit przed sondą dał 1 oczekiwany FAIL
  właściwej regresji; nie jest liczony jako dodatkowy PASS.
- Ruff/format, zgodność zasobów schematów, E0 i diff-check PASS. E0 sprawdził
  między innymi lokalne odnośniki. Surowe nieudane próby środowiskowe
  i pierwotny FAIL pozostały zachowane; nie są zastępowane zielonym opisem.

Produkcja była identyczna bajtowo podczas tego zakresu. Jedna późniejsza
zmiana łamania linii testu ma identyczny AST; zachowano obie wersje źródeł.
Własny klaster zatrzymano po kwalifikacji PID/czasu utworzenia/exe/datadir/port,
z kodem 0. Nie używano danych, klastra ani emulatora aktywnego demo.

Niezależny przegląd ujawnił dwie dalsze granice, zachowane jako osobne
oczekiwane porażki przed poprawką:

- Dwa rzeczywiste równoczesne żądania HTTP PULL przy trzech utrwalonych kopiach
  dostały 200/200 i pozostawiły pięć. PostgreSQL potwierdził oczekiwanie B
  na blokadę A; obie transakcje używały RR. Po wykorzystaniu admission z E5 dwa warianty
  (marker istniejący i stara kopia bez markera) dają 200/503, rzeczywisty błąd `40001`
  i nowy `Session` przy retry, dokładnie cztery kopie. Pierwotne trzy kopie,
  licznik, jego `xmin` i pozostałe 89 tabel zachowują hashe; jedyną dodatkową
  dopuszczoną tabelą jest właściwy marker właściciela. Odmowa nie publikuje
  snapshot/page/checkpoint. Osobne regresje API-role zachowują final retry.
- Pełny odczyt E9 ustawiał yield_per dopiero na wykonanym Result.
  Teraz TextClause ma opcję przed execute. Dwie rzeczywiste regresje
  jednej strony i materializowanej kontynuacji sprawdzają nazwany kursor psycopg, partię 1
  i jego zamknięcie; RED→PASS. Cały sześcioprzypadkowy zakres E9 sync
  przeszedł po tej zmianie. Iterator nadal zamyka wynik przy wczesnym spill.

Surowe porażki i wynik 1794 pozostają historią commita `2fa7`. Końcowy zakres na
kodzie `0cb19` dał 81 PASS/0 FAIL/0 SKIP: 58 testów integracyjnych PG i 23 testy tokenów,
w tym istniejące przypadki współbieżności, RR i ACL E5. Zestawu 1743 testów jednostkowych
nie uruchamiano ponownie. Ruff/format, zgodność schematów, E0 (930 lokalnych
odnośników) i diff-check przeszły. Wznowiono i zatrzymano z kodem 0 wyłącznie
własny kwalifikowany klaster testowy; aktywne dane Native pozostały nietknięte.

To odbiór komponentu z syntetycznymi granicami tożsamości/dostawców, nie
potwierdzenie Keycloak/TLS/Androida, Gemini, E4 lub wydania 1.0. Duże odczyty
nadal wymagają wolnego slotu utrwalanej kontynuacji. Zdalne CI oraz osobna
kwalifikacja backendu i powtarzany rzeczywisty przepływ APK pozostają etapem
integracji koordynatora.
