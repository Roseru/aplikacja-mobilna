# Niezależna recenzja E5-O2-R - osoba 2

Data: 11 października 2026. Recenzent: subagent `sources`, nieautor kodu runtime ani testów implementacyjnych E5. Ten subagent zebrał materiały źródłowe katalogu i zaktualizował audyt; niezależność tej recenzji dotyczy runtime/testów, nie oceny własnego audytu źródeł. Wykonawca i CI podają swoje wyniki osobno w [raporcie](RAPORT_E5.md).

**Werdykt: 9,4/10 dla E5-O2-R, bez otwartych istotnych usterek/P1/P2.** Odczyty/statystyki nadają się do osobnego odbioru koordynatora po weryfikacji końcowego head/CI. Nie jest to odbiór zespołowego E5, katalogu official, APK lub HTTPS; recenzent nie wykonuje merge ani nie zwalnia E6.

## Tożsamość ocenionego stanu

Baza checkoutu podczas wykonania: `b27838b9aa1027aa00b342df1c922f2bdb38ef3a`, gałąź `codex/backend-e5-odczyty-statystyki`. Recenzowano lokalną implementację na tej bazie przed jej commitem. Nie przypisujemy wyników fikcyjnemu przyszłemu head. Wykonawca wiąże końcowy commit/PR i CI w raporcie oraz sprawdza, czy po recenzji nastąpiła zmiana runtime.

Sprawdzono 17 plików runtime: nowe moduły `diary/read_*`, `analytics`, wspólny `profiles/service`, migrację0012/env, `main`, `health` i retencję sync. Utrwalono prywatny manifest hashów SHA-256; jego SHA-256 to `89af0620bd7a2bdb0abfd5afb48cbf09b806f3ff82f41cb16797506f8d05a4da`. Przed zapisem recenzji ponownie porównano wszystkie17 plików: identyczne bajty.

| Kluczowy plik ocenionej implementacji | SHA-256 |
|---|---|
| `backend/migrations/versions/0012_e5_reads.py` | `2b73c9d7e059a64763050872a01215101b945e08be9f9601ab7b92dd221f0309` |
| `backend/src/calorie_app/modules/diary/read_service.py` | `0b8b68312f9f5488c27c88eae0597a842cab703118460b811aa8ab3a6f0dd528` |
| `backend/src/calorie_app/modules/analytics/service.py` | `32de9fcdab87626bb3a68dde78b8c2ece518d1c77e9a84c8bba266fcb4a1e315` |
| `backend/src/calorie_app/modules/profiles/service.py` | `ea9152ce6adea7caaf91ef33e3e0a8f64a3f9bf5bbb277ae0bc8fffb4bf321b6` |

## Faktyczne wykonanie recenzenta

Własna odseparowana baza `e5_review_test`, rzeczywisty PostgreSQL17.11 Windows, nie SQLite. Prywatne procesy/proby i JUnit poza repozytorium; nie publikowano sekretów ani prywatnego dziennika. Testy HTTP korzystają z roli `calorie_app_api`; verifier fixture podaje kontrolowane principal OIDC. To test prawdziwego PostgreSQL/HTTP/autoryzacji aplikacyjnej, nie własny dowód real Keycloak. Ten ostatni pozostaje osobną kontrolą wykonawcy/CI.

| Końcowe wykonanie recenzenta | Wynik | Zakres |
|---|---:|---|
| Nowe testy unit: privacy, reads_unit, statistics_unit | **93 PASS**, 2,72s | Tokeny/filtry, DTO, Decimal/null/zero/mianowniki, wektory i no-store błędów middleware/OIDC |
| Nowe testy integration: reads + statistics po obu naprawach | **75 PASS**, 63,76s | Rzeczywiste PG/HTTP, A/B/role, sesje/kontekst, TTL/limity, upgrade/downgrade/ACL/prune/purge, statystyki7/30/90, korekty, DST, snapshot i zapisana historia odżywienia |
| Pełny graf E4 przez upgrade/downgrade/reupgrade | **1 PASS**, 3,74s | Bezstratne rowsets wszystkich wcześniejszych tabel, epoch/receipts/sync/catalog/usuwanie, readiness503/200 oraz pełne efektywne ACL |
| Własne dodatkowe próby recenzenta | **12 PASS**, 10,38s | Scenariusze opisane poniżej, rzeczywiste transakcje i HTTP na osobnej bazie |

Brak skipów. Razem181 końcowych wykonań w tych czterech zakresach; nie dodajemy wcześniejszych powtórzeń do tej liczby i nie przedstawiamy testów wykonanych przez recenzenta jako nowych testów napisanych przez autora. Jedno ostrzeżenie deprecacyjne Starlette/httpx nie oznacza pominięcia wykonania.

Własne12 prób wykorzystują fixture bazy i domenowe helpery do zapisu, lecz mają niezależne asercje/scenariusze; nie zmieniono produkcji ani testów autorów:

- Kontrolowana bariera wymusza sześć początkowych snapshotów RR przed blokadą konta. Dwa rzeczywiste pomiary, limit1: dokładnie cztery wielostronicowe sesje oraz dwie bezpieczne odmowy zasobów, w DB dokładnie4 kopie.
- Zamrożona druga strona posiłków nadal pokazuje istniejący w kopii posiłek po usunięciu z domeny, a świeży odczyt już go wyklucza. Zamrożona rewizja osi celu0 pozostaje0 po nowej decyzji, nowy odczyt pokazuje1.
- Cztery endpointy osobno odmawiają brakującemu/nieprawidłowemu tokenowi i samemu adminowi/moderatorowi z401/403, poprawnym Error DTO i no-store, bez prywatnych items/daily.
- Profil Pacific/Honolulu przy00:05UTC kotwiczy poprzednią datę. Dzisiejszy wynik jest wstępny. Dokładne89.999999kcal przy celu100 pozostaje poza dolną granicą90; wyświetleniowe zaokrąglenie nie zmienia oceny. Brak białka daje średniąnull/day_count0.
- Pełne begin/confirm/purge konta usuwa kopie; stary token nie zwraca payloadu. Upgrade/downgrade0012↔0011 na istniejącym pomiarze zachowuje dane E4. Osobne dodatkowe wykonanie1PASS potwierdziło bezstratne JSONB rowsets całego grafu E4 przez0011→0012→0011→0012, readiness503/200/503/200, wszystkie efektywne prawa tabelowe/kolumnowe i PUBLIC oraz właściciela SECURITY DEFINER/search_path trzech funkcji. Sprawdzono efektywne prawa do kolumn i funkcji admission: API nie modyfikuje context, worker/operator nie wykonują admission, żadna z ról nie dostaje tabelowego DELETE.
- Wymuszone wyczerpanie bajtów daje503/no-store bez prywatnej treści; rollback pozostawia0 rekordów admission/session/items. Czterdzieści kolejnych odświeżeń pustej albo jednostronicowej listy daje200 i0 utrwalonych sesji/itemów.

## Wykryte usterki i rzeczywiste ponowne sprawdzenie

Pierwsze niezależne wykonanie integracji dało **62 PASS +1 FAIL**, a nie PASS: sześć równoległych pierwszych odczytów utworzyło6 sesji zamiast maksymalnie4. Sama blokada niezmienionego konta nie odświeża wcześniejszego snapshotu RR. Była to istotna usterka P2, zgłoszona wykonawcy.

Naprawa tworzy osobny techniczny tuple-write admission przez SECURITY DEFINER z ustalonym search_path; początkowy RR waiter po konkurencyjnym commicie otrzymuje40001 i ograniczone ponowienie, zamiast policzyć stare sesje. Nie modyfikuje generacji ani stanu konta i zachowuje blokady właściciela. Recenzent sprawdził kod, faktyczny limit na6 transakcjach oraz rollback/ACL/purge. Pierwsze powtórzenie integracji68PASS i własne11PASS potwierdziły zamknięcie P2; późniejsze końcowe75+12 uwzględniają następną poprawkę.

Recenzent wskazał także problem użyteczności: puste/jednostronicowe odświeżenia wcześniej zajmowały4 sloty na60min. Wykonawca poprawił go przed dostawą. Tylko nowa kopia, której pierwsza odpowiedź nie wystawiła next_page_token, jest usuwana w tej samej transakcji wąską funkcją discard. Funkcja wymaga aktywnego właściciela, zgodnej generacji/epoki i małej kopii; API ma tylko EXECUTE, bez tabelowego DELETE. Admission tuple pozostaje zatwierdzony, aby nadal wymuszać ponowienia starych RR. Prawdziwe sesje stronicowane pozostają do TTL również po końcowej stronie, więc token poprzedniej strony nadal nadaje się do retry. Własna próba40 odświeżeń, pełne zmienione testy i migracje potwierdziły poprawkę.

Dodatkowy przegląd zgodności starszych testów: aktualizacja `test_foundation` dodaje wyłącznie trzy tabele migracji0012 do nadal dokładnie porównywanego zbioru; `test_e4_snapshots` dodaje wyłącznie zerowe `read_items`/`read_sessions` do nadal dokładnie porównywanej odpowiedzi wspólnej retencji. Nie usunięto dawnych tabel/pól/asercji, nie zastąpiono równości podzbiorem ani nie pominięto scenariuszy E4. To poprawne addytywne oczekiwania E5, nie osłabienie testów. Ich faktyczne ponowne wykonanie pozostaje wynikiem wykonawcy, poza181 wykonaniami recenzenta. Ponownie potwierdzono niezmienność wszystkich17 hashów runtime; ocena9,4 pozostaje aktualna.

## Ocena techniczna i granice

Podział DTO/transport/reguły/SQL jest czytelny. Kopie stron mają osobny model i domenę podpisu; kolejne żądania ponownie sprawdzają konto/generację/epokę. H/as_of i rewizje należą do zamrożonego RR, bez utożsamiania tokenów z checkpointem lub ACK. No-store obejmuje błędy przed routerem. Limity rekordów, bajtów UTF-8 i czasu mają stabilne bezpieczne błędy; retencja i purge obejmują nowe kopie oraz admission.

Statystyki używają jednej spójnej transakcji, ograniczonych zapytań owner/date i wspólnego batch resolvera osi. Przejście7→90 nie powoduje osobnego odczytu osi na dzień. Poprawne są osobne mianowniki, brak danych vs0, dzisiejsze preliminary, dokładne granice celu i ostatnia rzeczywista waga/ujemna różnica. Testy potwierdzają historyczne korekty przesuwające daty/rozgałęzienia, zamknięcie kompletności po usunięciu posiłku i brak przeliczenia historii po zmianie katalogu.

Ocena9,4 wynika z naprawionej rzeczywistej konkurencji, dodatkowych własnych prób, sprawdzonych semantyk i migracji/ACL. Pozostałe ograniczenia nie są ukryte: recenzja nie obejmuje osobnego środowiska wdrożenia O3, rzeczywistego Android Room/APK, wykonania Kotlin vectors, kompletnego katalogu official ani finalnego CI nieopublikowanego jeszcze commita. [Audyt źródeł](../e0/ZRODLA_KATALOGU.md) opisuje konkretne braki C. Koordynator musi osobno odebrać final head/CI i bramki C/O1/O3; sama recenzjaR ich nie zamyka.

## Ponowny niezależny odbiór korekty dokumentacji rotacji

11 października2026, po projekcie poprawki wykonawcy: **9,4/10 dla tej korekty, bez otwartych istotnych uwag/P1/P2**. Poprzednia recenzja9,4/10 nie wychwyciła błędnego zdania o zachowaniu ważności checkpointów; jej181 testów i ówczesne zielone CI nie poświadczały tej instrukcji. Historię pozostawiono wyżej. Ponownie przeczytano końcową [instrukcję O3](KONFIGURACJA_O3.md#kontrolowana-rotacja-wspólnego-klucza), odsyłacz w [obsłudze sync](ODCZYTY_I_SYNCHRONIZACJA.md), historię korekty w raporcie oraz rzeczywiste token codecs, preflight/snapshot i SyncStore/SyncHTTP. Nie dopisano keyring, automatycznego odzyskania ani nowej funkcji APK. Sekret niezmieniony przy restarcie, spójna wymiana replik, brak gwarancji ważności starych30-dniowych checkpointów, rozdzielenie trwałych danych od tokenów, aktualny kontekst/nowy pełny pull bez starych checkpoint/snapshot/page, końcowy checkpoint przed push, zachowane operation_id/treści/lostACK i receipts oraz ograniczone sprzątanie/backoff odpowiadają kodowi. Instrukcja poprawnie zaznacza, że sam422 nie identyfikuje rotacji ani zmiany epoki i nie uruchamia automatycznego full pull; klient/uzgodnienie O1/O3 pozostają bramką operacyjną.

Recenzent wykonał **3 zgrupowane prywatne próby PASS**, bez wypisywania kluczy/tokenów i bez dopisywania pozornych testów pod treść instrukcji. (1) Bezpośrednie wywołania produkcyjnych funkcji kryptograficznych: checkpoint podpisany losowymA jest poprawny zA, a zB daje422invalid_sync_token również w swoim okresie ważności; snapshot/page sync także422invalid_sync_token, read1 daje422invalid_read_token, katalogrp1 jest odrzucany, kursor celówgp1 daje422invalid_request. (2) Rzeczywisty klient referencyjny SQLite/SyncStore i SyncHTTP z **HTTP MockTransport**:422invalid_sync_token kończy pojedyncze żądanie i propaguje ClientError, bez automatycznego retry/full lub zmiany checkpoint/requires_recovery. Niepuste originals, niezmienny wire/outbox i prawidłowy zachowany receipt pozostały identyczne. (3) Jawny full=True z oryginalnymID tworzy pierwsze żądanie wyłącznie z aktualną epoką/limitem/IDreceipt, dwie kontrolowane strony korzystają z nowych tokenów, a dopiero końcowa odpowiedź aktywuje nowy checkpoint podpisanyB; prepare_push zachowuje pierwotne operation_id/treść i używa nowego checkpointu. Nie symulowano braku ACK jako braku zapisu. Te3 grupy nie są dodawane do wcześniejszych181 testów; natywna walidacja podpisu jest rzeczywista, transport/snapshot odpowiedzi w tej próbie są kontrolowanym mockiem, nie nowym dowodem PostgreSQL, liveHTTP, Keycloak, wdrożenia replik lub APK.

Porównano ponownie wszystkie17 wcześniejszych hashów runtime: identyczne. Zmiana tej naprawy dotyczy wyłącznie dokumentacji; nie rotowano prawdziwego sekretu ani nie zmieniano epoki, kont, bazy, migracji lub protokołu. Końcowy commit/CI i odbiór koordynatora pozostają osobnym dowodem wykonawcy; ta ocena dotyczy zweryfikowanego projektu korekty, a nie fikcyjnego przyszłego head.
