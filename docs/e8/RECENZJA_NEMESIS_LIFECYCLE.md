# Recenzja Nemesis lifecycle E8.3-C - osoba 2

12 października 2026 r. Niezależny nieautor komponentu. Aktualny wynik: **9,3/10 dla lokalnego prototypu komponentu na `ced65cc3c9913260619ae5052b6be05fa48680ab`, zero otwartych P1/P2 kodu tego zakresu; końcowy E8.3-C oczekuje na rzeczywistą nową linię migracji**. Wcześniejsze źródło `a2dc066155494bb9ebb453698055123e63cdcb9a` zostało dodatkowo sprawdzone i ujawniło piąty P2 ścisłości liczbowych terms; jego dawny pełny PASS został wycofany, a małą poprawkę na ced odebrano odrębnie przed/po. Ten wynik odbiera izolowany komponent. E8.3-I, osiem zdalnych CI, realny Keycloak, O1/O3, APK, produkcja i pełne E8 pozostają osobnymi odbiorami. Publiczna aktywacja i statystyki są zamknięte do E8.4.

## Źródło i granica odbioru

Gałąź autora: `codex/backend-e8-nemesis-lifecycle`. Początek kodu: `fe0098c079d199e346b9eb1b2131165d2dd90d5e`, zależność od PR #35. Pierwszy freeze `bf2a5a6a03580d1594d957a286ae35f42f5bb43d` wymagał zmian. Poprawkę odczytano na czystym, własnym detached managed worktree i odebrano na `a2dc066155494bb9ebb453698055123e63cdcb9a`. Recenzent nie edytował kodu wykonawczego autora i nie wykonywał commit/push. Migracja jest nadal nieopublikowaną 0017 po 0016; pierwsza publikacja wymaga uzgodnionego finalnego numeru/parent przez koordynatora. Draft stacked PR i późniejszy retarget/main należą do autora oraz koordynatora.

Odczytano master E8.3, wymagania i reguły repozytorium, master koordynacji oraz motywacji, komunikację, decyzje/interfejsy i właściwy kod identity/profiles/diary/sync oraz SQL 0016–0017. Kanoniczny master z `e93e38e02fed9663217b9036e5831cbc934e1baf` ma zweryfikowany SHA-256 LF `32c3925be33333a49781f96c65675350b872948d515c6f0564c67c10fa7416e5`. Znana poprawka upstream `6606cf1` w profiles.service nie jest częścią starego freeze i nie została tu zaliczona jako nowy PASS rankingu.

Nie podłączano wspólnego main, sync, health, model imports, provision lub purge wrapper. SQL i source guard wykonano przez jawne prywatne adapters; fake release pary w prywatnej bazie migratora nie dowodzą E8.4 ani produkcyjnej aktywacji. Cancel/revoke oraz własne metadata działają przy zamkniętej bramce, po aktualnym access/epoch/auth.

## Manifest źródła, testów i instalacji

Manifest kanonicznych blobów Git LF obejmuje dziewięć plików runtime Nemesis, migrację z pięcioma SQL resources oraz dwa testowe helpers. Jego SHA-256 wynosi `2509477d00f922bc7fb82ac9231b9ee9880d140fcc9f11c7bf504cd1cd98c9b2`. Dokładne SHA-256 źródeł migracji:

| Plik | SHA-256 LF |
| --- | --- |
| migrations/versions/0017_e8_nemesis_lifecycle.py | `4c4f07dd7b9f0fec035a81fe55fcd241b56c5ea0c9fa9fbc4c1a053da18350aa` |
| migrations/versions/e8_0017/acl.sql | `b7b2d98abe398568eff768a006cb6014807602b17be3560f1b30cfd8f3560f5b` |
| migrations/versions/e8_0017/addressing.sql | `270f45df0b03c51736b901736f0f9674e156bd925407d312438ee8e7f9381f1e` |
| migrations/versions/e8_0017/lifecycle.sql | `8b4c7e4a816d4b022d8c4ab42d98aa1f95652477190cc3214034c9f06261b27b` |
| migrations/versions/e8_0017/maintenance.sql | `52ed6de6fa8551a23d58c7207f9abb5ffaa11b5bccc5a6c3acd7f35ac5743bb4` |
| migrations/versions/e8_0017/schema.sql | `2a4cfbe16141ea214fc1f3b9ba927d31d55a2b519d2d7f70185f941e463d3e23` |

Manifest 14 własnych tracked plików test/support E8.3 na tym samym SHA: `94157099cb772b8233c31c0b16d448bab8d5d085f2e409bb818d2d48e2a72531`. Manifest ośmiu nowych prywatnych programów recenzenta: `3d96817343e1e8156b1387c7c4323725d7208eda466a11bd27b6b600dd9f9205`. Pełne manifesty oraz JUnit/logi są zachowane w ignorowanym prywatnym katalogu dowodów; nie publikujemy credentials, kluczy, lokalnych ścieżek, buildów lub cache.

| Nowy własny program recenzenta | SHA-256 |
| --- | --- |
| test_independent.py | `1a8fc71df93d6103baa32cc0e287615cd1ef3b0e2d67eb28b2624c1fa7ae99fa` |
| process_review.py | `6b5c6f18e50eea3795dac60a3e469b404dec8a6e090338fa26f84e240c423852` |
| test_tcp_independent.py | `1a5e4f52a89f7a82d5fabd1c023476e1ca39661add2f064dc226847a68e11ed6` |
| tcp_server_review.py | `178999fd972dfd0241aada84da0570128d7df93ffa5cfdcbcfda2302afd3b094` |
| poison_green.py | `03f74e59868320b6cd3b88ab54f0a84e9a4ad524259c386a0e619e1d914bc788` |
| acl_semantics.py | `85c7546b47bf0c8bc312eda1a8e709dd8bf9b92cb1ac6fe9809f32e346266398` |
| manifest_installed.py | `c4aa9326df2ba40ad720ebb07357c438e68fe182449ca8cf121ebf8c874803c4` |
| installed_smoke.py | `162a4f859ba3f88244f006e11e1caab2e2bd04c85e8a17c79f13485be14eb808` |

Recenzent sam wykonał `uv sync --frozen` z Python 3.13.9, budowę wheel/sdist i instalację nieedytowalnego wheel. Wszystkie dziewięć runtime plików zainstalowanego pakietu i wheel odpowiadają LF Git; wszystkie sześć resources migracji w sdist odpowiadają aktualnemu Git. Testowa factory/bootstrap nie znajdują się w wheel. Wheel SHA-256 `1e7fd99defdf853922b336caba78ba1b941bd4f8af83ecc195ddd7de72062a96`, sdist SHA-256 `4591019a6e12d926ace50cf4579e8646585f1f123cdb9df43c93a489f19417cf`. Osobny Python `-I` wykonał rzeczywiste service/read/revoke i domyślną odmowę issuance na aktualnej bazie przez prawdziwy API LOGIN.

## Rzeczywiście wykonane własne próby

Recenzent uruchomił własny PostgreSQL **17.11** na port 55484 z osobnym storage i losowymi prywatnymi credentials. Wykonano świeży bootstrap 0016→0017 oraz osobne świeże bazy dla probes niebezpiecznych memberships. API i lifecycle worker używały rzeczywistych SCRAM LOGIN; SET ROLE nie zastępował dowodu logowania. Dla testów czasu wyłącznie migrator prywatnej bazy zmieniał e8n_clock. Nie przekazywano czasu w API.

| Zakres nieautora | Końcowy dowód |
| --- | --- |
| Nowe niezależne PostgreSQL/ASGI/transakcje/source/privacy/time probes na poprawionym freeze | **32 PASS, 54,35 s**, bez skips; `new-corrected.xml`. |
| Właściwe tracked unit komponentu uruchomione w własnym frozen środowisku | **138 PASS, 2,32 s**; `unit-corrected.xml`. |
| Nowe rzeczywiste dwie repliki TCP HTTP i restart | **2 PASS, 21,31 s**; `new-tcp-corrected2.xml`. |
| Nowe outgoing oraz inbound API poisoned membership przed migracją | **2 PASS**: SQLSTATE 23514, niezmienione 0016 i brak Nemesis DDL. |
| Semantic ACL oraz installed Python -I | PASS: prawdziwe SCRAM, zero PUBLIC EXECUTE, zamknięty search_path, zero Nemesis column privileges API/worker, gate/read/revoke. |
| Nowa własna historia 1007 rekordów na pierwszym freeze | **1 PASS, 180,38 s**, 11 stron, najwolniejszy odczyt 0,202 s, pula cursorów ≤8. |

Nie sumujemy powtórek ani autora i nieautora. Długą historię zachowano z pierwszego freeze, ponieważ `e8n_read`, schema, addressing i reguły cursorów są identyczne między bf2 a poprawką; końcowy zakres ponownie sprawdza zmieniony maintenance, ACL i wszystkie reprodukcje P2. Lokalny pomiar 30-dniowej akceptacji wynosił 0,352–0,379 s; nie jest docelowym SLA.

Nowe oczekiwania recenzenta obejmują:

- Dwa osobne procesy wykonujące przeciwne A→B/B→A oraz A→B/C→B: dokładnie jeden accept i jeden konflikt, tylko dwa slots. Próba NOWAIT na wysokim UUID wywołującego dowodzi braku wcześniejszego caller lock, a opóźniony accept używa czasu po zwolnieniu blokady i odmawia na granicy expiry.
- Dwóch tworzących jeden kod, atomowe consumption/rollback z deferred constraints, trwały receipt lost ACK, failure adaptera po accept bez slots/receipt oraz stałe terms, participant bindings i scope.
- Outgoing cap 3, incoming cap 5, brak refund po cancel, durable odmowa/replay, kod własny/nieznany/wycofany/wygasły z tą samą neutralną odpowiedzią, generation/cursor denial i pełny minimalny receipt po 60 dniach.
- Deletion przed własnym helperem odcina partner read/replay/list; dokładny purge job/context jest wymagany; po purge pozostaje tylko bezpieczny marker bez pseudonimu i bindingu usuniętego właściciela. Restore nowej epoki zamyka gate, stare receipts/zgody nie reaktywują challenge, bounded cancellation zwalnia slots przed nowym invite.
- Niezależne daty UTC dla Warszawy, północy, Hawany i półgodzinnej zmiany Lord Howe; UTC deadline 720 godzin. Dwie skrajne lokalne reprezentacje roku 0000/10000 odmawiają przed aktywacją.
- Source guard cofa zmianę/deletion profilu w tej samej transakcji i nie utrwala motywacji przy odmowie; po end dopuszcza zmianę. Obejmuje przyszłą konfliktową oś oraz konserwatywne discovery wag i całej osi celu. Immutable SourceMutationContext/provenance, kwalifikacja i jedna faza locks pozostają zachowane.
- Własne syntetycznie podpisane JWT przechodzą prawdziwy fixed-trust verifier: obce/admin/moderator, zły issuer/audience/ID token/podpis nie otwierają danych; body/errors i receipts nie ujawniają surowych danych partnera.

TCP używa dwóch własnych procesów uvicorn na portach 18184/18185. Klient wysłał pełny POST przez socket, poczekał na commit receipt w PostgreSQL i zamknął socket **bez odczytania odpowiedzi HTTP**. Po faktycznym zatrzymaniu listenera i restarcie replay zwrócił ten sam ID. Accept/cancel i stary accept replay nie odtworzyły sharing. Dwie HTTP repliki wspólnie wydały pięć kodów, szósta otrzymała 429 z Retry-After. Sprawdzono no-store także dla 401/404/405/422/503 i brak JWT/kodów/prywatnego body w przechwyconych logach. To syntetyczny JWKS, bez rzeczywistego Keycloak, HTTPS, O1 lub produkcji.

## Cztery zamknięte P2

1. **Nieaktualny skuteczny status przy replay.** Na bf2 GET rozpoznawał expired/finished, ale receipt replay bez nowej rewizji zwracał invited/active. Dwie niezależne próby RED na dokładnych granicach czasu. Na a2 replay buduje aktualne metadata po auth/access i obie próby są GREEN.
2. **Brak bounded cleanup admissions.** Na bf2 stare próby pozostawały bezterminowo; maintenance nie usuwał żadnej z 13 starych rows. Na a2 batch 5 usuwa dokładnie pięć najstarszych rekordów spoza maksimum 24 h, kolejne batche kończą cleanup, a minimalny receipt nadal zapobiega ponownemu admission/mutacji.
3. **Możliwa eskalacja przez istniejące membership workera.** Na bf2 po nadaniu worker base membership migratora migracja przechodziła, a realny SCRAM worker mógł SET ROLE i zmienić control/release row. Na a2 dwa osobne poisoned upgrades odmawiają 23514 atomowo przed DDL; czyste role nadal wykonują tylko minimalny zakres.
4. **SQL akceptował nieprzedstawialny local roundtrip.** Na bf2 Kiritimati dawało deadline w lokalnym roku 10000, a Honolulu accept w lokalnym roku 0000, mimo odmowy Python rules. Dwie nowe realPG próby RED. Na a2 oba przypadki są GREEN z odmową 409 i bez aktywacji/slots.

Pierwszy freeze nie otrzymał sztucznego PASS. Wcześniejsze przerwane przebiegi miały błędy prywatnego harnessu: zakończony proces PG, brak credentials, scalar dla poleceń bez rows oraz shadow zmiennej uczestnika przez connection. Windows launcher wymagał także sprawdzenia rzeczywistego PID/listenera. Poprawiono wyłącznie prywatne programs/harness i powtórzono właściwy zakres; te porażki nie zostały policzone jako PASS lub ukryte przez zmianę kodu aplikacji.

## Ograniczenia i następny odbiór

Ocena 9,3 dotyczy komponentu po czterech potwierdzonych poprawkach i nowych własnych dowodach. Dokumentacyjna uwaga P3 dotycząca uszkodzonych polskich znaków w decyzjach/interfejsie/raporcie została usunięta przez autora przed publikacją. Recenzent zweryfikował rzeczywisty poprawny tekst UTF-8 tych trzech plików; naprawa nie zmieniła wykonywalnego freeze. Oficjalne OpenAPI/header copies oraz produkcyjna integracja należą do fazy I. Oddzielny brak realnego Keycloak, CI i wrapper/provision/restore integracji jest jawną granicą C, nie zaliczonym runtime.

Recenzent po zakończeniu zatrzymał własne repliki HTTP i własny PostgreSQL; cudzych usług nie dotykał. Dowody i prywatne credentials pozostały poza Git. Kolejny krok koordynatora: końcowe potwierdzenie migracji i component callback; po merge E8.1+2 zlecenie E8.3-I w tej samej rozmowie/PR, zwykły merge main, retarget, właściwa pełna integracja, nowy nieautor i osiem rzeczywistych CI. E8.4 dopiero zapewni projekcje/finalizer i odbiór KO22/26/27/29; E8.3 nie nalicza wyników.

## Uzupełnienie: nowy P2 liczbowych warunków i zmiana rezerwacji

Po poprzednim odbiorze root wskazał dodatkową granicę JSONB numeric. Nieautor wznowił wyłącznie własny PG 55484 i wykonał na świeżej bazie z dokładnego a2 cztery nowe próby: **7.0/30.0/90.0 — trzy RED; zdrowe integer 7 — PASS**, 6,03 s. `e8n_terms_valid` zwraca true dla tych floats, a rzeczywisty API LOGIN przez raw EXECUTE create zapisuje invited z DTO-invalid terms i konsumuje kod. Własny `strict_accept_red.py` potwierdził późniejszy abort accept SQLSTATE 22P02 bez slots. Oczekiwana poprawka: numeric type oraz kanoniczny tekst duration wyłącznie 7/30/90, odmowa 422 przed consumption, następnie poprawny integer create/accept tym samym niewykorzystanym kodem. Błąd jest P2 integralności DB/wire; produkcyjna bramka nadal closed. Autor wykonuje małą poprawkę i permanentne regresje; nieautor wymaga nowego dokładnego freeze i własnego GREEN przed zamknięciem uwagi.

Koordynator przydzielił upstream korekcyjną `0017_e8_purge_commit` po niezmiennej 0016. Nieopublikowany lifecycle otrzymuje teraz `0018_e8_nemesis_lifecycle` z parent `0017_e8_purge_commit`. Dotychczasowe testy 0016→0017 lifecycle są prawdziwymi dowodami lokalnego prototypu, ale nie stanowią PASS rzeczywistej nowej linii 0016→0017 purge→0018 lifecycle. Jej źródło i downgrade/upgrade muszą zostać sprawdzone po otrzymaniu dokładnej rzeczywistej migracji upstream. Recenzent nie tworzy stubu upstream, nie naprawia cudzego purge i nie podłącza wspólnych plików. Pierwszy push pozostaje wstrzymany. E8.3-I oraz E8.4 nadal wymagają oddzielnego zlecenia i odbioru.

## Zamknięcie piątego P2 na dokładnym ced — odbiór prototypu

Nieautor odczytał czysty własny detached checkout `ced65cc3c9913260619ae5052b6be05fa48680ab`. Diff względem a2 obejmuje tylko schema.sql i permanentne testy DB. Odczytał konkretną poprawkę numeric type + kanoniczny tekst duration, wykonał świeży własny prototype upgrade 0016→0017 i **4 nowe niezależne próby PASS, 6,56 s** (`strict-ced2.xml`): trzy nieprawidłowe float durations są odrzucane 422 przed consumption/challenge/admission; bezpośredni INSERT migratora odmawia CHECK SQLSTATE 23514; po odmowie ten sam niewykorzystany kod działa dla integer 7/30/90 i accept. Oddzielna zdrowa integer 7 create/accept również przechodzi. Wcześniejsze trzy RED na a2 i jego 22P02 accept pozostają zachowanym dowodem błędu, nie PASS. Powtórka 6,61 s bez dodatkowego count admission nie jest sumowana.

W tym małym diff bramka, ACL/preflight, maintenance, replay, okresy, source guard oraz wszystkie dziewięć runtime plików są identyczne z odebranym a2. Zachowano zatem wcześniejsze właściwe dowody czterech zamkniętych P2, 32 PostgreSQL probes i dwóch TCP przypadków; nie powtarzano niezmienionego zakresu bez powodu. Źródło lokalnego prototypu po piątej poprawce nie ma otwartych P1/P2 i otrzymuje 9,3/10. Nie jest to jeszcze PASS nowej faktycznej migracji 0016→0017 purge→0018 lifecycle ani E8.3-I.

Manifest ced źródła Git LF: `3de89a019cd87bc5a69caaf7990d9997812e9f5f727dda5e1675b48f7a3a19ee`; manifest tracked testów: `33c662cfce58f52a384f155f6a1238f61b2faa9ff0c517464bc19fb6248ba1a4`; nowe schema.sql SHA-256 LF: `f029bca046dbaf5bd86cdf4aea8c3ea319e7fc9f163ba544145b60a044f9a37b`; prywatny test_numeric_strictness.py SHA-256: `d402eedd4ce9fafe9045e95d7f179e5ef7deb7601bf7454235bb4ebb20e7a035`. Pełny manifest zachowano w prywatnych dowodach. Wcześniejszy wheel/sdist dowód dotyczy a2 i nie udaje nowego sdist ced albo finalnego 0018; dziewięć runtime plików pakietu jest identyczne. Faktyczna nowa linia i pakiet finalnego źródła wymagają własnej weryfikacji po otrzymaniu prawdziwego parent, bez stubu upstream. Recenzent ponownie zatrzymał wyłącznie własny PG 55484 po tej kontroli.
