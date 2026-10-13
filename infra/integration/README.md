# Lokalne środowisko integracyjne — osoba 3

PostgreSQL 17 + API aktualnego checkoutu + Keycloak 26.8.0 na własnej bazie PostgreSQL.
Caddy dostarcza lokalny HTTPS. Obrazy usług i bazowy obraz Python są przypięte digestami,
a zależności backendu pochodzą z istniejącego `uv.lock`. Ten zestaw nie zastępuje
[izolowanego harnessu O2](../local/keycloak/README.md) ani nie zmienia jego fixture'ów.

## Uruchomienie

Wymagane: działający Docker z silnikiem Linux/Compose, Python 3.13 i uv.
Polecenia wykonuj z głównego katalogu repozytorium; działają na Windows i Linux:

```text
uv sync --project backend --locked
uv run --project backend --locked python infra/integration/run.py up
uv run --project backend --locked python infra/integration/run.py verify
uv run --project backend --locked python infra/integration/run.py status
```

Pierwsze `up` tworzy prywatny stan `.tools/local-integration/`, losowe hasła, trwały klucz
stron/sync, CA, certyfikat serwera i testowe konta A/B. Potem buduje obrazy, inicjuje bazy,
wykonuje migrację osobną rolą, uruchamia usługi i sprawdza API oraz issuer przez HTTPS.
Domyślny adres to `https://127.0.0.1:18443`; issuer ma końcówkę `/realms/calorie-dev`.

Aby przygotować adres osiągalny z emulatora lub telefonu, **przy pierwszym uruchomieniu**
podaj rzeczywisty lokalny adres IPv4 komputera, np.:

```text
uv run --project backend --locked python infra/integration/run.py up --host 192.168.1.50
```

Przykładowy IP zastąp swoim. Publikowany jest wyłącznie port HTTPS na wskazanym interfejsie;
nie bindujemy do `0.0.0.0`. Dla dostępu z LAN potrzebna jest osiągalność sieciowa i odpowiednia
reguła zapory gospodarza. Skrypt nie zmienia zapory, DNS, pliku hosts ani systemowego magazynu
zaufania. Adres i port są zapisywane na stałe: ich zmiana nie może po cichu zmienić tożsamości
kont `(issuer, sub)`. Przy DHCP utrzymuj ten adres przez rezerwację. `localhost` lub `127.0.0.1`
w emulatorze oznacza emulator, nie komputer. Nie zastępuj issuer adresem `10.0.2.2` tylko po
stronie Androida — musi być identyczny w discovery, JWT, API i aplikacji.

Inny niezależny zestaw wymaga **innego stanu i innej nazwy projektu**:

```text
uv run --project backend --locked python infra/integration/run.py up --state .tools/integration-2 --project calorie-integration-2 --port 18444
```

Istniejące wolumeny bez odpowiadającego im stanu blokują nową inicjalizację. Zachowaj oryginalny
stan; nie generuj nowych haseł do istniejących baz i nie usuwaj wolumenów jako sposobu naprawy.
`init` jest dostępny osobno, ale nigdy nie nadpisuje istniejącego katalogu.

## Usługi i dostępy

| Usługa | Dostęp i rola |
|---|---|
| PostgreSQL | Bez portu gospodarza; oddzielne bazy `calorie_app`, `keycloak`, lokalna `calorie_test` |
| `migrate` | Jednorazowy Alembic upgrade head, `calorie_app_migrator`; poprzedza API |
| API | UID 10001, `calorie_app_api`, bez DDL i dostępu do bazy Keycloak; filesystem read-only |
| Keycloak | UID 1000, rola `keycloak` wyłącznie we własnej bazie; tryb `start --optimized` |
| `retention` | UID 10001, wyłącznie `calorie_app_worker`; okresowe gotowe funkcje retencji O2 |
| `storage-init` | Jednorazowo ustawia właściciela własnego wolumenu katalogu; bez dostępu DB |
| Caddy | Jedyny opublikowany port; TLS, proxy API/OIDC/admin, bez access logów i cache |

Aktualny oczekiwany head to `0014_catalog_search`. Test pobiera wymagany head z backendu,
żeby późniejsza zgodna migracja O2 nie wymagała osobnego ręcznego przepisania liczby w teście.
Przed takim rolloutem O3 nadal sprawdza zgodność migracji i obrazu. API nie wykonuje DDL przy
starcie; role, ACL i wszystkie istniejące migracje O2 zachowano bez zmian.

API ma dokładny publiczny `OIDC_ISSUER` oraz zaufany wewnętrzny JWKS
`https://gateway:8443/realms/calorie-dev/protocol/openid-connect/certs`.
`OIDC_CA_BUNDLE=/run/trust/ca.pem` jawnie ustala prywatny CA. Hostname i certyfikat są sprawdzane;
`trust_env=False`, RS256, audience, subject, lifetime oraz pozostałe kontrole JWT pozostają.
HTTP działa wyłącznie między reverse proxy a usługami w prywatnej sieci kontenerów.
Publiczny issuer i JWKS widziany przez klienta używają HTTPS; `OIDC_ALLOW_LOCAL_HTTP=false`.

## Logowanie i zaufanie TLS

Realm `calorie-dev` korzysta z istniejącej konfiguracji O2, z `sslRequired=all`:

- publiczny `calorie-android`, Authorization Code, obowiązkowe PKCE S256;
- dokładne callbacki `pl.roseru.kalorie:/oauth2redirect` i
  `pl.roseru.kalorie.validation:/oauth2redirect`, bez wildcardów;
- istniejący opcjonalny zakres `profile` wyłącznie dla Androida, zgodny z `openid profile` O1;
- audience API `calorie-api`, role `user`, `catalog_moderator`, `admin`, TTL 300 s;
- pomocnicze publiczne klienty harnessu i negatywnego testu audience służą wyłącznie lokalnym
  testom, z dokładnym loopback callbackiem; nie są szablonem produkcji;
- losowe konta `integration-a`, `integration-b` i administrator `local-admin`.

Hasła odczytuj wyłącznie lokalnie w `.tools/local-integration/credentials.json`.
Nie kopiuj tego pliku do dziennika, PR, logów ani APK. Do konfiguracji zwykłej przeglądarki
można świadomie zaufać **wyłącznie publicznemu** `tls/ca.pem` w magazynie bieżącego użytkownika.
Testy Python i API jawnie używają tego pliku; nie wymagają instalacji CA w systemie.
[Odbiór APK 0.8.0](ANDROID_PKCE.md) opisuje zewnętrzny overlay z ograniczonym CA wyłącznie
dla wariantu validation oraz rzeczywiste próby Chrome/callbacku/A/B/gościa O3.
Istniejący realm dostaje opcjonalny profile przez jawny `android_scope.py`, bez ponownej
inicjalizacji; sam restart nie aktualizuje zaimportowanego klienta. O1 niezależnie odbiera
własny PR i następne adaptery HTTP/sync. Nie wyłączamy walidacji certyfikatów w APK.

CA jest ważny 730 dni, certyfikat serwera do 90 dni. Odnowienie certyfikatu serwera zachowuje
CA, issuer, hasła i klucz checkpointów; zatrzymuje tylko gateway, odtwarza jego mounty i
sprawdza HTTPS:

```text
uv run --project backend --locked python infra/integration/run.py renew-tls
```

Zmiana CA lub issuer wymaga osobnego planu migracji zaufania/tożsamości. Ponowna inicjalizacja
nie jest odnowieniem certyfikatu ani rotacją sekretu sync.

## Trwałość i zatrzymywanie

### Okresowa retencja i kontrola pracy

Usługa `retention` startuje z zestawem i od razu wykonuje ograniczony przebieg.
Następnie sprząta co godzinę, również dla kont bez ruchu HTTP. Używa istniejącego
`calorie_app.modules.sync.retention.prune`, bez nowych reguł kasowania. Na dostarczonym
head0014 obejmuje sync, prywatne sesje odczytu i minimalizację receipts community E6.
Funkcję i reguły retencji nadal utrzymuje O2; runner nie dodaje własnych reguł.
Upgrade E6 wykonuj według [rolloutu O2](../../docs/e6/KONFIGURACJA_O3.md):
zatrzymaj stare API/worker/publisher, wykonaj spójną kopię, następnie migrację i readiness.
Nie uruchamiaj starego obrazu API lub workera równolegle z migracją.

```text
uv run --project backend --locked python infra/integration/run.py worker-status
```

Status zawiera tylko agregaty: `last_attempt`, `last_success`, `last_full_sweep`,
`elapsed_seconds`, `owners`, `skipped`, `errors`, `removed`, `pending` i stan.
`last_success` oznacza udany **ograniczony przebieg**, nie pusty backlog;
`last_full_sweep` oznacza dojście do końca listy aktywnych kont, nie usunięcie wszystkich
zaległości. `pending` oznacza dalszą pracę albo osiągnięcie limitu; nie jest dokładnym
pomiarem liczby zaległych rekordów. Po błędzie lub przekroczeniu wieku sukcesu
healthcheck jest niezaliczony. Nie wystawiamy portu/HTTP monitoringu.

W prywatnym `worker.env` można ustawić: `RETENTION_INTERVAL_SECONDS` (domyślnie3600,
5–86400), `RETENTION_RETRY_SECONDS` (60,1–3600), `RETENTION_BATCH` (1000,1–1000),
`RETENTION_MAX_OWNERS` (1000,1–10000), `RETENTION_PASS_SECONDS` (120,1–300).
Zmiana konfiguracji wymaga odtworzenia tylko tej usługi z nowym env. Kolejne części
przebiegu lub próby po awarii startują po retry; po całym przebiegu bez zaległości
wraca interwał godzinny. SQL ma timeout2s, blokada wiersza1s; całkowity limit czasu
sprawdzany jest pomiędzy partiami, więc kończąca się partia może go nieznacznie przekroczyć.

Jedna partia i krótka transakcja na konto, maksymalnie100 identyfikatorów w stronie.
Trwały prywatny kursor w `worker_data` zapewnia kolejność i kontynuację bez zagłodzenia
kolejnych kont. Konto w usuwaniu jest pomijane; worker nie jest operatorem deletion.
Stare pełne odpowiedzi mogą zostać zminimalizowane, lecz minimalne receipts, żywe encje,
świeże sesje, mapowania i historia pozostają zgodnie z regułami O2.

Przebiegi używają jednej fizycznej sesji i
[blokady sesyjnej PostgreSQL](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS).
Druga kopia dostaje `busy`, nie sprząta i nie nadpisuje statusu właściciela blokady.
Utrata połączenia przerywa przebieg; nie ma ponownego połączenia bez blokady w trakcie
sprzątania. Zamknięcie sesji zwalnia blokadę; SIGTERM kończy bieżącą ograniczoną partię.
Status `running` jest zdrowy tylko z niedawnym wcześniejszym sukcesem; `failed` lub
`stopped` nie zalicza zdrowia, również gdy zachowano dawny czas sukcesu.

Pierwszy `up` istniejącej instalacji dopisuje brakujący `worker.env` z **dotychczasowym**
hasłem workera zapisanym w chronionym stanie. Nie nadpisuje istniejącego pliku ani nie
rotuje haseł, CA, issuer, klucza sync lub epoki. Worker nie dostaje innych credentiali.
Wolumen `worker_data` mieści prywatny kursor i agregaty, ma UID10001/0700, przetrwa down/up.
Runtime nie ma DDL, członkostwa operatora usunięć lub dostępu do bazy Keycloak.

Testy CI na rzeczywistym loginie workera sprawdzają wiele partii, konta A/B bez HTTP,
zachowanie danych i epoki, świeże/wygasłe sesje, proces okresowy, restart kursora,
konkurencyjną blokadę, timeout konta, przejście w deleting i utratę połączenia.
Próba całego zestawu dodatkowo sprawdza zdrowie/UID/ACL workera po restarcie.
Retencja nie jest harmonogramem AI/zdjęć, pełnym monitoringiem ani backup/restore.
Odrębne, opcjonalne usługi E8 opisano poniżej; nie zmieniają roli retencji.

## Opcjonalne workery E8

Istniejący wolumen sprzed E8 wymaga owner-only sprawdzenia/utworzenia brakujących
bazowych ról przed upgrade. Sam nowy init-db.sh działa wyłącznie przy pierwszej
inicjalizacji. [Odbiór aktualizacji E7→E8](../../docs/e8/AKTUALIZACJA_ISTNIEJACEJ_INSTALACJI_O3.md)
podaje minimalne atrybuty i rzeczywisty test zachowania historii/receipts/zgód.

Po aktualizacji własnego środowiska przez `run.py up` można przygotować i uruchomić
trzy usługi z odebranego backendu E8. W przykładach należy wskazać ten sam prywatny
`--state` co dla właściwego lokalnego zestawu. Polecenie `up` nie aktywuje Nemesis.

```powershell
uv run --project backend --locked python infra/integration/run_e8.py up
uv run --project backend --locked python infra/integration/run_e8.py status
uv run --project backend --locked python infra/integration/run_e8.py verify
```

`compose.e8.yaml` jest osobnym overlayem. Zwykły `run.py up` nie dołącza go.
`motivation`, `nemesis-lifecycle` i `nemesis-finalizer` otrzymują trzy różne
SCRAM LOGINy, tworzone wyłącznie istniejącymi hardened provisionerami O2.
Ich hasła pochodzą z prywatnych plików środowiska; ponowny `up` zachowuje je.
Usługi nie otrzymują administracyjnych PG* ani haseł pozostałych usług.
Provisioner ma odrębny, jednorazowy kontener administracyjny. Nie dopisujemy
uprawnień do API, retencji ani Keycloak i nie zmieniamy opublikowanych migracji.

Każdy runner uruchamia zainstalowany CLI przez `python -I`, jako UID10001,
bez surowego źródła lub editable. Start nadrabia pierwszą ograniczoną partię;
dalsze wywołania rozpoczynają się co60s. Procesy nie nakładają się w jednej
usłudze. Domyślny timeout55s przerywa zbyt długi proces, który zamyka połączenie
i wycofuje otwartą transakcję. Gdy historia wymaga dłuższej pracy, można jawnie
ustawić `E8_PASS_TIMEOUT_SECONDS=5..300` w prywatnym pliku danej usługi;
długi cykl opóźnia następny. SIGTERM kończy runner i jego dziecko. Utrzymujemy
jedną replikę każdej usługi dla jednoznacznego statusu jej prywatnego wolumenu.

Status przechowuje tylko allowlistę agregatów, `last_attempt`, `last_success`,
czas przebiegu i stan. `pending` oznacza udany bounded batch z zaległością.
Motywacja raportuje faktyczny backlog i najstarszą maturity, finalizer due
backlog. Lifecycle raportuje liczby transitions/pruned; pełna partia oznacza
możliwą dalszą pracę, nie pomiar całego backlogu. Brak timestampu, błąd,
timeout, przyszła/stara data lub `disabled` dają unhealthy. Zwykły healthcheck
nie restartuje kontenera: `unless-stopped` odtwarza zakończony proces, a operator
reaguje na unhealthy i zaległości. Prywatne wolumeny zachowują ostatni status
przez restart; sukces jest aktualizowany dopiero po właściwym przebiegu CLI.

Domyślnie zamknięty finalizer zwraca `disabled`, `ready=false` i unhealthy.
To oczekiwany sygnał, a nie powód do automatycznej aktywacji. Operator po własnym
odbiorze pakietu, migracji, ACL i manifestu może świadomie wykonać:

```powershell
uv run --project backend --locked python infra/integration/run_e8.py activate
```

Polecenie korzysta z istniejącego owner-only `e8n_activate` bieżącej epoki.
Nie zastępuje rzeczywistego odbioru O1 lub produkcyjnego rollout. `verify`
wymaga zamkniętej bramki i sprawdza startup, drugi naturalny minutowy cykl,
efektywne LOGINY/UID oraz restart bez rotacji epoki. CI uruchamia ten odbiór
na własnym zestawie; receipt nie zawiera sekretów lub identyfikatorów kont.
Nie należy uruchamiać tej próby restartu na cudzym współdzielonym środowisku.

Przed zatrzymaniem własnego zestawu zatrzymaj także opcjonalne workery:

```powershell
uv run --project backend --locked python infra/integration/run_e8.py stop
uv run --project backend --locked python infra/integration/run.py down
```

Nie usuwa to wolumenów. Pełny lokalny odbiór przetwarzania danych i granice
produkcji/restore opisuje [raport O3](../../docs/e8/ODBIOR_O3_WORKERY.md).

```text
uv run --project backend --locked python infra/integration/run.py down
uv run --project backend --locked python infra/integration/run.py up
```

`down` nie usuwa wolumenów. Obie bazy oraz artefakty katalogu pozostają w named volumes;
sekrety, import początkowy i CA pozostają w prywatnym stanie. Keycloak pomija istniejący realm
podczas kolejnego importu, więc nie zeruje kont. API montuje katalog tylko do odczytu;
operator z tego samego obrazu może go montować do zapisu. Nie promujemy danych demo do official.
Klucz `CATALOG_PAGE_TOKEN_SECRET` nie zmienia się przy restarcie, nowym buildzie ani odnowieniu TLS.

Stan jest ignorowany przez Git; w POSIX ma katalog 0700, a na Windows inicjalizacja ogranicza
NTFS ACL do bieżącego użytkownika i SYSTEM. Plik importu realm z testowymi hasłami jest czytelny
dla kontenera Keycloak, ale jego katalog nadrzędny pozostaje prywatny. Nie udostępniaj całego stanu.
Wolumeny i stan są powiązaną instalacją — oba należy zachować. Kopie i kontrolowany restore
z nową epoką oraz rejestrem usunięć należą do osobnego zadania; zwykły down/up nie jest restore.

## Prywatna kopia i odizolowana próba odtworzenia

Po lokalnym odbiorze workerów można wykonać spójną kopię własnego zestawu.
Wskaż jego konkretny `--state` i nowy prywatny `--backup` poza Git. Przykład:

```powershell
uv run --project backend --locked python infra/integration/backup.py capture --state .tools/local-integration --backup .tools/paired-backup-1
uv run --project backend --locked python infra/integration/backup.py verify --backup .tools/paired-backup-1
uv run --project backend --locked python infra/integration/backup.py rehearse --backup .tools/paired-backup-1
```

Capture zatrzymuje ruch i wszystkich piszących klientów, włącznie z Keycloak;
kopiuje obie bazy, role/SCRAM, konfigurację/TLS i katalog. Pozostawia źródło
zatrzymane. Rehearse odtwarza nowy własny PG bez publicznego portu, nadaje nową
epokę i wykonuje fence/cleanup z zamkniętym AI/Nemesis, sprawdza katalog oraz
rzeczywisty LOGIN finalizera, po czym usuwa tylko własny kontener próby.
Nie przywraca danych do istniejącej instalacji i nie otwiera API.

Archiwa, konfiguracja, manifest i raw logs są prywatne i zawierają dane/sekrety.
CI publikuje wyłącznie neutralny receipt. Wymagania przed rzeczywistym reopen,
wykonane pomiary i granice RPO/RTO opisuje [raport](../../docs/e8/KOPIA_ODTWORZENIE_O3.md).

Osobna [pełna lokalna próba odtworzenia](../../docs/e8/ODTWORZENIE_SESJE_I_KLIENT_O3.md)
obejmuje prawdziwe sesje HTTPS/PKCE, deletion wykonaną po kopii, niezależny
lokalny rejestr, odcięcie starego JWT/refresh i świadome recovery po zmianie epoki.
Nie zmienia zachowania `rehearse`: ta komenda nadal kończy się z zamkniętym ruchem.
Produkcyjny rejestr, docelowe środowisko, RPO/RTO i Room/APK wymagają własnego odbioru.

## Co sprawdza `verify`

Test wykonuje rzeczywiste żądania HTTPS, podpisane tokeny z Keycloak i API z PostgreSQL:

- discovery/issuer/readiness oraz odrzucenie nieznanego CA;
- oba callbacki Androida, podpis ID tokenu i nonce, prawidłowy access token;
- odmowę ID tokenu, błędnego JWT/audience, brakującego/błędnego PKCE, replay code,
  password grant i niedozwolonego redirectu;
- bootstrap i jego replay, izolację kont A/B, mutację zgody i pełny checkpoint sync;
- rzeczywisty head migracji, brak uprawnień DDL API, izolację baz i brak ich publicznych portów;
- UID API/Keycloak, zapis plików przez operatora i odmowę zapisu z API;
- pełny down/up oraz zachowanie kont obu baz, danych, epoki, receipts, ważności wcześniejszego
  checkpointu i zawartości katalogu.

`verify` zakłada przez administracyjne API Keycloak własną nową parę kont
`integration-probe-<losowy-sufiks>-a/b`. Ich losowe hasła zapisuje tylko w prywatnym stanie.
Nie zeruje wcześniejszych kont ani snapshotów i nie zmienia limitu czterech aktywnych sesji.
Konta testowe pozostają w lokalnej instalacji; to dane techniczne, nie konta rzeczywistych osób.
Konta startowe A/B pozostają do pracy ręcznej. Test zatrzymuje usługi na czas down/up
i pozostawia działający zestaw. Nie uruchamiaj go w produkcji.
Wynik bez sekretów to `verification.json`; prywatne `compose.log` i `operation-error.log`
pomagają w diagnozie. Nie publikuj całego katalogu stanu ani tych logów automatycznie.

Job `local-integration` odtwarza osobny zestaw na loopback runnera, wykonuje tę samą próbę i
publikuje wyłącznie receipt na 14 dni. Jest obowiązkową zależnością `ci-required`; failure,
cancelled lub skipped nie zalicza integracji. Istniejące kontrole Androida, PG i harnessu O2
pozostają obowiązkowe. Testy TLS obejmują prawdziwy lokalny serwer JWKS, nie mock transportu.

## Granice odbioru

To działająca infrastruktura lokalna. Podstawowy `verify` nie potwierdza podłączenia obecnego APK,
KO-31, kompletu official ARPOL, publicznego VPS/domeny/SMTP ani restore/RPO/RTO.
Minutowe workery E8 mają odrębny `run_e8.py verify` i lokalny odbiór opisany wyżej.
O1 otrzymuje issuer/API, publiczny CA i konfigurację klienta; osobne próby sesji konkretnego
APK O1/0.8.0 i ich ograniczenia dokumentuje [odbiór O3](ANDROID_PKCE.md).
O2 zachowuje kontrakty i kod logiki. Publiczny deployment oraz kopie/restore są kolejnymi etapami.

Przypięte obrazy Python/PostgreSQL pobieramy z Docker Hub z tymi samymi SHA256
co wcześniejszy mirror ECR. [Opis i faktyczny odbiór](REGISTRY.md) zachowuje
historię błędów429; failure/skipped nie jest sukcesem kontroli.

Źródła konfiguracji: [Keycloak containers](https://www.keycloak.org/server/containers),
[Keycloak hostname](https://www.keycloak.org/server/hostname),
[Caddy TLS](https://caddyserver.com/docs/caddyfile/directives/tls),
[HTTPX SSL](https://www.python-httpx.org/advanced/ssl/).
