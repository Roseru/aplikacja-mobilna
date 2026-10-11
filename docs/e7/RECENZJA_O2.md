# Niezależny odbiór backendu E7-O2 - osoba 2

11 października 2026 r. Recenzent: niezależny nieautor implementacji E7.
Werdykt: **9,3/10; zero otwartych istotnych P1/P2. E7-O2 gotowe do osobnego odbioru koordynatora.**
Ocena dotyczy backendu, a nie E7-R, APK, wdrożenia lub pełnego wydania.
Zakres normatywny określa [master E7](../MASTER_PROMPT_E7.md).

## Źródło i niezależność

Dostarczana gałąź: codex/backend-e7-analiza-zdjec, [PR #28](https://github.com/Roseru/aplikacja-mobilna/pull/28).
Końcowy sprawdzony source binding: 9a7edcc95ae254cf6d1b59ca78add4c1a188ce75;
baza 75c4414a1aab22094c9425fa3dda890782e92370.
Własny managed checkout recenzenta był zamrożony, bez edycji runtime lub testów autora.

Odbiór wykonałem samodzielnie na własnym PostgreSQL 17/SCRAM, prywatnym storage
z rzeczywistym Windows DACL, osobnych procesach i loopback HTTP oraz własnym
Keycloak 26.8.0 z repozytoryjnego development harnessu. Nie korzystałem z bazy,
storage lub procesów autora ani koordynatora. Próbki były syntetyczne; nie wysyłano
zdjęć do Google. Keycloak jest rzeczywistym IdP, a development harness nie stanowi
odbioru jego produkcyjnego magazynu lub restore.

Zmiana c091c5a → b4d2780 obejmowała precondition ACL, kontrolę MAINTAIN w CLI,
fresh bootstrap i właściwe testy/dokumenty. b4d2780 → 9a7edcc zmienia wyłącznie
wspólne dokumenty zespołu; porównanie zakresu backend/kontrakty/infra jest puste.

Manifest 264 śledzonych plików runtime, migracji, testów, kontraktów, lockfile,
narzędzia referencyjnego i lokalnej infrastruktury: SHA-256
699ad0c6e645562de12aa51c0ecad47d169cbc50ed3abe16fe9068ed644a4c36.
Manifest dla wcześniejszego c091c5a: SHA-256
228f02893e172469fd60114a1839abc17d6ced11136ac91dafee2e86e589da08.
Prywatne probes końcowe: SHA-256
3b214bfe30cae0bbf10a2054dca2c47f00fd087f307089802d83f912085f2941.
Logi, zrzuty, poświadczenia, środowiska i obrazy pozostają poza Git.

## Faktycznie wykonane kontrole

| Zakres | Wynik i source binding |
|---|---|
| Pełne unit | 1170 PASS na c091c5a; 25 właściwych unit provisioningu ponownie na b4d2780 |
| Pełne integration PG17 | 928 PASS na b4d2780, 904,05 s; źródła identyczne z końcowym 9a7edcc |
| Real Keycloak / PKCE / E7 | 28 PASS na własnym IdP i PG, c091c5a; zakres auth/E7 HTTP nie zmienił się |
| Własne adversarial probes | 21 PASS na 9a7edcc, 25,60 s; wcześniejsze 15 są podzbiorem |
| Dokładny fresh bootstrap | 1 własny scenariusz PASS: SQL init-db.sh przez psql → migracja 0015 → minimalny SCRAM LOGIN → real worker CLI |
| Jakość / kontrakty | Ruff PASS; format 251 plików PASS; E0 89 valid / 32 invalid / 18 scenarios oraz 374 lokalne linki na b4d2780 |
| Pakiet | Wheel/sdist PASS; 127 plików runtime identycznych bajtowo ze źródłem; locked install oraz installed -I smoke poza checkoutem PASS |

Nie było skipów. Powtórek i nakładających się zakresów nie sumuję.
Pełne PG obejmuje nowy E7 oraz właściwą regresję E0–E6: migracje, całe dawne grafy,
historię, standard sync, ACL, concurrency, actual worker processes i dump/restore.

Pierwszy własny pełny PG run na c091c5a zakończył się 801 PASS / 11 FAIL / 111 ERROR,
więc nie jest zaliczony. Jedna odmowa dotyczyła potwierdzonej starej listy tabel E6
poprawionej przez autora. Pozostałe wynikały z mojego niepełnego harnessu: brak
ścieżek PG17 CLI/sekretu legacy workera, wymaganych pustych baz i zbędny własny
grant CONNECT do bazowej roli AI. Poprawiłem wyłącznie prywatne środowisko,
zachowałem pierwszy log i wykonałem cały właściwy run ponownie. Jeden własny
test połączenia wymagał korekty oracle: psycopg nie dostarcza SQLSTATE dla tej
odmowy startowej; potwierdziłem efektywny brak CONNECT i rzeczywistą odmowę.

## Zamknięte istotne uwagi i własne oczekiwania

- **P1 cleanup race:** bariery zatrzymały create po staging i sweep po odczycie
  intentów. Acceptance usunęło intent i zwolniło lock, zanim cleaner kontynuował.
  Aktualny recheck po locku zachował zaakceptowane bajty i queued job.
- **P2 COMMIT ACK:** awaria przed oraz po rzeczywistym COMMIT zachowała plik.
  Przy braku zapisu durable intent umożliwił unlink; przy zapisie replay zwrócił
  jeden job bez ponownego codec/staging.
- **P2 fazy/żywe IO:** ponowny preflight callback po rozpoczętej generacji nie
  cofnął fazy; drugi dispatch, finish podczas żywego IO i zwolnienie cudzym
  tokenem zostały odrzucone. Opaque fences i hash tokenu nie udostępniają
  aktywnych capabilities nowemu workerowi.
- **P2 minimalne ACL:** własne upgrade probes obejmowały direct/column/PUBLIC
  grants, LOGIN, MAINTAIN i SECURITY DEFINER EXECUTE. Odmowa nastąpiła przed DDL;
  head, lista tabel i wcześniejsza funkcja purge pozostały zachowane.
  Rzeczywisty CLI odrzucił MAINTAIN przyznane loginowi lub PUBLIC, bez dispatch.
- **P2 namespace/CONNECT:** disabled stara pool nie umożliwiła nowego środowiska
  tego samego projektu. PUBLIC CONNECT do własnej dodatkowej bazy odmówiło
  provisioningu atomowo; po odebraniu grantu minimalny LOGIN działał wyłącznie
  we właściwej bazie, bez odczytu fence.
- **Deadline i restore:** własny transport child bez watchdogu rodzica zakończył
  trickling HTTP przy absolutnym deadline i zamknął socket, bez kolejnego call.
  Rzeczywisty zrzut sprzed dwóch późniejszych mock calls odtworzył pusty ledger,
  ale nowa epoka nadal zamknęła oba purpose, odmówiła wcześniejszego resume
  i odcięła wysłanie starego joba.

Pełne testy potwierdzają też zgodę przed przygotowaniem, brak spoola oryginału,
JWT/context przed replay, cancel/purge fences, compensation/deletion intents,
TTL, rolling RPM/TPM, Pacific RPD/DST, UTC admission i 336 h energy interface,
null/Decimal, exact refs, korektę oraz confirm → standard sync bez wcześniejszego
zapisu Meal/ProductDraft. Zachowano prawa legacy workera i retencję O3.

## Granice dowodu

Własne VP8 i VP8L probes potwierdziły identyczny fresh JPEG po usunięciu inert
excess bytes oraz odmowę rzeczywistego drugiego kontenera ZIP. Nie deklaruję
uniwersalnego exact-bitstream-end proof dla WebP ani odrzucenia wszystkich
dowolnych inert bajtów w declared entropy chunk. Oryginał pozostaje w pamięci;
do storage/provider trafia świeżo zakodowany obraz bez metadanych.

E7-R pozostaje **WAITING_EXTERNAL**: wymagane datowane free-only/model/project/limits
O3 oraz zatwierdzony corpus minimum 30 zdjęć. Mock i loopback REST nie potwierdzają
trafności Gemini ani publicznego wydania w EOG. Room/outbox/fallback/APK O1,
produkcyjny mount/cleanup/backup exclusion/restore O3, pełne E5-C i KO-31 pozostają
osobnymi odbiorami.

Nie odczytywałem ani nie zatwierdzałem końcowego CI/merge PR. Ten raport jest dowodem
własnego odbioru technicznego; exact head/base i zdalne kontrole potwierdza wykonawca
oraz koordynator. Nie scalałem PR, nie rozpocząłem E8/E9 i nie uruchamiałem automatyzacji.
Własne Keycloak, oba klastry PG i procesy prób zostały zatrzymane. Przed zapisem
tego raportu tracked diff był pusty; jedyna zmiana recenzenta to ten dokument.
