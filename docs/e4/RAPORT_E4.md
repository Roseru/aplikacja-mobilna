# Raport synchronizacji E4 - osoba 2

**Aktualny wynik: poprawka czterech uwag osobnego odbioru z 11 października 2026.**
Kontynuujemy `codex/backend-e4-synchronizacja` / [PR #12](https://github.com/Roseru/aplikacja-mobilna/pull/12),
bez merge i bez E5. Oceniony head `2cdf513` oraz 885 PASS nie obejmowały
[potwierdzonych usterek](https://github.com/Roseru/aplikacja-mobilna/pull/12#issuecomment-6102583876).
Poprawka ma własną regresję autora i niezależnego recenzenta:
**569 unit + 468 PostgreSQL17.11 + 9 real Keycloak = 1046 PASS**, bez skipów.
Aktualna niezależna ocena runtime: **9,5/10**, bez istotnych nierozwiązanych uwag.
Commit runtime poprawki: `080ef076f7affd4e0a08e45515eb5128c179abe9`;
poprawiona fixture: `10232289b039256dec3db1796cb72ac01d1f1d93`.
Odczytano [CI 38092517302](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38092517302)
tego head: **completed/success, wszystkie pięć jobów**. Logi potwierdzają
merge `7edc46ebe6f410f88492a9598478f73aa834bf3e` = head `1023228` + main
`fa5684b3dd0bb420d969104999f85dee247f8184`: **569 unit + 468 PostgreSQL
17.11 + 9 real Keycloak/PKCE/sync/deletion = 1046 PASS**, bez skipów;
Ruff/format, kontrakty, wheel/sdist, installed wheel Python -I oraz oba
buildy/smoke obrazu PASS. Końcowy commit tego raportu i przekazania wymaga
osobnego ponownego CI; dokładny końcowy head i jego wynik wskazujemy w PR
i odpowiedzi po odczycie, bez utożsamiania go z wcześniejszym przebiegiem.

Pierwsze nowe [CI 38091981536](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38091981536)
commita `080ef076f7affd4e0a08e45515eb5128c179abe9` zakończyło się failure:
569 unit i 9 real Keycloak przeszły, PostgreSQL miał 438 PASS i 30 błędów
setupu fixture operatora. Fixture tworzyła login bez hasła przed próbą
brakującego CONNECT; lokalne trust maskowało błąd uwierzytelnienia SCRAM.
Poprawiono wyłącznie fixture: hasło SCRAM jest ustawiane przed próbą,
asercja odmowy CONNECT i rzeczywiste ACL pozostają niezmienne. Autor ponowił
całe 30 testów na SCRAM (30 PASS); niezależny recenzent odtworzył starą awarię
i uzyskał 30 PASS na własnym klastrze ze SCRAM dla wszystkich połączeń,
także administratora. Ten nieudany CI nie jest dowodem gotowości poprawki.

## Poprawka po odbiorze

| Przyczyna | Wynik i dowód |
|---|---|
| Decimal z `$` przepuszczał finalny LF; Unicode i strefy nie były w pełni sprawdzone przed pierwszym commit | Normatywny wzorzec sprawdza cały string; DTO pobierają ten sam zasób. NUL/samotne surrogates i overflow 0001/9999 są odrzucane. 26 real HTTP paczek: 422 i identyczny stan wszystkich tabel przed/po; polskie Unicode/emoji, zero/null zachowane |
| Klient wybierał najpierw 100 operacji, potem sprawdzał bajty | Prefix według dokładnych UTF-8 bajtów całej koperty, wspólnym serializerem pomiaru/HTTP. Domyślny HTTP/CLI wysyła 8 Meal × 100 składników po lostACK/restart; niewybrane pozostają queued, wire/ID/hash/originals niezmienne |
| Goal recovery zawsze sprawdzało nową oś | Wyjątek tylko dla świadomego recovery z potwierdzonym mapping bieżącego pełnego Context i identycznym żywym Goal targetem. A ACK → B pull/restart → already_applied/ten sam target/oś 1, bez zmiany oryginalnego payloadu |
| Operator-only LOGIN nie miał CONNECT | Fresh init daje CONNECT; osobny idempotentny psql krok przed upgrade E3 tworzy rolę/login, po upgrade sprawdza ACL. Real LOGIN/CLI działa bez członkostwa API/worker/migratora; DML/DDL/TRUNCATE nadal zabronione |

Migracje **0001–0011 są niezmienione**. Uprawnienie CONNECT jest provisioningiem
administratora instancji; 0012 nie jest potrzebna. SQLite `mapping_contexts`
jest addytywna i nie dopisuje fikcyjnego potwierdzenia starym mapowaniom:
wymagają nowego ukończonego pull. Schematy źródłowe, zasoby wheel, DTO/OpenAPI,
walidator E0 i przykłady są zgodne. Opublikowane bajty/hash katalogu, Android
i materiały źródłowe pozostają niezmienne.

Autor i nie-autor najpierw odtworzyli usterki. Recenzent sam wyeksportował
stary commit, wykonał wszystkie cztery probes, następnie całe 1046 PASS oraz
dodatkowy realny operator CLI → PKCE → Keycloak confirmation/purge →
odmowa refresh/staregoJWT A; B/katalog identyczne. [Odbiór poprawki](RECENZJA_O2.md).
E0: 68 valid/26 invalid/18 scenarios, 16 Decimal/5 completeness; Ruff/format 128,
OpenAPI/resources, sdist/wheel i installed wheel Python -I poza checkoutem: PASS.
Prawdziwa późna awaria DB nadal może zachować prefix. CI poprawki potwierdziło
obraz; końcowy commit dokumentacji ma własne ponowne CI. Room/APK/WorkManager
i produkcyjny restore pozostają O1/O3.

## Historyczna dostawa z 10 października

Poniższe wyniki opisują wcześniejsze wykonanie i nie są dowodem poprawki
czterech uwag. Zastępuje je powyższy odbiór poprawionego runtime.

Data: 10 października 2026. Agent 2 / O2. Gałąź:
`codex/backend-e4-synchronizacja`; baza `fa5684b` po dozwolonym merge
odebranego PR #11 (head7669f2a, wszystkie pięć jobów finalnego CI success,
ponowny odbiór poprawki DELETE). Zastane nieśledzone materiały, `.review-o2/`
i Random Data zachowano. PR E4 pozostaje do osobnego odbioru; bez merge/E5.

## Wynik i architektura

POST /api/v1/sync/push i GET /api/v1/sync/pull realizują sześć prywatnych
typów, trwałe receipts, commit-order ChangeLog, checkpointy, materializowane
snapshoty/incremental, ograniczoną retencję i RecoveryMapping. Router obsługuje
transport i commit; service/repository reguły i owner queries; E3 pozostaje
źródłem reguł encji. Szczegóły decyzji, transakcji i granic:
[v1](DECYZJE_V1.md). DTO normatywne są zasobami wheel/obrazu, runtime nie
importuje walidatora E0; draft HTTP sync usunięto z aktywnego design OpenAPI.

Trwały [klient SQLite](../../tools/sync_client/README.md) demonstruje dwa
urządzenia, immutable wire, oryginały, shadow/staging, ACK/restart, Decimal,
guest binding, konflikty i świadome recovery. [CLI deletion](USUNIECIE_KONTA.md)
kończy konto przez oddzielny service account Keycloak i wąski potwierdzony
purge. Brak endpointu samousunięcia, Androida, produkcyjnego deploymentu,
statystyk E5, Gemini lub funkcji późniejszych etapów.

## Migracje, kompatybilność i retencja

0009_e4_sync → 0010_e4_retention → 0011_e4_deletion rozszerzają odebrane
0008. Stare migracje pozostają niezmienne. ACL API/worker nie poszerzono
o fizyczne DELETE rodziców/DDL/TRUNCATE; retencja i purge mają oddzielne
SECURITY DEFINER z fixed search_path, bez runtime GUC lub wyłączania guardów.
Compatible rollback do 0008 zachowuje minimalne dowody i zabezpieczenia.
Stary obraz E3 nie obsługuje sync; powrót wymaga świadomego zamknięcia ruchu E4.

Minimalne dowody, mapowania i rezerwacje trwają do usunięcia konta. Rodzice
i tombstones są konserwatywnie zachowane także po zminimalizowaniu szczegółów
>=60dni. Aktywne kopie i ważne checkpointy pozostają chronione. Cele/katalog
oraz historyczne snapshoty nie są przepisywane.

## Wykonanie i odbiór

Autor: pełne **469 unit + 401 PostgreSQL17.11 + 9 real Keycloak/PKCE =
879 PASS**, bez skipów. Po ostatniej zmianie ponowiono cały push/live HTTP
oraz niezależne regresje: **38 PASS**, w tym pięć nowych przypadków.
Łącznie wykonano 406 różnych przypadków PostgreSQL przed publikacją.
Po publikacji dodano bezpośredni fizyczny restore przez HTTP z dwoma SQLite,
restartem i równoczesnym recovery do jednego targetu: cały zestaw 6 live HTTP
przeszedł u autora i niezależnego recenzenta. Końcowy zestaw ma 407 testów PG.
Ruff122/format,
schematy/resources, E0 (67 valid/20 invalid/18 scenarios/82 HTTP, 16 Decimal,
200 linków), OpenAPI, sdist/wheel i installed wheel Python -I poza checkoutem:
PASS. Obrazu nie budowano lokalnie; właściwy build/smoke wykonuje CI head.

Implementacja: commit `83f2feeb86eb9d7fe53ee684ab9069f1f51af353`,
[PR #12](https://github.com/Roseru/aplikacja-mobilna/pull/12).
Odczytano [CI 38087517688](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38087517688)
completed/success, wszystkie pięć jobów. Rzeczywiste logi integracji
`6a6c33d` (head83f2fee + mainfa5684b): **884 PASS** — 469 unit, 406
PostgreSQL17.11 i 9 real PKCE/sync/deletion, bez skipów. Python3.13.16;
sdist/wheel, installed wheel -I oraz oba build/smoke obrazu success.
Końcowy commit raportu/przekazania i dodatkowego testu ma własny ponowny CI;
jego exact head i wynik podajemy w PR i końcowej odpowiedzi po odczycie.

Recenzent sam: pełne 879 PASS, końcowy push/live29 PASS, własne probes,
opakowanie i dokładność 66 plików wheel. **9,2/10 bez istotnych nierozwiązanych
usterek**, [szczegóły](RECENZJA_O2.md). Rzeczywisty restore starszej DB,
barierowe pg_blocking_pids, minimalne receipts61dni, raw ACL/purge,
SQLite/restart oraz real provider wykonano; fixtures E0 nie są ich dowodem.

Pierwsza pełna regresja ujawniła brak modeli deletion w Base.metadata,
dawne założenia testów migracji i niepełny provisioning; naprawiono je.
Nowy test upgrade odtwarza również default ACL po DROP SCHEMA;
cała poprawiona regresja przechodzi. Seed counterMAX poprawiono z UPDATE0rows
na INSERT/ON CONFLICT i sprawdzono ponownie. Nie zaliczano nieudanych ani
niewykonanych prób. Wcześniejsze 707 PASS E3 nie jest wynikiem E4.

Nie zaliczamy skipów ani odczytu kodu jako wykonania integracji. Niezależny
recenzent nie jest autorem implementacji. [O1](INTEGRACJA_O1.md) oraz [O3](KONFIGURACJA_O3.md)
dostają wymagane komendy i granice. Odbiór O2 nie oznacza Room/APK/WorkManager,
KO-31 ani produkcyjnego restore/RPO. Produkcyjny issuer/HTTPS, odbiór obu
baz z zewnętrznym rejestrem deletion i mobilna integracja pozostają O1/O3.
