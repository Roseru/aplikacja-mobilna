# Raport wykonania E2 - osoba 2

**Poprawka O2 odebrana lokalnie: 9,5/10; CI aktualnego head oczekuje.
Integracja O1 oczekuje.** Bieżąca
pełna regresja: **396 PASS**, bez skip, na rzeczywistym PostgreSQL 17 i SQLite
importera. Ponowny przegląd head `962d0cc66e14ab0f85d2e1a34b7766d92c01a76b`
wykrył dwa brakujące przypadki i ocenę 8,7/10. Historyczne 327 PASS, 9,4/10 i CI
nie stanowią dowodu poprawki. Wiążące kontrole aktualnego head wskazuje
[PR #4](https://github.com/Roseru/aplikacja-mobilna/pull/4/checks).

Zakres: backend, dane i integracje O2. Start z aktualnego zdalnego `main`
`a79b0732df71955ebf893391cc767805be674ed0` po scalonym E1; gałąź
`codex/e2-katalog-offline`. Zastane nieśledzone master prompty E1/E2 zachowano
bez zmiany; nie są częścią implementacji. Nie zmieniano Androida, nie scalano
gałęzi O1 i nie rozpoczęto E3. Room/APK pozostają osobnym odbiorem O1; końcowy
odbiór O2 wymaga również niezależnej recenzji i zielonego CI aktualnego head.

## Dostarczone zachowanie

Modularny katalog `backend/src/calorie_app/modules/catalog/` obejmuje modele,
typed DTO, wspólną walidację Schema/grafu, arytmetykę Decimal, repozytorium,
kontrolowany import, eksport/publikację, cztery publiczne odczyty i CLI operatora.
`db/models.py` zachowuje importy E1 bez drugiej definicji tabel. Migracja
`0003_catalog_offline` rozszerza poprzednią bazę. Poprawka dodaje
`0004_catalog_timestamp` i `0005_ration_cursors`; `0001–0003` są niezmienione.

Źródła i rewizje są niezmienne, składniki mają złożone FK do dokładnych wersji,
członkostwo pakietu jest relacyjne. Identyczny import jest no-op; inna treść
to konflikt i rollback. Stare rekordy E1 zachowano z NULL nowych metadanych;
nawet dawny status verified nie czyni ich eksportowalnymi. Nowy snapshot źródła
i rewizja wymagają rzeczywistego materiału; nie uzupełniamy ich fikcją.

Eksporter czyta rzeczywisty PostgreSQL w repeatable read i tworzy uporządkowany
UTF-8/kanoniczny Decimal oraz gzip z mtime=0, bez zmiennej nazwy. SHA-256 dotyczy
gzip. Plik jest fsync/zapisywany atomowo bez nadpisania przed commit metadanych.
Blokada kanału i unikalne release serializują publikacje, a active_release nie
cofa się. Awaria pliku lub commit pozostawia poprzednie wydanie; osierocone pliki
nie są publiczne. Starsze opublikowane bajty pozostają dostępne.

Publiczne v1 wskazuje stałe **official package_id
`c12631e2-1a02-547c-a7f9-ebf87bb42e55`**. Demo/inny official package_id z tym samym
basename/release nie podmienia publicznego URL. Manifest, plik i racje wybierają
ten sam pakiet. Lista ma limit 1..500/default100 i token przypięty do release,
limitu/pozycji na 60 minut, bez przedłużania TTL; 410 ma code page_expired.
Chronione produkty HTTP pozostają projektem E3; usługa wyszukiwania jest gotowa.
Nie istnieje dowolny Bearer ani publiczny include_demo.

## Poprawka po ponownym przeglądzie 10 października

Przed pracą odczytano stan lokalny, fetch origin oraz metadane PR #4:
head nadal `962d0cc…`, PR otwarty, main `a79b073…`; nie cofnięto cudzych zmian.
Przyczyna dat była w hashowaniu poprawnego tekstu wejściowego przed konwersją
PostgreSQL timestamptz. `.1Z` odtwarzało się jako `.100000Z`, `.000000Z` jako `Z`;
repeat i eksport myliły tę samą chwilę ze zmianą snapshotu.

Nowy import normalizuje UTC **przed** hashem/zapisem jednym serializerem:
zero mikrosekund bez ułamka, inaczej sześć cyfr. E0 nadal przyjmuje bez ułamka,
zerowy ułamek i 1–6 cyfr. Repeat najpierw weryfikuje hash odtworzonego grafu,
potem porównuje semantyczną chwilę i całą treść. Inna chwila/release pozostaje
konfliktem. Publikacje poprawnej starej implementacji zachowują bajty i hashe.

Istniejący uszkodzony draft wymaga jawnego `recover-timestamp --input ORIGINAL`.
Weryfikujemy oryginalny hash, kompletny relacyjny graf i każdy hash źródła/
produktu/racji. Migracja `0004` dodaje immutable audyt oryginalnego kanonicznego
uporządkowanego JSON, jego hasha i pisowni daty, operatora i czasu. DB sprawdza
SHA-256 dowodu, identyfikatory i tę samą chwilę sealed draftu. Audyt pozwala
odtworzyć pierwotny tekst w package/manifest bez zmiany żadnego wiersza/hasha
offline_packages. Eksport nadal pochodzi z relacji, nie blobu dowodu.
Odzyskanie jest idempotentne przed publikacją; publikacji, zdrowego draftu,
fałszywego dowodu lub zmienionych danych nie naprawia automatycznie.
Brak oryginału wymaga archiwum operatora. SHA gzip sprawdzamy na dokładnych
pobranych bajtach przed parsowaniem; importer referencyjny nie został osłabiony.

Przyczyna paginacji: TTL ograniczał użycie UUID, lecz każdy odczyt dodawał nowy
rekord bez usuwania. Własne odtworzenie na PG pokazało **51 rekordów po 51
odczytach** tej samej strony. Nowy token `rp1` jest podpisany HMAC-SHA256 i
zawiera package_id, release, limit, pozycję/rewizję oraz pierwotny TTL w
mikrosekundach. Nie zapisuje rekordu; powtórzenia i kolejne strony nie dodają
stanu ani nie wydłużają czasu. Sekret środowiska jest stały między replikami/
restartami; brak sekretu blokuje readiness. Format jest nieprzezroczysty dla O1.

Migracja `0005` zamyka stare INSERT/UPDATE i odbiera API INSERT. Zachowuje aktywne
UUID oraz TTL; każdy odczyt listy uruchamia ograniczone sprzątanie w DB
(do 1000 wygasłych rekordów, SKIP LOCKED). Usunięcie starego rekordu i zapis
minimalnego tombstone `(id,package_id,limit)` są atomowe. Znany wygasły UUID
nadal daje 410 page_expired po sprzątaniu; inny UUID/limit daje 422. Suma
legacy + tombstones nie przekracza skończonego backlogu przy upgrade; nowe
odczyty zwiększają ją o **zero**. Tombstones pozostają dla dokładnej semantyki
błędu, bez nowego rekordu na odczyt. CLI `prune-page-tokens` działa również
bez ruchu HTTP. API ma EXECUTE jednej funkcji z fixed search_path i SELECT,
bez DELETE/UPDATE/INSERT tokenów i dodatkowych praw prywatnych; worker nie
dostaje EXECUTE. Downgrade przy audycie/tombstones odmawia usunięcia dowodów.

O3 otrzymuje w [backend README](../../backend/README.md) dokładny rollout:
zatrzymać stare API, zachować pakiety/DB, wygenerować i bezpiecznie utrzymać
CATALOG_PAGE_TOKEN_SECRET, migrator `upgrade head`, nowy obraz, readiness/smoke.
Sekret nie może zmienić się przy restarcie; E2 nie wdraża automatycznej rotacji.

| Bieżąca weryfikacja poprawki | Wynik wykonany |
|---|---|
| Pełne E1/E2 i importer | **396 PASS**, 187 integration na PostgreSQL 17.11 i 209 unit, 27,23 s, bez skip; wszystkie 109 wcześniejszych E1 zachowane |
| Daty i zgodność danych | 24 nowe testy PostgreSQL: wszystkie pisownie, import/repeat/export/publish/repeat, równoważne i różne chwile, hash/DB/manifest/package, stare publikacje, recovery i fałszywe dowody, ACL/immutability, operator CLI |
| Paginacja | 10 nowych testów PostgreSQL + 35 unit: powtarzane odczyty bez przyrostu, dokładna granica TTL, HMAC/malformed/limit, stare UUID po upgrade, sprzątanie i 410, batch 1000, restart, nowe release, role i CLI |
| E0 | 5 schematów, 12 draft + 4 generated, 124 przykłady HTTP, 64 valid/20 invalid, 18 scenariuszy, 16 Decimal, 72 normalizacje źródeł, linki i diff-check PASS |
| Ruff/zasoby/OpenAPI | Check i format 52 plików PASS, wygenerowane zasoby zgodne, OpenAPI aktualne i porównane przez test |
| Pakiet | sdist/wheel offline PASS; aktualny wheel zainstalowany w izolowanym env, Python -I poza repo: walidacja bez DB, rzeczywisty eksport PostgreSQL, SQLite import/repeat PASS |
| Publikacja demo | PostgreSQL → gzip/manifest → SQLite PASS; 3099 B gzip z hashem nadal 65f4aae8…45b2bef, committed seed/source/export nietknięte |

Niezależny recenzent `review_e2_fixes` nie napisał żadnego ocenianego pliku
produkcji ani testów regresji. Samodzielnie wykonał końcowe **396 PASS**, bez
skip, **28,13 s**, Ruff/check i format 52 plików, diff-check oraz smoke
zainstalowanego wheel przez Python -I poza checkoutem. SHA-256 wszystkich
plików runtime Python w wheel są identyczne z ocenianym src. Ocena:
**9,5/10, brak istotnych nierozwiązanych usterek**; dowód obrazu wymaga jeszcze
zielonego CI nowego commita.

Jego osobne **3 próby PostgreSQL PASS, 2,77 s** ładowały rzeczywiste pliki
service/repository/export/router przez `git show 962d0cc…`, zamiast symulować
przyczynę. Dla `.1Z` i `.000000Z` stary kod dawał konflikt identycznego importu
i eksportu. Upgrade zachował wiersz i hash; jawne odzyskanie przywróciło
dokładny pierwotny JSON oraz zgodne manifest/HTTP gzip bez ich przepisania.
Stary router wytworzył 51 rekordów przy 51 odczytach; po upgrade kolejne 51
odczytów zachowało 50 aktywnych UUID + 1 tombstone. Sprawdzono pierwotny TTL
aktywnego UUID oraz 410 wygasłego po sprzątaniu i 422 przy innym limicie.
Pełna regresja obejmuje także restart, nowszy release i podpisane tokeny
innego package_id, aktywne oraz wygasłe.

Lokalnie nie ma Docker; dowód obrazu będzie pochodził z wymaganych aktualnych
zadań quality/postgres. CI zachowuje dotychczasowe realne build/smoke i dodaje
w obrazie fractional input `.1Z`, identyczny repeat, eksport/publikację/import
release 2 oraz porównanie zachowanych bajtów release 1 i realne CLI sprzątania.
Starszego sukcesu CI nie uznajemy za odbiór tej poprawki.

Pełny run wykrył kolizję nazw nowych modułów testowych i pozostały audyt fixture'a
przed dawnym downgrade E1; poprawiono nazwę i izolację dedykowanego grafu
testowego. Nie osłabiono blokad downgrade, nie pominięto żadnego testu.
Jeden wcześniejszy warning Starlette/httpx pozostał jawny.

Importer `offline_import.py`/`tools/offline_catalog/` działa bez sieci i
DATABASE_URL. Kontroluje rozmiary przed parsowaniem, gzip/CRC/hash, tożsamość,
wersje, schemat, duplikaty, Decimal, źródła i graf. Trwały SQLite przechowuje
dokładne teksty Decimal oraz nieaktywne generacje. Krótka transakcja aktywuje
wyłącznie kompletny nowszy release; zachowuje historię, outbox i stare rewizje.
To importer referencyjny, nie Room.

## Dane i przekazanie

[Wejście i pochodzenie demo](../../backend/data/demo/README.md),
[manifest](../../backend/data/demo/export/manifest.json) i
[gzip](../../backend/data/demo/export/base-pl.1.json.gz) pochodzą z wykonanej
ścieżki PostgreSQL 17 → eksport → importer. Gzip ma **3099 B**, JSON **15691 B**,
SHA-256 `65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef`.
Pakiet demo `47bdff67-e58b-5437-919b-ec00159afbc5`, release/schema/reader 1,
18 produktów, 1 racja, 18 składników i 1 źródło. Powtórzenie importu, eksportu
i publikacji zostało wykonane bez duplikacji i zmiany bajtów.

Oryginalny materiał S-RG-1 jest niezmieniony. Demo ma unverified/complete=false;
4 pozycje bez danych, 3 w sztukach bez masy i wyposażenie/sól/pieprz pozostają
jawnymi metadanymi. Baton jest opcjonalny, proszek w g, 3466/3468/3600 kcal osobne.
Brakuje etykiet ARPOL WZ 1/WZ 4 WEGE i źródeł produktów bazowych z rejestru E0.
Nie ma prawdziwego official seed; jego publikacja jest bramką E5. Syntetyczne
kompletne dane official istnieją tylko w izolowanych testach mechanizmu.

[Instrukcja O1](INTEGRACJA_O1.md) porównuje faktyczny Android
`f5aabfc3aa4ed189a4fa3d9ad245a71faeff46d2` z E0/E2: robocze ID, Double/REAL,
plaintext assets i IGNORE wymagają migracji do UUID/revisions/BigDecimal,
generacji i kontrolowanej aktywacji. O1 ma osadzić pakiet w APK, zachować dawne
snapshoty/outbox, wykonać Kotlin/Room i scenariusze urządzenia bez sieci.

O3 otrzymuje [komendy/config backendu](../../backend/README.md), stałe official ID,
CATALOG_ARTIFACT_ROOT, układ kind/package_id, wymóg trwałego filesystemu z hard
link, osobny migrator, prawa API/worker i wymagania HTTPS/nagłówków. Kopie mają
obejmować DB oraz opublikowane pliki. Katalog magazynu nie może być publicznym
statycznym mountem. Sekrety, cache, runtime, lokalne DB i magazyn są ignorowane.
Nie wysyłano wiadomości innym osobom.

## Odtworzenie i zakres dowodów

Z nowego checkoutu: Python 3.13, uv 0.9.5, PostgreSQL 17; pełna instrukcja
i role w backend README oraz infra/local. Po `uv sync --project backend --locked`
i migracji z DATABASE_URL operatora:

```text
uv run --project backend --locked python -m calorie_app.modules.catalog.cli import --input backend/data/demo/seed.json
uv run --project backend --locked python -m calorie_app.modules.catalog.cli export --package-id 47bdff67-e58b-5437-919b-ec00159afbc5 --release 1 --output backend/var/demo-export
uv run --project backend --locked python -m calorie_app.modules.catalog.cli publish --package-id 47bdff67-e58b-5437-919b-ec00159afbc5 --release 1
uv run --project backend --locked python -m calorie_app.modules.catalog.offline_import --database backend/var/catalog.sqlite --manifest backend/data/demo/export/manifest.json --package backend/data/demo/export/base-pl.1.json.gz --expected-package-id 47bdff67-e58b-5437-919b-ec00159afbc5 --expected-kind demo
```

Utwórz backend/var przed importerem. Walidacja i importer nie potrzebują DB:
`python -m calorie_app.modules.catalog.cli validate --input ...` oraz powyższy
offline_import. Bez uv po instalacji wheel używa się tych samych modułów Python.

Pełna regresja: `python -m pytest backend/tests` z TEST_DATABASE_URL dedykowanej
*_test, Ruff check/format, `python backend/sync_catalog_schemas.py --check`,
`tools/contracts/validate.ps1`, generator OpenAPI, `uv build backend` i build/smoke
obrazu z workflow. Testy nie pomijają brakującej bazy i nie używają SQLite dla
backendu. Lokalnie PostgreSQL 17.11, Python 3.13.9, uv 0.9.5; role z bootstrapu E1.

## Wyniki pierwotnego odbioru — historyczne, przed poprawką

| Kontrola wykonana lokalnie | Wynik |
|---|---|
| Pełny backend, PostgreSQL 17 + SQLite referencyjny | **327 PASS**, bez skip: 153 integration i 174 unit. Zachowano 109 regresji E1; doszło 218 testów E2 |
| Regresja migracji E2 | Pusta baza, upgrade 0002 na poprawnych danych, brak fałszywej weryfikacji legacy, prawa i niezmienność; 18 nowych prób migracji |
| Delivery | 36 testów PostgreSQL: atomowy import, rewizje, rzeczywisty roundtrip, deterministyczny eksport, no-op publikacji, dwie równoległe publikacje, odwrotna kolejność release, awarie pliku/commit, HTTP/paginacja/izolacja; uszkodzony/brakujący zarejestrowany plik daje 503 |
| Importer | 64 wykonane scenariusze: stream limits/bomba, gzip/CRC/hash, graf, duplikaty, wersje, restart/przerwanie i rzeczywiste SQLITE_FULL, wyścig, history/outbox sentinels i przypięte wersje |
| Arytmetyka | 16 wektorów E0, części racji, 250 ml → 105 kcal, NULL/zero, gęstość i HALF_UP; exact demo 347.0000004 / 3466.00000145 |
| Kontrakty E0/E2 | 5 schematów, 12 operacji draft + 4 generowane, 124 przykłady HTTP, 64 valid/20 invalid, 18 scenariuszy, 72 normalizacje źródła; linki lokalne i diff-check PASS |
| Ruff / zasoby / OpenAPI | Check/format 45 plików PASS; zasoby identyczne z normatywnymi schematami, OpenAPI zgodne z bieżącą fabryką API |
| sdist i wheel | Rzeczywista budowa offline PASS; końcowy wheel zainstalowany w czystym env z zależnościami uv.lock |
| Runtime poza repo | PASS: Python -I, systemowy katalog tymczasowy poza checkoutem, import zasobów, walidacja bez DB, rzeczywisty eksport PostgreSQL i import/repeat SQLite bez DATABASE_URL |
| Obraz | **PASS w CI**: rzeczywiste build/smoke, migracja PostgreSQL, seed/repeat, eksport/repeat i zgodność gzip z repo, publikacja demo, importer/readback oraz API rolą wykonawczą; lokalnie brak Docker |

Pierwsza pełna próba zatrzymała się na opcjonalnym FormatChecker dat. Poprawka
zapewnia kontrolę kalendarza/URI w zainstalowanym backendzie bez dodatkowych
bibliotek. Wykryty drift E1 błędów (`details:{}` wobec E0 `[]`) skorygowano,
410 stosuje page_expired; oba przypadki obejmuje regresja kontraktowa. Próby
zablokowane przez sandbox/ACL/TCP nie są zaliczone jako sukcesy; wykonane wyniki
pochodzą z uruchomienia z właściwymi uprawnieniami i izolowanym tmpdir. Ostrzeżenie
Starlette/httpx pozostało jawne i nie powodowało pominięć.

Referencyjne testy SQLite oraz odczyt kodu Androida **nie są wykonaniem KO-30
na Androidzie**. Pełny zespołowy odbiór E2 wymaga osobnych dowodów Room/APK O1;
brak źródeł official pozostaje zadaniem E5. PR E2 nie jest scalany w tej pracy.

## Pierwotna niezależna recenzja i CI — dowody historyczne

Recenzent `review_e2` nie był autorem ocenianych plików produkcji ani testów.
Ocena **9,4/10**, bez istotnych nierozwiązanych usterek. Samodzielnie wykonał
pełne **327 PASS**, bez skip, 17,08 s, walidację E0, Ruff/zasoby/diff-check,
budowę sdist/wheel oraz smoke instalacji z Python -I poza checkoutem z rzeczywistą
ścieżką PostgreSQL → gzip → SQLite bez DATABASE_URL dla importera.

Własny probe recenzenta zakończył osobny proces przez `os._exit(73)` przed
commit stagingu i aktywacji. Po otwarciu DB `integrity_check` był poprawny,
stary release, historia, outbox i przypięte rekordy pozostały; późniejsza
aktywacja release 2 była monotoniczna. Sprawdził też trailing gzip, niepoprawny
kalendarz/IPv6 URI i exact Decimal 3466.00000145. Pierwszy probe wymagał
poprawienia zamykania uchwytów w skrypcie recenzenta; nie była to usterka produkcji.

Gałąź E2 wypchnięto po odbiorze. [PR #4](https://github.com/Roseru/aplikacja-mobilna/pull/4)
jest otwarty do main i dołączony do zadania, bez scalenia. Pierwszy commit
implementacji `229a2b8bcd10948fec7a6aac58c5b8a9b1b3a49c`; poprawka CI
`5183c7a9048faf8c7bee8a0e6dbb2b8915c94930`. Dla tego drugiego SHA
[CI 37995920748](https://github.com/Roseru/aplikacja-mobilna/actions/runs/37995920748)
zakończyło wszystkie cztery zadania (`contracts`, `quality`, `postgres`,
`ci-required`) sukcesem. Logi potwierdzają 174 unit i 153 integration bez skip,
build/smoke obrazu i całą rzeczywistą ścieżkę pakietu, z hashem demo identycznym
jak w repo. Python runnera/obrazu 3.13.16; pakiet powstał lokalnie na 3.13.9.

Ten CI stanowi dowód kodu implementacji i poprawki obrazu. Każdy późniejszy
commit raportu również musi przejść wszystkie zadania; wiążące aktualne head/CI
wskazuje PR oraz końcowy raport czatu. Scalenie pozostaje osobnym poleceniem.

Pierwszy przebieg commita `229a2b8` i jego ponowienie zakończyły się na timeoutach
auth.docker.io/504 oraz limicie pull Docker Hub, przed uruchomieniem bazy/obrazu.
Kontrakty, 174 unit, wheel i jego instalacja przechodziły; to nie był odbiór CI.
Poprawka CI używa oficjalnego wydawcy Docker w ECR Public, z manifestami odczytanymi
także po dokładnych digestach: Python `70729b46…5678c2f`, PostgreSQL
`2d2b8998…dbdf9e3`. [Źródło publikacji mirroru](https://aws.amazon.com/blogs/containers/docker-official-images-now-available-on-amazon-elastic-container-registry-public/).
Kontrole nadal budują i uruchamiają rzeczywisty obraz oraz PostgreSQL; nie ma
zamiany na mock, pomijania testów ani zmiany danych. Zmienił się magazyn obrazów
w CI, a Dockerfile dostał jawny build arg bazowego Pythona.

Recenzent niezależnie odebrał także tę poprawkę CI: YAML, wszystkie 17 skryptów
Bash, porównanie trzech odwołań do obrazów i zachowanie wszystkich bramek PASS.
Ówczesna ocena wynosiła 9,4/10, bez wykrytych istotnych usterek; ten historyczny
odbiór obejmował backend z 327 testami i nie uwzględniał dwóch późniejszych regresji.
