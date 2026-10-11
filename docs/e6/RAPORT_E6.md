# Raport E6-O2 - osoba 2

**Backend E6-O2 dostarczony do osobnego odbioru w [PR #20](https://github.com/Roseru/aplikacja-mobilna/pull/20).** Gałąź `codex/backend-e6-spolecznosc`; implementacja40337b9, poprawka kontekstu tokenów9b4925d, poprawka dostawy fixture689780c. Start z odebranego main `a5da8307d5fdf8b53eb8f47015abb86f6dcf880a` / master#17; późniejsze main74f26dd i73860fa dołączone zwykłymi merge. Czat `01a12a2f-781c-7141-8d6e-9f415bbc3111`; własny managed checkout, główny E4/pliki nieśledzone/Random Data zachowane. Bez własnego merge PR/E7.

WF-07/08, UC-14/15/20 oraz backend KO-09/13: online publikacja własnej dokładnej rewizji szkicu, prywatny binding i niezmienny szkic; matching z konserwatywną tożsamością i niezależnym Decimal oracle; osobny community DTO/read; feedback również official; głosy/reports; bounded kolejka, korekta nową wersją, weryfikacja/hide/unhide, audit i source→canonical merge. [Decyzje](DECYZJE_V1.md), [O1](INTEGRACJA_O1.md), [O3](KONFIGURACJA_O3.md), [niezależna recenzja](RECENZJA_O2.md), [OpenAPI](../../backend/openapi.json) i [przykłady E6](../../contracts/examples/e6/e6_community_merged.json) stanowią przekazanie.

Zgodność: stare ProductDTO/ProductPage, pp1/official GET/racje/manifest/gzip oraz ścisły ProductDraft/sync-v1 zachowane. Historyczne MealItem/RationComponent/FK, szkice, sync receipts/recovery/read snapshots i wartości statystyk nie są przepinane. Moderator/admin nie staje się autorem official; głosy nie nadają official/verified. Własność i role ustala serwer. Source-kind AI jest oznaczeniem pochodzenia, bez wywołania modelu.

Migracja0013 po0012:10 relacyjnych tabel, pg_trgm i indexed selectors/keyset, wąskie SECURITY DEFINER/ACL także kolumnowe, immutable exact metadata/audit, trwałe receipts/admission, bounded60-dniowa minimalizacja odpowiedzi i bezpieczny purge.0001–0012 bez zmian. Shared catalog row serializuje fuzzy publikację, official activation, feedback/moderację/merge i wersję tokenów. Downgrade z trwałym E6 odmawia atomowo przed DDL, także dla osieroconego E6 source w starej tabeli. Pusty down/re-up zachowuje pełny reprezentatywny graf E4/E5.

## Dowody autora

- **817 pełnych unit PASS**, bez skipów; po końcowym decoderze wspólny przebieg 817 unit+43 właściwe PG read/queue/token+2 helper Androida =862 PASS.43 PG obejmują4 nowe HTTP przypadki signed cp1/mq1 epoch/generation.
- **757 pełnych PostgreSQL17/SCRAM PASS**, bez skipów,693,52s, przed późniejszą poprawką decoderów; jej cała właściwa regresja jest powyżej. Nie udajemy jednego lokalnego761 przebiegu finalnego decoderu. Zdalny dokładny head wykonał pełne761.
- **22 real Keycloak PASS** (9 wcześniejszych+13E6); po dołączeniu nowego CA O3 powtórzono22 PASS na własnym świeżym providerze i bazie, proces zatrzymany finally.
- Po merge main73860fa: **817 unit+10 privateTLS/helper+2Androidhelper =829 PASS**,6 subtests osobno; default TLS/JWT i prywatny CA zachowane. Nie dodajemy powtórek do pełnej liczności.
- Ruff/check+format PASS dla189 plików aktualnego zakresu CI; OpenAPI/community schema generowane, bundled resources identyczne; E0 **84 valid/28 invalid/18 scenarios**,16 Decimal,5 kompletności,72 normalizacje,316 linków przed wpisem wyniku. Wheel/sdist i installed Python-I poza checkoutem, walidacja oraz realny SQLite import demo PASS. Lokalnie Dockera nie uruchamiano; oba buildy/smoke i rzeczywisty eksport/import obrazu potwierdza CI.

Nowe autor-scope scenariusze, zawarte w pełnych przebiegach lub jawnie powtórzone:98 matching/schema unit,26 token/hash unit,28 communityPG,48 DB/ACL/purgePG,12 matchingSQLPG,11 feedback/moderacjaPG,4 official/historyPG,7 vote/opposing-merge barriersPG,4 token-contextHTTP/PG. Fraction oracle w jednym teście obejmuje3136 kombinacji, wspólne rho1.2/240→200, dokładnie10% oraz ponad próg. Indexed SQL sprawdza wysoką zgodność poza pierwszymi20 kandydatami; paginacja pobiera najwyżej16 metadata rows na partię i dobiera odpowiedź po bajtach.

Rzeczywiste bariery obejmują fuzzy równoczesne publikacje, retry tego samego klucza/zmianę treści, edit/delete/deleting konta versus publish, official activation versus community w obu porządkach, vote/change/withdraw versus merge i A→B/B→A. Jeden efekt/receipt/audit/quota, kontrolowany savepoint rollback, brak niekontrolowanego deadlocku/częściowego wyniku. Historyczny posiłek i późniejszy offline exact zapis przechodzą po merge/hide bez zmiany dawnych wartości. Purge autora usuwa prywatne identyfikatory/raporty i zachowuje cudzą historię/sealed shared wersje.

## Nieautor i naprawy

Niezależny nieautor: **9,3/10, zero otwartych istotnych P1/P2**, własny checkout/PG/role/provider;817 unit,770 pełnych PG(757dostawy+13prywatnych), właściwy końcowy scope tokenów/read/queue z19 własnymi adversarial,22 real Keycloak,17 przykładów runtime/schema PASS. [Recenzja](RECENZJA_O2.md) rozróżnia momenty snapshotów i nie sumuje powtórek.

Pierwszy pełny lokalnyPG:666 PASS/80 FAIL.72 dawnych raw API/worker writes zostały prawidłowo odcięte przez noweACL; każdy NUMERIC przypadek pozostaje pod migratorem, poprzedzony trzema realnymi42501 odmowami. Pozostałe8 dotyczyły starych ACL oczekiwań, seedowania przedE6 bez nieistniejącej blokady oraz dodatkowych retencji keys.160 właściwych historycznych/ACL/retencji+81finite PASS, potem pełne757 PASS; bez usuwania lub skipowania przypadków.

Naprawiono przedwczesny autoflush state correction, nieprzenoszenie brand/composition do indexed search_text po korekcie (nieautorP2), spójne409 kontekstu własnego tokena przed expiry/catalog i przeniesioną ścieżkę fixture. Pierwszy zdalny9b miał816unitPASS/1 FAIL FileNotFoundError; poprawka689 przechodzi817. Próba bez prywatnego basetemp miała699 PASS/118setupErrors z niedostępnego globalnegoWindowsTemp; own basetemp862 PASS. Nie zmieniano praw globalnego Temp. Początkowe założenia trzech nowych testówKeycloak poprawiono do rzeczywistego paged weight i PKCE złego audience; final22 PASS.

## CI i integracja z main

Odczytane rzeczywiste logi [CI38131194698](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38131194698): head `689780c546100034659730217733b033447b55ba`, base `73860fabe8acfe25682a3022fba44f5aa40575de`, candidate `8c750b418729aebe6dee4aca929aad49dafba58c`. **817 unit +761 PG +22 real Keycloak =1600 PASS**, bez skipów. Osiem jobów success: contracts,quality,postgres,keycloak-pkce,android-build,android-device,local-integration,ci-required. Buildy/smoke/wheel oraz eksport/import obrazu PASS; osobno10 helper/privateTLS quality. Android pozostaje bazowym profilem O3, nie E6 formularzem ani KO-31 O1.

Aktualne main73860fa ma własne [CI38131045837](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38131045837), osiem success; logi693 unit+647 PG+9Keycloak=1349 PASS oraz10 privateTLS/helper. GitHub aktualizował candidate do nowszej bazy przed lokalnym fetch; rzeczywisty SHA potwierdzono w logach, następnie main dołączono zwykłym merge. O3 dodaje opcjonalny OIDC_CA_BUNDLE i closed TLS context, bez osłabienia verify/trust_env/JWT; autor i nieautor sprawdzili zmieniony zakres.

Ostatni commit tego raportu/recenzji i wyniku komunikacji wymaga własnego końcowego CI head/base. Odczyt finalnych logów będzie wskazany w opisie PR i odpowiedzi użytkownikowi; wcześniejszy zielony przebieg nie potwierdza dowolnego późniejszego commita. Nie scalałem PR#20.

## Otwarte bramki

Pełne E5-O2-C: właściwe etykiety/powiązania WZ/makra i official export/import/KO-01–02/30 pozostają. Nowy zbiór ARPOL z#18 zachowuje niepewne warianty i braki; nie jest automatycznie official. APK/Room/WorkManager/KO-31 O1 oraz publiczne HTTPS/issuer/restore/RPO/RTO O3 nadal wymagają odrębnych dowodów. Nowe lokalne HTTPS O3/CI nie zamyka produkcyjnego odbioru. PASS E6-O2 nie oznacza pełnego E5, zespołowego E6 lub wydania. Bez kontaktu z dostawcą, Gemini/billing/produkcji/E7; koordynator osobno odbiera i decyduje o merge.

Końcowy wheel po dołączeniu CA i poprawce tokenów:96 identycznych plików kodu/zasobów względem źródła, wszystkie produkcyjne wersje zgodne z uv.lock; installed Python-I DTO/matching/409 decoder/routes i demo import/retry PASS. SHA-256 wheel: f391dbb350def6e694d9b930f8ebc9e855a9ecb1d8d1625ebfcef51dd79876ad. Buildy/cache/sekrety/logi pozostają poza Git.
