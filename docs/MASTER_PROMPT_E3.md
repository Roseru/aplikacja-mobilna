# Master prompt E3: tożsamość i prywatny model - osoba 2

Status z 10.10.2026: zakres i weryfikację E3 sprawdzili dwaj niezależni subagenci, obie końcowe oceny **9,4/10**, bez istotnych nierozwiązanych uwag. Następnie uwzględniono nowe zasady komunikacji/Git i przekazanie Androida 0.6 z opisanych niżej commitów. To instrukcja wykonania; implementacja E3 i jej weryfikacja następują w nowym czacie.

Pracujesz jako **OSOBA 2** w repozytorium `https://github.com/Roseru/aplikacja-mobilna`. Wykonaj E3 w tym nowym czacie. Priorytetem jest jakość, czytelność dla ludzi i udowodnione działanie. Doprowadź etap do sprawdzalnego PR; nie kończ na analizie lub szkielecie.

## 1. Stan wejściowy i rozpoczęcie

Odczyt z 10.10.2026: E0/E1 są scalone. Część O2 poprawionego E2 na `52f3547f47bcfae1080aa1e9720b1f37a1ef6b88` została zaakceptowana po niezależnym sprawdzeniu dat/recovery oraz paginacji. [PR #4](https://github.com/Roseru/aplikacja-mobilna/pull/4) był otwarty; [CI 38042927890](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38042927890) miało sukces wszystkich czterech zadań. Raport E2 dokumentuje 396 PASS. **Zweryfikuj aktualny stan; te dane nie zastępują sprawdzenia późniejszego commitu.** O1 nadal odbiera Room/APK; to nie blokuje backendowego E3.

Najpierw sprawdź cwd, lokalne instrukcje, status Git, gałąź, remote, aktualne `origin/main`, stan PR #4 i jego CI. Nie nadpisuj cudzych zmian ani nie usuwaj danych. Zastane nieśledzone master prompty zachowaj. W aktualnym main mogły pojawić się materiały racji i inne zmiany zespołu; `Random Data/` przechowuje źródła projektu i nie jest katalogiem do porządkowania przez usuwanie.

Przeczytaj również aktualne `AGENTS.md` i wspólną komunikację. Na main `151885d` są starsze `komunikacja-agentow/ZASADY.md` i `TABLICA.md`. [PR #5](https://github.com/Roseru/aplikacja-mobilna/pull/5), gałąź `codex/komunikacja-agentow`, commit `aed79c72797eb14d891b9c909eb1035bd3be7634`, przenosi historię i zasady do **`docs/KOMUNIKACJA_AGENTOW.md`**. Przy tym odczycie PR #5 był otwarty. Zweryfikuj aktualny stan: dopóki nie jest scalony, czytaj jego dokument i AGENTS przez `git show` na konkretnym commicie. Nie scalaj całej gałęzi O1 dla pojedynczego dokumentu ani nie przedstawiaj jej zawartości jako main. Po scaleniu korzystaj z jednego dziennika, bez odtwarzania dawnej tablicy.

Nowe zasady: Agent 2 / O2 odpowiada za backend; nowe gałęzie mają obszar `backend`, commity format `agent 2: <wynik>`. Przed pracą i publikacją wczytaj nowe wpisy, w szczególności O1-002, O1-005–007, oraz wskazane raporty na podanych commitach. Komunikaty adresuj `Do: Agent 1 / O1` lub `Do: Agent 3 / O3`. Dopisuj własne wpisy O2 z kolejnym ID, odniesieniami, commitem/PR, testami i ograniczeniami; tylko na końcu sekcji Wpisy, przed wzorem/archiwum. Nie zmieniaj cudzych wpisów i nie potwierdzaj odczytu za odbiorcę. Przy konflikcie zachowaj wszystkich autorów, bez force-push. Jeśli dziennik nadal jest w osobnym niescalonym PR, przygotuj odpowiedź do publikacji po udostępnieniu właściwej bazy, bez drugiego konkurencyjnego dziennika. Numer roli ustalono z użytkownikiem jako O2; przestrzegaj lokalnego pliku tożsamości poza repo i nigdy go nie publikuj.

**Upoważnienie użytkownika z 10.10.2026:** O2 ma komunikować się w razie potrzeby z pozostałymi agentami projektu. Odpowiadaj na przekazania, zgłaszaj rzeczywiste pytania/blokady oraz informuj o zmianach kontraktów i wykonanych etapach, bez ponownego pytania o zgodę na każdą taką wiadomość. Podstawowym kanałem jest wspólny dziennik przez Git/PR; możesz też kierować potrzebne wiadomości bezpośrednio do jednoznacznie zidentyfikowanego czatu O1/O3, jeżeli jest dostępny. Nie zakładaj, że opublikowanie wpisu oznacza jego odczyt; nie uruchamiaj automatyzacji ani nowych czatów samym tym upoważnieniem. Upoważnienie dotyczy współpracy nad tym projektem, nie wiadomości do innych odbiorców ani scalenia cudzych PR-ów.

Bazą E3 ma być aktualny `main` zawierający zaakceptowane E2. Jeżeli użytkownik w wiadomości startowej zlecił scalenie PR #4, wykonaj je dopiero po potwierdzeniu zaakceptowanego head, zielonych wymaganych kontroli i rozwiązaniu ewentualnych konfliktów z ponowną weryfikacją. Jeśli head się zmienił, sprawdź nowe zmiany przed scaleniem. Nie obchodź ochrony gałęzi. Bez takiego zlecenia nie scalaj PR samym odczytaniem tego dokumentu; zgłoś zależność i wykonuj niezależną analizę.

Po przygotowaniu bazy utwórz/reużyj właściwą gałąź `codex/backend-e3-tozsamosc-profile`. To nazwa zgodna z nowymi zasadami `codex/<obszar>-<temat>`; istniejących gałęzi nie przemianowuj. Nie pracuj bezpośrednio na main, nie scalaj Androida ani równoległej gałęzi O1. Ten czat wykonuje **wyłącznie E3**; synchronizacja E4 jest następnym osobnym czatem.

Przeczytaj:

- `WYMAGANIA_PROJEKTOWE.md`, szczególnie 10 oraz 11.2–11.5;
- `docs/ARCHITEKTURA.md`, `docs/PLAN_PRAC.md`, `docs/WORKFLOW.md`;
- `docs/e0/KONTRAKTY_I_INTEGRACJA.md`, `docs/e0/SYNCHRONIZACJA.md`, `docs/e0/ODBIOR.md`;
- `contracts/README.md`, schematy/przykłady domeny, aktywny design OpenAPI oraz `backend/openapi.json`;
- raporty E1/E2, przekazanie E2 dla O1, aktualne modele, migracje, uprawnienia DB, konfigurację, CI i testy.

Nowszy punkt odniesienia O1: **Android 0.6.0 / Room 5**, commit `ad8c0a6f0741f00fa48b90912155ee36633329b4`, [PR #7](https://github.com/Roseru/aplikacja-mobilna/pull/7), gałąź `codex/android-izolacja-kont`. Przeczytaj `android/RAPORT_0_6.md`, aktualne sekcje `android/README.md`, modele/repozytorium właścicieli i wskazane wcześniejsze raporty przez `git show` tego commita, bez merge lub edycji Androida. PR jest zależny od #6 i #1; obecność kodu w gałęzi nie oznacza odbioru/main. O1 raportuje lokalne 51 testów JVM i 39/39 urządzenia, lecz nie potwierdza zdalnego CI, OIDC ani sync; nie przypisuj tych testów własnemu wykonaniu. Demo E2 jest już zintegrowane w nowszym APK według raportu O1, ale pełny KO-30 nadal wymaga dalszych dowodów. Przekazanie E3 ma odpowiadać Room 5 zamiast dawnej bazie Room 2.

Przed kodem podaj krótki plan, zakres odbioru, strukturę modułów i rzeczywiste zależności. Rutynowe wybory rozstrzygaj sam; pytaj wcześnie tylko o brakujące informacje zmieniające zakres lub integrację, pracując równolegle nad niezależną częścią.

## 2. Zakres i granice

E3 dostarcza prawdziwą weryfikację OIDC, konto aplikacyjne/bootstrap, profil, niezmienne wersje celów i oś, zgody online, kalkulator utrzymania oraz prywatne modele/usługi przygotowane do E4. Podłącza chronione odczyty produktów z E2.

Wdrożone operacje E3 pod `/api/v1`:

| Operacja | Rezultat |
|---|---|
| `POST /me/bootstrap` | Techniczna tożsamość, domyślne zgody, UUID/epoka/generacja/czas; bez body |
| `GET /me` | Własny profil albo null, zgody i rewizja osi zgodnie z ProfileRead |
| `GET /me/goals` | Własne niezmienne wersje celów; brak danych to pusta lista |
| `POST /energy-estimates` | Deterministyczny mifflin_pal_v1; nie zapisuje ani nie wybiera celu |
| `PUT /me/consents` | Trwała idempotencja i kontrola niezależnej rewizji zgód |
| `GET /products`, `GET /products/{id}` | Rzeczywiste OIDC, dozwolony opublikowany katalog i dokładne rewizje |

Nie dodawaj `PATCH /me`, `POST /me/goals`, równoległego zapisu posiłków/wagi/szkiców ani pozornego push/pull. Prywatne zapisy klienta przechodzą dopiero przez sync E4. Listy dziennika/wagi/kompletności, statystyki i oficjalny pełny seed należą do E5. Społeczność, Gemini, ranking, Nemesis i korekty AI są późniejsze. W E3 nie wywołuj Gemini, nie uruchamiaj billing ani płatnych usług.

E3 wdraża kontrolę `active/deleting` i generacji oraz wewnętrzne, atomowe rozpoczęcie blokady konta. Nie dodaje nieuzgodnionego HTTP usuwania konta. Pełne skoordynowane usuwanie Keycloak → danych/receipts/znacznika wymaga osobnego zadania O2/O3. To doprecyzowanie podziału prac: zapisz je w planie jako osobny element E4, wymagany przed odbiorem reguły 11.3 i wydaniem. KO-31 obejmuje przełączanie kont/import gościa, nie pełny protokół usuwania. Nie oznaczaj tego protokołu jako wykonanego na podstawie samego pola `deleting`.

## 3. Czytelna architektura i baza

Zachowaj modularny monolit: FastAPI/Pydantic 2, Python 3.13, SQLAlchemy 2/psycopg 3, Alembic i PostgreSQL 17. `calorie_app`/schemat `app` przechowuje dane aplikacji; oddzielna baza `keycloak` tylko dane dostawcy. Backend nie przechowuje haseł i nie łączy się do bazy Keycloak. Android nadal korzysta z Room/SQLite i JSON gzip; nie zmieniaj tej decyzji.

Podział odpowiedzialności, dopasowany do rzeczywistego kodu:

```text
backend/src/calorie_app/
  integrations/keycloak/    # zaufane JWKS i weryfikacja tokenów, bez HTTP logowania hasłem
  modules/identity/         # konto, bootstrap, principal, role i blokada konta
  modules/profiles/         # profil, cele/oś, zgody i kalkulator
  modules/diary/            # posiłek/agregat, waga, DiaryDay i prywatny szkic
  modules/catalog/          # istniejący E2 + chronione odczyty
  core/                    # wspólna konfiguracja/błędy; tylko rzeczywiście wspólny kod
  db/                      # Base, sesje i obsługa transakcji
backend/migrations/versions/
backend/tests/unit/, integration/
infra/local/               # odtwarzalne testowe Keycloak/realm i instrukcja dla O3
docs/e3/                   # raport oraz przekazanie O1/O3
```

W module używaj czytelnych `models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py` tylko tam, gdzie są potrzebne. Router tłumaczy HTTP, usługa reguły i transakcje, repozytorium zapytania. Nie twórz pustych przyszłych modułów, ogólnego frameworka CRUD ani kilku definicji tej samej tabeli. Przeniesienie UserAccount zachowuje jedną definicję i potrzebne importy zgodności. Transakcji nie zatwierdzają ukryte helpery; przyszłe E4 musi atomowo dołączyć rewizję, licznik, receipt i ChangeLog do zmiany encji.

Dodaj nowe migracje po `0005_ration_cursors`, bez edycji odebranych migracji. Upgrade pustej bazy i istniejącego E2 zachowuje konta, sealed katalog, dowody recovery, publikacje i hashe. API/worker nie mają DDL, mutacji alembic_version, dostępu do DB Keycloak ani nowych uprawnień operatora katalogu. Jawnie ogranicz prawa nowych tabel; nie rozszerzaj ogólnych grantów dla wygody.

## 4. OIDC, principal i uprawnienia

Konfiguracja wskazuje dokładny zaufany issuer i JWKS/discovery. Nie przyjmuj URL z tokenu, `jku`, `x5u` lub requestu; unikaj fetchów do dowolnych hostów i niekontrolowanych redirectów. Produkcja HTTPS; jawny wyjątek HTTP może dotyczyć wyłącznie izolowanego lokalnego/CI Keycloak i nie może przypadkowo włączyć się w produkcji. Publiczny issuer i ewentualny wewnętrzny adres JWKS są osobno zaufaną konfiguracją, nie zmianą claimu `iss`.

Weryfikuj podpis **RS256** z algorytmem wybranym w konfiguracji, dokładne `iss`, `aud` zawierające `calorie-api`, niepuste `sub`, `exp`, `iat`, poprawność `nbf`, tolerancję zegara 60 s i `0 < exp-iat <= 300 s`. Czas odrzuca booleany/NaN/Infinity i niepoprawne typy. Rozstrzygnij opcjonalność `nbf` zgodnie ze standardem i rzeczywistym Keycloak: jeśli nie emituje claimu, nie wymagaj fikcyjnego pola; obecny claim zawsze sprawdzaj. Utrwal tę regułę w kontrakcie, konfiguracji i testach.

Odrzucaj ID token oraz access token przeznaczony tylko dla Androida. Sam nagłówek `typ=JWT` nie rozróżnia tych tokenów: sprawdzaj rzeczywisty profil access tokenu Keycloak, np. claim `typ=Bearer`, oraz mapper audience dodający `calorie-api` do access tokenu, nie ID tokenu. Potwierdź na rzeczywistych tokenach, nie tylko ręcznie przygotowanej imitacji.

Role pochodzą wyłącznie z `resource_access.calorie-api.roles`. Udokumentuj macierz dostępu i skonfiguruj rolę `user` dla zwykłego użytkownika. Uprawnienia moderator/admin nie omijają własności danych prywatnych; brak wymaganej roli daje 403. Nie ufaj podobnym rolom klienta Android, realm role ani polu właściciela z payloadu. `(issuer, sub)` ustala konto; e-mail/nazwa nigdy nie są kluczem.

JWKS: cache najwyżej 900 s, ograniczony czas/rozmiar odpowiedzi/liczba kluczy, bez nieograniczonego wzrostu stanu dla różnych kid. Odświeżanie nieznanego kid ograniczaj i koordynuj także przy równoległych żądaniach. Poprawny świeży klucz z cache może obsłużyć przerwę dostawcy; nie używaj go bezterminowo po TTL. Po skutecznym odświeżeniu brak klucza/nieważny token daje 401; awaria dostawcy przy braku niezbędnego klucza daje 503 + Retry-After. 401 ma WWW-Authenticate; błędy zachowują format i request_id E1. Nie utrzymuj transakcji DB podczas sieciowego fetchu kluczy.

Każde uwierzytelnione żądanie, również produkty, bootstrap i replay idempotencji, kontroluje stan konta w DB. Zmiana na deleting i zwiększenie generacji blokują dostęp oraz ponowne tworzenie tej samej tożsamości. Generacja jest wartością serwera; nie zakładaj, że Keycloak automatycznie emituje taki claim. Nie cache'uj aktywności konta w sposób omijający blokadę. Nie loguj tokenów, code/verifier, haseł, JWKS sekretów, DSN ani prywatnych payloadów.

Bootstrap, mutacje zgód, zapis receipts i wewnętrzne mutacje domenowe sprawdzają stan/generację pod wspólną blokadą konta utrzymywaną do commit. Rozpoczęcie deleting używa tej samej blokady. Kontrola wykonana przed transakcją nie zastępuje tej kontroli; mutacja dopuszczona dopiero po deleting nie zapisuje danych. Naturalne tworzenie nowego konta serializuj z późniejszymi mutacjami bez drugiego wiersza tej samej tożsamości. Zwracaj 403 `account_deleting` bez wykonania albo odtworzenia mutacji. Testy odtwarzają obie kolejności przeplatania transakcji.

## 5. Bootstrap, epoka i zgody online

`POST /me/bootstrap` zabrania body. Zgodnie z E0 wymaga `Idempotency-Key` UUID; nie wymaga If-Match. Naturalna unikalność `(issuer,sub)` i zapis receipts muszą działać razem. Konto i jeden rekord zgód `ranking=false`, `automatic_energy_adjustment=false`, revision 1 powstają atomowo; wyścigi różnych kluczy nadal dają ten sam account_id. Utrata odpowiedzi nie tworzy drugiego konta. Nie powstaje profil, cel, historia gościa ani domyślny posiłek. Nie resetuj istniejących zgód.

Bootstrap zwraca dokładny kontrakt E0: account_id, sync_epoch, account_generation, server_time. Dodaj trwałe źródło epoki instalacji, tworzone jednokrotnie poza startupem API. Restart/repliki korzystają z tej samej wartości; API ma odczyt, nie prawo rotacji. Opisz dla O3 zmianę epoki po restore przy zatrzymanym ruchu; pełna procedura snapshot/odzyskiwania jest E4. Nie losuj epoki przy każdym żądaniu ani nie przyjmuj jej od klienta.

Zwiąż wynik bootstrapu z generacją/epoką. Przy identycznym kluczu w tej samej generacji/epoce zwracaj pierwotny wynik, także pierwotny server_time. Stary klucz po zmianie epoki daje 409 `sync_epoch_changed` z bieżącą epoką w kontrolowanym formacie Error/details; klient wykonuje bootstrap z nowym kluczem i dostaje ten sam account_id, aktualną epokę, bez resetu zgód. Zmiana generacji unieważnia stary replay; dla aktywnego konta daje 409 `account_generation_changed` z wymaganiem nowego klucza, a deleting zawsze 403. To jawny wyjątek kontekstowy wobec zwykłego replay, nie nadpisanie poprzedniego receipt. Udokumentuj go w schematach/kontrakcie/przykładach E0 i instrukcji O1 oraz testuj; nie twórz tutaj protokołu uzgodnienia E4. Bieżąca kontrola bezpieczeństwa ma pierwszeństwo przed replayem.

`PUT /me/consents`: pełne wymagane booleany, Idempotency-Key UUID, If-Match z cytowaną revision. Zgody są osobnym zasobem online, nie polem profilu ani outbox. Atomowo zapisuj zmianę, hash body/warunku i wynik, z unikalnością owner+operacja+klucz. Identyczne ponowienie po uwierzytelnieniu i kontroli konta **sprawdzaj przed bieżącą rewizją** i zwracaj pierwotny wynik. Inna treść/warunek przy tym samym kluczu daje 409; niezgodna revision dla nowej operacji 409; brak/zły nagłówek 422. Klucze dwóch kont są niezależne. Pełny wynik przechowuj co najmniej 60 dni, minimalne potwierdzenie do usunięcia konta. Opisz sprzątanie i zachowanie po usunięciu pełnej odpowiedzi, bez odtworzenia mutacji.

`GET /me` po bootstrapie dopuszcza profile:null i goal_timeline_revision=0. Każda chroniona trasa poza bootstrapem wymaga istniejącego aktywnego konta aplikacyjnego. Brak konta zwraca 403 `account_bootstrap_required`, bez ukrytego tworzenia również dla produktów/kalkulatora. O1 wykonuje bootstrap przed tymi wywołaniami. Udokumentuj tę kolejność, kody i przykłady błędów.

## 6. Prywatny model i reguły domenowe

Wdrożone modele, walidatory i usługi mają rzeczywiście działać na PostgreSQL, nie być pustymi klasami. Testy mogą wprowadzać dane przez usługi domenowe/fixture; nie otwieraj w tym celu prywatnego HTTP zapisu.

- **Profile:** własny UUID, owner, revision i stan usunięcia; najwyżej jeden żywy profil na konto. Schemat E0 wymaga pseudonym, height_cm nullable, activity_class i IANA time_zone. UUID profilu jest niezależny od account_id; brak to null.
- **GoalVersion/oś:** niezmienne wersje, osobna rewizja osi, blokada właściciela i kontrola timeline_base_revision. Ręcznie zadany cel jest niezależny od szacunku utrzymania i nie potrzebuje Gemini. Nowa decyzja/korekta tworzy UUID, reason i correction_of; historyczny cel/snapshot pozostają. Nie nadpisuj celu dla daty ani nie usuwaj wersji użytej przez historię. Zachowaj decided_at/effective_from/strefę i jawny audyt korekty zgodnie z E0.
- **Meal/MealItem:** jeden agregat 1..100 elementów, exact ProductRef opcjonalny i pełny snapshot. Złożone FK wymuszają własność celu/posiłku/składników; cudzy goal_id nie może zostać zapisany. Zmiana katalogu nie przelicza historii. Przeliczanie g/ml wymaga odpowiedniej gęstości i źródła; null nie jest zerem. Usunięcie ostatniej pozycji to usunięcie posiłku.
- **Weight:** UUID/owner/revision, dokładne kg, UTC/IANA/local_date; wiele pomiarów dziennie dozwolone.
- **DiaryDay:** UUID i unikalna para owner+local_date, niezmienna strefa ustalona dla dnia. Posiłek stosuje regułę daty/strefy tego dnia; zmiana strefy profilu nie przesuwa historii. Waliduj kompletność na danych zgodnie z E0, bez punktów/statystyk E5/E8.
- **ProductDraft:** prywatny właściciel, payload i rewizja/tombstone zgodne ze schematem E0; bez publikacji i udawanej referencji publicznego produktu.

Własność, kluczowe FK, unikalność i zakresy wartości wymusza również DB. Dodaj testy surowego SQL, które omijają walidator aplikacji. Nie wymagaj fikcyjnego globalnego RLS, ale wszystkie zapytania/usługi prywatne filtrują owner i nie pozwalają workerowi/adminowi ominąć reguł domenowych.

Decimal wejściowy to kanoniczny string do 6 miejsc, NUMERIC z ograniczeniami skończoności i zakresu E0; bez float/NaN/Infinity. Wyjście kalkulatora ComputedDecimal ma do 12 miejsc. Stosuj istniejące reguły precyzji/zaokrągleń; nie obcinaj sum pośrednich do skali wejścia. UTC RFC3339 Z i IANA/local_date sprawdzaj semantycznie, również DST. Rewizje mają zakres E0 i nie zawijają się.

Kalkulator `mifflin_pal_v1` korzysta z parametrów i PAL 1.5/1.8/2.2 ustalonych w E0. Zwraca wejście, metodę, resting_kcal, pal, maintenance_kcal i estimated_at; nie narzuca deficytu ani nie zapisuje celu. Testuj niezależnie ustalone wektory, również submikro wyniku i niepoprawne zakresy.

## 7. Odczyty, paginacja i kontrakty

Chronione produkty korzystają z dozwolonych opublikowanych wersji E2: teraz kanału official. Demo, drafty, nieopublikowane wersje i prywatne szkice nie są ujawniane; brak official nie uprawnia do wystawienia demo. Test sukcesu używa jawnie syntetycznego kompletnego katalogu tylko w bazie testowej. Wyszukiwanie zachowuje nazwy/aliasy/brand/variant i nie łączy podobnych produktów. Szczegół obsługuje dokładną opublikowaną revision; brak revision oznacza najnowszą dozwoloną publiczną wersję, a niedostępna daje 404.

Listy E3 mają limit 1..500/default100, stabilny porządek UUID i rzeczywisty snapshot stron, TTL 60 min bez przedłużania. Token wiąże owner/generację/epokę, operację, filtry/limit i granicę snapshotu; podmiana konta/filtra nie ujawnia danych. Wygasły daje 410 page_expired, błędny 422. Nie utożsamiaj strony z checkpointem sync. Publiczny token racji E2 nie jest tokenem prywatnych list. Niezmienny release E2 może stanowić snapshot produktów bez kopiowania całego katalogu dla każdego konta; token nadal wiąże wywołującego. Stan snapshotów ma ograniczoną retencję i odtwarzalne sprzątanie; ponowienia nie powodują nieograniczonego wzrostu. Udowodnij stabilność przy równoległych zmianach osi/publikacji katalogu.

Wygeneruj `backend/openapi.json` z rzeczywistych DTO/routerów. Przejęte operacje usuń z aktywnego draft albo jawnie zarchiwizuj; nie utrzymuj dwóch obowiązujących definicji. Porównaj auth, body, nullable/required, błędy, pagination i przykłady z normatywnymi schematami E0. Rozszerz kontrolę kontraktów zamiast wyłączać dotychczasowe sprawdzenia wymagające auth/stage E3. Pliki potrzebne runtime mają być również w wheel/obrazie, działając poza repo.

## 8. Rzeczywisty Keycloak i zależności O1/O3

Obecny Compose tworzy PostgreSQL i bazę Keycloak, **nie serwer Keycloak**. E3 przygotowuje odtwarzalny izolowany testowy serwer/realm, konfigurację audience/roles/TTL i testy rzeczywistych tokenów. Użyj oficjalnego obrazu lub dystrybucji, przypnij zweryfikowaną wersję/digest, instrukcję i lockfile. Nie zakładaj, że alias java/py w PATH to odpowiedni runtime.

W tym Windows potwierdzono JDK 21 w `C:/Program Files/Android/Android Studio/jbr/bin/java.exe`; `.tools` ma portable Python/uv/PG, a Docker nie był dostępny. To informacja pomocnicza, nie wymaganie wspólnego repo. Możesz uruchomić dystrybucję testową lokalnie albo obowiązkowy job CI z efemerycznym Keycloak. Nie instaluj płatnych usług ani nie kasuj istniejących wolumenów. Podaj komendy start/stop i posprzątaj tylko własne procesy/testowe zasoby.

Testowy realm `calorie-dev`, publiczny klient `calorie-android`, klient/audience `calorie-api`, Authorization Code + **PKCE S256**, konta A/B i role. Bez sekretu aplikacji mobilnej, wildcard redirectów i skrótu przez password grant. Sekrety administracyjne/testowych użytkowników są efemeryczne lub lokalne, poza Git/logami; konfiguracja realm nie zawiera produkcyjnych credentiali.

Do backendowego testu możesz sam wybrać dokładny loopback callback **testowego harnessu**, z allowlistą i jednoznaczną instrukcją. Odtwórz rzeczywisty code → token exchange, kontrolę PKCE/state, bootstrap/odczyt/zgody i odrzucenie ID tokenu. To nie dowód logowania Androida. Rzeczywisty applicationId/redirect APK dostarcza O1, allowlistę/issuer/HTTPS produkcji O3. Nie wymyślaj ich wartości ani nie zmieniaj Androida. Udokumentuj osiągalność identycznego issuer z hosta/kontenera/emulatora; testowy URI nie staje się produkcyjnym redirectem.

Uwzględnij model O1-007: lokalny rejestr `(issuer,sub)` i owner UUID nie uwierzytelniają i nie są automatycznie serwerowym account_id. O1 potrzebuje jawnego mapowania po poprawnym bootstrapie, bez przepisywania historycznych UUID/operacji. Lokalna generacja aktywnego właściciela/lease zwiększana przy przełączeniu konta jest inną wartością niż serwerowe account_generation i sync_epoch; nie utożsamiaj tych liczników. O1 odtwarza ViewModel/repozytorium i czyści pamięć ekranów przy sesji, a E4 kontroluje właściciela przed wysyłką i zapisem odpowiedzi. E3 przekazuje właściwe kształty, błędy i parametry; nie deklaruje wykonania mobilnego adaptera, WorkManager ani importu gościa.

Oficjalne etykiety, Room/APK, domena produkcyjna, SMTP i Gemini nie blokują lokalnego E3 O2. **Brak wykonanego testu z rzeczywistym Keycloak blokuje końcowy odbiór integracji OIDC E3**: modele i podpisane testowe JWKS można rozwijać, ale same mocki nie zamykają etapu. Zgłoś konkretną zależność/właściciela, jeśli nie da się uruchomić ani lokalnie, ani w CI.

## 9. Weryfikacja i niezależna recenzja

Wykonaj odpowiednie unit/integration na rzeczywistym PostgreSQL 17, walidator kontraktów, Ruff, generowanie OpenAPI, migracje, wheel i obraz. Zachowaj całą regresję E1/E2, w tym timestamp recovery, niezmienne bajty, bounded pagination i importer SQLite. Podaj aktualne liczby; nie zaliczaj odczytania testu, skipu, wiszącej komendy lub raportu poprzedniego etapu jako własnego wykonania.

Obowiązkowe przypadki:

1. A/B: odczyty, FK do celu/posiłku, profile, zgody, prywatne snapshoty i tokeny stron; moderator/admin nie uzyskuje cudzych danych. Zakazane dodatkowe HTTP zapisy nie istnieją.
2. Rzeczywiste podpisy: zły algorytm/podpis/issuer/audience/sub, brak exp/iat, wygasły/przyszły/zbyt długowieczny token, granice skew, ID token, roles z niewłaściwego klienta. Brak auth 401, roli 403, niezbędnego dostawcy 503; jku/x5u/kid nie wywołują arbitralnej sieci.
3. Rotacja JWKS, świeży/wygasły cache przy awarii, unknown kid, wiele równoległych żądań i ograniczenia fetchów/pamięci; brak tokenów/sekretów w logach/błędach.
4. Bootstrap równoległy, ten sam/inny klucz, utrata odpowiedzi, brak częściowo utworzonego konta/zgód, brak resetu zgód, body zabronione; deleting/generation i replay nie wskrzeszają konta. Wspólna blokada chroni wyścig mutacji z deleting. Epoka przetrwa restart; replay po zmianie epoki/generacji i nowy klucz dają opisane wyniki. Wszystkie chronione trasy przed bootstrapem zwracają określony błąd.
5. Zgody: idempotencja przed revision, inna treść/If-Match, wyścigi, A/B ten sam klucz, rollback mutation+receipt, retencja bez powtórnej mutacji.
6. Modele/usługi: jeden żywy profil, jedna data DiaryDay, własność FK, niezmienne cele/korekta i konflikt osi, snapshot historii po aktualizacji katalogu, null/zero, granice NUMERIC i surowy SQL NaN/Infinity; DST/strefa, agregat posiłku, manualny cel bez AI.
7. Paginacja: snapshot pod zmianami, filtrowanie/owner, TTL graniczny/replay, bounded cleanup. Upgrade E2 z reprezentatywnymi danymi, poprawne role DB i readiness nowego head.
8. Rzeczywisty Keycloak/PKCE → access token → backend A/B oraz ID token odmowa, w odtwarzalnym środowisku. CI musi wymagać tego wyniku, gdy job jest dowodem odbioru; brak usługi nie daje zielonego skipu.

Używaj subagentów do niezależnych zadań; ustal zakresy plików, aby nie pisali równocześnie tego samego kodu/DB testowej. Dla prostych kontroli wystarcza low/medium reasoning, dla OIDC, współbieżności i końcowej recenzji high lub wyższe według potrzeby. Oszczędzanie tokenów nie może pomijać obowiązkowej weryfikacji.

Końcowy recenzent musi być niezależny od autora ocenianego zakresu. Ma odczytać bieżący diff/kontrakty, samodzielnie odtworzyć istotne scenariusze i podać findings z priorytetem, plikiem i skutkiem. Wymagamy **co najmniej 9/10 i braku nierozwiązanych istotnych usterek**. Ocena bez uzasadnienia ani zielone testy autora nie wystarczą. Poprawiaj i ponawiaj właściwy przegląd do spełnienia progu; nowe commity dostają aktualne testy/CI.

## 10. Rezultat, Git i przekazanie

Dodaj `docs/e3/RAPORT_E3.md`, `INTEGRACJA_O1.md`, `KONFIGURACJA_O3.md` oraz aktualizuj istniejące README/plan/architekturę/kontrakty w zakresie rzeczywistych zmian. Nagłówek główny każdego naszego dokumentu kończy się `- osoba 2`. Raport zawiera zachowanie, strukturę, migracje/kompatybilność, komendy odtworzenia, faktyczne wersje, wyniki i zakres własnych/subagentowych testów, ocenę, braki O1/O3 oraz commit/PR/CI. Oddziel gotowość O2 od niewykonanej integracji APK/produkcji.

Po wykonaniu i recenzji zrób spójny commit `agent 2: <konkretny wynik>`, push gałęzi i PR do main, jeśli zlecono to w wiadomości startowej; dołącz PR do czatu. Przestrzegaj wymaganej recenzji innej osoby z AGENTS/workflow; ocena subagenta jej nie zastępuje. Nie używaj force-push i nie wersjonuj runtime/cache/.env/DB/sekretów. Sprawdź sukces wymaganych zadań dla aktualnego head, również po ostatniej poprawce raportu; istniejący ci-required nie może stać się zielony mimo brakującego testu. Przed publikacją ponownie pobierz komunikację, a upoważnione przekazanie wyniku zapisz zgodnie z sekcją 1. Nie scalaj E3 ani nie rozpoczynaj E4 bez osobnego polecenia użytkownika po odbiorze.

Do sprawdzania zależności korzystaj z aktualnej dokumentacji pierwotnej: [Keycloak OIDC](https://www.keycloak.org/securing-apps/oidc-layers), [oficjalne dystrybucje](https://www.keycloak.org/downloads), [PyJWT API](https://pyjwt.readthedocs.io/en/stable/api.html), [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252), [RFC 7519](https://www.rfc-editor.org/rfc/rfc7519). Wybór konkretnej biblioteki/dystrybucji ma być zweryfikowany i przypięty podczas implementacji, z zachowaniem powyższych wymagań projektu.

## 11. Przygotowana odpowiedź O2 na przekazania O1

To przygotowana treść do jedynego wspólnego dziennika, **jeszcze nieopublikowana wiadomość**. Przy publikacji pobierz nowe wpisy, sprawdź właściwą bazę po PR #5, dobierz następne wolne ID O2 i zaktualizuj datę/stan PR. Nie twórz drugiej tablicy ani nie publikuj cudzych zmian organizacyjnych jako własnych. Treść opiera się na faktycznym odczycie z 10.10.2026; kolejne wykonanie E3 dodaje osobny wynik, nie deklaruje go wstecznie.

```markdown
### 2026-10-10 — Agent 2 — ODPOWIEDŹ — O2-001

**Agent 2:** Do: Agent 1 / O1 i Agent 3 / O3.
- Status: ODCZYTANE dla przekazań O1; WYMAGA ODPOWIEDZI dla parametrów integracji.
- Odniesienie: O1-002, O1-005, O1-006 i O1-007.
- Źródło odczytu: komunikacja aed79c7, Android ad8c0a6 / PR #7,
  RAPORT_0_6.md, LocalOwners.kt oraz fragmenty DiaryRepository.kt.
  Odczytano też przekazania importera E2 i lokalnej analityki.
- Potwierdzam nowszy punkt odniesienia Android 0.6 / Room 5.
  Raportowane testy O1 nie są moim wykonaniem ani pełnym odbiorem PR #7.
  Lokalny owner UUID i generacja lease są odrębne od account_id,
  account_generation i sync_epoch backendu. E3 przekaże jawne mapowanie
  po bootstrapie oraz błędy sesji/konta; E4 dostarczy push/pull i odzyskiwanie.
- E2 O2 na 52f3547 / PR #4 przeszedł przegląd poprawionych dat/recovery
  i paginacji oraz zielone CI 38042927890: 396 PASS, cztery zadania success.
  Przy odczycie PR #4 nie był scalony. Demo zachowuje bajty/hash;
  materiały MRE 2026 pozostają osobnym zbiorem źródłowym.
- E3 ma przygotowany master prompt; implementacja nie została rozpoczęta.
  Chronione produkty/bootstrap/profil/cele/kalkulator/zgody należą do E3,
  prywatne zapisy klienta wyłącznie do sync E4; nie dodamy PATCH /me
  ani POST /me/goals. Brak wpisu/nieznane wartości nie stają się zerem.
- Do O1: potwierdź docelowy applicationId i dokładny redirect PKCE APK;
  podaj ograniczenia adaptera sesji/owner, które wpływają na kontrakt.
- Do O3: podaj stan testowego Keycloak, dokładny issuer/JWKS,
  calorie-android/calorie-api, audience/role/TTL i dozwolone redirecty
  oraz stan CI Androida/dostawy APK. Bez sekretów w odpowiedzi.
  Produkcyjnych adresów nie wymyślamy; lokalny/CI harness może wykonać
  rzeczywisty test E3, lecz nie dowodzi integracji APK.
- Następny krok O2: wykonanie E3 w osobnym czacie na właściwej bazie,
  po czym nowe przekazanie z commitem, PR, CI i wynikami testów.
```
