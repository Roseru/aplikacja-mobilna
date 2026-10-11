# Raport odczytów i statystyk E5-O2-R - osoba 2

11 października 2026. Wykonawca: Agent 2 / O2, czat `01a12833-ba8d-7671-9f6a-33db1e532dc2`. Baza: odebrany main `b27838b9aa1027aa00b342df1c922f2bdb38ef3a`, [master prompt](../MASTER_PROMPT_E5.md) / scalony [PR #14](https://github.com/Roseru/aplikacja-mobilna/pull/14). Gałąź wykonania `codex/backend-e5-odczyty-statystyki`, dedykowany checkout. Główny katalog E4 aa4d97c, jego gałąź/pliki nieśledzone oraz Random Data pozostają zachowane.

Status wykonania i publikacji jest uzupełniany po rzeczywistych kontrolach. [Niezależny odbiór runtime](RECENZJA_O2.md): 9,4/10, bez otwartych P1/P2, z własnym PostgreSQL/HTTP i dodatkowymi próbami. Nie jest to odbiór całego E5 ani zgoda na merge/E6.

## Działające zachowanie

GET /api/v1/me/meals, /me/weights, /me/diary-days udostępniają wyłącznie żywe dane właściciela według jawnych lokalnych dat. Pierwszy odczyt materializuje spójny REPEATABLE READ, kolejne strony zachowują treść, as_of/H/strefę/rewizje i ponownie sprawdzają dostęp/generację/epokę. Read1 ma osobną domenę podpisu, TTL60min i granice rekordów/bajtów/kopii. Odpowiedź bez continuation usuwa niepotrzebną nową kopię w tej samej transakcji; prawdziwe kopie paged pozostają do TTL, także na retry ostatniej strony. Wszystkie wyniki i błędy mają no-store, również OIDC/middleware.

GET /api/v1/me/statistics?days=7|30|90 korzysta z jednego as_of/strefy profilu i wspólnego batch resolvera historycznych korekt celu. DokładnieN dat, dzisiaj preliminary, zamknięte efektywnie kompletne dni, dokładne Decimal/null/zero, osobne mianowniki każdego pola, inclusive goal_band_v1 i rzeczywiste dzienne punkty wagi. Zmiana katalogu nie przelicza snapshotu historii. Brak profilu daje409; brak wartości nie daje zera/deficytu.

Architektura: diary/read_schemas/router/service/repository/tokens/models; analytics/schemas/router/service/repository; współdzielone diary completeness/nutrition i profiles batch. Routery nie liczą wartości i nie wykonują ukrytych commitów. Transport/formy i normatywne przykłady przeniesiono z draft do [generowanego OpenAPI](../../backend/openapi.json), zachowując walidację. [Statistics vectors](../../contracts/test-vectors/statistics-v1.json) rzeczywiście wykonują Python; Kotlin/Room oczekuje O1.

## Baza i zgodność

Nowa migracja0012_e5_reads dodaje trzy techniczne tabele read_admissions/read_sessions/read_session_items, checks/FK/indeks i wąskie funkcje. API ma SELECT/INSERT kopii, kolumnowy UPDATE liczników i EXECUTE admission/discard. Worker ma tylko EXECUTE prune, operator deletion nie dostaje prywatnych odczytów. Purge usuwa kopie/admission przez FK CASCADE przy usunięciu konta po zatwierdzeniu procedury E4. Retencja w dotychczasowej komendzie sprząta ograniczone partie również bez ruchu API. Downgrade usuwa odtwarzalne kopie/funkcje, zachowuje dane E4 i epokę. Migracje0001–0011 są niezmienione. Readiness wymaga0012 oraz stałego sekretu stron.

Limity/czas/błędy i rollout: [decyzje](DECYZJE_V1.md), [O3](KONFIGURACJA_O3.md). [O1](INTEGRACJA_O1.md) wskazuje różnice strefy urządzenia/profilu, osi localSequence/correction_of i REAL/Double względem dokładnego wire. [Obsługa sync](ODCZYTY_I_SYNCHRONIZACJA.md) zachowuje pull/push/pull, 401, lostACK,30dni, konflikty, świadomy recovery, oryginały i outbox. Read/H nie są potwierdzeniem sync ani importem gościa.

## Faktycznie wykonana weryfikacja

| Wykonawca / środowisko | Wynik / zakres |
|---|---|
| Root, pełne unit po regeneracji kontraktów | 693 PASS, bez skipów; Python3.13.9,41,23s |
| Autor modułu read | 42 PG17/runtime-role HTTP +24 unit PASS; w tym6 kontrolowanych snapshotów,4 sukcesy/2 odmowy i20 odświeżeń pustego/jednostronicowego wyniku na każdym endpointzie |
| Autor analytics | 33 PG17/runtime-role HTTP +49 unit PASS; dodatkowo19 wcześniejszych testów celów E3 PASS, bez dodawania powtórzeń do liczności pełnej regresji |
| Root, real Keycloak26.8/JDK25 | 9 PASS,5,07s, własny izolowany realm i PostgreSQL; PKCE/sync/deletion, proces zatrzymany przez harness |
| Niezależny nieautor runtime/testów | 93 E5 unit +75 E5 PG/HTTP +12 własnych dodatkowych PG prób PASS; 9,4/10; [dokładna recenzja](RECENZJA_O2.md) |
| Root, kontrakty/zasoby | PASS:69 valid /26 invalid /18 scenarios,15 generated moved operations,82 HTTPexamples,16 Decimal/5 kompletności/72 normalizacje i linki; OpenAPI/resources zgodne |
| Root, jakość/wheel | Ruff/check+format PASS; sdist/wheel zbudowane; installed Python-I poza checkoutem:78 identycznych runtime/resources oraz wszystkie produkcyjne wersje zgodne z uv.lock, model/reducer statystyk i read HMAC/tzdata/routes; real SQLite demoimport PASS |

Root wykonał końcowe **76 testów E5 HTTP/PostgreSQL/migracji PASS** (63,50s) i **28 właściwych regresji PASS** foundation/provisioning/retention (55,38s). Dodatkowy test porównuje wszystkie stare wiersze grafu E4 przez upgrade/downgrade/reupgrade, w tym epokę, receipts, ChangeLog, snapshoty, opublikowany katalog i deletion job/fence oraz pełne ACL. Pierwszy pełny PG dał **635 PASS /4 FAIL**: dwie ścisłe asercje wymagały nowych tabel/pól E5, a dwa błędy wynikały z brakujących calorie_app/keycloak we własnym lokalnym clusterze. Naprawiono wyłącznie addytywne oczekiwania oraz prywatny provisioning; wszystkie 28 właściwych prób ponowiono PASS, a niezależny recenzent potwierdził zachowanie dawnych asercji. Ostatni pełny przebieg PostgreSQL jest w toku. CI końcowego head będzie odczytane oddzielnie, bez zastępowania wcześniejszym CI E4. Obrazy wymagają rzeczywistych buildów/smoke w bieżącym CI; lokalnie brak Docker. Ostrzeżenie Starlette/httpx pozostaje jawne, bez skipów.

Pierwsze root unit687PASS/3FAIL wskazało brak regeneracji OpenAPI i pozostałe aktywne draftoperacje; naprawiono artefakty/walidator i pełne693PASS potwierdziło zgodność. Łączna kolekcja unit+integration jednym wywołaniem wykryła zastaną kolizję modułu E3; testy wykonujemy odrębnie dokładnie jak CI, bez pomijania przypadków lub zmiany starych testów. Pierwsze niezależne E5 PG62PASS/1FAIL ujawniło rzeczywiste przekroczenie4sesji. Tuple-write admission naprawił staleRR; współbieżne próby autora i recenzenta potwierdziły4/2. P3 puste odświeżenia wyczerpujące sloty również naprawiono i sprawdzono; kopie paged nadal wspierają stabilny retry.

## Trwały audyt źródeł i otwarte bramki

[Audyt E0/E5](../e0/ZRODLA_KATALOGU.md) i [materiały z11.10](../../Random%20Data/E5_2026-10-11/README.md) zachowują rzeczywiste odczyty, źródła/hash/date/version/units i braki. ARPOL WZ1/WZ4WEGE: skład/masy oraz1517/1433kcal całej racji, bez rozdzielenia sumy na komponenty. Indywidualne karty są kandydatami; sklepowa dostępność/nazwa/zdjęcie nie dowodzi konkretnego wariantu racji. Zachowano6 alternatyw batonów, sprzeczne kJ/kcal kisielu i niepewne '<'makra.

Coca-Cola Original PL: na100ml42kcal, B0/T0/W10.6g z polskiej karty, bez wymyślania gęstości. USDA publiczny eksport SR Legacy April2018 dostarczył pełne rekordy173944/171688/169097 banana/jabłka ze skórką/pomarańczy na100g części jadalnej. Nutrient1005 to Carbohydrate, by difference; semantyka i źródłowe zaokrąglenia są zachowane. MRE2026 i S-RG-1 pozostają niezmienione i nie zastępują ARPOL. Nie publikowano niepełnego official/seeda ani nie importowano MRE.

- R realizuje prywatne odczyty WF-03/10, część KO-11/25 i izolacji KO-13 na backendzie, historyczne cele i null/jednostki; nie poświadcza APK.
- C nadal wymaga kompletu etykiet komponentów i konkretnego powiązania producenta/wersji z racją, profili/mas jadalnych dodatków oraz wyjaśnienia sprzecznych wartości. O2-C jest osobnym zleceniem koordynatora i PR eksportu/importu official (KO-01–02/30).
- O1: Kotlinvectors, OIDC/HTTP/Room/WorkManager, A/B/gość/KO-31 i aktualne APK mają odrębny dowód. O2 nie potwierdza go za O1.
- O3: osiągalny issuer/HTTPS, wdrożenie0012, retencja, restore obu baz z rejestrem deletion/RPO/RTO pozostają jego czynnościami i dowodami. PR AndroidCI#10 jest osobny; kontrola keycloak-pkce zachowana.

Koordynator odbiera finalny PR/head/CI i decyduje o merge oraz C/O1/O3. Wykonawca nie scala i nie zaczynaE6; watcher pliku pozostajePAUSED, bez nowego czatu/rejestru/automatyzacji.
