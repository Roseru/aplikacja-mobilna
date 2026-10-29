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

Gdy potrzeba kolejnej strony, przed materializacją działa dotychczasowy cap.
Przy czterech kopiach następuje odmowa bez piątego grafu. Mały kompletny
odczyt może zadziałać przy czterech slotach, bez zmiany istniejących grafów.
Ich wcześniejsze i końcowe strony pozostają dostępne przez dotychczasowe
60 minut; checkpoint zachowuje 30-dniowy okres i wszystkie kontrole kontekstu.
Nie ma nowego endpointu, migracji, wersji wire, skrócenia TTL ani live-prune.

Weryfikacja lokalna na nowym własnym PostgreSQL 17.11:

- Stary kod: oczekiwany FAIL regresji, piąty pusty initial PULL dawał503.
  Po poprawce sześć kolejnych initial PULL nie zapisuje grafów.
- 74 wybrane przypadki PASS: 51 integracyjnych PG i 23 jednostkowe tokenów.
  Obejmują cztery prawdziwe wielostronicowe kopie i mały odczyt200 bez zmiany
  ich fingerprintów lub SQL zapisującego grafy; overflow liczby/bajtów
  zachowuje503. Sześć cykli z rzeczywistym push i retry zachowuje UUID,
  treść operacji i pojedyncze potwierdzenia.
- Zachowane middle/final retry, expiry, izolacja kontekstu i scope energy,
  requested receipts/mapowania, kontrola wieku po odczycie, UTF-8 oraz
  null/zero i tombstone. Przejście całego backend unit:1743 PASS; zawiera
  te same23 testy tokenów, więc łącznie1794 unikalne przypadki końcowe.
- Izolowany mutant przywracający cap przed sondą dał1 oczekiwany FAIL
  właściwej regresji; nie jest liczony jako dodatkowy PASS.
- Ruff/format, zgodność zasobów schematów, E0 i diff-check PASS. E0 sprawdził
  między innymi lokalne odnośniki. Surowe nieudane próby środowiskowe
  i pierwotny FAIL pozostały zachowane; nie są zastępowane zielonym opisem.

Produkcja była identyczna bajtowo podczas końcowego zakresu. Jedna późniejsza
zmiana łamania linii testu ma identyczny AST; zachowano obie wersje źródeł.
Własny klaster zatrzymano po kwalifikacji PID/czasu utworzenia/exe/datadir/port,
z kodem0. Nie używano danych, klastra ani emulatora aktywnego demo.

To odbiór komponentu z syntetycznymi granicami tożsamości/dostawców, nie
potwierdzenie Keycloak/TLS/Androida, Gemini, E4 lub wydania1.0. Duże odczyty
nadal wymagają wolnego slotu utrwalanej kontynuacji. Zdalne CI oraz osobna
kwalifikacja backendu i powtarzany rzeczywisty przepływ APK pozostają etapem
integracji koordynatora.
