# Raport realizacji etapu E3 - osoba 2

Data: 10 października 2026 r. Autor: Agent 2 / O2.
Odbiorcy: właściciel projektu, Agent 1 / O1 i Agent 3 / O3.

**Poprawka E3 dotycząca DELETE jest zaimplementowana i sprawdzona lokalnie.**
Nowe wykonanie: **707 PASS**, bez skipów — 357 unit, 343 PostgreSQL 17.11
(w tym 46 przypadków poprawki) oraz 7 rzeczywistych Keycloak/PKCE.
Osobny odbiór head 479b6ce ujawnił brak ochrony DELETE; poprzednie 661 PASS
oraz ocena 9,4/10 nie obejmowały tego przypadku i nie stanowią odbioru poprawki.
Bieżące dowody i niezależną ocenę opisuje poniższa sekcja korekty.

## Baza i zachowana praca

Gałąź: `codex/backend-e3-tozsamosc-profile`, utworzona z aktualnego
main `0ff4b4cd59f8b9dbced66dab95225683c393c2ca`.
Zweryfikowano akceptację O3/Roseru E2 na head `c5330ad` i merge PR #4
`fcfb2097937f7ba8edbef35ee9e12dcba63386df`. Historyczna blokada wejściowa
została usunięta. PR #5, #8 i Android do #9 są scalone.

Punkt odniesienia O1: Android **0.7.1 / Room 6**, scalony PR #9.
Wykorzystujemy dostarczony model bootstrapu i dokładne redirecty O1.
Nie scalano gałęzi O1 w ramach E3 ani nie zmieniano Androida.

Zachowano zastane nieśledzone master prompty E1/E2, `.review-o2/`
i dane `Random Data/`. Poprzedni lokalny raport zachowano jako
[RAPORT_PRZYGOTOWANIA_E3.md](RAPORT_PRZYGOTOWANIA_E3.md), a
[PRZYGOTOWANIE_E3.md](PRZYGOTOWANIE_E3.md) pozostaje historycznym
zapisem analizy. Nie usuwano wolumenów ani prywatnych danych użytkownika.

## Wdrożone zachowanie

| Operacja pod /api/v1 | Wynik |
|---|---|
| POST /me/bootstrap | Bez body; UUID Idempotency-Key. Tożsamość z tokenu, konto i zgody false atomowo, stały wynik ponowienia |
| GET /me | Własny profil albo null, zgody, account_id, epoka i rewizja osi |
| GET /me/goals | Własne niezmienne wersje, stabilny snapshot stron i brak danych jako pusta lista |
| PUT /me/consents | Wymagane dwa booleany, klucz UUID i cytowane If-Match; trwały replay przed bieżącą revision |
| POST /energy-estimates | Dokładny mifflin_pal_v1 bez ustawiania celu/deficytu i bez Gemini |
| GET /products | Tylko opublikowany official, wyszukiwanie nazw/aliasów/marki/wariantu i snapshot stron |
| GET /products/{id} | Najnowsza dozwolona lub dokładna opublikowana revision; niedostępna daje 404 |

Każda chroniona operacja wymaga access tokenu RS256, dokładnego issuer,
audience calorie-api, sub, exp/iat, typ=Bearer oraz roli user z klienta API.
nbf jest opcjonalny i walidowany, jeśli występuje. Lifetime tokenu wynosi
najwyżej 300 s, skew 60 s. ID token i token przeznaczony tylko dla Androida
są odrzucane. Role Androida/realmu nie przyznają roli API.

Przed bootstrapem odczyty, kalkulator i zgody zwracają
403 account_bootstrap_required. Każde żądanie i replay sprawdzają DB.
Wspólna blokada konta chroni mutację/receipt przed deleting;
moderator/admin nie omija właściciela. Nie ma PATCH me, POST me/goals,
prywatnych HTTP zapisów ani pozornego push/pull.

Bootstrap zachowuje pierwotny server_time. Zmiana epoki/generacji blokuje
stary klucz kodem 409 z kontrolowanym details; nowy klucz zwraca bieżący
kontekst tego samego konta bez resetu zgód. deleting zawsze daje 403.
Pełna odpowiedź zgód jest przechowywana co najmniej 60 dni; po sprzątaniu
minimalny receipt pozostaje i nie pozwala odtworzyć mutacji.

## Architektura i model prywatny

Adapter `integrations/keycloak` odpowiada wyłącznie za zaufany JWKS
oraz weryfikację tokenów. Nie pobiera URL z JWT, nie podąża za redirectami,
nie loguje tokenów. Cache ma ograniczone TTL, rozmiar i liczbę kluczy;
równoległe i nieznane kid nie powodują nieograniczonego fetchu ani pamięci.
Świeży znany klucz działa podczas awarii, wygasły wymaga dostawcy.
Weryfikacja kończy się przed transakcją DB.

Moduł identity obsługuje konto, principal, trwałą epokę, blokadę i receipts;
profiles profil, oś celów, zgody i kalkulator; diary prywatne agregaty.
Router tłumaczy HTTP, usługa utrzymuje reguły, a caller zatwierdza transakcję.
E4 może atomowo dołączyć własne liczniki i ChangeLog do tych samych mutacji.

DB wymusza jednego żywego profilu, złożone FK właściciela celu/posiłku,
unikalny owner+local_date i niezmienną strefę dnia. Meal ma 1..100 składników,
pełny snapshot i opcjonalną dokładną referencję produktu. Usunięcie ostatniej
pozycji daje tombstone agregatu; nowy katalog nie przelicza historii.
Waga pozwala na wiele pomiarów dziennie; prywatny szkic nie staje się
publicznym produktem. Brak danych pozostaje null, a zero jest znaną wartością.

Cele są niezmiennymi wersjami z rewizją osi. Korekty zachowują pierwotne
wiersze i referencje historii, a aktywna oś wybiera końcową korektę.
DB sprawdza spójność payloadu z kolumnami, kolejność osi i wcześniejszy
cel korekty, odrzucając cykle i uzupełnianie dawnych dziur snapshotu.

Decimal wejściowy ma do 6 miejsc, kalkulator do 12; zakresy i NaN/Infinity
są sprawdzane również surowym SQL. Czas UTC, IANA/local_date i DST są
walidowane semantycznie. Dane IANA `tzdata==2026.5` są jawnie zależnością
runtime na wszystkich platformach, także w obrazie bez systemowych stref.

Tokeny gp1/pp1 wiążą konto, generację, epokę i parametry, zachowując
pierwotny TTL 60 min. Produkty przypinają niezmienny release, cele granicę
niezmiennej osi. Nowe strony nie tworzą rekordów snapshotów ani tombstones.
Publiczny kursor rp1 E2 pozostaje osobnym protokołem.

## Migracje i kompatybilność

Początkowe E3 dodało `0006_e3_identity` i `0007_e3_diary` po
`0005_ration_cursors`; poprawka dodaje `0008_diary_delete`. Migracje
0001–0007 pozostają nieedytowane.
Upgrade zachowuje konta E2 i tworzy ich domyślne zgody, katalog, sealed
wersje, dowody recovery, publikacje, bajty i hashe. API/worker nie mają DDL,
rotacji epoki ani nowych uprawnień operatora katalogu. Nowe granty są jawne.

Epoka singletonu powstaje w migracji i przetrwa restart/repliki. Downgrade
odmawia niszczenia istniejących prywatnych danych. Pełny protokół usunięcia
Keycloak/danych/receipts i uzgodnienie po restore są osobnymi zadaniami E4,
wymaganymi przed wydaniem; samo active/deleting ich nie zastępuje.

## Rzeczywisty Keycloak i PKCE

Uruchomiono oficjalną dystrybucję **Keycloak 26.8.0** na portable
**OpenJDK 25.0.4.1**. ZIP Keycloak sprawdzono przez SHA-256
`7ed1de3fda2598369262613bf682aab7e233d80a38c405e91588f7a7454370a1`.
Dystrybucję/źródło/sumę przypina lockfile w infra/local/keycloak.
Provider używa izolowanych efemerycznych danych H2, a backend rzeczywistego
PostgreSQL 17; nie wykorzystywano produkcyjnych credentiali.

Test odtwarza prawdziwy formularz logowania i cookies, state/nonce,
Authorization Code z PKCE S256 i wymianę code/verifier. Sprawdza A/B,
bootstrap/replay, odczyty i zgody, ID token, audience wyłącznie Android,
zły verifier, ponowne użycie code, brak PKCE, password grant i niedozwolone
redirecty. Nie korzysta z password grant jako skrótu do logowania.

Próby wykryły i naprawiły rzeczywiste różnice integracyjne: zachowanie
Secure cookies loopback i potrzebę scope basic dla claimu sub. Backend
nie osłabia wymagań tokenu, a harness sprawdza dokładny redirect błędu OAuth.
Dane logowania, code/verifier i tokeny są efemeryczne oraz redagowane w testach;
procesy harnessu mają identyfikację i bezpieczny stop własnego runtime.

To dowód integracji backendu, nie logowania APK. Dokładne callbacki O1
są w realm, lecz mobilny handler/HTTP i produkcyjny issuer pozostają
odrębną integracją O1/O3. Szczegóły w [instrukcji Keycloak](../../infra/local/keycloak/README.md).

## Wykonane testy pierwotnego E3 i odtworzenie

Środowisko: Python 3.13.9, uv 0.9.5, PostgreSQL/psql 17.11,
PyJWT 2.15.1, cryptography 50.0.2, tzdata 2026.5. Stos jest przypięty w uv.lock.

| Wykonawca | Zakres | Wynik |
|---|---|---|
| O2 root | Pełne unit E1/E2/E3 | 357 PASS, 19.91 s |
| O2 root | Pełne integration E1/E2/E3 na PostgreSQL | 297 PASS, 242.80 s |
| O2 root | Rzeczywisty Keycloak/PKCE | 7 PASS, 3.35 s |
| Niezależny review_e3 | Pełne unit po poprawkach | 357 PASS, 21.78 s |
| Niezależny review_e3 | Istotne scenariusze E3 na osobnej bazie PostgreSQL | 110 PASS, 179.08 s |
| Niezależny review_e3 | Rzeczywisty końcowy realm Keycloak/PKCE | 7 PASS, 5.24 s |
| O2 root i recenzent | Installed wheel Python -I poza checkoutem | PASS, domain/IANA bez OS TZPATH, kalkulator i routery |
| O2 root | sdist/wheel, OpenAPI, Ruff | PASS, 84 pliki lint/format |
| O2 root i recenzent | Walidator E0 | PASS: 5 schematów, 5 draft + 11 generated, 99 HTTP; 67 valid / 20 invalid / 18 scenarios, 16 Decimal, 156 linków |

Zachowano regresję E1/E2: recovery timestampów, niezmienne bajty i hashe,
bounded pagination, migracje oraz importer SQLite. Nowe testy obejmują
A/B, złe podpisy/claims i rotację JWKS, rollback/utraconą odpowiedź,
równoległe klucze, rzeczywiste oczekiwanie na blokadę, epoch/generation,
retencję i brak powtórnej mutacji, raw SQL, DST, granice NUMERIC oraz
snapshoty przy zmianie osi i publikacji. Nie było skipów.

Jedno ostrzeżenie pochodzi z przejściowej integracji Starlette TestClient
z HTTPX; nie dotyczy błędnego wyniku i nie jest wyciszone. Poprzednie
nieudane próby i problemy środowiska tymczasowego nie są zaliczane do PASS.

Odtworzenie z przygotowaną dedykowaną bazą *_test:

```text
uv sync --project backend --locked
uv run --project backend --locked python -m pytest backend/tests/unit
uv run --project backend --locked python -m pytest backend/tests/integration
uv run --project backend --locked python backend/export_openapi.py
uv run --project backend --locked ruff check --config backend/pyproject.toml backend tools/offline_catalog
uv run --project backend --locked ruff format --check --config backend/pyproject.toml backend tools/offline_catalog
uv run --project tools/contracts --locked python tools/contracts/validate.py
uv build backend
```

TEST_DATABASE_URL musi wskazywać PostgreSQL 17 i dedykowaną bazę *_test;
fixture odmawia czyszczenia innych baz. Polecenie rzeczywistego PKCE,
JDK/start/stop i dane środowiska są w instrukcji Keycloak. CI wymaga tego
jobu i nie dopuszcza zielonego skipu przy braku usługi.

## Niezależna recenzja pierwotnego head

Recenzent review_e3 nie był autorem implementacji. Przeczytał aktualny diff,
kontrakty i model O1, sam uruchomił testy unit, osobną bazę PostgreSQL,
realne PKCE i wheel poza repo. Poprawiono jego uwagi dotyczące niezmiennej
własności, blokady deleting w surowym SQL dziennika, cykli/spójności osi,
osiągalnego błędu revision_exhausted i spójności dokumentacji.
Historyczna ocena pierwotnego head wynosiła 9,4/10. Późniejszy osobny odbiór wykazał pominięty przypadek DELETE; świeże testy i ocena 9,5/10 korekty są w sekcji poniżej. Dowody CI tego pierwotnego head zachowano jako historię.

## Przekazanie i CI pierwotnego head

[Integracja O1](INTEGRACJA_O1.md) odpowiada Androidowi 0.7.1 / Room 6:
mapowanie bootstrapu bez przepisywania UUID/outbox, rozdzielenie liczników,
kolejność odczytów, nullable/Decimal, zgody i błędy. [Konfiguracja O3](KONFIGURACJA_O3.md)
opisuje role, migracje, epokę, retencję, JWKS i odtwarzalny test Keycloak.
Wynik jest przekazywany w jedynym wspólnym dzienniku z nowym ID O2.

Commit implementacji: `47d4bcc4c888f6cb22b0733bafa714430f76b602`,
`agent 2: wdroż E3 tożsamości profili i rzeczywistego PKCE`.
[PR #11](https://github.com/Roseru/aplikacja-mobilna/pull/11) jest otwarty,
skierowany do main, bez merge. [CI 38078335230](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38078335230)
ma completed/success dla tego head: contracts, quality, postgres,
keycloak-pkce i ci-required zakończyły się sukcesem.

Autor odczytał metadane i logi wszystkich czterech jobów. Checkout wskazuje
merge candidate `8c413dc` z dokładnym head `47d4bcc` i main `0ff4b4c`.
Na Linux/Python 3.13.16 wykonano 357 unit (6.09 s), 297 PostgreSQL 17.11
(23.71 s) i 7 rzeczywistych PKCE (4.95 s), bez skipów. Logi potwierdzają
pobranie przypiętego Keycloak 26.8.0, wheel/sdist i installed wheel,
84 pliki Ruff, kontrakty oraz build/smoke obrazu z wymuszonym fallbackiem
IANA. Job postgres wykonał także rzeczywisty eksport/import w obrazie,
fractional timestamp release 2, porównanie zachowanych bajtów release 1,
import SQLite i cleanup CLI. Lokalnie Docker nie był dostępny; dowód obrazu
pochodzi z tego rzeczywistego CI.

Po dopisaniu raportu i PR do przekazania końcowy head przechodzi ponownie
wszystkie wymagane kontrole. Bieżący head i najnowsze wyniki są w zakładce
Checks PR #11; autor potwierdza je także w odpowiedzi końcowej.
Własne procesy Keycloak/PostgreSQL i utworzona efemeryczna baza recenzenta
zostały posprzątane; istniejące bazy i źródła zachowano.
Nie scalono E3 ani nie rozpoczęto E4.

## Korekta DELETE po osobnym odbiorze

Źródło: [uwaga odbioru](https://github.com/Roseru/aplikacja-mobilna/pull/11#issuecomment-6101355087)
i oceniony head 479b6ce. Fizyczny DELETE runtime omijał blokadę deleting
oraz pozwalał usunąć Weight tombstone i odtworzyć ten sam UUID/base_revision=0.
Dotyczyło to ACL/SQL, bez stwierdzenia osiągalnego exploitu obecnego HTTP.

Dodano wyłącznie nową migrację `0008_diary_delete` po 0007; migracje
0001–0007 i wspólne guardy pozostały bez zmian. API/worker tracą zbędny
DELETE diary_days/meals/weights/product_drafts. DELETE meal_items pozostaje
potrzebny do wymiany, ale nowy guard OLD blokuje konto i rodzica, wymaga
active i żywego posiłku, zwraca OLD. Chroni także snapshot tombstone posiłku.
Readiness wymaga 0008. Szczegóły kolejności i downgrade są w instrukcji O3.

Downgrade zachowuje ochronę i dane zamiast przywracać wadliwe granty;
operator otrzymuje widoczny komunikat. Ponowny upgrade nie zmienia wierszy.
Nie wdrożono pełnego usuwania konta ani retencji E4 i nie dodano obejścia
workera. Nie zmieniano Androida, workflow PR #10 ani danych Random Data.
Aktualny main przy rozpoczęciu/odczycie pozostawał 0ff4b4c; merge nie był potrzebny.

| Weryfikacja poprawki wykonana przez root | Wynik |
|---|---|
| Pełna regresja unit | 357 PASS, 11.90 s |
| Pełna regresja PostgreSQL E1/E2/E3 | 343 PASS, 103.97 s |
| Nowe przypadki poprawki w tej regresji | 46 PASS: obie role, ACL/SQL, tombstones, blokady, agregaty, upgrade/downgrade i jawny stdout |
| Rzeczywisty Keycloak 26.8.0 / JDK 25, nowy izolowany realm | 7 PASS, 3.26 s |
| Ruff / OpenAPI / resources / kontrakty | PASS, 86 plików Ruff; OpenAPI bez zmian |
| sdist/wheel i installed wheel Python -I poza repo | PASS, także wymuszony brak OS TZPATH |

Testy rzeczywistych uprawnień rozróżniają poprawny setup od odrzuconej
operacji: has_table_privilege i działające SIU, SQLSTATE 42501/23514,
rollback przed odczytem, niezmienny UUID/revision i odmowa odtworzenia.
Wymiana została przerwana dopiero po rzeczywiście wykonanym DELETE i
przywróciła pełny poprzedni agregat. Ostatni składnik daje tombstone ze
snapshotem. Dwa połączenia/obie kolejności i pg_blocking_pids dowodzą
blokowania; NOWAIT rodzica wykrywałby odwrócenie triggerów.
Upgrade oryginalnego 0007 porównuje wszystkie wiersze 26 tabel, epokę,
receipts, tombstones, katalog, gzip/manifest i opublikowane bajty/hash.

Niezależny `review_delete_fix` nie jest autorem migracji ani testów.
Sam wykonał **156 różnych testów E3 PASS** (153 oraz 2 po poprawieniu
wyłącznie katalogu tymczasowego i 1 nowy rzeczywisty test stdout downgrade) i **12 własnych grup SQL/probe PASS**
na osobnej bazie PostgreSQL 17.11, bez skipów. Odtworzył obie role,
rollback/recreate, blokady i downgrade/reupgrade. Wykrył P3: warning
logging Alembica był niewidoczny; po poprawce print_stdout sam potwierdził
widoczny komunikat. **Ocena korekty: 9,5/10, bez istotnych nierozwiązanych
usterek.** Nie przypisujemy recenzentowi pełnej regresji E1/E2 ani PKCE/CI.

Commit poprawki: `a7520bf1e7b297aa097fb86411444e466b92a8c9`,
`agent 2: zabezpiecz DELETE dziennika po odbiorze E3`. Istniejący
[PR #11](https://github.com/Roseru/aplikacja-mobilna/pull/11) pozostaje otwarty.
[CI 38081956260](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38081956260)
ma completed/success dla exact head a7520bf: contracts, quality, postgres,
keycloak-pkce i ci-required. Root odczytał metadane i logi czterech jobów:
checkout ccd12b0 = a7520bf + main 0ff4b4c, Python 3.13.16 / PostgreSQL 17.11,
357 unit (9.26 s), 343 PostgreSQL (30.01 s), 7 real PKCE (4.67 s), bez skipów.
Wheel/sdist, installed-I smoke i oba build/smoke obrazu są zaliczone;
obraz wykonał także rzeczywisty eksport/import SQLite, bajty E2 i cleanup.
Końcowy commit tego raportu przechodzi ponownie wszystkie wymagane kontrole;
bieżący head/CI są w Checks PR #11 i w odpowiedzi końcowej autora.
Historyczne logi poprzednich head w sekcjach wyżej pozostają opisane jako
poprzednie wykonania. E3 pozostaje do osobnego odbioru, bez merge/E4.

Własne procesy Keycloak i izolowanego PostgreSQL poprawki zatrzymano po testach. Istniejących baz i źródeł nie używano ani nie usuwano.
