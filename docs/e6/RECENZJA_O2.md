# Niezależna recenzja E6-O2 - osoba 2

## Zakres ponownego odbioru

Koordynator odtworzył na `aed555b` trzy nowe P2: E0 po Windows CRLF, nieunieważniany `mq1` po korekcie canonical oraz brak official kandydatów dla wspólnej normalizacji Unicode. Wymagają osobnego odbioru poprawki w PR #20. Poprzednia ocena 9,3/10 i wszystkie jej rzeczywiście wykonane testy są zachowane poniżej jako wcześniejszy zakres; nie oznaczają odbioru nowych reprodukcji. Nowy nieautor odczytuje i testuje poprawiony commit we własnym czystym Windows checkout/PG, w tym `0014` backfill/ACL/downgrade, niezmienność official oraz direct/transitive queue/replay/rollback. Dokładny końcowy head i CI będą wskazane osobno w PR i odpowiedzi wykonawcy.

## Ponowny odbiór poprawki 83a1a6b

Werdykt nieautora: **9,3/10, zero otwartych istotnych P1/P2** na `83a1a6ba0a8475e02c7c4dd8f6dd4a7c6a2fe40a`. Własny zamrożony checkout, oddzielna baza PostgreSQL17 z rzeczywistymi rolami i czysty Windows `core.autocrlf=true`; bez edycji runtime autora.

Niezależne RED: exporter na clean `aed555b` miał 1329 CRLF, 31917 zamiast 30588 bajtów, normalized_equal=True; --check exit2 i właściwy E0 exit1. Po poprawce exporter/bundle/E0 PASS w rzeczywistym clean CRLF, tracked diff pusty. Na pierwszym lokalnym 784c711 recenzent znalazł i odtworzył dwa FAIL legalnego official100aliases: nowy import i backfill0013→0014 łamały names_limit51. Autor przed pierwszym pushem nowej migracji poprawił0014/ORM do101 nazw, zachowując stare limity official100 i community50. Własne dwa RED przechodzą GREEN na83a1a6b; trzy P2 koordynatora i dodatkowy P2 zgodności zamknięte.

Końcowy własny delivery: **107 PASS = 94 PG +13 unit**, bez skipów. PG to26 Unicode/migration/ACL,4 queue,48 DB,4 official/history i12 SQL matching; unit13 toEOL i wspólna/frozen norma. Osobno **12 własnych PG PASS**: dwa official100aliases new/backfill, sześć Unicode pod API (ß, fullwidth, final sigma, ligatura, whitespace, alias), cztery direct/transitive queue commit/replay lub savepoint denial z historycznymi rowsets. Nie sumujemy powtórek wcześniejszych pełnych817/770 przebiegów; ponowny odbiór obejmuje przyczynowy zmieniony zakres. E0:84valid/28invalid/18scenarios/321linków. 0001–0013, źródła/DTO/exact refs, posiłki, membership/hash/gzip zachowane. Brak nowej własnej pełnej sesji Keycloak/Android/produkcji — potwierdza je odrębne właściwe CI lub zespół.

Źródłowy manifest: **213 blobów**, SHA-256 `c8cc1261020da0f88bdb349173a7e1f6bafd8a4e3104c81aa48e6d9606694c1a`. Obejmuje także exporter/sync scripts i .gitattributes; wyklucza raport oraz recenzję, aby uniknąć samoodniesienia. SHA prywatnego pliku własnych probes: `38d69a962bde17c569b40db3124198a5dc32d6f8aac743ce605f09296753cbcc`; pliku i prywatnych logów nie publikuje się. Końcowy dodatkowy commit report/comm wymaga porównania tych213 blobów, bez nieuzasadnionego powtarzania identycznych testów. Własne runs/fixtures/procesy zakończone; root zatrzymuje tylko swój shared test PG po potwierdzeniu końca odbioru. Dokładne finalne CI/head/base podaje osobno wykonawca w PR i odpowiedzi. Pełne E5 i zespołowe E6, APK/KO-31 i produkcyjne HTTPS/restore pozostają otwarte; bez merge/E7/uruchamiania automatyzacji.

## Historyczny odbiór wcześniejszej dostawy

Niezależny odbiór E6-O2 — recenzent nieautor
Ocena: 9,3/10; zero otwartych istotnych P1/P2.

Odebrany snapshot: 9b4925d6b2fd16b0d981537afb4510677afb7161 plus jednoznaczna poprawka ścieżki w backend/tests/unit/test_e6_schemas.py (git blob 12c5b61fa5cdaebaa3a754e9a890498ddbd60903). Autor musi związać ostatnią poprawkę z końcowym head przed zdalnym CI. Własny managed checkout backend-e6-recenzja, oddzielna e6_reviewer_test, realny PostgreSQL 17/SCRAM z role/ACL init-db. Recenzent nie jest autorem runtime, migracji ani testów dostawy i nie zmieniał checkoutu autora.

Prywatny manifest efektywnego odczytanego/testowanego źródła: 204 śledzone pliki; SHA-256 7774df5d64c6d66f352615b316785b355cb4e2a4e97bfa8f42f58064ca3a0609. Manifest obejmuje kod, migracje, testy dostawy, OpenAPI, zasoby/schematy/wektory/przykłady i O1/O3/decyzje; wyklucza raport i tę recenzję, aby uniknąć samoodniesienia. SHA normalizuje CRLF do LF; zawiera też git blob dla każdego pliku. Własne probes pozostają prywatnie.

Dowody niezależne:
- Pełne unit po korekcie fixture: 817 PASS, bez skipów (36,67 s).
- Pełne integration PG przed późniejszą poprawką walidatora kontekstu tokena: 770 PASS, bez skipów (757 testów dostawy + 13 prywatnych adversarial; 677,88 s). To rzeczywisty pełny przebieg, bez udawania, że obejmował późniejszy decoder.
- Końcowy zmieniony zakres tokenów/read/queue: 84 PASS (26 unit + 28 publikacja/read PG + 11 feedback/moderacja PG + 19 prywatnych PG), następnie 4 nowe testy HTTP/PG autora PASS na dokładnym checkoutcie 9b. Powtórek nie dodajemy do fikcyjnej liczby przypadków.
- Własny realny Keycloak: 22 PASS (9 wcześniejszych + 13 E6), bez skipów, oddzielny efemeryczny provider; własny proces zatrzymany finally. Sprawdzono PKCE/JWT, user/user+moderator/user+admin/role bez user/niewłaściwy klient, złe issuer/audience/signature, generację/deleting i brak odczytu obcej prywatnej wagi.
- 17 przykładów E6 przeszło niezależny runtime DTO + Draft202012 JSON Schema; invalid owner i vote=0 poprawnie odrzucone. Bundled community schema identyczne ze schematem kontraktu.
- Dostosowany stary zakres ACL/historical fixtures/NUMERIC/retention: 89 PASS; jest zawarty w pełnym PG, nie dodatkowe 89 przypadków.

Własne 19 probes:
1. Recipe i brand nadal wyszukiwane po korekcie moderatora.
2. Transitive A→B→C: autorzy całej grupy mają is_mine; źródłowe głosy i target samogłosy wycofane; purge autora zachowuje exact rowsets/wersje/źródła i autorstwo pozostałych osób.
3. Replay merge po hide zwraca tylko pierwotne refs/stany, bez ukrywalnego DTO, nowego efektu/audytu/quota.
4. Restore: stara epoka z nowym kluczem nie tworzy receipt ani publikacji.
5–7. Efektywne chronione column DML i PUBLIC EXECUTE pod API, worker, NOLOGIN operator.
8. HTTP role loss przed replay oraz owner/verification spoof.
9. Niezależny Fraction oracle: 147 kombinacji przy Decimal precision=2, g/ml i skrajnych gęstościach.
10–11. Rzeczywiste race vote change/withdraw vs merge.
12. Przeciwne merge różnych moderatorów: jeden 200, jeden 409, bez cyklu/deadlocku.
13. Kontrolowany savepoint rollback: tylko denial receipt/receipts quota, bez głosu/audytu/vote quota.
14–19. Własny podpisany cp1/mq1 pod rzeczywistą rolą API: epoch/generation/both+expired x community/reports. Epoch409 ma pierwszeństwo nad generation/expiry; aktualna utrata moderator role daje403 przed kontekstem; cudzy/domain token pozostaje422; Cache-Control:no-store.

Znalezione i zamknięte:
- P2 wyszukiwania po correction: search_text zawierało wyłącznie nazwy/aliasy. Początkowa reprodukcja 8 PASS/1 FAIL; autor odtworzył również brand/variant/composition według normalize_text. Własne brand+recipe probes PASS.
- Niespójność kontekstu strony: poprawnie podpisany własny token po restore/generation dawał422 zamiast409 zgodnego z E4/E5/masterem. Naprawiona ścisła shape/owner/params walidacja, następnie epoch→generation→expiry/catalog; 84+4 oraz własne6 HTTP probes PASS.
- Błąd dostawy fixture po przeniesieniu examples/e6: dokładny checkout 9b z czystymi śledzonymi plikami miał816 PASS/1 FAIL na starej ścieżce. Autor poprawił jedną ścieżkę; pełne817 PASS. Nie odtworzono zbędnego duplikatu.

Przejrzany zakres: master/AGENTS/wymagania/architektura/plan/workflow/komunikacja; matching i DTO; community repository/service/idempotency/tokens/transport/router/feedback; moderation state/correction/report queue/merge; 0013 SQL functions, efetktywne ACL, append-only, purge, admission, bounded retention i downgrade; official activation; readiness, no-store/errors; generowany OpenAPI/bundled resources i przykłady; przekazanie O1/O3/decyzje. 0001–0012 pozostają niezmienione. Pełny stary graf i exact historie zachowane rzeczywistymi testami; mały/duży rosół i Decimal mają oracle oraz SQL/race dowody. Historyczne fixture pomijają wyłącznie funkcje E6 nieistniejące w dawnych schematach; durable bytes/guards i NUMERIC pozostają rzeczywistymi kontrolami PG. Zmiana main po bazie a5 nie zmieniła bazowego backendu; dodane narzędzia Android CI zachowane.

Werdykt: backend E6-O2 gotowy do osobnego odbioru po związaniu poprawki fixture z finalnym commitem i rzeczywistym wymaganym CI finalnego head/base. Ocena wynika z przeglądu transakcji/ACL/retencji/kontraktów i własnych dowodów, nie z oceny mastera. Singleton katalogu jest uzgodnionym punktem serializacji; docelowy pomiar wydajności jest osobnym zadaniem O3.

Zdalnego CI/merge nie potwierdza ta recenzja; wykonawca/koordynator raportuje je osobno. Pełne E5-O2-C/official/etykiety, APK/Room/WorkManager oraz HTTPS/issuer/restore/RPO/RTO pozostają otwarte. Brak PASS pełnego E5/zespołowego E6/wydania, brak Gemini/billing/produkcji/E7. Recenzent nie zatrzymał wspólnego klastra PG; własne provider/procesy zakończone, diagnostyka i syntetyczne sekrety prywatne.


Powiązanie dostawy: poprawka fixture została opublikowana jako `689780c546100034659730217733b033447b55ba` w [PR #20](https://github.com/Roseru/aplikacja-mobilna/pull/20). Logi [CI38131194698](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38131194698) potwierdzają exact candidate `8c750b418729aebe6dee4aca929aad49dafba58c`, czyli ten head do main `73860fabe8acfe25682a3022fba44f5aa40575de`: 817 unit, 761 PG i 22 real Keycloak PASS, osiem jobów success. To odrębny od nieautora dowód CI.

Po tym przebiegu wykonawca zwykłym merge dołączył nowy main73860fa jako da70c52. Main dołożył opcjonalny OIDC_CA_BUNDLE i SSLContext dla prywatnego CA, obok nowego obowiązkowego local-integration. Domyślne sprawdzanie TLS, trust_env=False i walidacja JWT pozostają. Nieautor odczytuje te osiem linii konfiguracji/transportu i wykonuje właściwe unit/private-CA, a autor powtórzył 817 unit +10 TLS/helper +2 Android helper =829 PASS oraz22 real Keycloak na aktualnym kodzie. Nie utożsamiamy tego z produkcyjnym HTTPS/restore.

Ostatni commit dokumentacji otrzyma własny wymagany CI. Jego actual head/base/candidate i odczyt logów wskażą końcowa odpowiedź i opis PR; wcześniejsze zielone CI nie potwierdza dowolnego późniejszego commita.
