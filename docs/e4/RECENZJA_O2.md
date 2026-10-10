# Niezależny odbiór E4 - osoba 2

## Ponowny odbiór poprawki 11 października 2026

Aktualna ocena runtime: **9,5/10**, brak istotnych nierozwiązanych usterek.
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
