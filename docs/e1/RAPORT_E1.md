# Raport wykonania E1 - osoba 2

Data: 9 października 2026 r. Gałąź: `codex/e1-fundament`, utworzona z `main` po scaleniu PR E0 nr 2 (merge `534f5ae`).

**Wynik poprawki: zamknięto lukę NaN w bazie; 109 testów backendu przeszło na PostgreSQL 17.11. Końcowa niezależna recenzja i CI bieżącego commita są w toku.** Dawne wyniki CI i recenzji nie stanowią odbioru tej poprawki.

## Wykonane

- Backend Python 3.13/FastAPI/Pydantic 2, SQLAlchemy 2, psycopg 3, Alembic i uv.lock.
- Fabryka API, lifespan bez DDL, konfiguracja ze środowiska, maskowane URL, żądania z UUID, logi JSON i bezpieczne błędy. Nagłówki WWW-Authenticate/Retry-After są zachowane.
- Liveness niezależne od bazy, readiness zależne od PostgreSQL 17 i aktualnej migracji; wygenerowany kontrakt wdrożonych endpointów.
- Pierwsza migracja kont i podstawowego katalogu; NUMERIC, FK, unikalność tożsamości i walidacja danych w PostgreSQL. Katalog/racje i prywatne profile nie są jeszcze API E2/E3.
- Lokalny Compose, oddzielne bazy i konta techniczne, role wykonawcze bez DDL. Dockerfile z użytkownikiem bez praw roota.
- Workflow PR/main: kontrakty E0, Ruff, testy jednostkowe, PostgreSQL 17, inicjalizacja ról, budowa pakietu i obrazu; zbiorcze ci-required.

## Luka wykryta po pierwszym odbiorze

Pierwszy odbiór E1 dał 9,1/10, jednak ponowna recenzja wykryła nieobjętą testami lukę i obniżyła ocenę do **8,8/10**. `nonnegative_nutrition` sprawdzało wyłącznie `>= 0`, co w PostgreSQL przepuszcza NaN w `energy_kcal`, `protein_g`, `fat_g` i `carbs_g`. Kontrakt E0 dopuszcza wyłącznie skończone wartości `0..999999.999999` albo brak danych. Dawna ocena 9,1/10 dotyczyła wcześniejszego stanu i nie jest oceną poprawki.

[PostgreSQL 17](https://www.postgresql.org/docs/17/datatype-numeric.html) traktuje NaN jako większe od pozostałych wartości; Infinity przekracza precyzję `NUMERIC(12,6)`. To rozróżnienie potwierdzają rzeczywiste wyjątki i SQLSTATE w nowych testach.

## Wykonana poprawka

- Model `ProductVersion` ma dla każdej kolumny warunek `IS NULL OR (wartość >= 0 AND wartość <= 999999.999999)`.
- Nowa migracja **`0002_finite_nutrition`**, zależna od `0001_foundation`, dodaje zwalidowany `ck_product_versions_finite_nutrition`, następnie usuwa stary CHECK. `op.f` zachowuje pojedynczy prefiks nazwy. Opublikowana migracja `0001_foundation` pozostała niezmieniona.
- Migracja nie zmienia danych ani tabel. Przy zastanym NaN walidacja odmawia upgrade; transakcja zachowuje dane, stary CHECK i rewizję. Instrukcja diagnozy wskazująca konkretne rekordy i kolumny jest w [backend/README.md](../../backend/README.md). Korekta wymaga ustalenia poprawnej wartości z właścicielem danych; nie ma automatycznej zamiany na zero/NULL ani kasowania.
- Readiness oczekuje `0002_finite_nutrition`: na starej rewizji 503, po upgrade 200. Liveness pozostaje niezależne od bazy i rewizji.
- Zachowano uprawnienia API i workera: SELECT historii migracji, bez INSERT/UPDATE/DELETE, DDL i CONNECT do Keycloak. Nie zmieniano `migrations/env.py`, bootstrapu ról ani CI.

## Kontrole lokalne poprawki

Python **3.13.9**, uv **0.9.5**, PostgreSQL **17.11**. Utworzono własny izolowany klaster w ignorowanym `.tools/e1-fix-pg-data` na `127.0.0.1:65433`. Role i bazy utworzono SQL wyodrębnionym bez zmian z `infra/local/init-db.sh`. Testy dotyczyły wyłącznie dedykowanej bazy `calorie_test`; fixture wykonuje migracje rolą migratora i odtwarza domyślne granty bootstrapu. Sandbox blokował TCP i kończył serwer, więc testy wykonano z uprawnieniem do lokalnego połączenia. Pierwszą próbę bez działającego serwera przerwano; nie zaliczono jej do sukcesów.

| Kontrola | Wynik i dowód |
|---|---|
| `python -m pytest backend/tests -x` | **109 PASS**, w tym **99 integracyjnych i 10 jednostkowych**, bez skip; 4,23 s |
| Każda kolumna przez role API i worker | `NULL`, zero, sześć miejsc i maksimum zachowane; NaN/ujemne: `CheckViolation`, SQLSTATE `23514`, dokładna nazwa CHECK; ponad zakres i oba Infinity: `NumericValueOutOfRange`, `22003`, bez nazwy CHECK |
| Pusta baza i istniejące poprawne dane | Upgrade do head; cztery próby upgrade z `0001_foundation` zachowują identyfikatory, wartości, referencje i NULL; porównanie pełnych danych czterech tabel przed/po |
| Stara baza z NaN | Cztery niezależne próby, po jednej na kolumnę: upgrade odrzucony, dane/CHECK/rewizja niezmienione, readiness 503, live 200; sprzątnięto tylko rekordy testu |
| Rzeczywisty CHECK | Odczyt z PostgreSQL: nazwa z pojedynczym prefiksem i `convalidated=true`; porównano działanie modelu i CHECK na skończonych i specjalnych liczbach, także bez ograniczenia precyzji |
| Readiness i uprawnienia | Stara rewizja 503, head 200, HTTP 200 przez obie role; realne próby DDL i DML historii odrzucone z `InsufficientPrivilege`, `42501`; brak CONNECT do Keycloak dla obu ról |
| Ruff check i format | PASS; 21 plików sformatowanych zgodnie z Ruff |
| `uv build backend --offline` | PASS: sdist i wheel zbudowane z lokalnego cache |
| `tools/contracts/validate.ps1` | Pełna walidacja E0 PASS: 5 schematów, 16 endpointów, 124 przykłady HTTP, 64 poprawne/20 błędnych, 18 scenariuszy, 16 wektorów Decimal |
| `git diff --check` | PASS |

Nowa regresja: [test_finite_nutrition.py](../../backend/tests/integration/test_finite_nutrition.py). Istniejące testy E1 zostały zachowane; rozszerzono regresję uprawnień obu ról. TestClient zgłasza jedno nieblokujące ostrzeżenie Starlette dotyczące httpx; nie wyciszano go ani nie pomijano testów. Lokalnie brak Dockera; obowiązkową budowę i smoke test obrazu zweryfikuje zadanie `quality` w CI bieżącego commita.

## Niezależny odbiór poprawki

Recenzja niezależnego subagenta jest w toku. Warunek odbioru: minimum **9/10**, samodzielnie wykonane kontrole i brak istotnych nierozwiązanych usterek. Wynik zostanie uzupełniony po zakończeniu recenzji.

## Publikacja i scalenie

Kontynuowana gałąź `codex/e1-fundament` i [PR nr 3](https://github.com/Roseru/aplikacja-mobilna/pull/3). Stan wejściowy: `112ff5f007b404a0692bd5c2f840ceec95264cd3`. Zastany, nieśledzony `docs/MASTER_PROMPT_POPRAWKA_E1.md` jest instrukcją wejściową; zachowano go bez zmian, poza commitem poprawki. Runtime, hasła testowe, baza, cache i buildy pozostają ignorowane.

Poprzednie [CI dla 112ff5f](https://github.com/Roseru/aplikacja-mobilna/actions/runs/37977189519) jest wyłącznie historycznym dowodem. Przed merge wymagane są zielone `contracts`, `quality`, `postgres` i `ci-required` dla aktualnego head oraz potwierdzenie budowy/smoke obrazu. Wynik aktualnego CI i stan scalenia zostaną dopisane po rzeczywistym wykonaniu kontroli; nie zmieniano reguł ochrony ani wymaganych recenzji.

## Dalsze etapy

**Zakończenie tej pracy dotyczy wyłącznie poprawki i odbioru E1; E2 nie rozpoczęto.** O3 dostarcza rzeczywistą infrastrukturę, hosty/sekrety i ochronę gałęzi. W E1 nie wykonywano wdrożenia produkcyjnego ani Gemini. Instrukcje nowego checkoutu: [backend](../../backend/README.md), [bazy lokalne](../../infra/local/README.md).
