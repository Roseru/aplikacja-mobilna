# Lokalny rollout backendu E9 — O3

13 października 2026 r., agent 3 / O3. **Wykonano upgrade rzeczywistej lokalnej
instalacji0021 → 0024 oraz odbiór API i istniejących workerów.**
Przyjęte źródło: main `2b4073e05d800fe3abc2388c17308323adf5ed56`,
[PR54](https://github.com/Roseru/aplikacja-mobilna/pull/54) i
[osobny odbiór main](ODBIOR_MAIN_O3.md).

## Kopia i próba przed zmianą źródła

Najpierw zbudowano nowy obraz oraz zachowano poprzedni image pod odrębnym tagiem.
Istniejące API nadal miało0021. Przy zatrzymanej bramce, API, Keycloak, retencji
i trzech workerach potwierdzono brak innych piszących klientów PostgreSQL.
Wykonano nowy paired backup obu rzeczywistych baz wraz z globals/SCRAM,
konfiguracją, realm, TLS i katalogiem. Odczyt manifestu zweryfikował sizes/SHA-256
i rzeczywisty source head0021; nie używano starej kopii0014.

Oba archiwa i role odtworzono w nowym, oznakowanym kontenerze PostgreSQL17,
bez portów gospodarza. Fingerprint kont/tożsamości obu baz był zgodny,
katalog bezpiecznie wyekstrahowano, a wartości wszystkich wcześniejszych kolumn
**78 tabel** porównano przed i po rzeczywistym upgrade kopii0021 → 0024.
Zachowano je oraz installation epoch i zamknięte bramki. Dopiero po tym PASS
wykonano migrację na źródle.

Z porównania identyczności celowo wyłączono trzy tabele kontraktu migracyjnego:
`alembic_version` zmienia head, `nemesis_runtime_contract` kwalifikuje nowe funkcje,
a `nemesis_releases` dostaje nowe release entries. To oczekiwane zmiany,
nie dowód niezmienności tych trzech tabel. Pozostałe wcześniejsze wartości
porównano przez uporządkowany JSON i SHA-256, bez ujawniania danych.

## Rzeczywista instalacja po migracji

- Źródło ma `0024_e9_history_graph`. Przed restartem porównanie tych samych
  78 tabel/kolumn, kont/tożsamości obu baz, epoki i CA/server.pem/server.key PASS.
- API i retencja używają nowego obrazu. Jednorazowy migrator również wymieniono,
  żeby późniejszy start bramki nie uruchamiał starego obrazu0021 przeciw0024.
- Minimalne istniejące LOGINy motivation/lifecycle/finalizer kwalifikowane przez
  aktualne provisionery; bez API/migratora/superusera jako workera.
- Rzeczywisty HTTPS/discovery/readiness, PKCE dotychczasowego konta oraz
  `GET me`, `GET me/motivation`, `GET me/energy/state` i historia energii:200.
  Tokeny pochodziły z istniejącego Keycloak; TLS i issuer sprawdzane, bez mock JWKS.
- Naturalny drugi minutowy cykl, UID10001, actual LOGIN, odmowy DDL/raw source/
  identity DB/SET ROLE oraz restart z zachowaniem epoki PASS.
- API, retencja, Keycloak, motivation i lifecycle działają. Finalizer ma stan
  disabled i nie jest deklarowany ready przy zamkniętym capability.
- `ai_controls.dispatch_open=false`, `nemesis_control.enabled=false`.
  Analiz E9, receipts E9 i osi z baseline/notice:0. Upgrade ani odczyt nie
  uruchomiły automatu; nie startowano provider worker lub Google I/O.

Runner zakończył się exit0. Własny kontener kopii usunięto po kontroli jego
ownership label; nie zatrzymywano obcych testów lub usług. Backup, poprzedni
image, fingerprinty i chronione logi pozostają poza Git. Neutralny receipt
SHA-256: `ccaede6c153fbf49e9b86ac04351a35582cb80a24f3aaef3cb46c9cf875968e5`.

## Sieć i granice

Zachowano istniejący origin/issuer `https://192.168.3.162:18443` oraz certyfikaty.
Gateway nadal binduje tylko `127.0.0.1:18443`, ponieważ dawny LAN adres nie jest
przypisany hostowi. Operatorowy probe przekierował wyłącznie socket do własnej
bramki, zachowując URL/Host/SNI/CA. To rzeczywiste HTTPS, lecz nie odbiór
osiągalności z telefonu lub publicznego internetu. Nie zmieniano DNS, hosts,
zapory, magazynu zaufania, tożsamości lub haseł.

Ten rollout nie potwierdza Room/UI/APK, pełnego E9/R/live Gemini, E10,
produkcyjnego RPO/RTO lub produkcyjnego wdrożenia. Następny wspólny scenariusz
jest w [odbiorze APK/API](../integracja/ODBIOR_APK_API_O2.md). O1 ma
[kontrakt energii](INTEGRACJA_O1.md), a O3
[wymagania konfiguracji](KONFIGURACJA_O3.md).

Dowód identyczności danych dotyczy migracji przy zatrzymanych writers.
Po wznowieniu użytkownik i retencja mogą normalnie zmieniać dane. Stary obraz
nie jest deklarowany zgodnym z nowym head; ewentualne odtworzenie kopii pozostaje
osobną procedurą z nową epoką i fencing/recovery, nie zwykłym restartem.
