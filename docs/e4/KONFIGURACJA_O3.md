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
`DELETION_OPERATOR_LOGIN` i `DELETION_OPERATOR_PASSWORD` dostarcza menedżer
sekretów poza repozytorium. Login jest osobny, niesuperuserski, członek wyłącznie
roli operatora. Skrypt konfiguruje SCRAM i bezpiecznie ponawia te same kroki.

```text
psql -X -w --dbname calorie_app --file infra/local/provision-deletion-operator.sql
alembic -c backend/alembic.ini upgrade head
psql -X -w --dbname calorie_app --file infra/local/provision-deletion-operator.sql
```

Pierwsze/ostatnie polecenie wykonuje administrator; środkowe migrator ze swoim
DATABASE_URL. Przed 0011 skrypt tworzy brakującą NOLOGIN rolę i odrębny login,
daje CONNECT; po upgrade dodatkowo sprawdza USAGE, SELECT job i EXECUTE trzech
operatorowych funkcji. Nie nadaje nowych praw tabel, CREATE/TEMP/TRUNCATE,
migratora ani członkostwa API/worker. Przy nieoczekiwanych efektywnych prawach
kończy się błędem i rollbackiem. Hasło jest celowo ustawiane/rotowane przy każdym
uruchomieniu; nie są zmieniane dane aplikacji ani epoka.

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
