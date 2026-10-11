# Niezależny odbiór E4 - osoba 2

## Niezależny odbiór poprawki praw kolumnowych

Recenzent `e4_column_review` nie jest autorem SQL, testów ani dokumentacji.
Sam zachował baseline aa4d97c i odtworzył 6 przypadków SELECT/UPDATE × LOGIN/
PUBLIC/operator-role na swoim PG17/SCRAM (również admin). Stary helper exit=0,
table privilege=false, any-column=true. Trzy real LOGIN czytały prywatną wagę;
UPDATE odmawiał 42501 i nie zmieniał danych. Osobno nowy test ze starym helperem
dał oczekiwany FAIL, bez sekretu/DSN/raw logu w diagnostyce.

Po minimalnej zmianie sam wykonał 36 fixed probes czterech praw, trzech źródeł
i fresh/E3 przed/po 0011: odmowa zachowała hasło, membership, database/column
ACL i hash wszystkich tabel; stary sekret działał, odrzucony nowy nie. Po
administracyjnym REVOKE helper działał. Dozwolony job SELECT zachowany; jego
kolumnowe I/U/REFERENCES nie otrzymały wyjątku.

Własna regresja: **600 unit + 70 column + 33 real server-log/SCRAM + 30 real
operator LOGIN/CLI/ACL = 733 PASS**, bez skip/fail. Nie jest to deklaracja
wykonania całych 571 PG ani lokalnego Keycloak. Pierwsze błędy zastanego
systemowego TEMP ponowił z własnym basetemp; bez zmiany źródeł/uprawnień TEMP.
Ruff z jawnym backend config i diff check PASS. Własne procesy zatrzymane.

Globalne intensywne logi aktywne; 0 sekretów/weryfikatorów. Sprawdzono minimalne
has_any_column_privilege wraz z zachowaniem wcześniejszych kontroli tabel,
PUBLIC/dziedziczenie, rollback własnych zmian i zachowanie zastanego grantu.
O3/usunięcie konta zgodne z wykonaniem: administrator identyfikuje i świadomie
odbiera konkretny grant, dopiero wtedy ponawia helper. **9,5/10, brak
nierozwiązanych P1/P2 lub istotnych uwag**. Ocena wynika z własnych dowodów,
nie z samego odczytu kodu. Końcowy raport i CI pozostają osobnym odczytem.

Root osobno odczytał [CI 38098862007](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38098862007)
head `c7b74480af38ee1e8cd3f9bd210cb1c8b92e8ced` / baza `e392d1f`: pięć jobów
success, 600 unit + 571 PG17.11 + 9 real Keycloak = 1180 PASS i oba buildy/smoke
obrazu. To zdalny dowód, oddzielony od moich 733. Sprawdzono również zachowanie
wpisów O2-003–005/007 i mastera po zwykłym merge dokumentacyjnego main.
Ostatni commit dokumentacji wymaga osobnego CI, którego exact head wskazuje PR.

## Historyczny odbiór ochrony sekretu

Poniższe 9,5/1110 nie obejmowały późniejszego P2 uprawnień kolumnowych.

Recenzent `e4_fix_review` nie jest autorem helpera, SQL, testów ani dokumentów.
Sam zachował stary SQL z `c9bdac0` i odtworzył **3 linie jawnego sekretu w logu
serwera, 0 w kliencie** na osobnym PG17.11 z SCRAM również dla admina.
Statement/duration/sampling/transaction/error/parameter logging było aktywne.

Sam przeanalizował i wykonał poprawkę po ostatnim hardeningu 17 startup GUC:
lokalna walidacja bez normalizacji, rzeczywiste PQencryptPasswordConn z jawnym
SCRAM, bind weryfikatora i stały DO, wspólna transakcja role/ACL/hasło.
Na niechronionej kontrolnej sesji samo wyliczenie SCRAM dawało **0 SQL**;
algorithm=None był dodatnią kontrolą SQL. PQtrace na użytym Windows binary
nie było obsługiwane, więc dowód stanowi rzeczywisty log serwera.

Własne powtórzenia/rotacja i nowe niepoolowane połączenia przyjmowały nowe
hasło, odrzucały stare/błędne. Apostrofy, quotes, Unicode, spacje na początku/końcu
i quoted Unicode LOGIN działały. Na E3 oraz po upgrade do 0011 wszystkie
tabele i epoka były identyczne przed/po uruchomieniu helpera. Rollback przy
błędzie ACL oraz własna
prywatna kopia z awarią po ALTER przed commit przywracały poprzedni weryfikator
i logowanie. W kodzie produkcyjnym nie ma testowego przełącznika awarii.
Rzeczywisty operator-only LOGIN/CLI działał; private SELECT/DML, DDL/TEMP,
TRUNCATE i SET ROLE API/worker/migratora odmawiały. Brak prawa SET admina
kończył się przed przekazaniem weryfikatora lub zmianą roli.

**0 trafień nowego jawnego hasła i 0 weryfikatora w serwerze/kliencie**, także
startupu, błędu i rollbacku; globalne logi nadal aktywne, kontrolne sesje piszą
do tego samego logu. Własna nowa regresja recenzenta: **600 unit + 33 real
PG server-log + 30 poprzednich real LOGIN/CLI/ACL = 663 PASS**, bez skip/fail.
Nie jest to deklaracja wykonania przez recenzenta całych 501 testów PG.
Ruff/format/helper i diff check PASS; instrukcje O3/usunięcia są zgodne.

**9,5/10, brak nierozwiązanych P1/P2 lub istotnych uwag.** Uzasadnienie:
odtworzona przyczyna, brak jawnego hasła w SQL, sprawdzona biblioteka,
osobno wykazana ochrona weryfikatora i zachowana rotacja/transakcja/ACL/dane.
Ochrona dotyczy wbudowanych kanałów PG17. Weryfikator pozostaje poufny w
pg_authid, pamięci i backupach; DBA/OS, dodatkowy audit/proxy/trace oraz
produkcyjny TLS wymagają własnych zabezpieczeń O3. Odczyt raportu i dokładnego
końcowego CI pozostaje osobnym dowodem. Dawne 1046 PASS nie obejmowały P2.

Root osobno odczytał [CI 38095748566](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38095748566)
head `73a2be9ac26132056eeb8b7cef86aea7a6bebc3c`: pięć jobów success,
600 unit + 501 PG17.11 + 9 real Keycloak = 1110 PASS oraz oba buildy/smoke
obrazu. To zdalny dowód, oddzielony od moich 663 lokalnych PASS. Ostatni commit
dokumentacji ma własny ponowny CI wskazany w PR i końcowej odpowiedzi.

## Historyczny odbiór czterech wcześniejszych usterek

Ówczesna ocena runtime: **9,5/10**; późniejszy odbiór znalazł P2 logów hasła.
Recenzent `e4_fix_review` nie jest autorem ocenianych plików. Sam wyeksportował
stary `2cdf513` i odtworzył wszystkie cztery usterki na osobnej PostgreSQL17.11,
dwóch SQLite i rzeczywistym HTTP. Decimal/Unicode zostawiały prefix, daty500;
duża kolejka nie wysyłała nic, drugi Goal był blokowany, real LOGIN nie miał
CONNECT. Dawne 885 PASS / 9,2 nie potwierdzały poprawności tych granic.

Po poprawce sam: **569 unit + 468 PostgreSQL + 9 real Keycloak = 1046 PASS**,
zero skip/fail. Własne 26 real HTTP paczek z dobrym prefixem i złą drugą operacją:
422 oraz identyczny hash wszystkich tabel. Poprawne Unicode/emoji, zero/null
działają. 8 Meal payload145893B:porcje 7/1, lostACK/restart/replay, identyczne
wire/ID/hash/originals;1 MiB/+1 oraz różne checkpointy UTF-8 sprawdzone.
Dwa urządzenia Goal:A ACK→B snapshot/restart→istniejący target/oś 1; odmowy
innej treści/typu/usuniętego targetu i nowej decyzji starej osi sprawdzone.

Real operator-only LOGIN bez PUBLIC CONNECT: idempotentny provisioning,
begin/status/resume/retry, privateSELECT/I/U/D/TRUNCATE/schemaDDL/TEMP odmawiają;
API/worker bez operatora. Własny cały CLI z Keycloak/PKCE: confirmation/purge A,
odmowa refresh/staregoJWT, B/katalog identyczne. Autor osobno odtworzył E3 bez
roli operatora oraz SCRAM poprawnym/błędnym zewnętrznym sekretem.
Ruff/format 128, E0/OpenAPI/resources, finalny wheel/sdist i Python -I poza
checkoutem: PASS. Własne dodatkowe Decimal/time/limit probes po ostatniej
zmianie kolejności kontroli transportu: PASS. Końcowe dokumenty i CI są osobno
odczytywane; Room/APK/produkcja pozostają odbiorem O1/O3.

Po pierwszym CI poprawki recenzent sam odtworzył błąd fixture operatora
z `080ef07` na nowym klastrze ze SCRAM dla wszystkich połączeń, także admina:
brak hasła LOGIN powodował odmowę uwierzytelnienia przed bramką CONNECT.
Przeczytał minimalną poprawkę ustawiającą hasło przed próbą i ponowił cały
moduł: **30 PASS / 16,07 s**, fresh oraz upgrade E3. Własne dodatkowe próby
rozróżniły błędny sekret (odmowa uwierzytelnienia) od poprawnego (odmowa
CONNECT przed provisioningiem, połączenie po dwukrotnym provisioningu).
Asercje, ACL i runtime nie są osłabione; ocena runtime 9,5 pozostaje aktualna.

Root osobno odczytał [CI 38092517302](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38092517302)
head `10232289b039256dec3db1796cb72ac01d1f1d93`: pięć jobów success,
1046 PASS i oba buildy/smoke obrazu. To dowód zdalnego CI, oddzielony od
powyższego własnego wykonania recenzenta. Końcowy commit dokumentacji
wymaga osobnego odczytu jego CI wskazanego w PR i końcowej odpowiedzi.

## Historyczny odbiór przed osobną recenzją

Poniższa 9,2 nie obejmowała wykrytych później czterech usterek. Dla poprawki
obowiązuje powyższa 9,5 z własnym wykonaniem, nie samą oceną liczbową.

Ocena końcowej implementacji: **9,2/10**, brak istotnych nierozwiązanych
usterek. Recenzent e4_review nie jest autorem ocenianych modułów. Używał
osobnej bazy PostgreSQL17.11, oddzielnych SQLite i własnego efemerycznego
realmu Keycloak; nie zaliczał odczytu kodu lub fixtures jako PASS integracji.

Sam wykonał pełne 469 unit + 401 PostgreSQL + 9 real Keycloak/PKCE =
879 PASS, bez skipów. Po ostatniej drobnej zmianie sprawdzania dokładnej
wersji produktu ponowił cały push/live HTTP: 29 PASS, w tym nowe granice
chunked i counterMAX. Dodatkowa własna próba istniejącego product_id z
brakującą dokładną revision dała trwałe dependency_missing bez półzapisanego
dnia; rzeczywisty BIGINT MAX nie utworzył receipt ani encji i nie zawinął H.

Własne probes obejmują foreign source i inny typ, równoczesny RecoveryMapping,
usunięty target, stabilny final checkpoint/TTL, rzeczywiste bajty/+1/zero DML,
SELECT1/0 po pierwszym commit i retry prefixu, trwałe SQLite i 12→6/underflow,
A→B→A oraz trzy dowody pg_blocking_pids: rollback pierwszej transakcji,
DB clock po oczekiwaniu i prefix przed wygaśnięciem checkpointu. Dziewięć
pierwszych zostało dołączonych do regresji jako test_e4_independent_regressions.

E0/schematy/scenariusze, Ruff, zasoby, sdist/wheel oraz Python -I po instalacji
poza checkoutem: PASS. Recenzent porównał 66 runtime plików PY/JSON wheel
z końcowymi źródłami. Przejrzał dokumenty E4 i poprawione reguły preflight/prefix
w wymaganiach i E0.

Pierwsza pełna niezależna regresja miała 320 PASS/72 FAIL z powodu nowego
testu upgrade, który odtwarzał schemat bez jego default ACL. Naprawiono wyłącznie
fixture, zachowując rzeczywisty provisioning; końcowy pełny przebieg 401 PASS.
Pierwszy counterMAX test ustawiał nieistniejący jeszcze licznik (UPDATE0rows).
Naprawiono seed INSERT/ON CONFLICT i ponowiono właściwe testy. Problemy te
nie są ukryte przez skipy lub poszerzanie praw produkcji.

Rzeczywisty test provider używał osobnego service account bez master/realm-admin,
syntetycznego usuwanego A i niezależnego B. Potwierdzono PKCE, odmowę
nieuprzywilejowanego service account, DELETE/authorized absence/crash retry,
odmowę refresh/login i starego JWT oraz niezmienny B/katalog.

Po publikacji niezależnie wykonano jeszcze cały zestaw sześciu live HTTP
(6 PASS/9,87s), w tym nowy fizyczny restore PostgreSQL z dwoma trwałymi
SQLite, restartem i równoczesnym recovery do jednego targetu. Oryginały
oraz immutable wire zachowane. Ówczesny runtime pozostał bez zmian; ówczesna ocena 9,2 dotyczy tamtego odbioru.

Ocena dotyczy backendu/klienta O2. Końcowy zdalny CI odczytuje autor po push;
Room/APK/WorkManager/KO-31 i produkcyjny restore obu baz z zewnętrznym
rejestrem usunięć pozostają odbiorem O1/O3. Nie wykonywano merge E4/E5.
