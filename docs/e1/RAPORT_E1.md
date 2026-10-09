# Raport wykonania E1 - osoba 2

Data: 9 października 2026 r. Gałąź: `codex/e1-fundament`, utworzona z `main` po scaleniu PR E0 nr 2 (merge `534f5ae`).

## Wykonane

- Backend Python 3.13/FastAPI/Pydantic 2, SQLAlchemy 2, psycopg 3, Alembic i uv.lock.
- Fabryka API, lifespan bez DDL, konfiguracja ze środowiska, maskowane URL, żądania z UUID, logi JSON i bezpieczne błędy. Nagłówki WWW-Authenticate/Retry-After są zachowane.
- Liveness niezależne od bazy, readiness zależne od PostgreSQL 17 i aktualnej migracji; wygenerowany kontrakt wdrożonych endpointów.
- Pierwsza migracja kont i podstawowego katalogu; NUMERIC, FK, unikalność tożsamości i walidacja danych w PostgreSQL. Katalog/racje i prywatne profile nie są jeszcze API E2/E3.
- Lokalny Compose, oddzielne bazy i konta techniczne, role wykonawcze bez DDL. Dockerfile z użytkownikiem bez praw roota.
- Workflow PR/main: kontrakty E0, Ruff, testy jednostkowe, PostgreSQL 17, inicjalizacja ról, budowa pakietu i obrazu; zbiorcze ci-required.

## Kontrole lokalne

Ruff check/format: PASS. Testy backendu: **17 PASS**, na Pythonie 3.13.9 i rzeczywistym PostgreSQL 17.11. Wykonano migrację pustej bazy rolą migratora, sprawdzenie zgodności modeli/migracji, rollback, NUMERIC/null, FK/unikalności/nieprawidłowych jednostek oraz downgrade/upgrade wyłącznie dedykowanej bazy `calorie_test`. Testy nie są pomijane przy braku bazy. Fixture odtwarza domyślne granty bootstrapu; usunięcie odebrania DML na `alembic_version` powoduje błąd testu.

Wykonano także SQL `infra/local/init-db.sh` w izolowanym lokalnym klastrze: role i bazy powstały, migracja przez migratora działała, rola API otrzymała readiness 200 bez praw DDL i bez CONNECT do Keycloak. Liveness przy awarii bazy i readiness 503 oraz bezpieczne błędy sprawdzono testami HTTP.

Środowisko nie miało Dockera: oficjalny pakiet PostgreSQL/EDB uruchomiono tymczasowo na `127.0.0.1:65432`. Runtime i dane są w ignorowanym `.tools`; nie trafiają do Git. Sandbox blokował lokalne gniazda, dlatego testy wykonano z prawem lokalnego połączenia. TestClient zgłasza nieblokujące ostrzeżenie przejścia Starlette z httpx na httpx2; testy są wykonane, nie wyciszane.

Budowa sdist i wheel: PASS. Ponowna pełna walidacja E0: PASS. Niezależna recenzja: **9,1/10**, bez nierozwiązanych usterek blokujących. Poprawiono zbyt szerokie domyślne granty na historii migracji: API i worker mają SELECT bez INSERT/UPDATE/DELETE, co recenzent potwierdził własnym odczytem PostgreSQL. Wzmocniono także wskazaną przez niego fixture regresji grantów.

PR E1: [nr 3](https://github.com/Roseru/aplikacja-mobilna/pull/3). Pierwszy przebieg CI potwierdził kontrakty, testy PostgreSQL, jakość kodu i budowę obrazu. Smoke test początkowo odczytał port podczas startu kontenera i dostał reset połączenia; dodano ograniczone oczekiwanie do 30 s oraz logi kontenera. Wynik końcowego przebiegu zostanie odnotowany po zakończeniu. Nie deklarujemy zielonego CI na podstawie samego pliku workflow.

## Dalsze etapy

E2: kompletny model katalogu/racji i eksporter pakietu. E3: OIDC, profil/cel i autoryzacja właścicieli. E4: działający sync. O3 dostarcza rzeczywistą infrastrukturę, hosty/sekrety i ochronę gałęzi. W E1 nie wykonywano wdrożenia produkcyjnego ani Gemini. Instrukcje nowego checkoutu: [backend](../../backend/README.md), [bazy lokalne](../../infra/local/README.md).
