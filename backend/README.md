# Backend E1/E2 - osoba 2

FastAPI na Pythonie 3.13, PostgreSQL 17, SQLAlchemy 2 i Alembic. E2 rozszerza fundament E1 o katalog, racje, kontrolowany import, eksport i publiczne odczyty wyłącznie opublikowanego official. Dane demo przekazujemy jako plik. Logowanie OIDC i chronione trasy produktów należą do E3, sync do E4; ich granice określają [kontrakty E0](../contracts/README.md).

## Struktura

- `src/calorie_app/main.py`: fabryka aplikacji, lifespan i kontekst żądania.
- `core/`: konfiguracja ze środowiska, bezpieczne błędy i logi JSON.
- `db/`: modele PostgreSQL oraz sesje; transakcję zatwierdza usługa wywołująca.
- `modules/catalog/`: modele, DTO/walidacja, repozytorium, usługi, eksport, router i CLI; także importer referencyjny bez DB/sieci.
- `data/demo/`: jawny seed wejściowy i osobny eksport z PostgreSQL dla O1.
- `health.py`: liveness procesu i readiness bazy/migracji.
- `migrations/`: niezmienne migracje Alembic; wykonywane osobno przed uruchomieniem API.
- `tests/unit/`, `tests/integration/`: testy transportu i prawdziwej bazy PostgreSQL 17.
- `openapi.json`: wygenerowany kontrakt wyłącznie wdrożonych endpointów.

## Uruchomienie z nowego checkoutu

Potrzebne: Git, Python 3.13, uv 0.9.5. Do standardowego lokalnego PostgreSQL potrzebny jest Docker z silnikiem Linux. Komendy poniżej wykonuje się z katalogu repozytorium; w PowerShell zmienne mają postać `$env:DATABASE_URL = '...'`, na Linuxie `export DATABASE_URL='...'`.

1. `uv sync --project backend --locked --python 3.13`.
2. Skopiuj `infra/local/.env.example` do `infra/local/.env` i ustal lokalne hasła. Są to oddzielne pliki konfiguracji infrastruktury i backendu.
3. `docker compose --env-file infra/local/.env -f infra/local/compose.yaml up -d --wait`.
4. Ustaw `DATABASE_URL` z rolą `calorie_app_migrator`, bazą `calorie_app` i sterownikiem `postgresql+psycopg`. Przykład lokalny: `postgresql+psycopg://calorie_app_migrator:local-dev-migrator@127.0.0.1:5432/calorie_app`.
5. `uv run --project backend --locked python -m alembic -c backend/alembic.ini upgrade head`.
6. Zmień `DATABASE_URL` na `calorie_app_api` z odpowiednim hasłem, np. z `backend/.env.example`. API nie korzysta z roli migratora. Plik `.env` jest czytany z bieżącego katalogu; można także używać wyłącznie zmiennych środowiska.
7. `uv run --project backend --locked python -m uvicorn calorie_app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log`.

`GET /health/live` daje 200 także podczas awarii bazy. `GET /health/ready` daje 200 dopiero dla PostgreSQL 17 z dokładną oczekiwaną migracją, w przeciwnym razie 503 z bezpiecznym błędem i identyfikatorem żądania. API nie tworzy tabel przy starcie. Żądania mają `X-Request-ID`, błędy pola `code`, `message`, `details`, `request_id`. Nie logujemy query, body, tokenów ani tekstu wyjątków mogącego zawierać sekrety.

Aktualny head to `0003_catalog_offline`, po niezmienionych `0001_foundation` i `0002_finite_nutrition`. Stara rewizja daje readiness 503, po upgrade bieżąca daje 200. CHECK `ck_product_versions_finite_nutrition` nadal dopuszcza w każdej z czterech kolumn wartości odżywczych `NULL` albo zakres `0..999999.999999`. `NULL` oznacza brak danych, zero pozostaje znanym zerem. NaN i wartości ujemne naruszają CHECK; przekroczenie precyzji oraz Infinity odrzuca typ `NUMERIC(12,6)`.

Migracja `0002` waliduje istniejące dane i zastępuje wyłącznie CHECK, bez przepisywania tabeli lub wartości. NaN pozostawione w starej bazie powoduje odmowę i rollback całej migracji, z zachowaniem danych, poprzedniego CHECK i rewizji. Przed upgrade rolą migratora sprawdź zakres wadliwych rekordów:

```sql
SELECT product_id, revision, energy_kcal, protein_g, fat_g, carbs_g
FROM app.product_versions
WHERE energy_kcal < 0 OR energy_kcal > 999999.999999
   OR protein_g < 0 OR protein_g > 999999.999999
   OR fat_g < 0 OR fat_g > 999999.999999
   OR carbs_g < 0 OR carbs_g > 999999.999999
ORDER BY product_id, revision;
```

PostgreSQL porządkuje NaN powyżej zwykłych liczb, więc zapytanie wykazuje również NaN. Zgłoś identyfikatory i kolumny wymagające korekty; uzgodnij ją z właścicielem danych. Nie zastępuj automatycznie wartości zerem ani `NULL` i nie usuwaj rekordów. [Dokumentacja PostgreSQL 17](https://www.postgresql.org/docs/17/datatype-numeric.html) opisuje NaN oraz ograniczenie precyzji Infinity.

Hasła z `.env.example` są wyłącznie demonstracyjne. Pliki `.env`, lokalne runtime’y, cache i dane bazy są ignorowane. Inicjalizacja Compose wykonuje się tylko dla pustego wolumenu: zmiana `.env` sama nie zmienia haseł istniejącej bazy. Nie usuwaj wolumenu z potrzebnymi danymi. Dane aplikacji i Keycloak mają osobne bazy i role. Serwer Keycloak, realmy i testy OIDC należą do E3; E1 tworzy jego bazę i konto techniczne.

## Weryfikacja

```text
uv run --project backend --locked ruff check backend
uv run --project backend --locked ruff format --check backend
uv run --project backend --locked python -m pytest backend/tests/unit
```

Do integracji ustaw `TEST_DATABASE_URL` na **dedykowaną** bazę z nazwą kończącą się `_test`, np. `calorie_test`. Testowy administrator musi mieć prawa tworzenia roli próbnej; ten credential nie jest rolą API. Testy usuwają schemat `app` tylko w tej jawnie testowej bazie i odmawiają działania bez konfiguracji. Nie zastępują PostgreSQL bazą SQLite i nie pomijają testów przy braku serwera.

```text
uv run --project backend --locked python -m pytest backend/tests/integration
uv run --project backend --locked python backend/export_openapi.py
uv build backend
```

Generowany OpenAPI obejmuje health oraz cztery publiczne odczyty E2. Projekt `contracts/openapi/design-v1.yaml` obejmuje niewdrożone operacje E3–E4 i nie dubluje przejętych operacji. Test porównuje wygenerowany dokument z wersjonowanym artefaktem. Zachowano regresję E1: migracje pustej bazy i poprawnych danych, rollback przy NaN w każdej kolumnie, rzeczywiste CHECK/SQLSTATE, NULL/zero/maksimum, prawa ról, readiness i izolację Keycloak. Testy E2 dodają upgrade z `0002`, niezmienność, atomowy import, publikację przy awarii i wyścigu, HTTP/snapshot, limity importera i pełny roundtrip PostgreSQL. SQLite służy wyłącznie importerowi referencyjnemu.

## CI i obraz

[Workflow](../.github/workflows/backend.yml) wykonuje kontrakty, Ruff, testy jednostkowe, integrację na PostgreSQL 17, budowę pakietu i obrazu. Zbiorczy `ci-required` wymaga sukcesu wszystkich zadań. Używa testowych danych i przypiętych SHA akcji; nie wdraża usług ani nie wywołuje Gemini. Techniczne wymaganie tego sprawdzenia w ochronie `main` ustawia O3 zgodnie z dostępnością funkcji GitHub.

Obraz `docker build -t calorie-backend:local backend` działa jako użytkownik bez praw roota. Migrację uruchamia się osobnym poleceniem z rolą migratora. Obraz zawiera moduł katalogu, wspólne wygenerowane zasoby schematów i jawny seed demo; nie potrzebuje `../contracts` ani `tools`. CI sprawdza rzeczywisty eksport PostgreSQL → gzip/manifest → referencyjny SQLite w zbudowanym obrazie, powtórzenie importu/eksportu oraz API z rolą wykonawczą. Osobna kontrola instaluje wheel i uruchamia go poza checkoutem.

## E2: kontrolowany import, eksport i publikacja

Operator pracuje z rolą `calorie_app_migrator` w kontrolowanym środowisku. API nie otrzymuje credentiala operatora i nie ma mutujących endpointów katalogu. Walidacja wejścia działa bez `DATABASE_URL`:

```text
uv run --project backend --locked python -m calorie_app.modules.catalog.cli validate --input backend/data/demo/seed.json
```

Po migracji `upgrade head` i ustawieniu `DATABASE_URL` operatora:

```text
uv run --project backend --locked python -m calorie_app.modules.catalog.cli import --input backend/data/demo/seed.json
uv run --project backend --locked python -m calorie_app.modules.catalog.cli export --package-id 47bdff67-e58b-5437-919b-ec00159afbc5 --release 1 --output backend/var/demo-export
uv run --project backend --locked python -m calorie_app.modules.catalog.cli publish --package-id 47bdff67-e58b-5437-919b-ec00159afbc5 --release 1
```

Import waliduje schemat/graf przed mutacją, a następnie zapisuje zależności i członkostwo atomowo. Identyczne ponowienie jest no-op. Inna treść UUID+revision, snapshotu źródła albo package_id+release jest konfliktem; poprawka wymaga nowej rewizji/źródła/wydania. Transakcyjna blokada serializuje kontrolę tożsamości także między pakietami. Nie pobieramy URL z danych. Pełny graph jest relacyjny; JSONB przechowuje tylko metadane, np. aliasy, uwagi i excluded_items.

Eksport odczytuje spójny snapshot PostgreSQL w repeatable read. Sortuje UUID/revision, serializuje UTF-8 i Decimal kanonicznie, stosuje gzip z `mtime=0` i bez nazwy. Data i release są ustalone w DB. SHA-256 manifestu dotyczy dokładnych bajtów gzip. Powtórzenie tego samego eksportera/danych daje identyczne bajty. CLI `export` nie publikuje metadanych DB. Jego katalog wyjściowy powinien być osobny dla każdego wydania; nie podmieniamy istniejącego manifestu/plików.

`publish` zapisuje kompletny plik przez fsync i atomowy hard link bez nadpisania, potem zatwierdza stan i monotoniczny active_release pod blokadą kanału PostgreSQL. Potrzebny jest jeden trwały lokalny filesystem obsługujący hard link, widoczny dla operatora i API. Magazyn rozdziela `demo/<package_id>/base-pl.<release>.json.gz` i `official/<package_id>/...`. `CATALOG_ARTIFACT_ROOT` wskazuje jego katalog główny: operator ma zapis, API odczyt. Nie wystawiać tego katalogu jako publicznego statycznego mountu. Błąd pliku/commit pozostawia poprzednie wydanie; osierocony plik nie trafia do API. E2 nie usuwa opublikowanych wersji.

Publiczne adresy `/api/v1/rations`, `/rations/{id}`, `/offline-package/manifest` i `/offline-package/{filename}` są na stałe związane z **official package_id `c12631e2-1a02-547c-a7f9-ebf87bb42e55`** (UUIDv5 z przestrzeni E0 i nazwy `official-base-pl-api-v1`). To tożsamość kontraktu, nie zmienna środowiska. Inny official package_id z tym samym release nie zmienia tych URL; nowa tożsamość wymaga osobnego kanału/kontraktu. Przy samym demo lista racji jest pusta, szczegół/manifest/plik daje 404. `include_demo=true` nie otwiera dostępu. Products HTTP pozostają E3 z prawdziwym OIDC; wewnętrzna usługa odczytu/wyszukiwania i DTO są gotowe.

Lista wybiera najnowszą rewizję racji w przypiętym release, porządek UUID; limit 1..500 (domyślnie 100). Nieprzezroczysty UUID token w DB wiąże release, limit i pozycję przez 60 minut; kolejne strony nie przedłużają TTL, zmiana limitu daje 422, wygaśnięcie 410 `page_expired`. To token listy katalogu, nie checkpoint sync. Bez revision szczegół wybiera aktywny release; z revision dokładne członkostwo dowolnego opublikowanego wydania tego samego pakietu. Starsze pliki pozostają dostępne. Gzip jest treścią `application/gzip`, Content-Length jest rozmiarem gzip, bez Content-Encoding. Reverse proxy nie może automatycznie rozpakowywać tych odpowiedzi.

`0003` zachowuje wszystkie stare rekordy. Ich brakujące metadane/content_hash pozostają NULL, nawet przy dawnym `verified`; nie kwalifikują się do pakietu. Uzupełnienie wymaga rzeczywistego nowego snapshotu źródła i nowej rewizji produktu, zaimportowanych kontrolowaną komendą. Nie przypisujemy fikcyjnych źródeł ani nie nadpisujemy starej wersji. DB blokuje zmiany zapieczętowanych danych, komponentów i członkostwa. API/worker mają odczyt nowych tabel; zapis do legacy skeletonu pozostaje ograniczony do dawnych kolumn E1. API może dopisywać tokeny listy. Role nie mają DDL ani zapisu historii migracji. Wygasłe tokeny można usuwać kontrolowanym zadaniem operatora, zachowując ważne tokeny i wszystkie wydania.

Referencyjny importer lokalny (bez DB/sieci):

```text
uv run --project backend --locked python -m calorie_app.modules.catalog.offline_import --database backend/var/catalog.sqlite --manifest backend/data/demo/export/manifest.json --package backend/data/demo/export/base-pl.1.json.gz --expected-package-id 47bdff67-e58b-5437-919b-ec00159afbc5 --expected-kind demo
```

Katalog `backend/var` utwórz przed pierwszym użyciem; jest ignorowany. [Opis importera](../tools/offline_catalog/README.md) podaje API staging/activation, a [integracja O1](../docs/e2/INTEGRACJA_O1.md) wymagane adaptacje Room/APK. Schematy edytuje się wyłącznie w `contracts/schemas`; `python backend/sync_catalog_schemas.py` generuje zasoby, `--check` weryfikuje ich zgodność. Testy i [raport E2](../docs/e2/RAPORT_E2.md) rozróżniają gotowość O2 od odbioru Androida. Brak oficjalnych etykiet pozostaje bramką E5. E3 nie jest rozpoczęte.
