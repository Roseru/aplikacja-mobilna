# Master E8.3 — zaproszenia, zgody i cykl Nemesis - osoba 2

Wersja 1, 12 października 2026 r. Drugi natywny czat wykonawczy E8. Wykonawca: Agent 2 / OSOBA 2. Priorytetem są poprawne transakcje, prywatność, zachowanie historii i czytelna struktura. Ten master wymaga publikacji i niezależnego odbioru przez koordynatora przed zleceniem wykonania. Nie jest dowodem runtime.

## 1. Konkretny rezultat i dwie fazy odbioru

Dostarcz rzeczywiście działający komponent Nemesis: prywatne adresowanie zaproszeń, wersjonowane warunki i zgody obu uczestników, create/accept/cancel, expiry, okres i strefę, izolację kont, idempotencję, migrację oraz rzeczywiste dowody PostgreSQL 17 i HTTP. E8.3 nie nalicza punktów ani agregatów i nie finalizuje wyniku. Nie implementuj E8.4, E9, Google, billing, produkcji, harmonogramów Codex ani Androida.

Praca ma dwie fazy w tym samym czacie, branch i PR:

1. **E8.3-C, izolowany komponent.** Możesz kodować równolegle z kończonym E8.1+2 na dokładnej zamrożonej podstawie. Tworzysz własny pakiet, migrację, SQL, testy i dokumentację. Produkcyjne API pozostaje niepodłączone, a publiczna bramka Nemesis zamknięta. Odbiór komponentu wymaga własnych realnych testów i niezależnego nieautora, ale nie udaje jeszcze zintegrowanej dostawy na main.
2. **E8.3-I, integracja.** Dopiero po odbiorze i scaleniu finalnego E8.1+2 koordynator zwalnia temu samemu wykonawcy potrzebne wspólne pliki. Wtedy dołączasz aktualny main zwykłym merge, podłączasz komponent i weryfikujesz zgodność całej aplikacji, kontraktów, ACL, migracji, deletion i restore. Publiczne rozpoczęcie rywalizacji nadal jest zamknięte do odebranego E8.4. Własny nieautor odbiera zmieniony zakres, finalne osiem kontroli CI i main wymagają osobnego potwierdzenia.

Nie zatrzymuj się na samym planie, mock routerze lub deklaracji gotowości. W fazie C ukończ autoryzowany samodzielny zakres, pokaż konkretny rezultat i jego ograniczenia; zależną integrację zostaw z jawnym właścicielem i warunkiem wznowienia. Nie obchodź tej granicy samodzielnym montowaniem routera do aplikacji produkcyjnej.

## 2. Dokładna podstawa, zależność i własność plików

Kod źródłowy fazy C: `fe0098c079d199e346b9eb1b2131165d2dd90d5e`, z E8.1+2 na `codex/backend-e8-motywacja-ranking`, [PR #35](https://github.com/Roseru/aplikacja-mobilna/pull/35). Baza upstream tego freeze: `af8df9af9bfd32aa8145eac6114fdfc7261a8477`. PR35 był draftem podczas odbioru freeze; jego pełny runtime, nieautor i CI nie są tym samym co odebrany interfejs. Późniejszy `8d57178` zawierał wyłącznie dokumentację/merge bez zmiany runtime i migracji względem fe0098c, ale start pozostaje dokładnym fe0098c. Koordynator odczytał main `0ed58d6` bez istotnej zmiany backendu względem af8df9a; przed własną publikacją sprawdź rzeczywisty aktualny stan.

Użyj własnego managed worktree i gałęzi `codex/backend-e8-nemesis-lifecycle` z dokładnego freeze. Nie przełączaj głównego E4, checkoutu koordynatora ani autora E8.1+2. Draft PR fazy C jest skierowany do `codex/backend-e8-motywacja-ranking` i jawnie zależy od konkretnego fe0098c / PR35. Pokazuje tylko nowy komponent. Nie scalaj go do oczekującej gałęzi upstream. Po merge PR35 koordynator zleci zmianę bazy na main i zwykły merge; bez force-push lub przepisywania opublikowanej historii.

Rezerwacja: `0017_e8_nemesis_lifecycle`, `down_revision = 0016_e8_motivation`. Przed utworzeniem sprawdź aktualny Alembic head i potwierdzoną rezerwację koordynatora. Kolizję zgłoś przed zapisem; nie zmieniaj użytych migracji 0001–0016. Alembic pozostaje jedną linią.

Freeze interfejsu nie jest pełnym PASS migracji0016. Możesz przygotować i testować lokalną0017, lecz **przed jej pierwszym pushem potwierdź z koordynatorem finalny numer i parent**. Jeżeli niezależny odbiór upstream wymaga nowej korekcyjnej migracji, koordynator rezerwuje nowy numer/parent zanim Twoja migracja zostanie opublikowana. Nie przepisuj0016 ani już opublikowanej0017. Własny package i testy mogą rosnąć dalej podczas tego uzgodnienia; sama niezapieczętowana rezerwacja nie blokuje całego komponentu.

Do końca finalnej dostawy E8.1+2 autor tamtej grupy posiada: `modules/sync/service.py`, wspólny motivation context/service/repository/facts, `main.py`, `health.py`, istniejące importy modeli i Alembic metadata, wspólne provision/bootstrap, aktualny purge wrapper, workflow oraz globalne generowane OpenAPI/schema copies. **Nie edytuj tych plików w fazie C.** Nie kopiuj ich ze swojego worktree nad cudzą pracę. Konkretną integrację tych powierzchni koordynator przydzieli później.

Twój zakres plików jest czytelny i wydzielony:

```text
backend/src/calorie_app/modules/nemesis/
  __init__.py
  models.py
  schemas.py
  rules.py
  identity_context.py
  repository.py
  service.py
  addressing.py
  access.py
  source_guard.py
  maintenance.py
  router.py
backend/migrations/versions/0017_e8_nemesis_lifecycle.py
backend/migrations/versions/e8_0017/
  schema.sql
  lifecycle.sql
  addressing.sql
  acl.sql
  maintenance.sql
backend/tests/unit/test_e8_3_*.py
backend/tests/integration/test_e8_3_*.py
backend/tests/support/e8_3_*.py
docs/e8/DECYZJE_NEMESIS_LIFECYCLE.md
docs/e8/RAPORT_NEMESIS_LIFECYCLE.md
docs/e8/RECENZJA_NEMESIS_LIFECYCLE.md
docs/e8/INTEGRACJA_O1_NEMESIS_LIFECYCLE.md
docs/e8/KONFIGURACJA_O3_NEMESIS_LIFECYCLE.md
docs/e8/INTERFEJS_NEMESIS_LIFECYCLE.md
```

Nazwy można uprościć, jeśli odpowiedzialności pozostają jasne. Unikaj ogromnego service i powielania reguł między routerem/SQL. Nie dodawaj drugiego backendu, brokera, ORM eventów lub automatycznego registry.

W fazie C wolno użyć własnej jawnej factory **wyłącznie w tests/support**, prywatnego PG i testowego bootstrapu 0016→0017. Nie eksportuj tej factory do produkcji/wheel ani nie obchodź wspólnego readiness. Tymczasowy SQL fixture może przygotować własne role/granty i aplikację do probe, ale nie zastępuje późniejszego rzeczywistego provision i produkcyjnej integracji. Nie zmieniaj wspólnych conftest ani oczekiwanego head autora, aby uzyskać pozorną zieloną regresję.

## 3. Wymagania do odczytu i zamrożona semantyka

Przeczytaj całe WYMAGANIA_PROJEKTOWE, szczególnie WF10–12, 11.2/11.3/11.7 i KO04/14/22/25/26/27/29/31/32; AGENTS, ARCHITEKTURA, PLAN_PRAC, WORKFLOW, aktualny KOMUNIKACJA_AGENTOW, master koordynacji i E8.1+2, `docs/e8/INTERFEJS_PROJEKCJI.md`, decyzje motywacji oraz aktualne identity/profiles/diary/analytics/sync i SQL0016. Odczyt freeze nie jest odbiorem całego E8.1+2.

Nemesis używa celu `regularity_v1`: regularność i realizacja własnego historycznego celu; 0–2 punkty dziennie. Większy deficyt nie daje dodatkowych punktów, remis jest remisem. Okres to 7, 30 albo 90 kolejnych dat kalendarzowych, domyślnie 30. IANA zone jest jawnie proponowana i akceptowana, domyślnie Europe/Warsaw. Start to następna lokalna północ po accept, koniec to północ po ostatnim dniu. Nie dodawaj N×24h w UTC do wyznaczenia okresu. Deadline dosynchronizowania to UTC end_at + **30×24h**. Zmiana czasu zmienia liczbę rzeczywistych godzin, nie liczbę dat rywalizacji.

Wybory scope v1 są częścią dokładnych warunków zaproszenia. `regularity` jest obowiązkowe i obejmuje punkty/kompletne dni/dni w celu oraz odpowiednie liczności. `weight_change` i `mean_deficit` są niezależnymi opcjonalnymi booleans, domyślnie false. Obie strony zatwierdzają ten sam symetryczny scope; w v1 brak negocjacji lub zmiany scope aktywnego challenge. Nieznany scope, raw weight, meals lub arbitrary fields są odrzucane. Zmiana propozycji wymaga anulowania i nowego invite. Ranking opt-in jest osobną zgodą i nie jest warunkiem Nemesis.

Zamrożenie dla E8.4: masa używa reprezentanta każdego dnia wybranego jako ostatni żywy pomiar według `(occurred_at UTC, UUID)`, następnie pierwszego i ostatniego dostępnego dnia okresu w accepted zone. Wymaga co najmniej dwóch różnych dni. Nie wprowadzaj `measured_at`, gdy model/wire używa `occurred_at`, ani średniej/mediany z E9. Deficyt wymaga efektywnej kompletności i dodatniego historycznego **szacowanego zapotrzebowania E**, nie celu spożycia; jest średnią dziennych procentów `100×(E−intake)/E`. Dane potrzebne do tych wyników E8.4 utrwali w swoich projekcjach. E8.3 nie oblicza tych agregatów z bieżącego dziennika.

Kontrakt przyszłych agregatów odróżnia `hidden` (scope wyłączony), `insufficient_data` (scope uzgodniony, value null z counts) i dostępny wynik. Hidden nie zdradza counts lub dat obserwacji partnera. Wynik istniejący wyłącznie lokalnie lub jeszcze nieobliczony ma jawny stan, nigdy fikcyjne zero. Nie poszerzaj partner API o surową masę, E, goal kcal, posiłki, źródłowe UUID lub revision graph.

## 4. Prywatne adresowanie i ochrona przed spamem

Adresat sam wydaje kod do zaproszenia i świadomie przekazuje go wybranej osobie poza aplikacją. Kod ma co najmniej 256 bitów losowości z CSPRNG, jest opaque, jednorazowy, ważny maksymalnie 24h i przypisany do konta, generacji oraz epoki. Sam kod pozwala tylko skierować propozycję; nie daje zgody na statystyki/accept ani dostępu do danych. Brak publicznego lookup, wyszukiwania po email/pseudonimie lub odkrywania UUID przez ranking.

Tabela adresowania przechowuje digest, nie kod. Jedynie krótka własna odpowiedź issuance receipt może przechować kod potrzebny do lost-ACK replay, z ACL właściciela i retencją nie dłuższą niż ważność kodu; po niej pozostaje minimalny receipt bez kodu. Nigdy nie loguj kodu, body żądania, Authorization lub partner data. Kod jest w JSON body POST, nie URL/query. Odpowiedzi mają no-store, również błędy. Obrót/wycofanie kodu uniemożliwia przyszły create ze starym kodem; już utworzone invite zachowuje własny lifecycle i wymaga osobnego cancel. Issuance replay nigdy nie tworzy nowego kodu lub nie reaktywuje starego.

Wybrany kontrakt ma endpoint issue/rotate, który pozostawia najwyżej jeden ważny kod na ownera, i revoke bieżącego kodu. Rotacja jest nową operacją z nowym key. Create atomowo konsumuje ważny kod wraz z challenge i receipt; rollback nie konsumuje. Retry tego samego create korzysta z receipt, a nie próbuje ponownie użyć skonsumowanego kodu. Nie ujawniaj adresata przez odmowę nieważnego/wygasłego/wycofanego kodu; wspólny neutralny kod błędu i bez danych konta. Kod do własnego konta odmawia.

Limity są wspólne w PostgreSQL dla wszystkich replik, nie w pamięci pojedynczego procesu. Wersja v1: najwyżej 5 nowych kodów i 5 przyjętych nowych zaproszeń na nadawcę w ruchomych 24h, najwyżej 3 oczekujące outgoing oraz 5 incoming invite na konto. Dodatkowo najwyżej 20 prób create z nowym key na requester w 15min, także dla nieważnych kodów. Cancel/expiry nie refundują tempa ani nie pozwalają obchodzić limitu przez reset. Identyczny replay nie nalicza ponownie admission. Niepoprawny payload odrzucony przed DB nie konsumuje kodu; ścieżka prób nie może ujawniać ani blokować nieznanego adresata. Limiter/account locks mają ten sam udokumentowany porządek. Odpowiedź429 ma Retry-After i nie ujawnia liczby zaproszeń/aktywności partnera.

Admission próby z nowym key pozostaje trwale naliczone także przy invalid-code lub odmowie domenowej429, np. przez savepoint mutacji i commit odmowy/admission; nie rollbackuje razem z nieudanym create, a identyczny replay nie nalicza ponownie. Dowiedź tego realnym PG testem20 nieważnych prób z różnymi keys→odmowa21. próby oraz jej replay, bez challenge/code consumption.

Jeśli testy wykażą, że konkretna wartość limitu blokuje legalny restart lub expiry, popraw wspólnie regułę i dokumentację decyzji z uzasadnieniem; nie usuwaj ochrony spamowej. W tej grupie nie ma wiadomości, push notifications, email lub kontaktu z ludźmi.

## 5. Minimalny kontrakt HTTP

Pakiet routera ma docelowy prefix `/api/v1`. W fazie C tylko prywatna app factory montuje go do testów. Faza I generuje oficjalne OpenAPI z rzeczywistego FastAPI i porównuje wszystkie wymagane copies.

| Operacja | Zachowanie |
|---|---|
| `POST /me/nemesis/share-code` | Świadome wydanie/rotacja jednego kodu. UUID Idempotency-Key i aktualny X-Sync-Epoch; raw kod tylko we własnej odpowiedzi. |
| `DELETE /me/nemesis/share-code` | Idempotentne wycofanie bieżącego kodu przez właściciela. Ten sam kontekst epoki i key. |
| `POST /nemesis` | Body: destination_code oraz pełne terms: rule_version, duration_days, time_zone, scope. Wyraźnie zatwierdza zgodę zapraszającego. Owner/participant IDs i czasy pochodzą z serwera. |
| `GET /me/nemesis` | Własne invites/accepted/finished/cancelled metadata, live bounded strony limit1..100 i opaque cursor związany z requester/generation/epoch/purpose/TTL. Bez globalnego obcięcia historii i bez snapshotu prywatnych statystyk. |
| `GET /nemesis/{id}` | Metadata dokładnych warunków i aktualnego własnego uczestnictwa. Tylko uczestnik; brak wyników partnera przed accepted consent. |
| `POST /nemesis/{id}/accept` | UUID key, X-Sync-Epoch, cytowane revision If-Match; body powtarza dokładne accepted terms. Tylko adresat; atomowe recheck i dwa slots. |
| `POST /nemesis/{id}/cancel` | Ten sam kontekst, key i If-Match; body ma wąski reason enum. Nadawca wycofuje invite, adresat je odrzuca, każdy uczestnik wycofuje sharing także po end. |
| `GET /nemesis/{id}/statistics` | Fail-closed do E8.4. Nie liczy wyników na żywo. Późniejszy adapter zwraca wyłącznie uzgodnione agregaty ze spójnych Nemesis projections. |

Ścisłe DTO mają extra=forbid, bounded stringi/payload, poprawną walidację Unicode, IANA i canonical dat/czasów. Body pojedynczej operacji najwyżej 16KiB, response najwyżej 1MiB; nie przyjmuj dowolnej notatki z danymi medycznymi. Nie używaj UserConsent/OnlineReceipt z E3 jako nowych encji: ich strict body/operation constraints pozostają zgodne. Nie twórz siódmej encji sync-v1 lub nowych danych w dawnych snapshot/ACK.

Odpowiedź metadanych zawiera challenge UUID, revision, własną rolę inviter/invitee, aktualny status, terms, czasy zaproszenia/akceptacji/okresu/deadline, result_status i powód anulowania, jeżeli istnieje. Minimalny pseudonim drugiej strony służy rozpoznaniu invite; nie zwracaj jej account UUID/issuer/sub/email, nie utrwalaj niepotrzebnych kopii profilu w receipt. Po deletion/restore/cancel stosuj bezpieczne metadata bez partner statystyk i bez odtwarzania utraconych danych. Zgody wyłącznie na określoną parę i dokładne terms, nie globalny boolean.

Wszystkie chronione operacje weryfikują JWT i rolę user przed DB, potem własność, state, generation i epoch. Moderator/admin bez uczestnictwa nie ma dodatkowego dostępu. 404 dla cudzego prywatnego challenge; 409 dla stale revision/terms/key reuse/epoch lub koniecznego uzgodnienia; 422 dla błędnych danych; 429 limit; 503 jawna niedostępność. Nie odsyłaj partner state/activity w szczegółach błędu. Auth i visibility są sprawdzane ponownie także przy replay/read/cursor, a cached receipt nigdy nie przywraca zgody.

## 6. Lifecycle i blokady

Statusy DB/wire to wyłącznie `invited`, `active`, `finished`, `cancelled`. Expiry to `cancelled` z reason `expired`, nie dodatkowy status. Cancel jest terminalny; nie można ponownie accept lub reconsent tego samego challenge. Result_status jest nullable przed akceptacją/anulowaniem i `provisional` dla zaakceptowanych okresów; `final` pozostaje zarezerwowane dla E8.4. Po deadline w E8.3 finished nadal jest provisional z jawnym brakiem finalizacji, nie pozornie finalnym wynikiem.

Invite wygasa po dokładnie 7×24h od clock_timestamp przyjętego create. Accept wolno wykonać tylko przy DB clock wcześniejszym niż expires_at; dokładnie na granicy jest już expired. Nie polegaj na terminowym expiry workerze. Read/accept potrafią rozpoznać aktualny skuteczny status; bounded maintenance może utrwalić expiry/end, bez obliczania wyników.

Accept jest jedną transakcją. Najpierw bez blokowania kont rozstrzygnij issuer/sub principal i immutable participants zaproszenia. `require_account()` kończy się lock_account i **nie może blokować konta wywołującego przed posortowaną parą**. Następnie zablokuj wszystkie potrzebne user_accounts UUID ASC, wszystkie SyncCounter UUID ASC i cały zbiór właściwych challenges UUID ASC. Rewaliduj subject fence, oba active accounts/generations, bieżącą epokę, adresata, revision, terms hash, zgody, ważność, zgodność osi/strefy i wolne miejsca.

Wymuszenie najwyżej jednej aktywnej rywalizacji na uczestnika musi istnieć w PostgreSQL i przetrwać race A→B/B→A oraz dwa invite ze wspólnym uczestnikiem. Można zastosować osobną membership/slot tabelę z unique owner i prawidłowymi constraints, lecz nie liczyć wyłącznie SELECT COUNT poza lockiem. `active` rezerwuje slot od accept, także przed przyszłym start_at, aż do end_at/cancel. Dwóch uczestników i ich bindings są immutable, nie dają się podmienić body lub raw SQL update.

Od end_at rywalizacja jest finished/provisional i nie blokuje nowego accept. Zakończony wynik pozostaje do późniejszego E8.4. Jeśli maintenance nie uruchomił się na czas, nowy accept pod konto/counter locks identyfikuje poprzednie zakończone challenge, bierze ich locki razem z candidate w **jednym UUID ASC porządku**, rewaliduje czas i atomowo zwalnia slot. Nie blokuj najpierw candidate, a dopiero potem starszych records. Nie pobieraj peer account po challenge lock.

Po wszystkich wymaganych lockach pobierz DB clock do lifecycle decyzji; clock HTTP/klienta i transaction-start now() nie zastępują go. To czas lifecycle, a nie późniejszy qualified_at mutacji E8.4. Wybierz pierwszy rzeczywisty początek następnej lokalnej daty przy prawidłowym IANA roundtrip/offset/gap; DST i pominięte północe nie dodają fikcyjnych dat. Wszystkie daty okresu i UTC instants muszą być reprezentowalne w wspieranym kontrakcie; skrajny nieprzedstawialny okres odmawia przed mutacją. Nie zmieniaj shared time resolvera autora fazy1; własny adapter i niezależne oracle demonstrują zgodną semantykę.

Create dotykający nadawcy i adresata stosuje również pair account/counter locks UUID ASC; lookup digest kodu przed lockami jest wyłącznie rozpoznaniem immutable binding. Po blokadach ponownie sprawdza code/generation/epoch/TTL/consumption i limiter. Cancel/read dla jednego caller zaczyna od jego account/counter, potem challenge; jeśli przypadek naprawdę wymaga dwóch kont, wraca do pair order od początku. Maintenance expiry/end/finalizer przyszłego E8.4 nie biorą kont/counters po challenge. Helpers/triggers/FK nie mogą niejawnie odwracać porządku.

## 7. Receipt, revision i zgodność danych

Own Nemesis receipt obejmuje owner+operation+UUID key, hash canonical body wraz z If-Match/terms/epoch semantyką, accepted revision/status, generation i sync_epoch. Create/accept/cancel, share-code issuance/revoke są atomowe z receipt i właściwymi licznikami. Identyczny replay poprzedza zwykłą kontrolę bieżącej revision, ale nie obowiązkową kontrolę aktualnego auth/epoch/deleting/access. Zmieniony key body/header/terms daje409; replay nie przesuwa start/expiry, nie odtwarza kodu ani nie przywraca sharing.

Pełne odpowiedzi zwykłych operacji przechowuj minimum60×24h, bounded per operation i bez partner statystyk. Po sprzątaniu pozostaje minimalny receipt do usunięcia konta: key/hash/type/entity/revision/result code. Ponowienie po sprzątaniu nie wykonuje mutacji; zwraca minimalne already_applied albo jawny idempotency_result_expired, bez rekonstrukcji dawnej partner odpowiedzi. Wydany raw share-code receipt ma oddzielną krótką retencję do TTL kodu. Wygasłe response/cursor/code cleanup jest bounded, retry-safe i nie usuwa minimalnej ochrony przed ponownym create.

Faza C nie dopina shared append_change lub snapshots. Docelowa faza I używa account/counter serialization i online H markerów zgodnie z E3/E8, bez udawania siódmej wire entity; konkretne wspólne wywołanie należy do zwolnionego właściciela seam. W testach dowodź, że lifecycle source rows i receipts commitują razem, lost ACK jest bezpieczne, rollback zostawia poprzedni stan. Unknown SQL/deadlock/serialization nie są durable domain refusal lub accepted; kontrolowany bounded retry bierze nowe locki/czas, bez reuse czasu nieudanej próby.

Schema/constraints wymuszają valid enums, dwa różne participants, daty/period/deadline, revision monotonicity i immutable accepted terms oraz participant bindings. Nowa migration jest addytywna względem E0–E8.1+2, zasoby SQL są migration-owned. Nie importuj zmiennego runtime do Alembica, nie stosuj create_all w endpointach. Downgrade z niepustymi Nemesis danymi/receipts domyślnie odmawia atomowo przed DDL; nie wymazuje historii dla łatwego rollbacku.

## 8. Strefa, source seam i zakres E8.4

Przed accept oba żywe profile oraz faktyczny dziennik Meal/DiaryDay dla uzgodnionych dat muszą być zgodne z accepted zone. Sprawdź już istniejące dane przyszłego okresu, a nie wyłącznie profile; nie dokonuj automatycznego rebinning. Od accept do end_at blokuj zmianę strefy profilu; profile delete nie obchodzi reguły (w v1 odmowa do cancel/end, poza protocol deletion). Meal/DiaryDay dla dni rywalizacji oraz old/new dates przy move muszą zachować uzgodnioną oś. Nie zakazuj historycznych stref poprawnych Weight lub GoalVersion: daty immutable goal timeline pozostają zgodne ze wspólnym resolverem, a pomiary wagi dla Nemesis klasyfikujemy przez occurred_at do accepted zone, bez przepisywania źródłowego local_date/time_zone. Po end_at profile może zmienić zone, bez zmiany historycznych dat/provisional projections.

Implementuj własny `source_guard` i testy na zamrożonym SourceMutationContext. Faza C używa go jawnie w testowym source transaction, bez podłączenia do shared sync. Koordynator zwolni podłączenie w fazie I. Guard analizuje source_kind, profile/delete i całe affected_dates; `goal_axis_changed` oznacza pełną oś, nie wyłącznie goal probe boundaries. Przy weight zmianie przyszły E8.4 rozważa wszystkie właściwe owner challenges i odczytuje źródła ich okresów według occurred_at/accepted zone: sam union źródłowych local_dates nie może pominąć przesuniętej strefowo obserwacji, a context nie przechowuje starego UTC instant po overwrite. Jest to konserwatywna granica discovery dla projekcji E8.4, nie dodatkowy zakaz zapisu wag w E8.3. Context nie ma epoch/generation: pobierz je z poprawnie zablokowanego, już uwierzytelnionego kontekstu i utrwal własną provenance.

**Dokładnie jeden aggregate Nemesis SourceProjection posiada wszystkie challenge locks UUID ASC.** Inne extensions nie biorą challenge locków. E8.3 guard i E8.4 projection writer korzystają z tej jednej fazy lock, nie z dwóch niezależnie sortujących extensions. Wszystkie kwalifikujące walidacje i required locks kończą się przed SQL e8_refresh→DB qualified_at. Apply nie dobiera kolejnych challenge locków ani nie wykonuje IO/commit. Null kwalifikacji jest fail-closed, nie pozwala zapisać wyniku.

General motivation projections pozostają korygowalne i nie są zamrożonym wynikiem Nemesis. E8.4 będzie właścicielem własnej NemesisDayProjection, atomowej inicjalizacji w accept, source refresh do qualified_at≤deadline, finalizacji z własnych projections i późniejszych races KO22/26/27/29. E8.3 opisuje ten dependency contract i testowy adapter; nie tworzy tabeli ze stale zerowym wynikiem, asynchronicznego backfillu realnych rywalizacji lub pozornego finalizera. Błąd adaptera podczas testowego accept cofa aktywację/slots/consents/receipt w tej samej transakcji.

## 9. Activation, deletion, restore i uprawnienia

Produkcyjna bramka **create/accept/issuance oraz shared statistics jest zamknięta do odbioru E8.4**. E8.3 nie może otworzyć jej przez setting/env=true, body/header, uprawnienie user/admin, deploy0017 lub automatyczną registration. Jedno źródło prawdy w DB ma default-closed capability z epoką i zgodnymi, odebranymi rewizjami projector/finalizer. W0017 brak tych rewizji oznacza odmowę; późniejszy E8.4 określi zgodne wartości i kontrolowany odbiór, a zwykły caller nie wybiera rewizji w żądaniu. Issuance/create/accept oraz shared statistics ponownie sprawdzają DB capability wewnątrz transakcji, również przy bezpośrednim EXECUTE roli API; cancel/revoke i bezpieczne własne metadata wymagają aktualnych auth/epoch/access, lecz nie aktywnej capability. API/worker nie mogą surowo zmieniać control row ani nadawać capability. Bramka HTTP lub sam brak routera nie wystarczają. Testowy pełny lifecycle można odblokować wyłącznie w prywatnej test factory i prywatnym PG przez jawny fixture migratora ustawiający fake test capability; nie eksportuj takiego helpera do produkcyjnej aplikacji/pakietu ani nie grantuj runtime loginowi. Testowa konfiguracja nie stanowi produkcyjnego fallbacku lub dowodu E8.4. Cancel/revoke oraz własne bezpieczne metadata muszą pozostać dostępne dla istniejących challenge mimo zamkniętej bramki.

Implementuj własne funkcje/helpery revocation/deletion i opisz integration seam, ale nie zmieniaj teraz wrappera begin/confirm/purge E8.1+2. W fazie I begin deletion odcina dostęp partnerowi atomowo przy state/generation change; read/replay musi fail-closed dla obu inactive/deleting kont nawet przed purge. Nemesis helper blokuje właściwe challenges UUID ASC bez peer account lock po challenge. Purge usuwa prywatne bindings/zgody/kody/receipts i identyfikowalne dane ownera, pozostawiając co najwyżej bezpieczny cancelled marker potrzebny drugiej stronie. Zachowaj cały wrapper E8.1+2→E7→E6→E4, subject fences, cleanup intents i anonimowe AI counters. Nie nadawaj API general DELETE, nie resetuj konta.

Restore starszej kopii wymaga zatrzymanego traffic/workera i nowej epoki. Najbezpieczniejsza polityka v1: stare invited/active/finished challenge przechodzą w cancelled z reason restore albo są całkowicie unavailable do ukończenia tej operacji. Ich sharing nie wraca przez ponowną zgodę w starym challenge; użytkownicy tworzą nową rywalizację z nowymi warunkami i ID. DB control epoch mismatch natychmiast zamyka activation/shared read, nawet zanim bounded cancellation przejdzie całą historię. Stare receipt/code/cursor/generation nie pozwalają mutować ani odtworzyć zgody. Nie przesuwaj deadline, nie przeliczaj historycznego wyniku z odzyskanego później telefonu. Przywrócone opt-in rankingu i zgody AI mają własne wcześniejsze gates i nie są zmieniane.

Faza C posiada własne SQL resources i jawne ACL. PUBLIC EXECUTE oraz zbędne table/column privileges są revoke, search_path zamknięty, każda SECURITY DEFINER funkcja ma wąski zakres i preconditions. API nie przyjmuje caller-supplied ownership/score/role authority. Nie rozszerzaj AI/motivation/retention worker o prywatne Nemesis source/history. Lifecycle maintenance dostaje minimalną capability do expiry/end/receipt cleanup, nie do accept/zmiany zgód/wyników. Docelowe role/provision są podłączane dopiero po zwolnieniu wspólnych plików; w fazie C testuj własne minimalne LOGIN/SCRAM i jawny bootstrap na prywatnym PG. Sam SET ROLE nie zastępuje realnego login dowodu.

## 10. Własne dowody komponentu i późniejszej integracji

Własne testy mają rzeczywiście wykonać unit, ścisły kontrakt, HTTP z JWT/ownership, realPG17/migration/ACL, osobne connections/processes z barierami commit i race. Nie używaj SQLite, fixed sleeps jako dowodu ani skips jako PASS. Kontrolowany czas DB i niezależne oracle nie mogą być caller-supplied clock produkcyjnego API.

Minimum fazy C:

1. Share-code entropy/digest/TTL/rotation/revoke, self-invite/unknown code bez identity leak, single consumption z rollback/lostACK, expiry response retention, no-store i brak kodów w logach/errors.
2. Limiter między dwiema replikami/processami, durable rolling caps, replay bez ponownego admission, cancel bez refund, receiver cap bez ujawnienia prywatnego stanu; bounded cleanup i legalna kontynuacja.
3. A/B/C, participant forgery, moderator/admin, wrong issuer/audience/signature/ID token, stale generation/epoch, cudzego cursor/challenge/receipt denial. Mock lub własne podpisane JWT nie są opisywane jako realny Keycloak.
4. Create/accept/cancel exact terms i If-Match, scope extra/unknown rejection, lostACK/retry/mismatched key, permanent minimal receipts po60d, revoke/cancel kontra replay bez regrant.
5. Dwa accepts A→B/B→A i A→B/C→B, account/counter/challenge order pod realną konkurencją, jeden active slot dla każdego, rollback po slot/consent/projection-init adapter failure. Brak wcześniejszego caller lock przez require_account.
6. Invite dokładnie7×24h, accept przed/na/po expiry, delayed maintenance; start w następnej lokalnej dacie, także accept dokładnie midnight; okresy7/30/90, Warsaw23/25h, nietypowa północ/skipped date/skrajny zakres. End opóźnionego workera zwalnia możliwość następnego accept.
7. Cancel/read/accept z barierami, revoke w active oraz finished/provisional, access odcięty po commit, wcześniej pobranych danych nie obiecujemy cofnąć. Żadnych raw partner source fields w payload/receipts/errors.
8. Profile i source timezone guard z old/new dates, existing future axis conflict, offline stale change, profile delete; shared SourceMutationContext immutable/provenance oraz jeden aggregate lock plan. Testowy source failure cofa również źródło, projekcję motywacji/change/receipt w prywatnym harnessie.
9. Deleting obu uczestników przed purge i races z begin helper, minimalna własna purge helper/powiązane cursor/code/receipt denial; restore copied opt-in/withdrawal/active state z nową epoką fail-closed, cancellation przed reopen, stare challenge nie reaktywuje się.
10. Pusta i wypełniona0016→0017, rollback migracji przed DDL, restrykcje raw SQL/PUBLIC/column grants/realLOGIN, wheel/sdist/installed source resources własnego pakietu, bounded duża historia/cursor/batches i zachowane wcześniejsze źródła. Test-only factory/bootstrap nie wchodzą do runtime.
11. Produkcyjny default bez test capability blokuje create/accept/statistics niezależnie od admin/header/config próby; own cancel/revoke pozostaje wykonalne. Brak routera w main fazy C nie jest sam wystarczającym testem gate DB/service.

Po zleceniu fazy I dodatkowo wykonaj właściwą pełną regresję E0–E8.1+2, realną aplikację z generowanym OpenAPI, instalację pakietu i zgodną readiness, produkcyjny chain deletion/provision/restore, źródłowe sync/savepoint/epoch/race i publiczną bramkę nadal closed. E8.4 KO22/26/27 oraz pełny KO29 nie są zaliczone samym lifecycle; dokumentuj tę granicę.

Nieautor sam uruchamia ważny nowy zakres na swoim zamrożonym source i własnych usługach/PG/processach, z niezależnymi oczekiwaniami. Ocena≥9/10 i zero otwartych istotnych P1/P2. Istotna zmiana source/head dostaje nowy odbiór właściwego zakresu, reprodukcję przed/po i sprawdzenie dowodów; nie sumuj powtórek. Własne usługi zatrzymaj, cudzych nie dotykaj.

## 11. Git, CI, komunikacja i dostawa

Publikuj po ważnym zweryfikowanym kroku: review diff, diff-check, właściwe testy, lokalna tożsamość Agent2, commit `agent 2: ...`, push własnego branch i jeden draft stacked PR. Do opisu wpisz exact dependency/start/head/base, etap C/I,0017, zgodność, faktycznie wykonane testy i niepodłączone wspólne granice. Nie używaj starego PASS upstream jako dowodu nowego source.

**Aktualny Project CI uruchamia pull_request do main i push main, bez workflow_dispatch.** Draft stacked PR do gałęzi motywacji nie ma pełnego Project CI. Nie twórz workflow obejścia, zastępczego dispatch lub zielonych pustych jobów. Lokalne testy i component review nie są zdalnym CI. Po merge upstream/retarget/main merge wymagane są rzeczywiste osiem wyników exact final head/base; agregator oraz brakujące/skipped kontrole muszą być sprawdzone przez koordynatora. Nie scalaj własnego PR.

Jedyny dziennik to KOMUNIKACJA_AGENTOW; rezerwacja **O2-026** dla E8.3. W fazie C jest to uzgodnione uzupełnienie istniejącego numeru po zwolnieniu wpisu przez koordynatora; nie edytuj całej tablicy lub cudzych wpisów. Przed końcowym push przeczytaj aktualne main/komunikację i preserved handoffs. Wspólne docs file koordynuj podczas równoległości, nie nadpisuj snapshotem sprzed zmian. Nie twórz drugiego dziennika.

Dokumenty dostawy mają nagłówki `- osoba 2`, czytelne pełne zdania i spacje. DECYZJE oraz INTERFEJS zapisujesz przed runtime: terms/scopes/timezone, addressing/privacy/limits, DB invariants, lock order, capabilities/gate, receipts/epochs, exact integration owners i E8.4 dependency. RAPORT rozróżnia **E8.3-C odebrane**, **E8.3-I oczekujące/zintegrowane** i **public activation zablokowana do E8.4**. RECENZJA zawiera source manifest, własne próby nieautora i ograniczenia. O1 dostaje ekrany świadomego scope/codes/accept/cancel/provisional/null/hidden oraz izolację cache/requestów po zmianie konta. O3 dostaje minimalne roles/ACL, migration/CLI/maintenance/restore cancellation/gate i obserwowalność bez prywatnych payloadów. Te przekazania nie zaliczają ich wykonania.

Właściciel zlecił trzy czaty E8 oraz ich odpowiedzi koordynatorowi `01a12156-2312-7c43-aedc-1858e782e5fb`. Zlecenie startowe koordynatora wskaże bezpośrednią ludzką autoryzację tego przekazania. Rzeczywisty blocker/freeze/wynik zgłoś temu czatowi; final + wait_threads także wystarcza. Nie wysyłaj wiadomości do innych ludzi/czatów bez autoryzacji i nie twórz następnego natywnego czatu E8.4. Subagenci wewnątrz zadania mogą pomóc przy testach i niezależnym odbiorze z jednym właścicielem pliku, według mastera koordynacji.

Zakończ konkretnym branch/head/base/PR, stanem migracji/compatibility, lokalnymi i nieautorskimi dowodami, rzeczywistym stanem CI oraz następnym krokiem koordynatora. Żaden component/backend PASS nie oznacza pełnego E8 ani odbioru użytkownikowego APK, WorkManager, produkcji lub O1/O3. Faza I wraca do tego samego czatu po finalnym E8.1+2; aktywację i projekcje dopiero później zwalnia koordynator E8.4.
