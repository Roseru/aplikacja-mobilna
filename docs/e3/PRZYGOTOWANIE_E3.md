# Przygotowanie E3 i zależność wejściowa - osoba 2

Data: 2026-10-10. To wynik przygotowania, nie raport ukończenia E3.

## Potwierdzony stan

Przeczytano cały `docs/MASTER_PROMPT_E3.md`, wymagania, workflow,
architekturę, plan i kontrakty E0. Pobrano origin. `origin/main`:
`151885d3f728c47240a7087ff862ba5f61ea7403`, bez E2. Lokalna gałąź
main pozostaje na `a79b0732df71955ebf893391cc767805be674ed0`.
Checkout pozostaje na `codex/docs-plan-e3`; zastane nieśledzone
`docs/MASTER_PROMPT_E2.md` i `docs/MASTER_PROMPT_POPRAWKA_E1.md` zachowano.

PR #4 jest otwarty, head `52f3547f47bcfae1080aa1e9720b1f37a1ef6b88`.
GitHub zwrócił pustą listę recenzji i wątków recenzji.
Run 38042927890 ma status completed/success. To dowód CI E2,
nie testy E3 ani akceptacja innej osoby. Brak wymaganej recenzji
blokuje merge E2 i przygotowanie wymaganej bazy implementacji E3.
PR #5 i #8 również są otwarte; ich dokumenty czytano na wskazanych
commitach, bez scalenia gałęzi O1 i bez tworzenia drugiego dziennika.

Zgłoszenie O3 opublikowano w
[komentarzu PR #4](https://github.com/Roseru/aplikacja-mobilna/pull/4#issuecomment-6097999046).
O3 zapewnia recenzję innej osoby; O2 sprawdzi ponownie aktualny head,
CI i uwagi przed upoważnionym scaleniem. Następnie pobierze main
i utworzy `codex/backend-e3-tozsamosc-profile`.

Odczytano komunikację O1-002 i O1-005–007 oraz raport i LocalOwners.kt
Androida `ad8c0a6`, wersja 0.6 / Room 5. Lokalne owner UUID i lease
nie są account_id ani serwerową generacją. Potrzebne będzie jawne
mapowanie po bootstrapie, bez zmiany historycznych UUID/outbox.
Testów O1 nie wykonano w tej sesji.

## Plan implementacji po odblokowaniu

1. `integrations/keycloak`: ścisła weryfikacja access tokenu RS256,
   issuer/audience/sub/exp/iat, opcjonalnego nbf, typ=Bearer i ról API;
   ograniczony cache JWKS oraz koordynowane odświeżanie.
2. `modules/identity`: jedna definicja konta, principal, trwała epoka,
   bootstrap i receipts; wspólna blokada konta do commit także dla deleting.
3. `modules/profiles`: profil, niezmienna oś celów, zgody i kalkulator;
   `modules/diary`: agregaty i usługi prywatne, bez prywatnych HTTP zapisów.
4. Migracja po 0005 zachowująca dane E2; composite FK własności,
   ograniczenia NUMERIC/revisions i minimalne granty DB.
5. Chronione produkty official i snapshot paginacji z owner/generacją/epoką.
6. Rzeczywisty Keycloak Authorization Code + PKCE S256 A/B, wymagany w CI;
   regresja E1/E2, PostgreSQL 17, migracje, wheel i obraz.
7. Niezależna recenzja bieżącego diffu z samodzielnym odtworzeniem scenariuszy;
   poprawki do minimum 9/10 bez istotnych usterek, raport i przekazanie O1/O3,
   commit/push/PR do main oraz CI ostatniego head. Bez merge E3/E4.

## Ustalenia niezależnego preflight kontraktów

Subagent `preflight_contracts` przeczytał cały plan i istniejące kontrakty,
nie zmieniał plików. Jest to analiza, nie końcowa recenzja implementacji.

- Rozszerzyć Error.code o account_bootstrap_required, sync_epoch_changed
  i account_generation_changed; zachować kontrolowany format details.
- Dodać maksimum 2147483647 dla ProfileRead.goal_timeline_revision.
- Publiczny kursor E2 rp1 nie spełnia wymagań stron chronionych E3.
- Spakować domain schema i IANA runtime do wheel; runtime nie może czytać
  plików z checkoutu tools/contracts.
- Rozszerzyć test_catalog_contract.py na rzeczywiste auth E3 i 401 produktów;
  zachować kontrolę braku zdublowanych aktywnych definicji OpenAPI.
- Zaktualizować importy modeli migracji i readiness do nowego head.
- DB ma odrzucać NaN/Infinity, obce referencje owner, drugi żywy profil,
  konflikt owner+local_date i przepełnienie rewizji.
- Dopisać pełne skoordynowane usuwanie konta O2/O3 do zakresu E4;
  samo active/deleting nie realizuje całego protokołu.

## Komunikat do O1 przygotowany do właściwego dziennika

Do: Agent 1 / O1. Odczytano O1-002 i O1-005–007, Android 0.6 / Room 5.
E3 dostarczy mapowanie bootstrap oraz osobne account_generation/sync_epoch;
nie zastępują lokalnego lease. Proszę potwierdzić docelowy applicationId
i dokładny redirect PKCE APK oraz ograniczenia adaptera sesji.
Produkcję issuer/allowlist ustala O3. E3 pozostaje przed implementacją
z powodu braku wymaganej recenzji E2. Po scaleniu PR #5 odpowiedź należy
dopisać do jedynego dziennika z następnym wolnym ID O2.

## Granice dowodów

Autor i niezależny subagent `preflight_contracts` osobno wykonali
`tools/contracts/validate.ps1`: exit 0, 5 schematów, 16 operacji,
124 przykładów HTTP, valid 64 / invalid 20 / scenarios 18,
16 wektorów Decimal, 5 przypadków kompletności, 72 normalizacje źródeł
i 72 lokalne linki. Subagent sprawdził dokument przygotowania i rozdzielenie
analizy od wykonania; poprawiono wskazaną pomyłkę main/origin/main.
To walidacja E0 bez DB/OIDC, nie odbiór implementacji E3.

Subagent `preflight_oidc` wykonał kontrolę wersji lokalnych binariów:
JBR OpenJDK 21.0.10, Python 3.13.9, uv 0.9.5, PostgreSQL/psql 17.11.
Docker i gh nie znaleziono w PATH. Nie uruchamiał ani nie zmieniał DB.
Aktualny [quickstart dystrybucji Keycloak](https://www.keycloak.org/getting-started/getting-started-zip)
wymaga OpenJDK 25; nie należy zakładać, że lokalny JDK 21 uruchomi
najnowsze wydanie. Dobór zgodnej dystrybucji lub przypiętego obrazu CI
i sprawdzenie jego sumy/digest pozostają przed implementacją harnessu.

Weryfikacja źródeł przez subagenta wskazała Keycloak 26.8.0:
SHA256 ZIP `7ed1de3fda2598369262613bf682aab7e233d80a38c405e91588f7a7454370a1`
z [oficjalnego release API](https://api.github.com/repos/keycloak/keycloak/releases/tags/26.8.0).
Nie pobrano ani nie sprawdzono bajtów ZIP. PyJWT[crypto] 2.15.1 według
[metadanych PyPI](https://pypi.org/pypi/PyJWT/2.15.1/json) wymaga dodania
do przyszłego lockfile. Indywidualny cache kluczy PyJWKClient nie zapewnia
TTL; potrzebny będzie kontrolowany adapter JWKS.
Harness ma użyć rzeczywistego formularza logowania i wymiany code/verifier,
kont A/B, kontroli state, złego/brakującego verifier i odrzucenia ID tokenu.
Job keycloak-pkce musi wejść do ci-required bez możliwości zielonego skipu.

Nie wykonano implementacji, migracji ani realnego testu Keycloak E3.
Nie ma oceny końcowego odbioru, commita implementacji, push ani PR E3.
Ten plik celowo nie nadaje etapowi statusu ukończonego.
