# Własny nowy cel Docker po odtworzeniu

`docker_restore.py` materializuje sparowaną kopię z `backup.py` w **nowym**
projekcie i nowych wolumenach. Nie odtwarza źródła w miejscu i nie zatrzymuje
źródłowych usług. Operator osobno prowadzi kopię T0, późniejsze zapisy,
odcięcie źródła oraz rzeczywistą próbę Room27.

To lokalna procedura z odmową przy zmianie kont/tożsamości od T0. Przy takiej
zmianie potrzebna jest istniejąca uwierzytelniona rekoncyliacja ledgeru; adapter
jej nie zastępuje. Nie jest to procedura produkcyjnego cutover. `full_ko32=false`
i `client_recovery=NOT_RUN` pozostają do rzeczywistego odbioru klienta.

## T0 i zewnętrzne dowody

Użyj kwalifikowanego Pythona backendu oraz `PYTHONPATH=backend/src`.
Istniejące konta A/B muszą mieć ukończony bootstrap. Hasła i tokeny pozostają
w chronionym stanie; wynik `hold-sessions` podaje tylko SHA osobnego pliku.
Każda komenda wymaga jawnych `--docker-endpoint $HeldLocalSocket` oraz
`--engine-id $HeldEngineID`, odczytanych i zachowanych przez operatora przed
oknem. Akceptowany jest lokalny named pipe albo unix socket. Adapter usuwa
odziedziczone DOCKER_CONTEXT/HOST/TLS z procesów Docker, używa jawnego
`--host` i sprawdza engine ID przed każdą operacją, również binarnym restore
i odczytem źródłowego PG. Endpoint i ID trafiają do target record; fence/activate
odmawiają innego lub brakującego bindingu. Nie podmieniaj źródła adaptera
w trwającej próbie ani nie dopisuj bindingu do starego target record ręcznie.
Programmatyczne wywołanie wymaga najpierw
`configure_transport(endpoint, engine_id)`; bez niego Docker nie jest wywoływany.

```powershell
& $Python infra/integration/docker_restore.py hold-sessions `
  --state $Source --sessions "$Source/old-sessions.private.json" `
  --docker-endpoint $HeldLocalSocket --engine-id $HeldEngineID
```

W uzgodnionym oknie odetnij klienta. Dla nowej lokalnej dostawy użyj odebranego
[prywatnego profilu](LOCAL_RELEASE.md), przypiętego do rzeczywistych kontenerów
i pełnej chain base→MOCK→SPI→E8. Bound BACKUP zamyka **wszystkich** writerów,
także AI, E8 i SMTP, sprawdza zakończenie procesów oraz brak innych klientów PG.
Nie usuwaj sesji lub danych, aby wymusić poprawny wynik.

```powershell
& $Python infra/integration/local_release.py backup --profile $SourceProfile --backup $ArchiveT0
& $Python infra/integration/backup.py verify --backup $ArchiveT0
```

Zachowaj SHA-256 surowego `manifest.json` **teraz**, w niezależnym dzienniku
operatora poza cofanym zestawem. Nie wyliczaj nowego pinu przy odtwarzaniu.
Źródło pozostaje zatrzymane po BACKUP. Wznów je przez `local_release.py start
--profile $SourceProfile`, który zachowuje pełną przypiętą konfigurację i wymaga
świeżych sukcesów workerów. Dawny bezpośredni `backup.py capture` pozostaje
oddzielnym kontraktem i nie jest nowym bound trybem archiwizacji.
Dopiero potem wykonaj późniejszy posiłek/ACK i AI,
zachowując dokładne dane Room, receipt serwera i osobny świadek poza T0.

## Nowa fizyczna kopia PostgreSQL i Keycloak

Plik `$Images` zawiera dokładnie `postgres`, `keycloak`, `backend`, `gateway`:
lokalne immutable identyfikatory `sha256:...` sprawdzonych obrazów. Nie podawaj
tagów `latest` ani nie buduj nowego API podczas odtwarzania.

```powershell
& $Python infra/integration/docker_restore.py materialize `
  --archive $ArchiveT0 --manifest-sha256 $HeldManifestSHA `
  --state $NewTarget --project $NewProject --images $Images `
  --docker-endpoint $HeldLocalSocket --engine-id $HeldEngineID
```

Odmowa istniejącego katalogu, projektu, kontenera, sieci lub wolumenu poprzedza
mutacje. Dane są najpierw kopiowane i ponownie weryfikowane w prywatnym wejściu
celu. Odtwarzane są globals/SCRAM, obie bazy i katalog. Cel zachowuje issuer,
CA i klucz serwera oraz role T0. Nowa epoka zamyka AI/Nemesis i stare sesje;
historia limitów AI nie jest resetowana. Historyczna kopia bez markera zdjęć
tworzy pusty własny photo_data; nie domniemywa obecności plików.

Nowa sparowana kopia może zawierać jawne optional_photos/format1 i photos.tar,
objęte tym samym trzymanym zewnętrznie hashem manifestu. Tylko wtedy adapter
sprawdza prywatne regularne JPG/staging, rozmiar zgodny z PhotoStore i mtime,
a następnie kopiuje je do NOWEGO target photo_data przed dopuszczeniem API.
Zachowuje mtime dla istniejącej retencji i nadaje UID10001/0700/0600.
Nie zmienia quota, terminów, historii lub cleanup DB, nie wznawia jobów,
nie wysyła zdjęć i nie otwiera AI. Stary format bez markera zachowuje
dotychczasowe zachowanie. Bound BACKUP zapisuje marker także dla pustego magazynu.
Rzeczywisty odbiór opcjonalnego formatu
jest osobny od wcześniejszego odtworzenia pustego magazynu zdjęć.

Cel uruchamia tylko własne PG i Keycloak. Nie publikuje portu, nie uruchamia API,
AI lub retencji. Nie montuje `init-db.sh`, nie uruchamia Alembica, nie importuje
realmu. Keycloak używa `migration-strategy=validate` i `initialize-empty=false`.
Wynik `OFFLINE_TARGET_READY` oznacza wyłącznie ten materializowany zakres.

## Odcięcie, prawdziwy fence i przyjęcie klienta

W osobnym oknie zatrzymaj źródłowe API, issuer, gateway i wszystkie workery,
zachowując dane. Źródłowy PG może pozostać do odczytu niezależnego świadka;
inne połączenia PG powodują odmowę. Adapter wymaga identycznych od T0
fingerprintów kont i tożsamości; przy różnicy pozostawia cel zamknięty.

```powershell
& $Python infra/integration/docker_restore.py fence --state $NewTarget `
  --docker-endpoint $HeldLocalSocket --engine-id $HeldEngineID
& $Python infra/integration/docker_restore.py activate --state $NewTarget `
  --sessions "$Source/old-sessions.private.json" --sessions-sha256 $HeldSessionSHA `
  --docker-endpoint $HeldLocalSocket --engine-id $HeldEngineID
```

Fence publikuje wyłącznie maintenance na **tym samym** issuer/porcie po odcięciu
źródła. Obserwuje 503 dla API/token issuance, rzeczywisty logout-all i puste
sesje wszystkich zachowanych użytkowników. Następnie mierzy co najmniej421
rzeczywistych sekund zegarem monotonicznym i ściennym. Nie zmienia TTL, zegara,
`closed_at` ani epoki, aby skrócić oczekiwanie. Przerwany fence nie kwalifikuje
aktywacji; ponowna kwalifikacja zaczyna się od nowego logout/session boundary.

`activate` sprawdza dokładne zachowane access/refresh, wcześniej przyjęte przez
źródło: wymagane401 i `invalid_grant`. Błąd nawet częściowego startu zamyka
gateway/API. Dopiero `TARGET_AUTH_QUALIFIED` pozwala operatorowi rozpocząć
nowe Code+S256 i jawne odzyskiwanie w istniejącym ekranie Room27. AI celu
pozostaje zamknięte; mock nie zwalnia z336h rzeczywistej blokady po restore.

Zachowaj pierwotne źródło i oryginalny klient. Klient obserwujący nową epokę
celu pozostaje oddzielny. Po próbie najpierw odetnij cel, potem wznów oryginalne
źródło właściwym pełnym Compose. Nie odtwarzaj kopii T0 na źródle w celu powrotu.

Testy źródeł adaptera:

```powershell
& $Python -m pytest infra/integration/tests/test_docker_restore.py `
  infra/integration/tests/test_backup.py infra/integration/tests/test_recovery_o2.py -q
```

Testy syntetyczne, rzeczywista materializacja PG/KC oraz późniejsze TLS/fence
i Room27 mają odrębne dowody. Żaden z tych zakresów sam nie zalicza całego KO32.
