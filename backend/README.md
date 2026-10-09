# Backend E1 - osoba 2

FastAPI na Pythonie 3.13, PostgreSQL 17, SQLAlchemy 2 i Alembic. E1 udostępnia dwa rzeczywiste endpointy health i pierwszą migrację kont/katalogu. Profile, logowanie OIDC, katalog publiczny i sync będą wdrażane w kolejnych etapach według [kontraktów E0](../contracts/README.md).

## Struktura

- `src/calorie_app/main.py`: fabryka aplikacji, lifespan i kontekst żądania.
- `core/`: konfiguracja ze środowiska, bezpieczne błędy i logi JSON.
- `db/`: modele PostgreSQL oraz sesje; transakcję zatwierdza usługa wywołująca.
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

Aktualny head to `0002_finite_nutrition`, zależny od niezmienionej `0001_foundation`. Stara rewizja daje readiness 503, po upgrade bieżąca daje 200. CHECK `ck_product_versions_finite_nutrition` dopuszcza w każdej z czterech kolumn wartości odżywczych `NULL` albo zakres `0..999999.999999`. `NULL` oznacza brak danych, zero pozostaje znanym zerem. NaN i wartości ujemne naruszają CHECK; przekroczenie precyzji oraz Infinity odrzuca typ `NUMERIC(12,6)`.

Migracja waliduje istniejące dane i zastępuje wyłącznie CHECK, bez przepisywania tabeli lub wartości. NaN pozostawione w starej bazie powoduje odmowę i rollback całej migracji, z zachowaniem danych, poprzedniego CHECK i rewizji. Przed upgrade rolą migratora sprawdź zakres wadliwych rekordów:

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

Generowany OpenAPI ma dwa endpointy health. Projekt `contracts/openapi/design-v1.yaml` obejmuje niewdrożone operacje E2–E4; nie dubluje tych endpointów. Test porównuje wygenerowany dokument z wersjonowanym artefaktem. Integracja sprawdza migrację pustej bazy do head, upgrade z `0001_foundation` na istniejących danych oraz rollback przy NaN w każdej kolumnie. Parametryzowane próby przez role API i worker obejmują `NULL`, zero, sześć miejsc dziesiętnych, górną granicę, NaN, liczby ujemne, przekroczenie zakresu i oba Infinity, z kontrolą klasy błędu PostgreSQL. Test odczytuje nazwę i zwalidowanie rzeczywistego CHECK oraz porównuje jego działanie z modelem; samo `alembic check` nie porównuje CHECK. Pozostałe regresje obejmują readiness, FK/unikalności, rollback, brak DDL i brak zapisu historii migracji przez obie role wykonawcze oraz izolację bazy Keycloak.

## CI i obraz

[Workflow](../.github/workflows/backend.yml) wykonuje kontrakty, Ruff, testy jednostkowe, integrację na PostgreSQL 17, budowę pakietu i obrazu. Zbiorczy `ci-required` wymaga sukcesu wszystkich zadań. Używa testowych danych i przypiętych SHA akcji; nie wdraża usług ani nie wywołuje Gemini. Techniczne wymaganie tego sprawdzenia w ochronie `main` ustawia O3 zgodnie z dostępnością funkcji GitHub.

Obraz `docker build -t calorie-backend:local backend` działa jako użytkownik bez praw roota. Migrację uruchamia się osobnym poleceniem z rolą migratora. Początkowy schemat obejmuje tożsamość konta, źródło, produkt i jego wersje; pola racji, profili i dziennika powstaną w przypisanych etapach.
