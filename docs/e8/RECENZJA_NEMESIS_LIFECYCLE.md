# Recenzja Nemesis lifecycle E8.3-I — osoba 2

12 października 2026 r. **Niezależny odbiór lokalnego zakresu E8.3-I: 9,3/10, zero otwartych zidentyfikowanych P1/P2 w sprawdzonym kodzie i poprawionej granicy producera CI.** Dokładny freeze testów to `26bc03609eb09f8388a01e2823453369154619ed`; wykonywalny runtime i migracja 0020 pozostają identyczne z `721f9a842e6aedeb2916bfa98d652045d6652423`. Branch: `codex/backend-e8-nemesis-lifecycle`, [PR #37](https://github.com/Roseru/aplikacja-mobilna/pull/37), baza main. Jest to odbiór lokalnego źródła i dowodów, przed publikacją finalnego head, ośmioma rzeczywistymi kontrolami CI oraz odbiorem integracyjnym koordynatora. Autor nie scala PR.

Faza I podłącza produkcyjny router, source guard, identity deletion i readiness 0020. Nowa addytywna migracja 0020 domyka minimalne uprawnienia operatora, kolejność blokad i owner-only cleanup po odtworzeniu bazy. Opublikowane migracje 0001–0019 pozostają niezmienione. Publiczna capability pozostaje closed; wyniki, projekcje, finalizer i aktywacja wymagają odebranego E8.4, najwcześniej na 0021. Historia odbioru C19 i wycofanego PASS 1433 jest zachowana niżej i nie zastępuje dowodów I.

## Niezależność i proweniencja aktualnego odbioru

Wcześniejszy nieautor I wykonał rzeczywiste próby na własnych PG 17.11, SCRAM LOGIN i procesach TCP w osobnym checkout. Obecny nieautor odtworzył proweniencję zachowanych XML, rozłączność przypadków i zgodność Git LF; nie przedstawia tych historycznych wykonań jako nowego pełnego przebiegu. Samodzielnie wykonał nowe próby poprawionego producera i statycznie przejrzał pasywny observer pełnej regresji. Recenzent nie zmieniał runtime, migracji lub testów autora, nie wykonywał commit/push/merge. Jego jedyną zmianą w checkout autora jest ten dokument.

| Dowód i dokładny zakres | Wynik |
| --- | --- |
| Własne programowe próby I wcześniejszego nieautora: 12 produkcyjnych SQL/HTTP/CLI, 5 migracyjnych, 1 rzeczywisty TCP | **18 rozłącznych PASS**. XML: `i-coherent2.xml`, `i-fullgraph.xml`, `i-migration.xml`, `i-nonempty.xml`, `i-tcp.xml`. |
| Niezależna regresja upstream E4/E5 na własnym PG | **77 PASS**: 76 w pierwszym XML oraz ten sam jeden przypadek po poprawieniu prywatnego basetemp. Pierwotny setup error pozostaje w zachowanym XML; nie liczono powtórki jako nowego testu. |
| Dostarczone próby produkcyjnego source i deletion na dokładnym 7386 | **30 PASS, 95,042 s**, własne PG i rzeczywisty plik operatora. Runtime jest identyczny z aktualnym 26bc; późniejszego test-only delta nie zaliczono samym tym wynikiem. |
| Nowe własne próby granicy producera na 26bc | **3 PASS, 2,84 s**: reprodukcja szkodliwego przekierowania starego 7386, niezmienne ACL/dane audit po poprawce oraz odziedziczony hostile PGHOSTADDR. |
| Samodzielnie uruchomione aktualne testy jednostkowe producera | **5 PASS, 0,60 s**. |
| Własny historyczny wheel/sdist oraz nieedytowalna instalacja Python -I | **150 runtime files i 21 zasobów migracji E8 (0016–0020)** zgodne z Git LF; helpers testowe poza wheel. Readiness 0020, router, odczyt, autoryzacja i default closed sprawdzone. |
| Pełna regresja PG wykonana przez autora na 26bc, z pasywnym observerem | **1200 PASS, zero failures/errors/skips, 2026,113 s**. Recenzent zweryfikował XML i manifest; nie uruchamiał jej sam. |

Własne 18 prób I obejmowało durable invalid_payload dla osi źródła, rollback nieznanego 23514 bez receipt, historyczną strefę Weight, Goal poza okresem i obie daty przesuniętego Meal, minimalny worker provisioning z rzeczywistym SCRAM i odmowami raw dostępu, operator begin/purge z błędami providera, rollback/COMMIT/retry, cały graf właściciela oraz zachowane dane partnera. Przetestowano owner-only bounded restore cleanup bez ponownego otwarcia capability, faktyczne blokowanie source/deletion, puste i wypełnione migracje, atomowe odmowy tampering/nonempty downgrade, a także TCP lost ACK po DB commit, zatrzymanie/restart listenera i jeden durable replay. Signed JWT oraz fixed-trust mock JWKS były jawnym adapterem testowym; nie zaliczono nimi rzeczywistego Keycloak lub HTTPS.

## Dwa P2 przygotowania CI i ich ponowny odbiór

Brak pliku operatora w producerze 721 był rzeczywistym P2. Poprawka 7386 użyła istniejącego hardened CLI, ale kolejne P2 ujawniło odziedziczone PGSERVICE/PGSERVICEFILE: CLI nadawał CONNECT innej własnej bazie audit, mimo że wygenerowany URL wskazywał source i umożliwiał logowanie. Role są wspólne dla klastra, dlatego pozytywny LOGIN nie dowodził właściwego targetu.

Na 26bc środowisko potomka nie zawiera odziedziczonych PG*; pięć parametrów połączenia pochodzi wyłącznie z zaufanego source admin_url. Własny nieautor odtworzył na starym helperze faktyczne audit CONNECT false→true, a następnie sprawdził tę samą granicę na nowym helperze: audit CONNECT pozostał false, ACL bazy i tabel oraz sentinel data były identyczne, rzeczywisty LOGIN prowadził do source, a ENV rodzica się nie zmieniło. Oddzielne inherited PGHOSTADDR=127.0.0.2 nie przekierowało nowego producera. Poświadczenia pozostawały w prywatnych plikach/ENV, poza argv i raportem. Własne oracle używały jawnego zaufanego hostaddr, aby nie odziedziczyć badanego przekierowania.

Koordynator dodatkowo [odebrał tę poprawkę na własnych rzeczywistych PG/SCRAM i consumerach](https://github.com/Roseru/aplikacja-mobilna/pull/37#issuecomment-6118547315): 9,5/10; drugi nieautor kontraktu/artifacts: 9,3/10. To osobne zakresy, niesumowane z trzema próbami tej recenzji. Nie pozostał otwarty P1/P2 tych dwóch naprawionych granic. Lokalne unit z symulowanym Docker nie są dowodem rzeczywistego Linux Docker CI.

## Pełna regresja i zachowana niewyjaśniona awaria E7

Wcześniejszy prawidłowo skonfigurowany pełny przebieg autora miał **1199 PASS i 1 FAIL**, zero errors/skips. Badany `test_two_physical_outbound_calls_block_a_third_actual_worker_until_io_ends` nie otrzymał event(done) w oryginalnym timeout 20 s po release dwóch wywołań. Jego XML SHA-256: `f2ea5dec4c09cabe80cb1fdab5e7c99f67359f47c3ca36c486e6a7faf0e2d76d`. Trace bez stderr/timeline/statusu helpera nie ustala przyczyny. Siedem późniejszych wąskich wykonań, 13 uporządkowanych przypadków E7 i nowy pełny GREEN **nie dowodzą naprawy ani przyczyny poprzedniej awarii**. Runtime, limiter, limit dwóch wywołań, timeouty i asercje nie zostały zmienione. Przyczyna pozostaje nieustalona; nie przedstawiamy jej jako zamkniętego błędu biznesowego.

Nowy pełny eksperyment autora zachował wszystkie 1200 przypadków i ich oryginalną kolejność. Prywatny observer obejmował tylko 13 procesowych testów E7, był przywracany po teardown i nie dodawał controlled pauses. Oryginalny release wywoływano jako pierwszy dokładnie raz, bez dodatkowego zapytania przed zwolnieniem HTTP; snapshot bazy był dopuszczony wyłącznie po pierwotnej porażce. SQL log zawierał etykiety funkcji/tabel i faz COMMIT, bez pełnych zapytań lub parametrów. Watch miał jedynie SYNCHRONIZE na rzeczywisty PID helpera albo Linux pidfd, oddzielony od PID launchera. Nie zabijał procesu i zamykał uchwyt dopiero po zakończeniu readera. Recenzent statycznie sprawdził tę wersję przed eksperymentem; observer nie trafia do źródeł produktu.

Zweryfikowany nowy XML ma 1200 PASS i SHA-256 `990db30b557488aa9253b25d04ad95940cc8f0b28d9fde429002c439a13b3876`. Timeline SHA-256 `1bb128239573ecf76f2febd455f42b508e70398c4d9218bd4fd35182c665d2dd` zawiera 13 start/end zakresów, 31 zakończeń rzeczywistych helperów, 22 normalne zakończenia launcherów i 9 celowych zabójstw scenariuszy fencing. Nie odnotowano błędu barrier/reader/watch; stderr był pusty. Badany przypadek trwał 8,391 s. Ten nowy pełny wynik jest PASS dla wykonanego eksperymentu, a wcześniejsze 1199/1 pozostaje osobnym FAIL. Niewyjaśniony historyczny przypadek jest ograniczeniem pewności regresji; kolejne faktyczne CI i odbiór main pozostają obowiązkowe.

## Manifesty, granice i następny krok

Na dokładnym 26bc manifest Git LF 150 runtime plików oraz 21 zasobów migracji E8 (0016–0020) ma SHA-256 `017bd587d19f3f7d9274fa3f236db86e63a644249b176a0f513854d2c762e025` i jest identyczny z historycznym manifestem I. Manifest testów E8.3: `8c41f66ae6935589f4e8924cea36129e604984c2bedc061fa494e08d96f81074`; support osobno: `e2627a15be922013112bd256ed5e15abd4efd9d2c444430babd5e0131aa9655d`; helper CI LF: `43ebd424c3310957d8b1fde086d2343a16c42d10eb8db4f8a7c7ae618390d64a`. Recenzent dodatkowo porównał 355 ścieżek runtime/migrations/infra/contracts/lock/OpenAPI: wszystkie Git blobs identyczne z 721. Per-file hashes, rozłączne case IDs, prywatne JUnit i artefakty instalacji pozostają w ignorowanym storage, bez sekretów w repo.

Observer SHA-256: `f2a8ee4102a35e3a8b81b87bf1a88d62531fef51084ab0b913ee10f0da407841`; obserwowany helper: `24c378abe65778ffb8fd9d67458d02833ce45fadfb223b94a7835ac980645198`; harness: `4b309d3748374ecf4e7fd4b8516576a352516a35b4a993e8d686edbcb18effc3`. Nie zmieniają manifestu produktu. Własne PG/TCP recenzenta są zatrzymane.

Odbiór 9,3 dotyczy aktualnego lokalnego I, poprawionego testowego bootstrapu i jawnie opisanych dowodów. Nie zalicza finalnego merge aktualnego main, ośmiu zdalnych kontroli finalnego head/base, rzeczywistego Docker Linux, rzeczywistego Keycloak/HTTPS, O1/O3, APK, produkcji lub E8.4. Następny krok autora: dokumentacyjny commit, zwykły merge aktualnego main z zachowaniem wszystkich wpisów zespołu, publikacja w tym samym PR37 i faktyczny odbiór ośmiu kontroli. Merge PR i odbiór main należą do koordynatora.

---

## Historyczny odbiór E8.3-C19 — zachowany bez zmiany zakresu

Poniższy zapis opisuje stan C19 z czasu jego odbioru. Zdania o przyszłej fazie I odnoszą się do tego historycznego stanu; aktualny wynik I znajduje się powyżej.

12 października 2026 r. Niezależny nieautor. **Aktualny odbiór E8.3-C po naprawie maintenance: 9,3/10, zero otwartych P1/P2 zmienionego kodu**, dla dokładnego head `29601128cdf18a8fac46b9803c80d9fb54d66741`. Rzeczywista linia to 0016→0017 purge→0018 lifecycle→0019 maintenance. Poprzedni końcowy PASS `1433f871504ea10420c857f40c241c84e1fc964f` jest **wycofany**: koordynator odkrył starvation, a nieautor sam odtworzył RED. Naprawę i nowy zakres odebrano ponownie przed/po; historyczny 9,3 nie był dowodem poprawki.

Ten odbiór kończy izolowany C. E8.3-I nie jest jeszcze zamontowane: wspólne main/sync/health/provision/purge pozostają poza tym zakresem, produkcyjny health nie został uznany za readiness 0019. Integracyjne sprawdzenia, problem portable import/collection przy uruchomieniu CI oraz osiem zdalnych wyników są osobnymi obowiązkami fazy I. Nie zaliczono realnego Keycloak/HTTPS, O1/O3, APK, produkcji lub E8.4. Publiczne issuance/create/accept/statistics pozostają closed do E8.4.

## Źródło i niezmienność historii

Branch autora `codex/backend-e8-nemesis-lifecycle`, PR #37. Pierwotny start kodu fe0098c079d199e346b9eb1b2131165d2dd90d5e; rzeczywisty parent b2c6709e95796ab2c10a63493b78635664ea4f9e i 0017 blob aac0cdc62e47af2f7c5391937b37e29a59bb8a82 zostały przyjęte oraz sprawdzone w poprzednim rzeczywistym odbiorze. Master E8.3 LF z e93 ma SHA-256 32c3925be33333a49781f96c65675350b872948d515c6f0564c67c10fa7416e5.

Nową addytywną 0019 po opublikowanej 0018 przygotował autor. Recenzent nie edytował wykonywalnego kodu autora, nie wykonywał commit/push i użył własnego managed detached worktree. Runtime freeze `91bd6b460f316797076d90a83fe8eed797b177d4` i finalny testowy `29601128cdf18a8fac46b9803c80d9fb54d66741` mają **zerowy diff runtime/migrations/pyproject/lock**. Względem wycofanego 1433 nie zmieniono żadnego runtime pliku, opublikowanych 0017/0018, ich SQL resources, pyproject lub lock. Jedyny nowy wykonywalny zakres to 0019 i jej migration-owned maintenance SQL.

0019 zmienia selekcję kandydatów na dokładnie `(invited AND expires_at<=clock) OR (active AND end_at<=clock)`. Account/counter nie są pobierane po challenge locks; UUID ASC, czas oraz powtórny test po wszystkich locks pozostają zachowane. Cleanup i minimalne receipts nie zmieniły kontraktu. SECURITY DEFINER funkcja zachowuje OID, owner/path/ACL, argument/default 100 i zwracany JSONB. Downgrade 0019→0018 jawnie **zachowuje naprawę**, zamiast przywracać starvation; reupgrade przyjmuje znane oryginalne albo naprawione ciało.

## Nowe dowody nieautora

Nieautor wznowił wyłącznie własny PG 17.11 na 55484, utworzył świeże prywatne bazy na rzeczywistej 0018 i wykonał własne 0018→0019. Runtime API/worker używały prawdziwych SCRAM LOGIN; SET ROLE nie zastępował połączenia. Własne programy oraz evidence pozostały w ignorowanym prywatnym storage. Zegar i syntetyczne dane backlogu były fixture migratora, bez produkcyjnego parametru czasu lub fake score/finalizer.

| Wykonany nowy zakres | Wynik |
| --- | --- |
| Dwie własne reprodukcje na dokładnym 1433 i świeżej 0018 | **2 RED, 20,41 s**; batch 1 oraz default 100 z prefiksem 101 stale active 90. `maint19-red.xml`. |
| Pierwsze siedem nowych niezależnych przypadków na runtime 91bd, rzeczywista 0019 | **7 PASS, 29,79 s**, `maint19-green.xml`. |
| Dwie dodatkowe niezależne odmowy preflight dla hostile ACL/path | **2 PASS, 4,00 s**, `maint19-preflight.xml`. |
| Dodatkowy własny clock-row oracle po rzeczywistej blokadzie PG | **1 PASS, 2,60 s**, `maint19-clock.xml`. |
| Wszystkie 14 nowych dostarczonych testów maintenance na finalnym 296, własnym PG i credentials | **14 PASS, 84,27 s**, `maint19-delivered.xml`, bez skips. |
| Własny aktualny wheel/sdist, installed -I i default-closed service/read/revoke | PASS; 148 runtime files i 16 migration resources odpowiadają Git LF, helpers testowe poza wheel. |

Zakresy własnych dziesięciu programowych przypadków są rozłączne. Nie sumujemy ich z nakładającymi się dostarczonymi testami, wynikami autora albo powtórkami poprzedniego C. Opublikowany 1433 nie jest nazywany zielonym dla naprawy. Zdalne CI nie zostało tu zaliczone; błędu collection nie zastąpiono lokalnym PASS.

### Postęp i prawdziwy restart workera

Na 0018 kandydat `active` z duration 90 miał już przeterminowane invite expires_at, ale przyszły end_at. Niski UUID zużywał batch 1, a 101 takich rekordów blokowało default 100 przed wyższymi UUID expired invite i ended active 7. Worker zwracał transitioned=0. Nieautor odtworzył to sam na rzeczywistym worker LOGIN.

Po naprawie batch 1 wykonał pierwszy wymagany transition; następny rzeczywisty proces `python -m calorie_app.modules.nemesis.maintenance --batch 1` wykonał drugi, a kolejny proces potwierdził brak duplikatu. Default 100 obsłużył oba due rows mimo 101 stale-active prefiksu. Aktywne 90-dniowe rekordy i ich dwa slots pozostały aktywne; zakończony okres stracił slots, a wygasłe zaproszenie otrzymało cancelled/expired. Nie użyto fixed sleeps jako dowodu race.

### Rzeczywista migracja, rowsets i security

Nowe empty i filled 0018→0019 porównały **wszystkie aplikacyjne table rowsets** poza koniecznym Alembic bookkeeping. Nie zmienił się żaden source/status/receipt/capability row podczas samej migracji. Porównano także function OID, migrator owner, search_path, ACL, SECURITY DEFINER, return type, arguments, names/default 100, volatility, language, kind i leakproof flag. Jedyną zmianą jest ciało funkcji: oryginalny SHA-256 `d34581def320c114e3e1e2325eccc5533f4c82d392268bc41afe81a22667ccc0` → naprawiony `8dcd70d6869792f297df482285b683393cd7a9eb6c273c4c8e2d235ed4a56a61`.

Downgrade 19→18 wypisał retained repair warning i zachował całe dane oraz naprawione metadata/body. Reupgrade 19 był bezpieczny, idempotentny i nie zmienił rowsets. Default control pozostał closed. API/worker nie mogli wykonać raw control/challenge DML lub ALTER FUNCTION; API nie mogło wykonać maintenance. Dwie świeże hostile probes — grant EXECUTE dla API albo zmieniony search_path — zostały odrzucone 23514 bez zmiany head 18, danych i istniejącej niezgodnej funkcji. Migracja nie normalizuje po cichu nieznanego, niebezpiecznego obiektu.

### Cleanup oraz test po blokadach

GC z batch 1 pruned dokładnie starą pełną response, admission, cursor i code, zachowując minimalny receipt oraz młode odpowiedniki. Nie zwraca żywego quota, nie usuwa minimalnej ochrony idempotencji i nie otwiera issuance.

Własny worker rzeczywiście czekał na challenge lock. Po zmianie kandydata z expired invited na newly active 90 i COMMIT blockera recheck nie wykonał transition i zachował oba slots. Dodatkowy niezależny oracle użył migrator-only clock row i VOLATILE reader: candidate był due przed blokadą, lecz po faktycznym `pg_blocking_pids` barrier czas przesunięto przed end. Po zwolnieniu lock worker zwrócił zero i nie utracił slots; po ponownym przesunięciu czasu nowy proces wykonał należny finish. Nie zastępowano stałej funkcji w trakcie wywołania, ponieważ jej cached body nie jest wiarygodnym testem zmiany zegara.

Własne testy nie ujawniły nowych P1/P2. Dostarczone 14 regresji, samodzielnie uruchomione na innym niż autora PG, obejmowały również clock/status barriers, bounded cleanup oraz tampering atomowych migracji.

## Manifest finalnego źródła i instalacji

Head `29601128cdf18a8fac46b9803c80d9fb54d66741`. Manifest 148 runtime plików oraz 16 resources linii 0016/17/18/19: SHA-256 `47977cfc99a5c3f0e49476f6ca99b2096c6c3ad6eadb1183273aa19d58b8233b`. Manifest tracked test/support E8.3: `2699e0edf2c2b701b4cd707eb725c8ca02a7bdf6a27d71d1977653523072f399`. Prywatny własny test_maintenance19.py SHA-256: `de054a60d2dd071bc27bca479db27cd136f1382f803fc0fe6b79f093875ac295`. Pełne per-file Git blob/LF hashes i JUnit/logi zachowano poza repo; nie publikujemy credentials, kluczy, lokalnych ścieżek, cache/buildów lub prywatnego dziennika.

| Nowy migration resource | SHA-256 LF |
| --- | --- |
| migrations/versions/0019_e8_nemesis_maintenance.py | `4a4405249faeaeae8327d52c84a77560b2a28b617d9a476e962fad966f01628e` |
| migrations/versions/e8_0019/maintenance.sql | `4ab5d24b6623a9e8967a19a12e4398adacca9bfca07821b0da61a0cab3d0a7e1` |

Nieautor zbudował aktualny wheel/sdist i porównał zainstalowane nieedytowalne 148 plików z Git. Wszystkie 16 migration resources sdist, również prawdziwa 0019, odpowiadają finalnemu Git LF. Test factory/bootstrap/server helpers nie znajdują się w wheel. Wheel SHA-256 `832665cf46d414702d608b4675b560d47028cce55859ed5783d559efe3416bf5`; sdist SHA-256 `572b136159a57a25e415e326d729219167c25d23735d36e29f24847ed5dd81b6`. Installed Python -I wykonał real SCRAM read/revoke i odmowę default-closed issuance na aktualnej 0019.

## Historyczne dowody C i granica integracji

Wcześniejsze rzeczywiste 0016→17→18: własne 36 lifecycle/numeric/PG, 9 nowych actual chain/deletion/source/profiles/E5, dwa realne TCP lost-ACK/restart/replica przypadki, sześć nowych delivered parent regressions, ACL i installed proofs pozostają udokumentowaną historią niezmienionego zakresu. Pięć wcześniejszych P2 miało reprodukcje RED/GREEN; szósty starvation wycofał dawny PASS i dostał nowy niezależny odbiór 19. Nie powtarzano niezmienionego runtime bez potrzeby ani nie przypisywano dawnym dowodom nowego CI.

Nieautor po zakończeniu zatrzymał wyłącznie własny PG 55484 i potwierdził brak własnych TCP listenerów 18184/18185. RECENZJA jest jedynym zmienionym plikiem autora przez recenzenta. Kod 0019 i jego testy pozostały pod kontrolą autora; brak commit/push nieautora.

**Rzeczywiste C po 0019 odebrane**, z naprawionym postępem maintenance i bez otwartych istotnych uwag nowego zakresu. Autor/koordynator mogą opublikować 19 w tym samym PR #37 i wykonać callback. Następny etap to oddzielne E8.3-I: zwykły merge zwolnionego main, retarget, portable imports/collection, rzeczywisty production router/source/deletion/provision/readiness, nowy nieautor i osiem faktycznych CI. Public activation, projekcje i finalizer nadal należą do odebranego E8.4; C19 nie nalicza wyników ani nie zalicza I, produkcji lub zespołowego E8.
