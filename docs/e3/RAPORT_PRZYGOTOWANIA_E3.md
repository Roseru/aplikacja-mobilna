# Raport przygotowania etapu E3 - osoba 2

Data: 10 października 2026 r. Autor: Agent 2 / O2.
Odbiorcy: właściciel projektu, Agent 1 / O1 i Agent 3 / O3.

**Stan E3: przygotowanie wykonane; implementacja i odbiór pozostają do wykonania.**
Zgodnie z poleceniem startowym implementacja ma rozpocząć się z main
zawierającego zaakceptowane E2. PR #4 nadal czeka na wymaganą recenzję
innej osoby. Zależność zgłoszono O3; nie obchodzono workflow.

## Stan repozytorium i PR

Repozytorium: [Roseru/aplikacja-mobilna](https://github.com/Roseru/aplikacja-mobilna).
Workspace: `S:\studia\projekt aplikacja moblina`.
Aktualny checkout: `codex/docs-plan-e3`, HEAD
`1908c9bcdf9bb38653939487a90583fdf51a9f76`.
Po pobraniu origin jego main wskazuje
`151885d3f728c47240a7087ff862ba5f61ea7403`; lokalna gałąź main pozostaje
na `a79b0732df71955ebf893391cc767805be674ed0`. E2 nie jest w origin/main.

Stan PR ponownie sprawdzono przy pisaniu tego raportu:

| PR | Zakres | Head | Stan |
|---|---|---|---|
| [#4](https://github.com/Roseru/aplikacja-mobilna/pull/4) | E2 O2 | `52f3547` | Otwarty; lista recenzji pusta |
| [#5](https://github.com/Roseru/aplikacja-mobilna/pull/5) | Wspólna komunikacja | `aed79c7` | Otwarty |
| [#8](https://github.com/Roseru/aplikacja-mobilna/pull/8) | Master prompt E3 | `1908c9b` | Otwarty |

[CI E2 38042927890](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38042927890)
dla head `52f3547f47bcfae1080aa1e9720b1f37a1ef6b88` ma wynik
completed/success. Sukces CI nie zastępuje wymaganej recenzji innej osoby.
Jest to odczyt dowodu E2, nie wykonanie testów E3.

Zachowano wcześniejsze nieśledzone pliki `docs/MASTER_PROMPT_E2.md`
i `docs/MASTER_PROMPT_POPRAWKA_E1.md`. Nie zmieniano Androida, istniejących
migracji ani danych źródłowych w `Random Data/`.

## Wykonane przygotowanie

Przeczytano cały [master prompt E3](../MASTER_PROMPT_E3.md), wymagania,
AGENTS.md, architekturę, plan, workflow i kontrakty E0. Dokument komunikacji
PR #5 czytano z jego commita; nie scalano gałęzi O1 i nie tworzono drugiego
wspólnego dziennika.

Uwzględniono O1-002 i O1-005–007 oraz raport i model właścicieli Androida
`ad8c0a6`: Android 0.6 / Room 5. Lokalny rejestr `(issuer, sub)` nie jest
uwierzytelnieniem. E3 musi przekazać mapowanie lokalnego właściciela na
serwerowy account_id; lokalna generacja lease jest odrębna od
account_generation i sync_epoch. Testy raportowane przez O1 nie były
wykonywane w tej sesji.

Dwaj subagenci przeprowadzili niezależne przygotowanie bez edycji kodu:

| Subagent | Zakres | Wynik |
|---|---|---|
| `preflight_contracts` | Kontrakty E0, modele i ograniczenia DB, integracja z E2 | Checklista zmian; własne wykonanie walidatora; ręczna recenzja dokumentu przygotowania |
| `preflight_oidc` | OIDC/JWKS, Keycloak/PKCE, konfiguracja E2 i lokalne binaria | Plan rzeczywistego testu oraz zweryfikowane wersje i ograniczenia środowiska |

Szczegółowa checklista jest w [przygotowaniu E3](PRZYGOTOWANIE_E3.md).
Najważniejsze ustalenia do implementacji:

- Rozszerzyć kontrakt błędów bootstrapu, epoki i generacji oraz ograniczyć
  goal_timeline_revision do 2147483647.
- Chronione tokeny stron muszą wiązać właściciela, generację, epokę,
  operację, filtry i limit. Publiczny kursor rp1 E2 nie wystarcza.
- Bootstrap, zgody i mutacje domenowe wymagają wspólnej blokady konta
  do commit; deleting ma pierwszeństwo również przed replayem.
- DB ma wymuszać własność referencji, jeden żywy profil, unikalny dzień,
  niezmienność celów i skończone zakresy NUMERIC.
- Runtime schematów i stref musi działać z wheel poza checkoutem;
  generowane OpenAPI ma zastąpić przejęte definicje aktywnego draftu.
- Pełny skoordynowany protokół usunięcia konta należy jawnie zaplanować
  dla E4; samo pole deleting nie oznacza wykonania tego protokołu.

## Dowody wykonanych kontroli

Autor oraz niezależnie subagent `preflight_contracts` wykonali:

```powershell
.\tools\contracts\validate.ps1
```

Oba przebiegi zakończyły się kodem 0 na Python 3.13.9:

| Kontrola | Wynik |
|---|---|
| Schematy / operacje / przykłady HTTP | 5 / 16 / 124 |
| Przykłady valid / invalid / scenariusze | 64 / 20 / 18 |
| Wektory Decimal / kompletność dnia | 16 / 5 |
| Normalizacje źródeł / lokalne linki | 72 / 72 |
| git diff --check | PASS |

To walidacja istniejących artefaktów E0, bez transakcji PostgreSQL i OIDC.
Walidator nie obejmuje automatycznie dokumentów `docs/e3/`; dokument
przygotowania sprawdzono ręcznie. W niezależnym przeglądzie poprawiono
omyłkowe utożsamienie lokalnego main z origin/main. Recenzent nie zgłosił
istotnych uwag do przygotowania; nie wystawił oceny implementacji E3.

Subagent wykonał lokalne binaria i potwierdził JBR OpenJDK 21.0.10,
Python 3.13.9, uv 0.9.5 i PostgreSQL/psql 17.11. Docker i gh nie znaleziono
w PATH. PostgreSQL nie był w tym przygotowaniu uruchamiany.

Aktualny [quickstart Keycloak](https://www.keycloak.org/getting-started/getting-started-zip)
wymaga OpenJDK 25. Lokalny JDK 21 nie dowodzi gotowości uruchomienia
najnowszej dystrybucji. Dobór środowiska, pobranie i weryfikacja dystrybucji,
konfiguracja realmu oraz rzeczywisty test PKCE pozostają do wykonania.

## Komunikacja i zależności O1 O3

O3 otrzymał [zgłoszenie blokady w PR #4](https://github.com/Roseru/aplikacja-mobilna/pull/4#issuecomment-6097999046):
potrzebna jest recenzja innej osoby dla aktualnego head E2. Przy zmianie
head O2 ponownie sprawdzi zakres, CI i uwagi przed scaleniem.
Zapytano również o testowy issuer/JWKS, audience, role, TTL i allowlistę
redirectów, bez sekretów. Publikacja komentarza nie potwierdza odczytu O3.

Do O1 przygotowano prośbę o docelowy applicationId, dokładny redirect PKCE
APK i ograniczenia adaptera sesji. Treść jest w dokumencie przygotowania;
nie została opublikowana do wspólnego dziennika. Lokalny harness może mieć
własny dokładny callback loopback, lecz nie zastępuje konfiguracji ani testu APK.

## Dalsza realizacja E3

Wariant zgodny z poleceniem startowym: po wymaganej recenzji i zielonym CI
scalić E2, pobrać aktualny main i rozpocząć implementację na
`codex/backend-e3-tozsamosc-profile`.

Zasady Git w AGENTS.md opublikowanym w niescalonym PR #5 opisują również
pracę zależną: gałąź E3 z dokładnego commita E2,
tymczasowy PR do gałęzi E2, następnie po scaleniu E2 dołączenie aktualnego
main, zmiana bazy PR i ponowna weryfikacja. Ten wariant pozwala rozwijać
E3 przed merge E2, ale zmienia wcześniejszy warunek użytkownika dotyczący
bazy; docs/WORKFLOW.md opisuje podstawowy przebieg z main. Wariant zależny
nie został uruchomiony; prośba o ten raport nie stanowiła decyzji
o zmianie sposobu implementacji.

Pozostały zakres obejmuje adapter OIDC/JWKS, konto/bootstrap, profil,
niezmienne cele i zgody, kalkulator, modele prywatne i chronione produkty,
migracje oraz rzeczywisty test Keycloak Authorization Code + PKCE S256 A/B.
Końcowy odbiór wymaga regresji E1/E2, testów PostgreSQL, wheel/obrazu,
niezależnej recenzji minimum 9/10 bez istotnych usterek i CI aktualnego head.

## Stan dostawy

Lokalnie zapisano dokument przygotowania i niniejszy raport. Nie utworzono
jeszcze gałęzi implementacyjnej, commita, push ani PR E3. Nie wykonano
migracji E3, testu Keycloak/PKCE ani końcowej recenzji implementacji.
E3 nie jest gotowe do odbioru. Nie scalono E3 i nie rozpoczęto E4.
