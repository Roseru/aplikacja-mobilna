# Raport wykonania E1 - osoba 2

Data: 9 października 2026 r. Gałąź: `codex/e1-fundament`, utworzona z `main` po scaleniu PR E0 nr 2 (merge `534f5ae`).

**Wynik poprawki: E1 poprawione i odebrane — 109 testów backendu PASS na PostgreSQL 17.11, niezależna recenzja 9,5/10 bez istotnych nierozwiązanych usterek oraz zielone CI kodu poprawki.** Kontrole aktualnego head i stan scalenia wskazuje PR. Dawne wyniki CI i recenzji nie stanowią odbioru tej poprawki.

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

Nowa regresja: [test_finite_nutrition.py](../../backend/tests/integration/test_finite_nutrition.py). Istniejące testy E1 zostały zachowane; rozszerzono regresję uprawnień obu ról. TestClient zgłasza jedno nieblokujące ostrzeżenie Starlette dotyczące httpx; nie wyciszano go ani nie pomijano testów. Lokalnie brak Dockera; obowiązkową budowę i smoke test obrazu potwierdziło zadanie `quality` w CI commita poprawki.

## Niezależny odbiór poprawki

Niezależny subagent `review_e1_nan` nie napisał ani nie zmieniał poprawki. Ocenił kod i testy z commita `a8556a9` na **9,5/10**, bez istotnych nierozwiązanych usterek. Próg minimum 9/10 został spełniony na podstawie własnych kontroli recenzenta:

- `python -m pytest backend/tests -x`: **109 PASS**, bez skip, 4,41 s; wszystkie cztery próby rollback przy NaN przeszły.
- Ruff check/format, pełna walidacja E0, budowa sdist/wheel offline i `git diff --check`: **PASS**.
- Potwierdzono niezmieniony blob `0001_foundation`, poprawną zależność `0002`, rzeczywiste role API/worker, CHECK i SQLSTATE, zachowanie NULL/zera/maksimum i danych, readiness oraz prawa do historii i izolację Keycloak.

Recenzent nie wskazał usterek wymagających poprawy. Ostrzeżenie Starlette/httpx jest nieblokujące. Opcjonalna dodatkowa próba Alembica poza fixture czekała na zatwierdzenie polecenia narzędzia i została przerwana; nie zaliczamy jej do wykonanych kontroli. Wymagane testy rollback recenzent wykonał w pełnym zestawie. CI i smoke obrazu są osobnym, rzeczywiście potwierdzonym dowodem prowadzącego.

## Publikacja i scalenie

Kontynuowana gałąź `codex/e1-fundament` i [PR nr 3](https://github.com/Roseru/aplikacja-mobilna/pull/3). Stan wejściowy: `112ff5f007b404a0692bd5c2f840ceec95264cd3`. Zastany, nieśledzony `docs/MASTER_PROMPT_POPRAWKA_E1.md` jest instrukcją wejściową; zachowano go bez zmian, poza commitem poprawki. Runtime, hasła testowe, baza, cache i buildy pozostają ignorowane.

Commit poprawki: **`a8556a94228fa06ef8be5f4eda64d10313577d8b`**. [CI poprawki](https://github.com/Roseru/aplikacja-mobilna/actions/runs/37982344173) zakończyło się sukcesem `contracts`, `quality`, `postgres` i `ci-required`. Metadane przebiegu potwierdzają ten dokładny head SHA. Logi potwierdzają **99 PASS** PostgreSQL i **10 PASS** unit, budowę sdist/wheel oraz obrazu i pomyślny smoke test: live 200, ready 503 przy niedostępnej bazie. [CI dla 112ff5f](https://github.com/Roseru/aplikacja-mobilna/actions/runs/37977189519) pozostaje wyłącznie historycznym dowodem.

Uzupełnienie tego raportu nie zmienia kodu ani testów. Każdy nowy commit dokumentacji również musi przejść wszystkie cztery zadania i build/smoke przed merge; [kontrole aktualnego head](https://github.com/Roseru/aplikacja-mobilna/pull/3/checks) są wiążące. Stan scalenia i końcowe SHA są dostępne w PR. GitHub wykazał `main.protected=false` i pustą listę rulesetów; nie przedstawiamy gałęzi jako technicznie chronionej i nie zmieniano jej ustawień. Konto Git ma prawo push/merge bez prawa administracji. Stosujemy zwykły merge z expected head SHA, bez force-push i bez bypassu; wymagane recenzje i nierozwiązane uwagi są ponownie sprawdzane przed scaleniem.

## Dalsze etapy

**Zakończenie tej pracy dotyczy wyłącznie poprawki i odbioru E1; E2 nie rozpoczęto.** O3 dostarcza rzeczywistą infrastrukturę, hosty/sekrety i ochronę gałęzi. W E1 nie wykonywano wdrożenia produkcyjnego ani Gemini. Instrukcje nowego checkoutu: [backend](../../backend/README.md), [bazy lokalne](../../infra/local/README.md).
