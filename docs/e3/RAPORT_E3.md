# Raport realizacji etapu E3 - osoba 2

Data: 10 października 2026 r. Autor: Agent 2 / O2.
Odbiorcy: właściciel projektu, Agent 1 / O1 i Agent 3 / O3.

**E3 jest zaimplementowane i przeszło lokalny odbiór funkcjonalny.**
Wykonano 357 testów jednostkowych, 297 integracyjnych na PostgreSQL 17
oraz 7 rzeczywistych testów Keycloak/PKCE: łącznie **661 PASS**, bez skipów.
Niezależny recenzent sam odtworzył istotne scenariusze, w tym realne tokeny.
Wynik jest opublikowany w [PR #11](https://github.com/Roseru/aplikacja-mobilna/pull/11).
Wymagane zdalne CI commita implementacji zakończyło się sukcesem, także
rzeczywisty PKCE i oba przebiegi obrazu. E3 pozostaje do osobnego odbioru.

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

Dodano `0006_e3_identity` i `0007_e3_diary` po odebranym
`0005_ration_cursors`. Nie edytowano migracji 0001–0005.
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

## Wykonane testy i odtworzenie

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

## Niezależna recenzja

Recenzent review_e3 nie był autorem implementacji. Przeczytał aktualny diff,
kontrakty i model O1, sam uruchomił testy unit, osobną bazę PostgreSQL,
realne PKCE i wheel poza repo. Poprawiono jego uwagi dotyczące niezmiennej
własności, blokady deleting w surowym SQL dziennika, cykli/spójności osi,
osiągalnego błędu revision_exhausted i spójności dokumentacji.
**Końcowa ocena: 9,4/10; brak nierozwiązanych istotnych usterek.** Recenzent potwierdził też spójność końcowej dokumentacji. Ocena dotyczy niezależnego odbioru technicznego; zdalne CI i obraz dodatkowo potwierdził autor po publikacji.

## Przekazanie i Git CI

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
