# Konfiguracja i odtwarzanie E4 - osoba 2

Wykonaj migracje jako calorie_app_migrator: `alembic -c backend/alembic.ini
upgrade head`. Bieżący head to 0011_e4_deletion; 0001–0008 pozostają
niezmienne. 0009 dodaje dowody/licznik/mapowania/rezerwacje, 0010 materializowane
sesje i wąskie prune, 0011 job/fence/purge. Readiness sprawdza dokładny head.

API/worker zachowują brak szerokiego DELETE rodziców, DDL i TRUNCATE.
Provisioning dodaje NOLOGIN calorie_app_deletion_operator; osobny login
operatora dostaje wyłącznie tę rolę, bez migratora/API/worker. Szczegóły ACL,
Keycloak i CLI są w [procedurze usunięcia](USUNIECIE_KONTA.md). Nie umieszczaj
service-secretów lub credentiali DB w APK/repo/logach.

## Operator w istniejącej instalacji E3

Nie uruchamiaj ponownie nieidempotentnego `init-db.sh` na używanej bazie.
Przed upgrade do 0011 administrator instancji (z prawem zarządzania rolami,
odrębny od migratora/runtime) wykonuje poniższy krok w docelowej `calorie_app`.
PUBLIC CONNECT musi być odebrany, jak w provisioningu E3. Połączenie admina
pochodzi z chronionego PG* środowiska/pgpass; nie wpisuj sekretu w argumenty.
Helper wymaga Python 3.13 i psycopg ze środowiska backendu według uv.lock,
serwera PostgreSQL 17 z kodowaniem UTF8 oraz uprawnień admina do zarządzania
rolami/prawami bazy i ustawienia ochronnych parametrów sesji. Runtime i migrator
nie otrzymują tych uprawnień. Bez wymaganych narzędzi lub ochrony jest błąd.
`DELETION_OPERATOR_LOGIN` i `DELETION_OPERATOR_PASSWORD` dostarcza menedżer
sekretów poza repozytorium. Login jest osobny, niesuperuserski, członek wyłącznie
roli operatora. Nazwa ma 1–63 bajty UTF-8, a hasło musi być niepuste; helper
sprawdza je lokalnie, nie przycina i nie normalizuje. NUL/niekodowalny Unicode
jest odrzucany. SASLprep i jego fallback wykonuje libpq, zgodnie z PostgreSQL.
Używaj nowego helpera, nie uruchamiaj pliku SQL bezpośrednio przez psql.

```text
python infra/local/provision_deletion_operator.py
alembic -c backend/alembic.ini upgrade head
python infra/local/provision_deletion_operator.py
```

Pierwsze/ostatnie polecenie wykonuje administrator; środkowe migrator ze swoim
DATABASE_URL. Python pochodzi ze środowiska backendu; admin dostarcza standardowe
PGHOST/PGPORT/PGDATABASE/PGUSER i chroniony PGPASSFILE/PGSERVICE lub PGPASSWORD.
PGDATABASE wskazuje docelową calorie_app. Helper nie przyjmuje sekretów/DSN
w argumentach. Przed 0011 skrypt tworzy brakującą NOLOGIN rolę i odrębny login,
daje CONNECT; po upgrade dodatkowo sprawdza USAGE, SELECT job i EXECUTE trzech
operatorowych funkcji. Nie nadaje nowych praw tabel, CREATE/TEMP/TRUNCATE,
migratora ani członkostwa API/worker. Przy nieoczekiwanych efektywnych prawach
kończy się błędem i rollbackiem. Hasło jest celowo ustawiane/rotowane przy każdym
uruchomieniu; nie są zmieniane dane aplikacji ani epoka.

Kontrola obejmuje również [efektywne prawa kolumnowe](https://www.postgresql.org/docs/17/functions-info.html#FUNCTIONS-INFO-ACCESS-TABLE)
SELECT/INSERT/UPDATE/REFERENCES przez has_any_column_privilege, dla LOGIN,
PUBLIC i odziedziczonych grantów NOLOGIN roli operatora. Sam has_table_privilege
nie wykrywa oddzielnego grantu kolumny. Wyjątek SELECT account_deletion_jobs
pozostaje; nie obejmuje jego kolumnowych INSERT/UPDATE/REFERENCES.

Odmowa provisioningu cofa wyłącznie jego własne zmiany. Zastane ACL, stare
hasło i dane pozostają takie jak przed próbą, więc błędny dostęp nie jest
automatycznie naprawiany. Administrator najpierw identyfikuje efektywny grant,
odbiera konkretną niepożądaną zgodę jej rzeczywistemu odbiorcy i ponawia helper.
Przykłady przetestowanego REVOKE dla potwierdzonego grantu weight_kg — wybierz
polecenie odpowiadające jego źródłu:

```sql
REVOKE SELECT (weight_kg) ON app.weights FROM PUBLIC;
REVOKE SELECT (weight_kg) ON app.weights FROM calorie_app_deletion_operator;
```

Dla grantu bezpośredniego użyj poprawnie cytowanej, potwierdzonej nazwy LOGIN;
dla INSERT/UPDATE/REFERENCES odbierz dokładnie stwierdzone prawo kolumny.
Nie zastępuj diagnozy zbiorczym odbieraniem cudzych praw. Po REVOKE helper
ponownie sprawdza efektywne ACL i rotuje hasło w tej samej transakcji.

## Ochrona hasła i weryfikatora operatora

Poprzednie SELECT length/format wysyłały jawne hasło do serwera. ECHO/QUIET
psql i password_encryption nie chroniły logów SQL; odtworzono trzy linie wycieku
przy log_statement=all i log_min_duration_statement=0, mimo czystego wyjścia
klienta. Helper używa [PQencryptPasswordConn](https://www.postgresql.org/docs/17/libpq-misc.html)
przez psycopg z jawnym algorytmem scram-sha-256. Weryfikator powstaje lokalnie;
jawne hasło nie trafia do żadnego SQL, również walidacji przed transakcją.

Od zestawienia połączenia helper narzuca i sprawdza ochronne startup options:
log_statement=none, log_duration=off, oba limity duration=-1, obie częstotliwości
sampling=0, log_min_error_statement=panic, oba limity parametrów=0,
log_min_messages=panic, log_error_verbosity=terse, statystyki SQL i
track_activities=off oraz search_path=pg_catalog,pg_temp. Wszystkie 17 ustawień
są sprawdzane; brak zgodności kończy pracę przed przekazaniem weryfikatora.
PGOPTIONS/opcje service nie mogą przywrócić logowania tej sesji. Globalne
ustawienia instancji i innych połączeń pozostają bez zmian. Komunikat klienta
jest stały, bez surowych wyjątków, parametrów, DSN lub treści SQL.

Weryfikator również jest poufny. Jest przekazywany jako parametr do lokalnego
ustawienia transakcji; stały DO ustawia hasło po kontroli ACL, przed wspólnym
commit. Parametryzacja sama nie chroni logów — konieczne są sprawdzone opcje
tej sesji. Regresja czyta rzeczywisty log serwera z włączonym logowaniem,
sprawdza osobno jawny sekret i zapisany weryfikator, także rotację i rollback.
Zwykłe połączenie kontrolne nadal zapisuje zapytania do tego samego logu.

Ochrona obejmuje sprawdzone wbudowane kanały [PostgreSQL 17](https://www.postgresql.org/docs/17/runtime-config-logging.html).
Nie daje gwarancji wobec niezależnych hooków/rozszerzeń audytu, proxy lub trace
libpq. O3 musi zweryfikować te elementy przed uruchomieniem. Weryfikator
pozostaje w pg_authid, pamięci procesów i chronionych kopiach bazy; administrator
bazy ma do niego dostęp. Sekrety środowiska/pamięci procesu także wymagają
ochrony systemowej. Połączenie poza loopback wymaga zaufanego TLS z verify-full
i właściwym certyfikatem CA. Testy loopback nie dowodzą produkcyjnego TLS.

DELETION_DATABASE_URL wskazuje ten rzeczywisty login, nie administracyjne
połączenie z SET ROLE. Odbiór obejmuje jego actual CONNECT, begin/status/resume,
odmowy private DML/DDL/TRUNCATE i brak operatora dla API/worker. Dodatkowy dowód
SCRAM oraz E3 bez wymaganej roli zachował prywatny graf i epokę. Migracje
0001–0011 pozostają niezmienne; nowa migracja nie jest potrzebna dla tego
provisioningu instancji. Nowy pusty klaster nadal korzysta z init-db.sh,
który uwzględnia CONNECT roli operatora.

API używa dotychczasowych DATABASE_URL/OIDC_ISSUER/OIDC_JWKS_URL i trwałego
CATALOG_PAGE_TOKEN_SECRET (32 losowe bajty jako hex). Sekret musi być zgodny
na replikach i po restartach przez okres wsparcia. Tokeny używają osobnego
prefiksu sync1; epoka E3 pozostaje trwała. Nie wyłączaj weryfikacji HTTPS.

Worker może wywołać `python -m calorie_app.modules.sync.retention <owner UUID>
--batch 1000` z własnym DATABASE_URL. Każda komenda ma własną transakcję;
funkcja app.prune_sync wymaga active owner, blokuje konto i licznik, używa
zegara DB i czyści ograniczone partie. Wykonuj okresowo, np. co godzinę,
aż raportowane partie spadną poniżej limitu. Mierz removed/latency/backlog
bez payloadów. Usuwane są stare szczegóły >=60 dni i wygasłe kopie; minimalne
receipts, rezerwacje, mapowania, żywe dane i rodzice/tombstones pozostają
do skoordynowanego usunięcia konta. Pełny prywatny graf purguje wyłącznie
potwierdzona procedura operatora.

Limity snapshotów: cztery sesje na konto, 100000 elementów/64 MiB każda,
1 MiB odpowiedzi/500 elementów łącznie, TTL60 min. Monitoruj jawne
sync_resources_exhausted; sprzątaj porzucone wygasłe kopie. Nie zwiększaj
limitów bez pomiaru. Rzeczywisty transport żądania jest ograniczony również
przy chunked/braku/kłamliwym Content-Length; reverse proxy może dodać zgodny
limit, ale nie zastępuje kontroli API.

## Restore i granice odbioru

1. Zatrzymaj API, workery i issuance dotychczasowego Keycloak; zachowaj kopię
   obu baz, konfiguracji i opublikowanych artefaktów. Rejestr ukończonych
   usunięć/blokad musi istnieć poza cofanym zestawem backupów.
2. Przywróć sprawdzoną kopię aplikacji i uzgodniony stan dostawcy. Porównaj
   deletion jobs/fences z niezależnym rejestrem; usuń lub zablokuj tożsamości
   usunięte po dacie kopii i uzyskaj potwierdzenie odcięcia issuance.
   Cofnięcie obu baz nie jest zgodą na przywrócenie skasowanych kont.
3. Przed ruchem nadaj nowy losowy sync_epoch w installation_state rolą
   migratora. Unieważnij stare sesje kontekstowo; klienci zachowują swoje
   dane i przechodzą świadome recovery. Nie restartuj starego outbox/AI.
4. Sprawdź role, head migracji, issuer/JWKS, stare JWT/refresh, B/katalog,
   snapshot+receipts, dwa urządzenia i mapowania. Dopiero wtedy otwórz API.

Odtwarzalna lokalna próba O2: `pytest backend/tests/integration/test_e4_restore.py`
z TEST_DATABASE_URL do nowej odseparowanej *_test bazy PostgreSQL17. Test
tworzy fizyczną kopię przez CREATE DATABASE TEMPLATE, przyjmuje późniejsze
zapisy, odtwarza starszą kopię w oddzielnej bazie i nadaje nową epokę przed
odczytami. Dowodzi zachowanych/brakujących receipts, braku potwierdzonego
rekordu, równej revision z inną treścią i świadomego nowego recovery.
Wymaga uprawnień testowego administratora do tworzenia swoich kopii;
runtime API/worker nie otrzymują ich. Test nie mierzy produkcyjnego RPO/RTO,
nie zastępuje restore obu baz z niezależnym rejestrem deletion ani KO-31 APK.

CI zachowuje contracts/quality/postgres/keycloak-pkce i ci-required.
Wykonuje klienta HTTP, migracje, ACL i real PKCE/usunięcie syntetycznej
tożsamości; brak usługi to FAIL. PR #10 Androida nadal jest niezależny:
gdy trafi na main, zachowaj również android-build/android-device w bramce
i ponów kontrole po integracji. Nie scalono go w ramach upoważnienia E4.
