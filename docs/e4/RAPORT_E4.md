# Raport synchronizacji E4 - osoba 2

## Poprawka efektywnych praw kolumnowych operatora

11 października 2026. Kontynuacja `codex/backend-e4-synchronizacja` /
[PR #12](https://github.com/Roseru/aplikacja-mobilna/pull/12), bez merge E4 i E5.
[Odbiór koordynatora](https://github.com/Roseru/aplikacja-mobilna/pull/12#issuecomment-6103576990)
head `aa4d97c9fd91bcc4985d43f582087c2559af748b` potwierdził ochronę sekretu
i znalazł P2: has_table_privilege pomija osobny grant kolumny. Dawne 1110 PASS
nie obejmowały tej regresji. Prace wykonano w dedykowanym checkoutcie, bez
zmiany gałęzi lub plików głównego katalogu oraz checkoutu koordynatora.

Root sam: 3 przewidziane FAIL nowego testu na starym SQL, fresh × LOGIN/PUBLIC/
operator-role, rzeczywisty odczyt prywatnej wagi. Autor testów: 36 przewidzianych
FAIL (4 prawa × 3 źródła × fresh/E3 przed/E3 po 0011), 9 realnych odczytów
SELECT także po exit=0 starego helpera. Niezależny recenzent: 6 własnych probes
SELECT/UPDATE × 3 źródła oraz red nowej regresji. Table privilege=false,
any-column privilege=true. UPDATE odmawia 42501 przez private_account_guard;
nie zgłaszamy potwierdzonej mutacji. Dawna kontrola provisioningu akceptowała
taki grant UPDATE.

Minimalna zmiana SQL dodaje has_any_column_privilege dla INSERT/UPDATE/REFERENCES
oraz SELECT w dotychczasowej gałęzi prywatnego odczytu. Uwzględnia efektywne
granty LOGIN, PUBLIC i NOLOGIN operatora, nie tylko pg_attribute. Stare kontrole
praw tabel pozostają; SELECT account_deletion_jobs jest dozwolony, jego I/U/
REFERENCES są zabronione także kolumnowo. Odmowa wycofuje własne zmiany helpera,
zachowuje stare hasło, memberships, ACL i wszystkie dane. Zastanego grantu nie
usuwa: administrator świadomie REVOKE konkretne prawo, po czym ponawia helper.

Lokalnie root: **600 unit + 571 PostgreSQL 17.11 = 1171 PASS**, bez skip/fail.
70 nowych przypadków obejmuje 36 weights, 18 job I/U/REFERENCES, 6 job SELECT,
6 rollback nowego LOGIN, 3 odmowy rzeczywistego UPDATE i globalne logi/SCRAM.
Pełne wcześniejsze 33 server-log i 30 LOGIN/CLI/ACL pozostają zaliczone.
Ruff/format 135, E0/kontrakty/OpenAPI/zasoby, wheel/sdist oraz zainstalowany
wheel Python -I poza checkoutem: PASS.
Root w tej poprawce nie deklaruje lokalnego Keycloak lub buildów obrazu;
ich dowód pochodzi z nowego CI, oddzielnie od lokalnego wykonania.

Poprawka: `71c1e9b`; wypchnięty head po zwykłym merge aktualnego main:
**`c7b74480af38ee1e8cd3f9bd210cb1c8b92e8ced`**. Zachowano O2-003–005,
pełny O2-007 oraz master koordynacji. Merge wniósł wyłącznie dwa dokumenty;
kod jest identyczny z lokalnie przetestowanym, walidacja dokumentacji PASS.
Odczytano [CI 38098862007](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38098862007):
**completed/success, wszystkie pięć jobów**, testowany merge
`7f7f5f7b326728f7f8da92d96d00f8ff3ad99201` = head `c7b7448` + baza
`e392d1f2b22fd98528e2d0f4c33da848ac3becce`. Rzeczywiste logi:
**600 unit + 571 PG17.11 + 9 real Keycloak/PKCE/sync/deletion = 1180 PASS**, bez
skipów; nowe column/server-log na własnych PG Docker, Ruff/format 135,
kontrakty, wheel/sdist, installed wheel -I i oba buildy/smoke obrazu PASS.
Ostatni commit raportu/przekazania ma własny ponowny CI; dokładny końcowy
head i wynik wskazujemy w PR i przekazaniu koordynatorowi po odczycie.

Niezależny nie-autor: **600 unit + 70 column + 33 server-log + 30 LOGIN/CLI/ACL
= 733 PASS**, plus 36 własnych fixed probes. Sam sprawdził zachowane hasło/
membership/ACL/dane po odmowie, nowe połączenia, REVOKE/retry, wyjątek job SELECT
i globalne logi. **9,5/10, brak nierozwiązanych P1/P2 lub istotnych uwag**.
Autor testów osobno 133 PG PASS; jego pierwszy 101 PASS/2 ERROR dotyczył
systemowego TEMP, pełne 33 ponowił z własnym basetemp bez osłabienia testów.
Recenzent także ponowił unit we własnym basetemp po błędach zastanego TEMP.

SCRAM wymagany również dla administratora; globalne statement/duration/error/
parameter logging aktywne. **0 hasła i 0 weryfikatora** w logach klienta/serwera.
Ochrona 17 ustawień sesji, lokalne libpq i transakcja hasła/ACL są zachowane.
Migracje 0001–0011, API, epoka, Android i źródła Random Data nie są zmienione.
[O3](KONFIGURACJA_O3.md) opisuje dokładny REVOKE i brak automatycznej naprawy
zastanego dostępu; pozostają dotychczasowe ograniczenia DBA/OS/audytu/proxy/TLS
oraz odrębny odbiór Room/APK/WorkManager i produkcyjnego restore.
Własne procesy testowe zatrzymano, dane i prywatne dowody zachowano. Wynik
wykonawcy gotowy do osobnego odbioru koordynatora; PR E4 nie jest scalony,
E5 nie rozpoczęto. Odczytu/PASS koordynatora nie potwierdzamy za niego.

## Historia poprawki sekretu provisioningu operatora

Poniższy odbiór na aa4d97c nie obejmował znalezionych później praw kolumnowych.

Data: 11 października 2026. Kontynuacja `codex/backend-e4-synchronizacja` /
[PR #12](https://github.com/Roseru/aplikacja-mobilna/pull/12), bez merge i E5.
[Osobny odbiór](https://github.com/Roseru/aplikacja-mobilna/pull/12#issuecomment-6103121954)
head `c9bdac066bb5220abb013edae1228f77fa80e2dd` potwierdził poprzednie cztery
poprawki i znalazł P2: jawne hasło operatora w logu SQL. Dawne 1046 PASS nie
obejmowały tej regresji. Poniższy odbiór bezpieczeństwa zastępuje tamtą ocenę
w zakresie provisioningu; wcześniejsze wyniki zachowano jako historię.

Root, autor i niezależny recenzent odtworzyli stary SQL na osobnych PostgreSQL
17.11 z SCRAM dla wszystkich połączeń, również administratora. Provisioning
działał, klient nie ujawniał sekretu, ale jawne testowe hasło wystąpiło w
**3 liniach logu serwera**. Nowa regresja uruchomiona ze starą prywatną kopią
SQL dała bezpieczny FAIL wykrywający log serwera, bez sekretu w komunikacie.

Nowy `infra/local/provision_deletion_operator.py` waliduje konfigurację lokalnie
bez trim/normalizacji i oblicza SCRAM przez rzeczywiste libpq
PQencryptPasswordConn z jawnym algorytmem. Własne kontrolne połączenie z aktywnym
logowaniem wykazało **0 nowych SQL podczas tego wywołania**. SQL nie otrzymuje
jawnego hasła nawet przed BEGIN. Role/ACL w dotychczasowym pliku SQL oraz
ustawienie weryfikatora należą do jednej transakcji. Weryfikator jest poufnym
parametrem lokalnego GUC, a stały DO ustawia go po sprawdzeniu ACL.

Ochronę 17 ustawień sesji narzucono przy zestawieniu połączenia i sprawdzono
przed przekazaniem weryfikatora: statement/duration/sampling/error/parameter
logging, diagnostyka/statystyki, track_activities i bezpieczny search_path.
Nie wyłączono logowania instancji ani testu: zwykła kontrolna sesja nadal
logowała do tego samego pliku. Po poprawce **0 jawnego hasła i 0 weryfikatora
w logu serwera oraz klienta**, także dla powtórzeń, rotacji, błędów i rollbacku
po rzeczywistym ALTER. Komunikaty błędów nie zawierają surowych wyjątków/DSN.

Autor: 31 nowych unit PASS, własne realne logi/SCRAM/Unicode/quotes/spaces,
rotacja, odmowa starego/błędnego hasła i rollback PASS. Autor testów: 33 nowe
regresje rzeczywistego logu oraz 30 poprzednich testów operatora PASS.
Root: **600 unit + 501 PostgreSQL 17.11 = 1101 PASS**, bez skip/fail. Ruff/format,
kontrakty/E0/OpenAPI/resources, wheel/sdist i installed wheel Python -I poza
checkoutem PASS. Pierwszy lokalny unit miał błędy wspólnego katalogu TEMP;
powtórzono go z własnym unikalnym basetemp, bez osłabiania testów ani
poszerzania uprawnień systemu.
Pierwszy pełny PG miał 499 PASS / 2 FAIL izolacji baz: prywatny skrypt root
omyłkowo nadał API/worker CONNECT do testowego Keycloak. Poprawiono wyłącznie
ACL własnego klastra i ponowiono cały zestaw: 501 PASS; testy/provisioning
aplikacji pozostają niezmienione. Nie zaliczamy pierwszych nieudanych prób jako PASS.

Niezależny nie-autor: **600 unit + 33 server-log + 30 operator LOGIN/CLI/ACL
= 663 PASS**, plus własne powtórzone próby na osobnym SCRAM klastrze:
lokalność biblioteki, fail-closed przed weryfikatorem, rotacja, Unicode,
rollback po ALTER, ACL, identyczne wszystkie tabele aplikacji przed/po
provisioningu E3/0011. **9,5/10, bez nierozwiązanych P1/P2 lub istotnych uwag**.
[Szczegóły odbioru](RECENZJA_O2.md). W tej poprawce root nie ponawiał lokalnego
Keycloak ani buildów obrazu; ich nowy dowód pochodzi z CI poniżej, oddzielnie
od lokalnego wykonania. Nie zaliczamy poprzedniego CI jako dowodu poprawki.

Poprawka wypchnięta: **`73a2be9ac26132056eeb8b7cef86aea7a6bebc3c`**.
Odczytano [CI 38095748566](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38095748566):
**completed/success, wszystkie pięć jobów**. Rzeczywiste logi merge
`ac4bfbb62ecdb2cfc679ddf1fb16270cd739a006` = head `73a2be9` + main
`fa5684b3dd0bb420d969104999f85dee247f8184` potwierdzają **600 unit + 501
PostgreSQL 17.11 + 9 real Keycloak/PKCE/sync/deletion = 1110 PASS**, bez skipów.
Nowa regresja logu/SCRAM wykonała się na osobnym przypiętym PG17 Docker.
Ruff/format 134, kontrakty, wheel/sdist, installed wheel -I i oba buildy/smoke
obrazu PASS. Ostatni commit tego raportu/przekazania ma własny ponowny CI;
dokładny końcowy head i wynik wskazujemy w PR oraz odpowiedzi po odczycie.

Migracje **0001–0011**, dane, epoka i API są niezmienione. Nowy helper zastępuje
bezpośrednie psql; idempotencja/rotacja, CONNECT, pre/post upgrade E3 i odmowy
DML/DDL/TRUNCATE są zachowane. Test logów wykonuje się w pełnym CI integration,
na własnym PG17 z logging_collector i SCRAM również administratora; brak narzędzia
jest FAIL. Linux używa przypiętego obrazu PG17, Windows własnych binariów i
unikalnych danych/portów. Żadne sekretne logi/verifiery nie są publikowane.

O3 stosuje [nowe przetestowane polecenia](KONFIGURACJA_O3.md), weryfikuje prawa
admina, systemowe środowisko/pamięć, pg_authid/backupy, dodatkowy audyt/proxy/
trace i produkcyjny TLS. Ochrona obejmuje sprawdzone wbudowane kanały PG17;
nie obiecujemy ukrycia weryfikatora przed administratorem bazy lub systemu.
Room/APK/WorkManager i produkcyjny restore pozostają odrębną integracją O1/O3.
Własne procesy testowe zatrzymano; dane, prywatne dowody i zastane materiały
pozostają zachowane. PR otwarty, niescalony; E5 nie rozpoczęto.

## Historia odbioru czterech wcześniejszych usterek

**Wynik poprzedniej poprawki czterech uwag z 11 października 2026.**
Kontynuujemy `codex/backend-e4-synchronizacja` / [PR #12](https://github.com/Roseru/aplikacja-mobilna/pull/12),
bez merge i bez E5. Oceniony head `2cdf513` oraz 885 PASS nie obejmowały
[potwierdzonych usterek](https://github.com/Roseru/aplikacja-mobilna/pull/12#issuecomment-6102583876).
Poprawka ma własną regresję autora i niezależnego recenzenta:
**569 unit + 468 PostgreSQL17.11 + 9 real Keycloak = 1046 PASS**, bez skipów.
Ówczesna ocena runtime: **9,5/10**; nie obejmowała później wykrytej P2 logów.
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
