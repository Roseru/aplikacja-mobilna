# Recenzja Nemesis lifecycle E8.3-C - osoba 2

12 października 2026 r. Niezależny nieautor. **Końcowy odbiór rzeczywistego E8.3-C: 9,3/10, zero otwartych P1/P2**, dla head `558e920166a2fee88c47567657a5d68aa6e7edc2`. Odbiór dotyczy izolowanego komponentu na rzeczywistej linii **0016→0017_e8_purge_commit→0018_e8_nemesis_lifecycle**. E8.3-I, osiem zdalnych kontroli CI, pełny odbiór upstream PR #35/main, realny Keycloak, O1/O3, APK, produkcja i E8.4 nie są tu zaliczone. Publiczne issuance/create/accept/statistics nadal są zamknięte do E8.4.

## Zamrożone źródło i zależność

Branch autora: `codex/backend-e8-nemesis-lifecycle`; pierwotny start kodu `fe0098c079d199e346b9eb1b2131165d2dd90d5e`. Recenzent użył własnego managed detached worktree i własnych usług, nie edytował wykonywalnych plików autora ani nie wykonywał commit/push. Przeczytał master E8.3, wymagania, AGENTS, koordynację i potrzebne kontrakty motywacji, repozytorium oraz nowy rzeczywisty parent. SHA-256 kanonicznego mastera LF z e93e38e02fed9663217b9036e5831cbc934e1baf pozostaje `32c3925be33333a49781f96c65675350b872948d515c6f0564c67c10fa7416e5`.

Nowa rzeczywista podstawa `b2c6709e95796ab2c10a63493b78635664ea4f9e` została jawnie przyjęta i dołączona zwykłym merge; jest sprawdzonym ancestor końcowego head. Jej 0017 ma dokładny blob `aac0cdc62e47af2f7c5391937b37e29a59bb8a82`. Runtime odebrano na `ee52b3bd2b7c5109325e19debf2339bcccf4934e`; końcowy `558e920166a2fee88c47567657a5d68aa6e7edc2` ma **zerowy diff backend/src, migrations, pyproject i lock** względem runtime freeze, a nowy testowy zakres wykonano odrębnie. 0018 jest addytywna po prawdziwej 0017. Nie użyto stubu parent, prototypowej migracji zamiast nowej linii albo przejęcia starego PASS jako nowego dowodu.

Produktowy router, wspólny main/sync/health/model imports/provision/purge wrapper nie zostały zintegrowane w C. Produkcyjny health nadal oczekuje parent 0017; prywatna factory 0018 nie ma produkcyjnego readiness. To świadoma granica zarezerwowanej fazy I, a nie potwierdzona gotowość wdrożenia.

## Własne rzeczywiste dowody nieautora

Recenzent uruchomił własny PostgreSQL 17.11 na porcie 55484, świeże prywatne bazy, własne random credentials, prawdziwe SCRAM API/worker/deletion LOGIN, własne procesy TCP 18184/18185 i osobny frozen Python 3.13.9. Świeża linia faktycznie wykonała migracje 0016, 0017 i 0018. Kontrolowany czas oraz fake release pary ustawiał wyłącznie migrator prywatnego fixture. Nie są to produkcyjne fallbacki lub projekcje E8.4.

| Wykonany zakres | Wynik i dokładny dowód |
| --- | --- |
| Własne lifecycle/PG/transakcje/source/time/privacy oraz ścisłe numeric probes ponowione na rzeczywistej 0018 | **36 PASS, 60,28 s**, `real-existing.xml`; jeden niezmieniony przypadek dużej historii nie był powtarzany. |
| Dziewięć nowych niezależnych przypadków dla rzeczywistego parenta i nowej linii | **9 PASS, 13,27 s**, `real-new3.xml`. |
| Dwie własne rzeczywiste TCP repliki na nowej podstawie | **2 PASS, 21,20 s**, `real-tcp.xml`. |
| Nowe dostarczone regresje parenta na końcowym testowym head, wykonane własnymi credentials/operator LOGIN | **6 PASS, 6,16 s**, `real-delivered.xml`. |
| Dwa poisoned memberships przed prawdziwą 0018 | PASS: 23514, head pozostaje 0017 purge, brak Nemesis DDL. |
| Semantic ACL, rzeczywiste SCRAM i installed Python -I na aktualnej bazie | PASS: zero PUBLIC EXECUTE, zamknięty search_path, zero bezpośrednich Nemesis column privileges API/worker; własne read/revoke dostępne przy closed gate. |
| Własna historia 1007 rekordów z pierwszego freeze, kod odczytu identyczny w finalnym źródle | **1 PASS, 180,38 s**; 11 stron, najwolniejsza strona 0,202 s, pula cursorów ≤8, obcy cursor denied. |

Nie sumujemy nakładających się scope, powtórek ani wyników autora. Poprzednie 138 komponentowych unit z a2 oraz pięć poprawionych P2 mają własne historyczne dowody; pełny finalny unit/regresje autora i CI mają osobne pochodzenie. Pamięć historii/cursorów została sprawdzona bez globalnego obcięcia. Lokalne czasy nie są docelowym SLA.

Nowy zakres nieautora obejmuje rzeczywiste empty i populated 0016→0017→0018, atomową odmowę nonempty downgrade 0018 przed DDL wraz z zachowaniem receipts, pusty downgrade 0018→0017→0016 i reupgrade 0018. 0017 celowo zachowuje SECURITY DEFINER repair przy downgrade. Własny oracle porównał niezmieniony prosrc hash `a07b30c41bda409d6aaa734486170d0141939eae729007269d3b46f2da5e473d`, właściciela, search_path, ACL oraz wcześniejsze źródłowe profile/DiaryDay/Meal/MealItem. Retained repair pozostaje zachowana, dane nie znikają.

Prawdziwy minimalny SCRAM deletion LOGIN nie ma SELECT/DML źródeł i nie może wywołać `diary_aggregate_count()` bezpośrednio. W prywatnym, jawnie zamontowanym seam wykonał jednak faktyczny COMMIT purge grafu Meal/MealItem i Nemesis poprzez realny upstream chain E8→E7→E6→E4. Rollback po purge i sprawdzeniu deferred constraints zachował wcześniejszy stan; COMMIT oraz retry zakończyły się poprawnie, peer data i bezpieczny cancelled marker pozostały. Osobna dostarczona próba potwierdziła rzeczywisty legacy purge bez sztucznego SET CONSTRAINTS shortcut. Ten testowy seam nie modyfikuje ani nie zastępuje produkcyjnego wrappera.

Nowe niezależne źródłowe probes potwierdziły rollback Meal/DiaryDay/motivation/change/counter po błędzie w apply **po** e8_refresh, wewnątrz właściwego savepointu. Nowa pierwsza ranking affirmation po restore przeżyła reconcile i worker/backfill. E5 puste dni 7/30/90 mają zamknięte przeszłe daty, null averages/counts bez fikcyjnego zera i nie tworzą źródeł. Dostarczone parent probes wykonane przez nieautora dodatkowo sprawdziły świeżą epokę/restore cancel, cutoff przy deleting oraz rzeczywisty legacy MealItem purge na własnym minimalnym LOGIN.

Ponowione 36 prób dowiodło dwóch osobnych procesów przeciwnych A→B/B→A i wspólnego receiver, dwóch slots, braku caller prelock przez NOWAIT i lifecycle czasu pobranego po lockach. Obejmują code consumption rollback, projection-init failure, durable limits i odmowy/replay, exact terms, immutable participants/scope, deletion/restore/generation/cursor isolation, źródłowy guard, retention oraz niezależne UTC/calendar oracle dla Warszawy, Hawany, półgodzinnego Lord Howe i granic roku 0000/10000. Minimalny receipt nie uruchamia mutacji po retencji; cancel/revoke nie przywracają sharing.

TCP utrata ACK została wykonana przez wysłanie pełnego POST socketem, oczekiwanie na **DB COMMIT receipt barrier** i zamknięcie socketu bez odczytania odpowiedzi HTTP. Sprawdzono faktyczne zamknięcie listenera przed restartem, a replay wrócił z tym samym ID. Accept/cancel i stary accept replay nie odtworzyły sharing. Dwie rzeczywiste repliki dzielą quota: pięć wydań kodu i szósta odmowa 429 z Retry-After. Odpowiedzi no-store, auth/wrong signature/foreign admin, parser/error redaction, 404/405 oraz captured logs bez JWT/kodów/prywatnego body są sprawdzone. JWKS/JWT były syntetyczne i podpisane; nie jest to dowód realnego Keycloak lub HTTPS.

## Pięć zamkniętych P2 i historia nieudanych prób

Pierwszy bf2 wymagał zmian. Na własnym PG ujawniono i odtworzono: cached invited/active replay po skutecznym expiry/end; brak bounded admission cleanup; eskalację istniejącego worker membership przez SET ROLE; nieprzedstawialny local roundtrip przy poprawnym UTC. Reprodukcje RED miały własne późniejsze GREEN na a2. Dodatkowa kontrola a2 odkryła piąty P2: JSONB przyjmował 7.0/30.0/90.0, konsumował kod i utrwalał DTO-invalid terms, a accept abortował 22P02. Poprzedni PASS został jawnie wycofany; mała poprawka ced dostała osobny własny odbiór. Na rzeczywistej finalnej linii wszystkie te granice ponownie przeszły: malformed floats 422 bez challenge/admission/consumption, direct INSERT CHECK 23514, potem ten sam kod działa dla integer 7/30/90.

Nie ukrywano wcześniejszych błędów prywatnego harnessu: zakończony PG, brak credentials, scalar dla DDL, shadow zmiennej connection, Windows venv launcher PID, brak jawnego testowego FK metadata bootstrapu, `%ROWTYPE` w driver SQL oraz zła nazwa pola E5. Naprawiono prywatne testy/harness i powtórzono odpowiedni zakres, bez zmiany wykonywalnego kodu autora. Ich nieudane przebiegi nie są liczone jako PASS. P3 uszkodzonych znaków UTF-8 w dokumentach został naprawiony i zweryfikowany.

## Końcowy manifest Git LF i zainstalowany pakiet

Kanoniczny manifest **148 plików runtime i 14 migration resources** dla `558e920166a2fee88c47567657a5d68aa6e7edc2`: SHA-256 `505b83c1a2c6e34041e2bd1dbc017d39b50ca4d08122276d2069e9ef81425eab`. Manifest tracked test/support E8.3: `37ddc8db653af13675aaf4fda3d7795af6d869e1606a68bb40be48babc6c1986`. Manifest dziewięciu własnych prywatnych programów nieautora: `57e0a72699a220e37a1bcf4c6620f4ec677a9a47415133be2532ea0f135a17a9`. Pełne per-file blob SHA/Git LF SHA-256 i JUnit/logi pozostały w ignorowanym prywatnym storage; bez publikacji credentials, kluczy, lokalnych ścieżek, buildów lub cache.

| Migration resource | SHA-256 LF |
| --- | --- |
| 0017_e8_purge_commit.py | `2e96203d212d374b6c3687edc622e5e832fc52391e170d3d9da889fcaa8b1333` |
| 0018_e8_nemesis_lifecycle.py | `42f324cd9ad9d325a3664cac1a755e8d23d205ea63d7c1080c346beb77801336` |
| e8_0018/acl.sql | `b7b2d98abe398568eff768a006cb6014807602b17be3560f1b30cfd8f3560f5b` |
| e8_0018/addressing.sql | `270f45df0b03c51736b901736f0f9674e156bd925407d312438ee8e7f9381f1e` |
| e8_0018/lifecycle.sql | `8b4c7e4a816d4b022d8c4ab42d98aa1f95652477190cc3214034c9f06261b27b` |
| e8_0018/maintenance.sql | `52ed6de6fa8551a23d58c7207f9abb5ffaa11b5bccc5a6c3acd7f35ac5743bb4` |
| e8_0018/schema.sql | `f029bca046dbaf5bd86cdf4aea8c3ea319e7fc9f163ba544145b60a044f9a37b` |

Nieautor zbudował aktualny wheel i sdist, zainstalował nieedytowalny wheel oraz porównał wszystkie 148 runtime plików z Git LF. Wszystkie 14 resources 0016/0017/0018 w sdist odpowiadają końcowemu Git. Wheel nie zawiera test factory/bootstrap/server helpers. Wheel SHA-256 `832665cf46d414702d608b4675b560d47028cce55859ed5783d559efe3416bf5`; sdist SHA-256 `b8bc606676861acae939757d7037a9de067b85489a9df04b751d2605c904b37d`. Python `-I` importuje installed package, a realny API LOGIN wykonał read/revoke i odmowę default closed issuance. Nie zalicza to produkcyjnego readiness lub montowania routera.

## Granica końcowego odbioru

**E8.3-C rzeczywiście odebrane**, na aktualnym kodzie, realnym parent i rzeczywistej nowej linii; poprzednie prototypowe oceny nie zastąpiły tego odbioru. Własne TCP listenery i PG 55484 zatrzymano po testach; cudzych usług nie dotykano. Brak zdalnego CI w stacked draft do feature branch pozostaje jawny.

Koordynator i autor mogą opublikować zaakceptowaną linię oraz draft stacked PR z dokładnym head/base/dependency. Pełny upstream PR/main i E8.3-I pozostają odrębnym warunkiem: zwykły merge main, retarget, zwolnione seams, właściwa produkcyjna integracja, nowy nieautor i osiem rzeczywistych CI. O1/O3, realne Keycloak/HTTPS/restore oraz APK nie są zaliczone. Public activation pozostaje closed, a E8.4 dopiero posiada projekcje i finalizer dla KO22/26/27/29; E8.3 nie nalicza wyników.
