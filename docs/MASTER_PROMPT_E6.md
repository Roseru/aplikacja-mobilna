# Master prompt E6 — backend katalogu społeczności - osoba 2

Wersja 1, 11 października 2026 r. Wykonawca: OSOBA 2 / Agent 2. Rezultat: **E6-O2**. Priorytet: poprawność, zachowanie historii i czytelny kod. [Niezależny odbiór instrukcji](e6/RECENZJA_MASTER_E6.md): 9,3 i 9,5/10, bez otwartych istotnych P1/P2; implementacja ma osobny odbiór.

## 1. Cel i rzeczywista bramka

Dostarcz działający backend publikacji prywatnych szkiców, wyszukiwania i dopasowania produktów, głosów, zgłoszeń, moderacji i audytu. Jeden spójny PR obejmuje ten rezultat wraz z migracjami, kontraktami, regresją oraz przekazaniem O1/O3. Kryteria: WF-07/08, UC-14/15/20, KO-09/13 oraz zachowanie WF-06, 11.2–11.4 i historii używanej przez statystyki E5.

Baza odebranych zależności: main `86121307b0a7ebe99f62775ec832097af19d613d`, E5-O2-R z PR #15 i checkpoint z PR #16. CI tego main: 693 unit + 647 PostgreSQL17.11 + 9 real Keycloak = 1349 PASS. Wiadomość startowa poda nowszy main zawierający ten master; nie resetuj checkoutu do historycznego SHA.

Zależności techniczne są obecne: niezmienne wersje/źródła katalogu E2, tożsamość/role i własność E3, prywatny ProductDraft oraz sync/deletion E4 i odczyty/statystyki E5. Brak official ARPOL, APK i produkcyjnego HTTPS nie blokuje samodzielnej implementacji E6-O2 na izolowanym PG/Keycloak i jawnych danych testowych. Brak modeli community, pg_trgm, ACL, purge i endpointów to zadania tego etapu, nie zewnętrzna blokada startu.

Pełne **E5 pozostaje otwarte**: E5-O2-C wymaga właściwych etykiet, wariantów, jednostek i kompletu źródeł z 11.4, official eksportu/importu i KO-01–02/30; O1/O3 dostarczają APK/Room/WorkManager/KO-31 oraz HTTPS/issuer/restore. **PASS E6-O2 nie oznacza pełnego E5 ani pełnego zespołowego E6 lub wydania.** Nie publikuj demo/testowych produktów jako official. Zachowaj audyt źródeł i Random Data; kontakt z dostawcą wymaga osobnego upoważnienia.

Koordynator zwalnia ten etap wyłącznie jawnym zleceniem z SHA opublikowanego mastera i odebranym main. Sam plik nie uruchamia pracy. Wykonawca przygotowuje PR i dowody, nie scala go i nie zaczyna E7.

## 2. Wejście, izolacja i organizacja

Przeczytaj AGENTS.md, WYMAGANIA_PROJEKTOWE.md, ARCHITEKTURA/PLAN_PRAC/WORKFLOW, aktualny KOMUNIKACJA_AGENTOW i MASTER_PROMPT_KOORDYNACJA. Przejrzyj raporty oraz integrację E2–E5, obecne catalog/identity/diary/sync/analytics, migracje 0001–0012, ścisły ProductDraft, ProductDTO, backend/openapi.json, contracts/openapi/design-v1.yaml i tools/sync_client. Obowiązująca korekta bramki jest opisana w planie i komunikacji; poprzednie WAITING_EXTERNAL pełnego E5 pozostaje historią, a nie zakazem tego zlecenia.

Sprawdź status, gałąź, remote, main, otwarte PR-y i nowe wpisy zespołu. Nie przeglądaj niezwiązanych gałęzi. Zachowaj nieśledzone pliki, .review-o2 i główny checkout E4. Nowy czat lokalnego projektu może zacząć w tym starym checkoutcie: odczytaj master przez `git show <SHA-ze-zlecenia>:docs/MASTER_PROMPT_E6.md`, pobierz referencje i utwórz własny managed worktree z tego main. Nie przełączaj głównego katalogu. Preferuj istniejący odpowiedni własny worktree; nie używaj checkoutu koordynatora do zmian.

Gałąź: `codex/backend-e6-spolecznosc`, chyba że istnieje już otwarty PR tego samego rezultatu. Jeden wykonawca O2. Bazy, porty, procesy i katalogi testów własne; zatrzymuj tylko swoje procesy i zachowuj diagnostykę poza Git. Nie wypisuj sekretów, DSN, JWT, prywatnych payloadów ani weryfikatorów SCRAM.

Podział czytelny dla człowieka:

```text
backend/src/calorie_app/modules/catalog/
  models.py, schemas.py, ...       # istniejący katalog i dostawa official
  matching.py                     # wspólne reguły normalizacji/tożsamości
  community/
    models.py, schemas.py
    repository.py, service.py, router.py
    idempotency.py, tokens.py      # tylko gdy mają własną odpowiedzialność
  moderation/
    schemas.py, service.py, router.py
backend/migrations/versions/       # nowa migracja po 0012
backend/tests/unit/, integration/, contract/
contracts/examples/, test-vectors/, schemas/
docs/e6/
```

Utrzymaj przepływ router → schemat → usługa → repozytorium → transakcja PG. Nazwy odpowiadają przypadkom użycia, moduły mają krótkie docstringi. Wspólne reguły Decimal/źródeł i istniejące mechanizmy konta są używane ponownie. Nie twórz drugiego backendu ani wielkiego pliku obsługującego cały etap. Usługi używają caller-owned Session; brak ukrytego commit w repozytorium. Szczegółowy podział może odpowiadać rzeczywistym zależnościom, ale odpowiedzialności pozostają jawne.

## 3. Kontrakt i publikacja

Zachowaj dotychczasowe official `/products`, `/products/{id}`, ProductDTO/ProductPage, pp1, racje, manifest/gzip oraz ścisły sync-v1 ProductDraft. Nie dodawaj pól do starych odpowiedzi lub payloadu szkicu bez zgodnego, jawnego wersjonowania. Normatywny runtime OpenAPI nadal generujemy z FastAPI do backend/openapi.json; usuń implementowane placeholdery projektu zgodnie z istniejącym generatorem/walidatorem, bez dwóch niezależnych normatywnych definicji.

Nowe chronione operacje `/api/v1`:

| Operacja | Konkretny wynik |
|---|---|
| POST /products | Publikacja własnej żywej rewizji szkicu albo wskazanie istniejącej dokładnej wersji |
| POST /products/matches | existing_variant / manual_candidates / new_product, referencje i uzasadnienia |
| GET /community/products i GET /community/products/{id} | Nowy ścisły CommunityProductDTO, aktualny lub dokładny publiczny snapshot |
| GET /products/{id}/feedback | Oddzielne plus/minus, moja wartość/rewizja i is_mine; również dla dostępnego official |
| PUT /products/{id}/vote, DELETE /products/{id}/vote | Zastąpienie/wycofanie jednego własnego głosu |
| POST /products/{id}/reports | Zgłoszenie konkretnej dostępnej wersji, również official |
| GET /moderation/reports, PATCH /moderation/reports/{id} | Kolejka i jawne rozstrzygnięcie/przekazanie zgłoszenia |
| PATCH /moderation/products/{id} | Korekta nową wersją, weryfikacja, hide/unhide community z powodem |
| POST /moderation/products/{id}/merge | Audytowane source → canonical target bez zmiany historii |

Zwykły użytkownik nie odczytuje cudzych szkiców, zgłoszeń, receipts ani identyfikatorów kont. Community DTO rozdziela pochodzenie, weryfikację, widoczność i kompletność; pokazuje źródło, jednostki, exact revision, canonical ID oraz osobne głosy. Nie ujawnia issuer/sub, account UUID, draft UUID ani prywatnego autorstwa. Informacja is_mine jest liczona dla caller; administrator publikujący official nie staje się autorem produktu.

POST /products wskazuje draft_id i oczekiwaną rewizję. Konto i właściciela ustala serwer. Cudzy/nieistniejący szkic daje jednakowe 404; usunięty szkic 404, stale revision 409. Pod blokadą odczytaj własną dokładną treść, sprawdź jej bieżącą rewizję i opublikuj wyłącznie zatwierdzone pola. Nie zmieniaj UUID szkicu w UUID produktu, nie usuwaj szkicu i nie przepisuj jego payloadu. Oddzielne prywatne powiązanie tej rewizji z wynikiem i hashem metadanych publikacji zapobiega ponownej publikacji pod innym kluczem: identyczna decyzja zwraca zapisany ProductRef, zmienione metadane/wybór dla już powiązanej rewizji dają409, bez drugiego produktu. Późniejsza edycja szkicu nie edytuje publicznego snapshotu.

Istniejący szkic nie ma składu/receptury, aliasów i klasy źródła. Przyjmij je w osobnym online DTO publikacji: source_kind `label|recipe|estimate|ai`, oryginalny opis źródła, opcjonalny skład/recepturę, aliasy i jawną porcję, gdy szkic jej nie zawiera. AI jest oznaczeniem pochodzenia; E6 nie wywołuje Gemini. Źródło i dodatnia porcja są wymagane, podstawą jest 100 g albo 100 ml. Kcal/B/T/W mogą być null i wtedy produkt ma complete=false oraz listę braków. Nowa publikacja ma serwerowo community/unverified/visible; klient nie nadaje verified/official ani właściciela/roli. Nie zastępuj braków zerami i nie osłabiaj walidacji official. Zachowaj Decimal/NUMERIC, parę gęstość/źródło i istniejące granice wartości.

Wynik publikacji zawiera rodzaj decyzji i dokładny ProductRef, nie cały ukrywalny publiczny payload w receipt. Decyzja użycia wybranego istniejącego produktu jest świadomym wyborem referencji; nie zmienia danych szkicu i nie udaje stwierdzenia zgodności. Automatyczne wskazanie ma spełniać reguły poniżej. Stale/hidden/merged wybór wymaga aktualizacji wyboru, nie cichego przekierowania mutacji.

W DTO community complete oznacza znane wszystkie cztery wartości odżywcze (kcal/B/T/W) i poprawne wymagane pola publikacji; missing_nutrition_fields jest dokładną listą nieznanych wartości. Kompletność danych do dopasowania i missing_identity_fields są osobne: znane makra nie dowodzą znanego składu lub wariantu. Nie łącz tych znaczeń w jeden niejasny boolean.

## 4. Deduplikacja i współbieżność

NFKC + casefold + uzgodniona normalizacja białych znaków dla nazwy/aliasów/marki/wariantu/składu. Zachowaj oryginalne teksty. pg_trgm i indeks są selektorem ograniczonej listy kandydatów; nie dowodem identyczności. V1 automatycznie wskazuje istniejący wariant tylko przy wspólnej znormalizowanej nazwie/aliasie i zgodnych znanych marce, wariancie, składzie/recepturze oraz jednostce. Puste pola nie są wildcard. DTO tożsamości odróżnia known, unknown i not_applicable: known wymaga wartości, pozostałe jej nie udają. Domowy rosół może mieć markę/wariant not_applicable i znaną recepturę; baton z nieodczytaną etykietą ma unknown i daje wybór ręczny. Skład nie jest not_applicable: także produkt jednoskładnikowy ma jawny skład albo unknown. Zachowaj zgodność ze znanymi wartościami brand/variant szkicu.

Energia: dokładny Decimal `abs(a-b)/max(a,b) <= 0.10`; dwa zera są zgodne, zero/dodatnia nie. Brak energii lub składu daje wyłącznie manual_candidates, także pustą listę z missing_identity_fields, jeśli nic nie znaleziono; to nie dowód nowej tożsamości. Świadoma publikacja niekompletnego wpisu nadal jest dozwolona. Porcja/opakowanie nie jest osobną tożsamością: mały i duży rosół są jedną definicją przy różnych ilościach. Inny przepis, marka, skład lub wariant nie staje się duplikatem od podobnych kcal. G i ml są różnymi podstawami; bez potwierdzonej gęstości nie porównuj ich automatycznie. Same ml są poprawne i nie wymagają gęstości.

Dla udokumentowanego rho w g/ml: wartość na100g = wartość na100ml / rho; na100ml = na100g × rho. Gęstość musi dotyczyć tego samego wariantu; sprzeczne dane gęstości oznaczają ręczny wybór, bez uśredniania. Porównanie progu wykonuj dokładnie przez przemnożenie stron nierówności, bez float i bez zaokrąglenia dzielenia. Przykład: rho1.2,240kcal/100ml daje200kcal/100g;200 wobec180 jest dokładnie10%, wobec179 przekracza próg. Umieść to we wspólnych wektorach.

Wynik `/matches` nie rezerwuje produktu. Podczas publikacji ponownie sprawdź dostępne official i community po zdobyciu blokady. Zero wysokich zgodności pozwala na nowy wpis; jedna zwraca istniejący wariant; wiele wymaga jawnego wyboru i 409 przy nieuzgodnionej publikacji. Podobne niejednoznaczne kandydatury nie blokują świadomego nowego wariantu z rozróżniającymi danymi. Wybór istniejącego produktu nie nadaje autorstwa ani statusu verified.

Poprawna prosta strategia v1: jeden relacyjny wiersz blokady katalogu dla publikacji/merge i zmian community/feedback. READ COMMITTED, ponowny odczyt po zdobyciu blokady, krótka ograniczona transakcja. Dwie równoczesne zgodne publikacje z różnych szkiców dają jeden wpis i dwa poprawne wyniki, także przy drobnej różnicy kcal. Sam unique hash payloadu nie chroni fuzzy decyzji. Kolejność: konto aktora → jego sync counter tylko gdy potrzebny → blokada katalogu → official channel/package gdy potrzebne → produkty w porządku UUID → vote/report/receipt. Nie blokuj arbitralnie cudzych kont w merge i nie wykonuj HTTP/Keycloak w tej transakcji. Purge używa tej samej kolejności.

Aktywacja official przez publish_package obecnie ma osobną blokadę channel/package. Dołącz jej fazę aktywacji do wspólnej kolejności (blokada katalogu przed channel/package), zachowując durable bytes, immutable snapshot i monotoniczny release E2. Bez długiego eksportu/I/O pod nową blokadą. Official commit wcześniejszy od decyzji E6 jest widoczny w ponownym matching; późniejszy release może dodać wariant po publikacji community i nie uruchamia automatycznego merge ani przejęcia głosów. Zapisuj exact ref/release użyty w decyzji i sprawdź oba porządki w rzeczywistym wyścigu PG. Rollout wyklucza stare równoległe narzędzie publikacji nieprzestrzegające nowej kolejności.

## 5. Głosy i zgłoszenia

Jeden bieżący głos konta na dostępny canonical produkt, wartość 1 albo -1. DB wymusza unikalność i zakres. Zmiana zastępuje głos, DELETE wycofuje; zachowaj rewizję/tombstone dla konfliktów. Przykład nowego kontraktu: osobny parser If-Match dopuszcza `"0"` dla braku głosu; stary parser E3 dodatnich rewizji pozostaje bez zmiany. Rewizja mojego głosu nie jest rewizją produktu ani globalnych liczników, więc głos innej osoby nie powoduje mojego stale write.

Własność jest serwerowa. Zakaz głosu na własny wpis obejmuje autorów wszystkich źródłowych produktów scalonej grupy. Oddziel plus/minus i liczbę głosujących; głosy nie zmieniają makr ani weryfikacji, także official. Liczniki i głos aktualizuj atomowo; test rzeczywistych wyścigów, nie naprawa po czasie.

Zgłoszenie: powód, opis, dokładna zgłaszana wersja, stan i własna rewizja. Zwykły user otrzymuje potwierdzenie własnego zgłoszenia, bez danych innych autorów. Moderator ma bounded kolejkę, filtr statusu i jawne rozstrzygnięcie z uzasadnieniem/audytem. Stany v1: open, resolved, dismissed, referred_to_admin. Przekazanie official do administratora nie udaje rozwiązania błędu; korekta official wymaga istniejącego procesu nowego release, a nie PATCH sealed wersji przez moderatora. Moderator nie otrzymuje prywatnego szkicu publikacji ani dziennika zgłaszającego.

## 6. Moderacja, scalenie i trwałość historii

Rola bazowa user zgodnie z obecnym current_principal; operacje moderatora dodatkowo wymagają catalog_moderator albo admin z `resource_access.calorie-api.roles`. Nie zakładaj hierarchii ról Keycloak. Sam admin/moderator bez user nie otwiera starych prywatnych endpointów. Żadna rola nie daje domyślnego wglądu w cudze dane konta. Uprawnienie sprawdzaj przed ujawnieniem zasobu i przed replayem.

Moderator zmienia wyłącznie community. Korekta wartości/źródła tworzy nową niezmienną wersję; weryfikacja i widoczność są osobnym stanem/revision z powodem. Verified wymaga kompletu wartości odżywczych i potwierdzenia ich źródła/wersji przez moderatora; nieznane dane nie uzyskują tego statusu. Source_kind pozostaje label/recipe/estimate/ai, więc przegląd szacunku nie zamienia go w etykietę ani official. Hide/unhide nie edytuje sealed snapshotu. Official i jego bajty/manifest/membership pozostają pod kontrolowanym procesem administratora. Głosy nie mogą opublikować community w official.

Audit jest append-only: aktor, czas DB, action/operation ID, powód, stare/nowe exact refs i wersje stanu, source/target. Nie kopiuj całego prywatnego szkicu lub dziennika. Użytkownik ani worker nie nadpisuje audytu; purge ma tylko jawny zakres usuwania identyfikatorów osobowych.

Merge sprawdza obie oczekiwane wersje stanu, blokuje source/target w stałej kolejności i zapisuje relację kanoniczną oraz audyt atomowo. Source i target są różnymi nieukrytymi community roots; nie scalaj w official w tym v1. Same kcal nie uzasadniają merge różnych wariantów. Moderator podaje potwierdzenie tożsamości i powód; sprzeczne znane marka/wariant/skład/jednostka dają409 identity_conflict. Błędne metadane można najpierw poprawić nową audytowaną wersją z uzasadnieniem i źródłem, potem ponowić merge z aktualnymi oczekiwanymi wersjami; sam tekst powodu nie omija zgodności. Zablokuj self-merge, cykle, rozwidlenia i nieograniczone łańcuchy. Resolver ma jawny limit głębokości, a przekroczenie nie zwraca losowego targetu.

Zachowaj wszystkie products, exact product_versions i sources, sealed pakiety, racje oraz membership. Nie przepinaj dawnych MealItem/RationComponent, UUID szkiców, payloadów/receipts sync, recovery mappings ani materializowanych read/sync snapshotów. Historyczne wartości i statystyki muszą być identyczne. Stary offline meal z poprawną exact referencją nadal synchronizuje się po hide/merge; nie dodawaj wymogu bieżącej publicznej widoczności do tej walidacji.

Nowe wyszukiwanie wybiera canonical roots. Mutacja starego scalonego ID daje 409 z canonical ref; nie działa pod innym ID po cichu. GET exact revision zachowuje pierwotną tożsamość/makra oraz podaje aktualny canonical ref, jeśli publiczny odczyt jest dozwolony. Hide źródła lub celu odcina zwykły społecznościowy odczyt również przez stary token; własna historia posiłku nadal używa swojego snapshotu.

Polityka głosów merge v1: **nie przenosimy opinii source na target**. Source głosy stają się nieaktywne z zachowaną historią i powodem w audycie; target zachowuje swoje głosy poza autorami wszystkich scalonych wpisów, którzy nie mogą mieć aktywnego samogłosu. Nie sumuj dwóch głosów jednej osoby. Użytkownik może później świadomie głosować na target, o ile nie jest autorem. Replay merge nie wykonuje ponownie dezaktywacji. Zgłoszenia zachowują original exact ref i canonical powiązanie, bez fałszywego rozstrzygnięcia.

## 7. Paginacja, zasoby i prywatność

Nie materializuj całego rosnącego community na każde wyszukanie i nie skanuj go w Pythonie. Indexed SQL, keyset po stabilnym ID oraz LIMIT. V1 używa relacyjnej monotonicznej wersji katalogu: pierwsza strona zapisuje ją w podpisanym tokenie, a zmiana danych potrzebnych DTO/rankingu/liczników daje na kolejnej stronie 409 catalog_changed i restart. Odczyt wersji oraz strony odbywa się w spójnym widoku zabezpieczonym tą samą blokadą współdzieloną katalogu; nie sprawdzaj wersji osobno przed niespójnym SELECT. Kolejka moderatora ma analogiczną własną wersję. Stary pp1 official nie zmienia semantyki.

Token ma oddzielną domenę/prefix community, owner/generation/epoch, query/filter/sort/limit/after, wersję i początkowy expiry. TTL 60 min bez przedłużania, limit 1–500/domyslnie100, query 1–100 znaków, token do4096. Odczyt bieżącej tożsamości i widoczności także na następnych stronach. Uszkodzony/cudzy token 422, wygasły 410; rotacja klucza unieważnia stare podpisy zgodnie z poprawioną instrukcją E5, bez zmiany epoki i bez deklaracji keyring.

Jedna odpowiedź strony max1MiB UTF-8, max500 rekordów; dobieraj stronę po bajtach, a rekord przekraczający limit jest kontrolowanym błędem. Body mutacji max1MiB, głębokość JSON max20, limit list/tekstu i ścisłe extra=forbid. V1: max50 aliasów, max100 pozycji składu (lub opis receptury max4000 znaków), pola nazwy/marki/wariantu/źródła/opisu raportu/powodu max2000. Nie przekazuj dostarczonych URL do HTTP fetch ani SQL. Kandydaci max20, deterministyczne sortowanie i uzasadnienia; truncation nie może dać fałszywego „brak duplikatu” — przed publikacją użyj ograniczonego SQL sprawdzającego pełny predykat wysokiej zgodności, a nadmiar takich trafień oznacza wybór ręczny.

Dodaj jawne admission/rate limits dla trwałych operacji, aby powtórzenia/sprzątanie nie otwierały nieograniczonego zapisu. V1 dla konta: nowe produkty 20/dobę DB UTC, nowe zgłoszenia 50/dobę, zaakceptowane zmiany głosu 200/dobę i wszystkie nowe wiersze receipts E6 (także utrwalone odmowy) 1000/dobę; moderator actions także mieszczą się w tej ostatniej puli. Admission poprzedza zapis nowego receipt; 429 nie produkuje kolejnego trwałego wiersza poza limitem. Identyczny replay nie zużywa ponownie puli. Limity nie blokują istniejącego sync/dziennika, dają429 i Retry-After; wyścigi nie przekraczają limitu, worker nie zeruje puli w retry. Udokumentuj rozmiary i koszt, nie dodawaj Redis.

Chronione odpowiedzi, błędy auth/walidacji/middleware i feedback mają Cache-Control:no-store. Oczekiwane statusy:401 JWT,403 rola/stan/własny głos,404 niedostępny zasób,409 wersja/klucz/deduplikacja/merge/katalog/epoka,410 token,413 body,422 kontrakt/jednostka/Decimal,429 quota,503 DB/migracja/JWKS. Używaj ApiError i stabilnych kodów; brak500 dla oczekiwanego konfliktu. Błędy/logi nie zawierają prywatnych payloadów.

## 8. Idempotencja i restore

Każda mutacja online ma UUID Idempotency-Key i kontrolę właściwej wersji zasobu. Osobny trwały rejestr E6; stary OnlineReceipt z bootstrap/consents nie zostaje poluzowany bez migracji. Klucz owner + operation_kind + operation_id; hash obejmuje metodę, path/target, oczekiwane wersje, wybrany produkt i całą semantyczną treść, z istniejącą normalizacją Decimal.

Najpierw aktualne JWT/rola, blokada active account, generation i kontekst epoki, potem hash/replay. Nowe mutacje E6 wymagają X-Sync-Epoch z bootstrapu; stare żądanie nie może z nowym Idempotency-Key ominąć restore. GET sprawdza aktualny kontekst konta, a strona wiąże go w tokenie. Błąd epoki ma pierwszeństwo przed rewizją. Ustal zgodne błędy i przykłady O1; nie zmieniaj istniejącego formatu operacji sync.

Identical replay zwraca pierwotny wynik operacji przed sprawdzeniem obecnej rewizji, bez nowych efektów. Nie odświeża publicznego payloadu ani nie ponawia publikacji po hide/merge. Receipt zawiera minimalny wynik/referencje, nie ukrywalne dane produktu/zgłoszenia; aktualne publiczne dane czyta się przez odrębny autoryzowany GET. Ten sam klucz z inną treścią daje409. Efekt, licznik/quota, audit i wynik są jedną transakcją; ACK po commit.

Pełna odpowiedź minimum60dni, minimalne potwierdzenie/hash/wynik/exact refs do usunięcia konta. Po usunięciu pełnej odpowiedzi jawny idempotency_result_expired z informacją o wykonaniu albo odmowie, bez ponownej mutacji. Szczegółowy denial może wymagać bieżącego odczytu; konflikt/odmowę rejestruj konsekwentnie. Worker sprząta bounded batch, zachowując minimalny rejestr i mappingi. Nie wywołuj dostawcy lub I/O sieciowego pod blokadami. Po restore współdzielone mapowania mogą być cofnięte z backupem: stara epoka wymaga uzgodnienia przez klienta, nigdy automatycznego powtórzenia publikacji/głosów/merge.

## 9. Migracje, ACL, purge i downgrade

Nowa migracja po0012: relacyjne publiczne metadane/current state i immutable metadata exact wersji, kanoniczne mappingi, prywatne autorstwo/publication binding, votes, reports, audit, receipts, quota i wersje paginacji. Nie edytuj0001–0012. Dodaj pg_trgm i indeksy przez migratora/provisioning z jawną kontrolą dostępności; API nie instaluje extension. Readiness rozpoznaje nowy wymagany head, rollout/worker/retencja opisane dla O3.

Zapieczętowane ProductVersion/ProductSource i offline membership nadal chroni DB guard. Community writes mają wąskie sprawdzane funkcje/ACL, bez GRANT całych tabel pozwalającego zmienić official. jawne REVOKE także wobec odziedziczonych/default PUBLIC grants. API nie wykonuje DDL ani UPDATE/DELETE audytu; worker ma tylko cleanup; deletion operator wąski purge. SECURITY DEFINER ma kwalifikowane nazwy, zamknięty search_path, walidację i brak PUBLIC EXECUTE. Testuj efektywne prawa tabel/kolumn/NOLOGIN/PUBLIC, nie tylko has_table_privilege.

Purge z0011 zna ręczny stary graf i musi dostać nowe bezpieczne rozszerzenie. Po potwierdzonym usunięciu tożsamości usuń prywatne bindingi/receipts, głosy i dane zgłoszeń konta, odłącz identyfikatory autora/aktora od współdzielonych publikacji i audytu. Publiczny interfejs nie identyfikuje autora; zachowane nieosobowe wersje/źródła i minimalny ślad decyzji nadal obsługują cudzą historię i pakiety. Nie zachowuj issuer/sub/account UUID ani osobowej treści raportu pod pozorem audytu. Nie kasuj wspólnego katalogu kaskadą od konta. Publiczne pola wynikają z jawnie zatwierdzonej publikacji, nie z kopii danych profilu/dziennika. Dokładną politykę i zakres anonimizacji pokaż w decyzjach, SQL i testach.

Wyścig deletion kontra publikacja/głos kończy się commit przed deleting albo odmową, bez wskrzeszenia konta/zapisu po purge. Testuje to realny PG oraz istniejący protokół blokady generacji; nie osłabiaj provisioningu sekretu deletion operatora ani ochrony jego logów.

Downgrade v1: na bazie bez trwałych danych E6 odwraca nową warstwę, zachowując pełny graf E4/E5; pg_trgm nie jest usuwane, jeśli używa go coś poza E6. Przy produktach/wersjach/źródłach E6, mappingach, głosach/raportach/audycie lub minimalnych receipts **odmów atomowo przed pierwszym DDL**. Guard sprawdza także artefakty E6 w starych współdzielonych tabelach. Nie deklaruj bezstratnego usunięcia funkcji mającej dane. Test downgrade refusal i rowsets/hash bez zmian, pusty downgrade/re-up oraz upgrade starego reprezentatywnego grafu. O3 dostaje jawny rollout i ograniczenie rollbacku; przywrócenie backupu jest osobną procedurą z nową epoką, nie automatycznym rozwiązaniem.

## 10. Weryfikacja, subagenci i kryteria PASS

Przed kodem zapisz decyzje v1 i konkretne przykłady kontraktu. Możesz używać subagentów; rozdzielaj niezależne zakresy z jednym właścicielem pliku/transakcji. Dobieraj reasoning do zadania: medium dla ograniczonego odczytu/kontraktu, high dla architektury, security, współbieżności i odbioru. Nie obniżaj reasoning kosztem pominięcia dowodów; autor nie recenzuje własnego modułu jako niezależny nieautor. Recenzent ma oddzielny checkout/DB i nie zmienia równolegle runtime autora.

Wymagane testy i dowody:

1. Unit i kontrakty: wszystkie stany DTO/źródeł/null/kompletności, Decimal, zera, dokładnie10% i ponad próg, Unicode/aliasy, brak składu/energii, różne marki/warianty/przepisy, mały/duży rosół, g/ml/density. KO-09 ma porównanie z niezależnym oracle, nie kopię predykatu implementacji.
2. PG/HTTP A/B: własny/cudzy/stale/deleted draft, payload owner/role spoof, prywatny szkic niewidoczny w search, publication binding i niezmienny szkic. Cel/dziennik/waga/read/stat nadal bez zmian.
3. Głosy/reports official i community: PUT/change/DELETE, wersje/tombstone, własny głos, liczniki, report resolution/referral, kontrola roli i cudzej własności; KO-13 również po merge/purge.
4. Rzeczywiste bariery PG: dwie zgodne/fuzzy publikacje, aktywacja official versus publikacja community w obu porządkach, dwa retry jednego klucza, różne body, draft edit/delete versus publish, konta deleting, vote/change/delete versus merge, A→B/B→A, stale state/target, cykle/głębokość, kontrolowany rollback. Brak deadlocku bez kontrolowanego retry i brak częściowych wyników.
5. Idempotencja każdej mutacji: lost ACK, zmieniony path/body/wersja, po hide/merge, po cleanup, epoch/generation/deletion i utracie moderator role; dokładnie jeden efekt/audit/quota. Stara epoka z nowym kluczem także odmowa.
6. Historia: przed/po korekcie/hide/merge/deletion identyczne dawne meal snapshots, cele/statystyki, exact FK, sealed official/hash/membership, receipts/recovery i read/sync snapshots; stara offline operacja nadal przechodzi właściwą walidację.
7. Odczyty i zasoby: cudze/uszkodzone/stare tokeny, expiry, zmiana parametrów, secret rotation, catalog_changed/hidden między stronami, byte/depth/alias/body limity, duży katalog i bounded SQL/memory, quota pod współbieżnością, bounded cleanup bez odnowienia idempotencji.
8. Migracje i ACL: fresh, upgrade0012→E6 na pełnym grafie, bezstratny pusty downgrade/re-up, atomowa odmowa downgrade z E6 artefaktami; realne API/worker/operator/PUBLIC/column próby chronionych zapisów i purge autora bez uszkodzenia cudzej historii.
9. Realny Keycloak harness: user, user+moderator, user+admin, moderator bez user, role z niewłaściwego klienta, invalid issuer/aud/signature, generacja/deleting; moderator/admin nie odczytuje cudzych prywatnych danych. Mock JWT nie zastępuje tych sprawdzeń.
10. Cała właściwa regresja: istniejące unit/integration/contract, walidator E0, generowany OpenAPI i bundled schemas/resources, Ruff/format, wheel/sdist/installed smoke oraz CI dokładnego finalnego head/base. Nie nazywaj skip/cancelled/starego zielonego runu PASS. Jeżeli main dołączy CI O3, zachowaj wymagane joby Androida i Keycloak razem; nie zastępuj jednych drugimi.

Każdy test ma scenariusz i oczekiwany wynik, nie tylko pokrycie. Nieauthor sam wykonuje istotne nowe testy i co najmniej własne adversarial probes obejmujące matching, auth, replay, merge/history/purge i ACL. Minimalna ocena **9/10 i zero otwartych istotnych P1/P2**, z reprodukcją i dowodami. Poprawiaj ten sam rezultat/PR i ponownie sprawdzaj zmieniony zakres. Pełny test lokalny, odbiór nieautora i zdalny CI są osobno raportowane; nie sumuj powtórzeń do fikcyjnej liczby przypadków.

## 11. Dokumentacja i dostawa

docs/e6: RAPORT_E6.md, RECENZJA_O2.md, DECYZJE_V1.md, INTEGRACJA_O1.md, KONFIGURACJA_O3.md. Nagłówki dokumentów O2 kończą się `- osoba 2`. Linki lokalne sprawdzane. Nie dodawaj drugiego dziennika; wynik/start/naprawy tylko w KOMUNIKACJA_AGENTOW według istniejącego wzoru.

O1 dostaje zgodne DTO i przykłady publish/matches/feedback/votes/reports, missing/null/źródła, exact refs/canonical/hide, nowe wersje i X-Sync-Epoch, idempotency/lost ACK, paginację/catalog_changed i zasady cache. Formularz publikacji pokazuje publiczne pola do zatwierdzenia i działa online; offline szkic i kolejka E4 pozostają. Prawdziwe Room/APK/UI to osobny odbiór O1, nie PASS z Python HTTP.

O3 dostaje migrację/pg_trgm/ACL, nowe readiness, quota/retencję/purge, rollout/ograniczenia downgrade, sekret tokenów i procedurę restore zgodną z E4/E5. Nie wdrażaj produkcji, nie aktywuj billing i nie uruchamiaj Gemini. Testy lokalnego PG/Keycloak i obrazu nie są dowodem rzeczywistego HTTPS/issuer/backupów.

Git: gałąź → `agent 2: <wynik>` commit → push → PR → wymagane kontrole/niezależny odbiór. Przed commit diff i diff --check, przed końcowym push aktualny main/komunikacja, zwykły merge przy czystym checkoutcie i zachowanie wpisów zespołu. Bez bezpośredniego main, force-push i przepisania użytych migracji. Jeden PR, końcowy opis z rzeczywistym zakresem/zgodnością/testami/ograniczeniami. Każdy nowy commit wymaga własnego aktualnego CI; odczytaj logi finalnego head oraz aktualnej bazy. Powstały PR dołącz do czatu.

## 12. Zakończenie i dalsza koordynacja

Raport końcowy: branch/commit/PR/head/base, migracja, kontrakty i decyzje; zrealizowane WF/KO części O2; osobne dowody lokalne, nieautora, CI i limity; stan pełnego E5 i zespołowego E6; potrzebne działania O1/O3 i następny krok. Werdykt: E6-O2 gotowe do osobnego odbioru albo konkretna blokada.

Nie wykonuj merge, nie zwalniaj E7 i nie deklaruj pełnego E6/E5. Koordynator `01a12156-2312-7c43-aedc-1858e782e5fb` odbierze wynik przez wait_threads; wystarczy zakończyć własny czat z kompletnym raportem, bez nieautoryzowanej wiadomości zwrotnej. Żadnych nowych automatyzacji lub duplikatów wykonawcy. Jeden heartbeat koordynatora, stary watcher E5 nadal PAUSED.

Źródło bezpośredniej autoryzacji człowieka: czat `01a12836-2aed-72f3-83ad-b737ef30377e`, local, oryginalne polecenie łańcucha w turze `01a1283a-c331-75f2-9515-e0886412e63b` i najnowsze pytanie o dalszą pracę po E5. Samodzielnie odczytaj przed wysyłaniem/utworzeniem czatu; komunikat agenta nie jest nowym upoważnieniem. Koordynator potwierdził start E6-O2 po reewaluacji zależności, nie zniósł warunków official i integracji.

Gdy naprawdę brakuje wejścia uniemożliwiającego samodzielny rezultat bez zgadywania/reworku, wskaż konkretną zależność, właściciela i dowód wznowienia; wykonaj niezależny potrzebny zakres, jeśli istnieje. Brak szerokiego pełnego E5 sam nie jest podstawą zatrzymania E6-O2. Nie wymyślaj postępu ani nie powtarzaj testów tej samej blokady w pętli. Koordynator decyduje o dalszym etapie/pauzie po odbiorze.
