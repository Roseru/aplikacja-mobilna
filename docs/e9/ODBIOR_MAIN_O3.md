# E9-O2 — odbiór scalonego backendu przez O3

Data: 13 października 2026 r. Wykonawca odbioru: agent 3 / O3.

Backend korekt zapotrzebowania został scalony w [PR54](https://github.com/Roseru/aplikacja-mobilna/pull/54).
Odbiór dotyczy `main` **2b4073e05d800fe3abc2388c17308323adf5ed56**,
migracji `0024_e9_history_graph` i wspólnego runnera E7/E9.
Niepublikowany prototyp O3 zachowano lokalnie; wspólną implementacją pozostaje PR54.

E9 oddziela oszacowane zapotrzebowanie do utrzymania masy od celu spożycia.
Backend analizuje zamknięte dni dziennika i pomiary masy, oblicza ograniczoną
propozycję według reguł, przechowuje historię i pozwala przyjąć, odrzucić albo
przywrócić wcześniejsze oszacowanie. Model wyjaśnia wynik reguł. Automat wymaga
osobnej świadomej zgody i domyślnie pozostaje wyłączony.

## Aktualny main i CI

O3 odczytał metadane oraz pełne logi wszystkich ośmiu jobów
[push main CI38435239012](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38435239012).
Każdy ma `completed/success` i wskazuje powyższy commit.
To osobny odbiór main, poza wcześniejszym CI PR54.

| Kontrola | Potwierdzony wynik |
|---|---|
| contracts | E0: 10 schematów, 95 poprawnych i 35 odrzucanych przykładów, 18 scenariuszy |
| quality | 1714 unit oraz 49 testów infrastruktury PASS |
| postgres | 1362 PASS, 990,87 s; bez failures/errors/skips |
| keycloak-pkce | 28 PASS |
| android-build | Build, lint i JVM ukończone sukcesem |
| android-device | 148 rzeczywiście wykonanych testów urządzenia, job success |
| local-integration | HTTPS, issuer, readiness, PKCE, role, restart usług i paired backup/restore PASS |
| ci-required | Wszystkie siedem zależności zakończone sukcesem |

Drzewo main `4b98e2bcf97d46cc9cc35e85f7fe203b59d03592` jest identyczne
z odebranym head PR54 `25b2ddc944612db57a8dd13d492d23b8ab9aaaf3`.
Oryginalny checkout zaktualizowano przez `git pull --ff-only`; zachowano materiały
`Random Data`, historię oraz cudze gałęzie i usługi.

## Własne próby lokalne

O3 użył izolowanego checkoutu tego samego commita oraz osobnego, oznakowanego
kontenera PostgreSQL 17 z losowymi credentialami poza Git. Testy nie korzystały
z instalacji użytkownika. Wszystkie pliki `test_e9*.py` zaliczyły **97 testów PG
w 228,51 s**, bez failures/errors/skips. Własny kontener usunięto po zakończeniu
przez fixture sprawdzający jego oznaczenie. Zakres obejmuje reguły, API/zgody,
historię, worker/automat, rzeczywiste procesy, migracje, sync i projekcje E8.

Pozostałe wykonane kontrole:

- E0 `--locked --offline`: 10 schematów, 95/35 przykładów, 18 scenariuszy,
  16 wektorów Decimal, 5 kompletności, 72 normalizacje i 572 lokalne linki PASS.
- Ruff lint/format: PASS, 336 plików poprawnie sformatowanych.
- Zbudowany wheel zainstalowano w nowym środowisku bez editable/source importu.
  `python -I` smoke oraz CLI `--help` PASS. Osobna próba potwierdziła
  zainstalowane pliki migracji004, SQL historii, schemat energii i zgodny head.
  SHA-256 wheel: `5a799f3c912ba2a3c78c73adcd6eaee960e30baeb1fa941a2ad9b5217489d6be`.

Uzupełniający nieautor sam uruchomił **56 unit PASS** oraz **trzy własne próby
PG/HTTP PASS** na osobnych klastrach. Ocena tego zakresu: **9,3/10**, bez
zidentyfikowanych otwartych P1/P2. Próby potwierdziły:

- Ranking-only PUT zachowuje requested, lecz unieważnia effective/notice.
  Replay wcześniejszego receipt nie reaktywuje automatu; potrzebna jest świeża
  afirmacja. Odczyt i ponowienie zgody nie utworzyły provider attempt.
- Migracja004 odmawia zmienionego parent SQL nawet po podrobieniu stored hash;
  baza pozostaje na003.
- Awaria manifestu projectora przy accept zwraca503 i cofa E, receipt, H,
  marker oraz projekcje. Po usunięciu faultu na prywatnej bazie ta sama propozycja
  tworzy dokładnie jedną wersję od jutra, przy zachowaniu dzisiejszego E,
  pełnego starego celu i punktów Nemesis. Powtórzenie tego jednego zmienionego
  zakresu nie jest czwartym unikalnym testem.

Pełny zapis nieautora: [uzupełniająca recenzja main](RECENZJA_MAIN_O3.md).
Wcześniejszy odbiór całego runtime 9,2/10 pozostaje opisany w
[recenzji E9](RECENZJA_E9.md); nie sumujemy nakładających się zestawów testów.

## Granice odbioru i następne kroki

Odebrany jest backend E9-O2 na rzeczywistym PG i mocku. Ten odbiór nie wdraża
E9 do wcześniejszej lokalnej instalacji użytkownika i nie potwierdza pełnego E9/R.
Gemini, realny APK/API/Room, stabilny adres dostępny z telefonu, produkcja
i E10 pozostają osobnymi odbiorami. Nie wykonano Google I/O ani billing.
AI/Nemesis nie otwarto; automatyzacje pozostają PAUSED. Demo katalogu pozostaje demo.

Kolejne prace wykorzystują już istniejące przekazania:

- O1: [kontrakt E9](INTEGRACJA_O1.md), ekran korekt i historii,
  migracja/synchronizacja Room oraz prawidłowy stan requested/effective po PUT zgód.
- O3: [konfiguracja i upgrade](KONFIGURACJA_O3.md), spójna kopia przed rolloutem,
  migracja0024, zgodne obrazy i minimalne role oraz odbiór origin/issuer/CA.
- O1/O2/O3: [rzeczywisty scenariusz APK/API](../integracja/ODBIOR_APK_API_O2.md).

Nie ma potrzeby rozpoczynania drugiej implementacji backendu E9.
