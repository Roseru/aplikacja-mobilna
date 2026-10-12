# Master prompt E8.4: projekcje i wynik Nemesis - osoba 2

Instrukcja koordynatora Agent 2 z 12 października 2026 r. Podstawa kodu: scalony PR37, main b68d645f6bea4c47a385c6aa1b39cd98bd94c814. Podstawa przeszła niezależny odbiór oraz osiem kontroli PR i osobne osiem kontroli push main (run38236250411). Zlecenie implementacji następuje po publikacji i odbiorze niniejszego mastera przez zwykły docs PR/CI/main. Sam dokument nie stanowi dowodu działania E8.4.

## 1. Zlecenie i warunki startu

Pracujesz jako Agent 2. Dostarcz backend E8.4: rzeczywiste projekcje dzienne Nemesis, ich atomową inicjalizację i korekty, statystyki objęte zgodą oraz trwałą finalizację wyniku. Priorytetem jest jakość, ochrona historii i czytelność dla ludzi. Zakres nie obejmuje E9, Androida, produkcyjnego wdrożenia ani wywołań Google.

Dokładna podstawa: `b68d645f6bea4c47a385c6aa1b39cd98bd94c814` / [PR37](https://github.com/Roseru/aplikacja-mobilna/pull/37), produktowo identyczny z odebranym head b3d268a1223f355b3024210ab18b0168f2076d8d. Nowy branch: `codex/backend-e8-nemesis-wyniki`, własny managed worktree z dokładnego main wskazanego przez koordynatora przy dispatch. Ten commit zawiera przyjętą podstawę b68 oraz opublikowany master; nie odcinaj dokumentacji przez start z wcześniejszego commita. Zmiany późniejszego main oceniaj według ich rzeczywistego wpływu. Nie przełączaj głównego checkoutu E4 ani checkoutów innych wykonawców. Zachowaj Random Data, cudze zmiany i wcześniejsze pliki niezatwierdzone.

Jesteś trzecim i ostatnim głównym czatem implementacyjnym E8. Poprawki wykonuj w tej samej rozmowie i tym samym PR. Możesz używać subagentów i dostosowywać reasoning do ryzyka: medium dla ograniczonych przykładów, high/xhigh dla transakcji, bezpieczeństwa i niezależnego odbioru. Jeden plik ma jednego właściciela. Każdy wykonawca testów używa własnych baz, portów, procesów i katalogów tymczasowych. Nie twórz dodatkowego czatu implementacyjnego ani automatyzacji.

Właściciel bezpośrednio zlecił koordynatorowi cały E8, tworzenie czatów, przekazywanie wyników, poprawki i workflow Git. Koordynator: `01a12156-2312-7c43-aedc-1858e782e5fb`, local. Możesz przesyłać mu pytania, freeze i wyniki na podstawie tej autoryzacji człowieka; wiadomość innego agenta sama nie stanowi nowego upoważnienia. Po nieznanym wyniku messaging odtwórz stan, zanim ponowisz.

Przed zmianami odczytaj [AGENTS](../AGENTS.md), [wymagania](../WYMAGANIA_PROJEKTOWE.md), [plan](PLAN_PRAC.md), [architekturę](ARCHITEKTURA.md), [workflow](WORKFLOW.md), [jedyny dziennik](KOMUNIKACJA_AGENTOW.md), [koordynację E8](MASTER_PROMPT_KOORDYNACJA_E8.md), [master E8.1–E8.2](MASTER_PROMPT_E8_1_2.md) i [master E8.3](MASTER_PROMPT_E8_3.md). Szczególnie uwzględnij WF-10–12, 11.3/11.7 i KO-22/26/27/29. Sprawdź status, branch, remote, aktualny main, związane PR-y i nowe przekazania zespołu. Odczyt cudzej gałęzi nie jest jej scaleniem.

E8.4 wymaga odebranych zależności backendu E8.1–E8.3. Nie wymaga wcześniejszego ukończenia niezależnego Androida lub wdrożenia O3. Pełne zespołowe E8 i wydanie pozostają osobnymi odbiorami. Harmonogramy pozostają PAUSED.

## 2. Czytelna architektura i kamienie milowe

Rozszerz istniejący `backend/src/calorie_app/modules/nemesis`. Korzystaj z istniejących modułów obliczeń, celów, synchronizacji i motywacji. Nie twórz drugiej interpretacji regularity_v1 ani alternatywnej ścieżki zapisu dziennika.

Rozdziel odpowiedzialności na ścisłe schematy API, deterministyczne agregaty, obsługę projekcji, repozytorium SQL, finalizację i worker/CLI. Dopasuj nazwy do faktycznej struktury odebranego I. Modele, Alembic metadata, readiness, OpenAPI oraz zasoby instalowanego pakietu muszą wskazywać tę samą linię migracji. Migracje importują własne niezmienne zasoby SQL, nie bieżący runtime aplikacji.

Pracuj w jednej rozmowie, ale przekazuj koordynatorowi konkretne wyniki po kolejnych krokach:

1. Odczyt podstawy i krótki dokument decyzji: model danych, granice transakcji, kolejność blokad, kontrakt statystyk oraz zgodność.
2. Migracja, prawdziwy initializer obu stron i atomowa aktualizacja projekcji wraz ze źródłem.
3. Odczyty statystyk, finalizer, uprawnienia workera, purge i restore.
4. Testy wyścigów, regresja, instalowany pakiet, niezależny odbiór i publikacja.

Nie przedstawiaj kamienia milowego jako ukończenia całego E8.4. Nie uruchamiaj długiej pełnej regresji ponownie po samym komentarzu lub dokumentacji, jeśli nie pojawił się nowy problem; obowiązkowe zdalne CI nadal obowiązuje.

### Rzeczywista podstawa integracji E8.3-I

[PR37](https://github.com/Roseru/aplikacja-mobilna/pull/37) włącza produkcyjny router, no-store, ORM/OpenAPI/readiness head 0020, zbiorczy source guard, scoped begin/purge i bounded restore. Wydawanie kodów, create/accept oraz statistics pozostają zamknięte w bazie do rzeczywistego odbioru E8.4. Nie zastępuj tej ochrony testowym initializerem lub env flagą.

| Miejsce | Odpowiedzialność przy E8.4 |
|---|---|
| `modules/analytics/motivation/service.py:source_mutated` | Obecnie lock extensions → plain repository.refresh → qualified context → apply. Dodaj jeden jawny wybór prawdziwego DB orchestratora zamiast równoległego drugiego refresh. |
| `modules/nemesis/source_guard.py` | SourceProvenance, SourceLockPlan i jeden NemesisSourceProjection posiadają all-challenge lockset, session/transaction/savepoint. Rozszerz faktyczny adapter, bez drugiego właściciela locks. Uaktualnij historyczne docstrings do końcowego zachowania produkcji. |
| `migrations/versions/e8_0018/` | Lifecycle, capability, boundary CHECK oraz accepted-field/result-status guards wymagają nowych migration-owned definicji; opublikowanych zasobów nie zmieniamy. |
| `migrations/versions/e8_0019/maintenance.sql` | Zachowaj status-specific discovery i retained repair starvation; finalizer ma własną równie uczciwą selekcję. |
| `migrations/versions/e8_0020/source_guard.sql`, `deletion.sql`, `restore.sql` | Zachowaj current-epoch/generation/source guards, rzeczywisty scoped deletion context i minimalne skuteczne ACL oraz natychmiastowe odcięcie starych wyzwań po restore. |
| `modules/identity/deletion.py`, istniejący worker/provision | Rzeczywisty begin/resume/COMMIT i techniczne role pozostają podstawą nowych cleanup/finalizer uprawnień. Nie dodawaj drugiego protokołu operatora. |
| `tests/support/e8_3_ci.py`, `tests/support/e8_3_archive.py` | Użyj odebranego producera fixture i przenośnych klientów PG17. Jawne targety/PG ENV/streaming archive nie mogą wrócić do lokalnej ścieżki lub mockowego restore. |

Stare wire v1 oraz hashe/receipts źródeł pozostają zgodne. Późniejsze rozszerzenia dotyczą osobnych kontraktów E8, a nie dopisywania wyników do sync.

## 3. Atomowe źródło i jeden właściciel blokad

Dokładnie jeden zbiorczy `NemesisSourceProjection` posiada pełny zbiór wymaganych challenge locks, uporządkowanych globalnie UUID ASC. Osobne extensions sortujące części zbioru nie zapewniają poprawnego porządku. Po fazie lock apply nie odkrywa nowych rywalizacji, nie dobiera blokad, nie wykonuje zewnętrznego IO i nie robi commit.

Zachowaj kolejność account → counter → wszystkie właściwe challenges UUID ASC → projekcje. Przy accept zablokuj oba accounts UUID ASC, oba counters UUID ASC oraz pełny zbiór challenges UUID ASC. Nie rozpoczynaj od blokowania konta wywołującego poza tą kolejnością. Finalizer i maintenance po challenge nie pobierają account/counter, również pośrednio przez FK, trigger lub helper.

W istniejącym sync walidacja źródła, jego zapis i source position, motywacja, projekcje Nemesis, znaczniki zmian, recovery mapping i receipt należą do jednej transakcji oraz właściwego savepointu. Błąd projekcji lub initializer cofa całość. Replay nie wywołuje hooka ponownie. Nieznany SQL error, 40001 lub 40P01 nie staje się trwałą odmową domenową; bounded retry używa nowej transakcji i nowej kwalifikacji.

Discovery obejmuje stare i nowe daty Meal/DiaryDay, pełną zmienioną oś GoalVersion oraz wszystkie właściwe rywalizacje właściciela przy korekcie Weight. Po nadpisaniu occurred_at starego pomiaru sam zbiór source local_dates nie odtworzy jego dawnego położenia. Bezpieczne ponowne wyliczenie właściwych okresów ma obejmować również przeniesione i usunięte obserwacje. Limit okresu 90 dni nie jest limitem liczby pomiarów lub wersji celów.

## 4. Kwalifikacja w bazie i trwałe fakty

Po walidacji źródła, constraints i zdobyciu wszystkich wymaganych blokad pobierz jeden autorytatywny czas kwalifikacji z bazy. Nie używaj czasu klienta, HTTP, rozpoczęcia transakcji ani timestampu dostarczonego do publicznego writera.

Wybrany mechanizm to jeden jawny DB orchestrator dla source refresh. Jego dokładną sygnaturę ustal na odebranym I. Przyjmuje provenance i dokładny plan źródła, bez gotowych punktów, faktów lub qualified_at. Ponownie sprawdza właściciela, generation/epoch, rewizję źródła, source position i pełny zbiór rywalizacji. Caller nie wybiera mniejszego discovery przez pominięcie dat lub wyłączenie pełnej osi celu.

Orchestrator wymusza pełny porządek blokad również przy direct EXECUTE. W zwykłym Python flow są to blokady już posiadane; nie dodaje nowych IDs po lock phase. Samo twierdzenie callera albo odczyt pg_locks nie stanowi dowodu uprawnienia. Następnie wywołuje istniejący `e8_refresh` dokładnie raz i w ramach tego samego wywołania SQL zapisuje Nemesis przez wewnętrzny writer z otrzymanym q. Writer nie ma PUBLIC/API/worker EXECUTE i nie przyjmuje faktów od klienta.

Powrót do Pythona przekazuje to samo q do source context. `source_mutated` wybiera jeden jawny refresh callable: plain refresh nie wykonuje się dodatkowo przed ani po orchestratorze. Apply sprawdza session, transaction/savepoint, provenance, dokładny plan i qualified_at równe q zwróconemu przez ten konkretny orchestrator; nie uruchamia drugiego przeliczenia ani dodatkowego SQL zapisu. Wyjątek apply cofa również zapis wykonany przez orchestrator. Zachowaj dotychczasowy plain refresh dla ścieżek bez Nemesis. Nie dodawaj rejestru ticketów, durable witnesses lub osobnego obiegu sync.

Dla każdej właściwej rywalizacji kwalifikacja obowiązuje przy q <= deadline. Kwalifikacja przed lub na terminie oraz commit po terminie wchodzi do wyniku; rollback nie wchodzi. Transakcja, która zdobyła ostatnią blokadę po deadline, aktualizuje własną historię i ranking ogólny, lecz nie projekcję tej rywalizacji. Retry nie odzyskuje czasu niezatwierdzonej próby. Jedno q może kwalifikować różne rywalizacje względem różnych deadline.

DayProjection identyfikuje challenge, immutable participant role, local_date i rule_version. Przechowuje rzeczywiste fakty potrzebne do późniejszego wyniku: candidate points, effective completeness, kwalifikację bonusu, maturity, dane do uzgodnionych agregatów, rewizje i provenance. Sam FK do później zmienialnego Meal/Goal/Weight nie wystarcza. Wewnętrzne surowe kcal, E i kg mają prywatne ACL i nie trafiają do partnera.

Accept inicjalizuje obie strony i wszystkie N dat okresu wewnątrz rzeczywistego DB lifecycle, przed zatwierdzeniem slots, zgód i receipt. Sam callback Python nie chroni direct EXECUTE API role. Seed uwzględnia istniejące poprawne przyszłe źródła, ale nie przyznaje niedojrzałych punktów. Błąd jednej strony cofa obie. Powtórzenie po utracie ACK używa receipt bez kolejnego seed. Brak lub niezgodny seed nie może udawać prawidłowego pustego wyniku.

## 5. Kalendarz, punktacja i agregaty

Okres obejmuje 7, 30 albo 90 kolejnych dat w zaakceptowanej strefie IANA, [start_date, end_date). Deadline to end_at UTC + 720 godzin. DST nie zmienia liczby dat. Utrwal day boundaries/matures_at oraz wersję resolvera przy accept; późniejsza zmiana profilu lub tzdata nie przesuwa zaakceptowanych terminów. Obecny CHECK w `e8_0018/addressing.sql` ponownie wylicza start/end także podczas UPDATE statusu. Nowa migration-owned definicja musi chronić utrwalone zaakceptowane instants i dopuścić legalną finalizację/cancel po zmianie tzdata; nowe accept nadal waliduje rzeczywisty resolver IANA. Nie edytuj opublikowanego zasobu 0018.

Regularity_v1 daje jeden punkt za efektywnie kompletny dzień: użytkownik zadeklarował kompletność, istnieje żywy posiłek, energia wszystkich pozycji jest znana, suma kcal jest dodatnia. Drugi punkt wymaga inclusive ±10% dodatniego historycznego celu. Brak celu nie odbiera pierwszego punktu. Pusty dzień, brak energii lub suma zero nie dają punktów i nie oznaczają zerowego spożycia w średniej.

Candidate dojrzewa na następnej granicy daty w accepted zone. Do tego czasu nie zwiększa należnego wyniku. Dojrzewanie nie wymaga zapisu klienta ani nowej kwalifikacji z późniejszego dziennika. Finalizer używa dojrzałego candidate z własnych trwałych projekcji, niezależnie od opóźnienia general motivation worker.

Nie kopiuj fallbacku aktualnej strefy profilu z `e8_day_facts` do historycznej maturity Nemesis. Po end_at zmiana strefy profilu jest legalna. Korekta przed deadline, usunięcie DiaryDay lub dzień wyłącznie z wagą nadal podlegają accepted zone. Test Warsaw → New York po end_at musi zachować wynik i maturity rywalizacji Warsaw.

Weight change wymaga co najmniej dwóch różnych dojrzałych dat okresu. Wybieraj pomiary przez occurred_at UTC w [start_at, end_at), klasyfikuj do accepted local_date, a reprezentanta daty wybieraj jako ostatni według (occurred_at UTC, UUID). Procent = (last - first) / first × 100. Użyj pierwszej i ostatniej dostępnej daty; nie dodawaj mediany lub algorytmu E9.

Mean deficit jest średnią dziennych procentów 100 × (E - intake) / E z efektywnie kompletnych, dojrzałych dni z dodatnim historycznym oszacowaniem E. Zweryfikuj na finalnym I pole resolved GoalVersion.payload.estimate.maintenance_kcal. Energy goal, bieżący profil i aktualny kalkulator nie zastępują E. Brak E wyklucza datę deficytu, ale nie bazowy punkt kompletności.

Wektor: intake 2000 przy E 2500 daje 20%; intake 3000 przy E 2000 daje -50%; średnia wynosi -15% przy eligible_days=2. Nie licz procentu z ilorazu sum. Zero jest poprawną wartością, brak danych daje null z liczbą obserwacji. Większy deficyt nie zwiększa punktów ani nie rozstrzyga wygranej.

Stosuj Decimal/NUMERIC oraz osobny ścisły typ procentu ze znakiem, addytywny względem dotychczasowych kontraktów. Istniejący `ComputedDecimal` jest nieujemny i ma sześciocyfrowy limit części całkowitej; dodatni validator kalkulatora również nie przyjmie poprawnego zera. Nie rozszerzaj tych starych typów. Nowy typ dla obu procentowych metrics zachowuje kanoniczny zapis i skalę do 12 miejsc, ale dopuszcza wartości ujemne oraz zero, bez arbitralnego sześciocyfrowego limitu. Zapewnij precyzję obliczeń odpowiednią dla poprawnych danych wejściowych. Zaokrąglaj dopiero wynik agregacji, HALF_UP; zero zapisuj jako "0". Schemat i przykłady wire przyjmują stringi "-50", "-15" i "0". Odrzucają float na wire, NaN, Infinity, wykładniki, zbędne zera oraz negative zero. Nie zaokrąglaj dziennych procentów przed średnią i nie ograniczaj deficytu arbitralnie do ±100%.

## 6. Ścisły kontrakt statystyk i prywatność

Zamroź addytywny kontrakt w OpenAPI, schematach i przykładach przed implementacją. Odczyt provisional pochodzi wyłącznie z kwalifikowanych projekcji; final z atomowo utrwalonego wyniku. Punkty obu stron, counts, outcome i read revision tworzą jeden spójny snapshot: równoległa korekta nie może złożyć odpowiedzi z fragmentów dwóch rewizji. Dobierz mechanizm zgodny z istniejącą transakcją i sprawdź rzeczywisty wyścig odczytu z korektą. Punkty decydują o self_wins, opponent_wins lub tie, względem uczestnika wykonującego request, bez UUID partnera.

Opcjonalne metric ma rozłączne stany:

- Hidden: dokładnie `{state: hidden}`, bez value, counts, dat lub bocznego data_available.
- Weight insufficient_data: value null i observed_days 0 lub 1. Available: skończony kanoniczny procent, observed_days >= 2 oraz first_date/last_date.
- Deficit insufficient_data: value null i eligible_days=0. Available: kanoniczny procent oraz eligible_days >= 1.

Liczności oznaczają właściwe dojrzałe daty, nie liczbę surowych pomiarów. Regularity ready podaje points, closed_days, complete_days i days_in_goal. Przed pierwszą dojrzałą datą envelope pending nie udaje obliczenia przez zerowe self/opponent/outcome. Brak lub uszkodzony initializer daje unavailable z HTTP 503. Po dojrzeniu pusty dzień może dać prawidłowe zero punktów, lecz nie 0 kcal ani 0% brakujących danych.

Każdy odczyt ponownie sprawdza JWT, uczestnictwo, oba active generations, installation/control epoch, status i aktualne sharing. Invited, cancelled, deleting oraz stara epoka odmawiają neutralnym404 także przy SQL entrypoint. Własne metadata nie uprawniają do statistics. Sprawdź dostęp przed ujawnieniem capability unavailable. Moderator lub admin bez uczestnictwa nie odczytuje cudzej rywalizacji.

Cancel, deletion i restore odcinają sharing także po finalizacji. Receipt, cursor, cache, ranking opt-in lub nowa rywalizacja nie przywracają starej zgody. No-store obejmuje sukcesy i wszystkie błędy; If-None-Match/304 nie omija rewalidacji. Nie dodawaj aggregate snapshot do lifecycle receipts. Partner nie dostaje surowych kg/intake/E/celów/posiłków, source UUID/revision graph ani takich danych w błędach lub logach.

## 7. Finalizer i worker

Discovery wybiera wyłącznie faktycznie due, accepted wyzwania właściwej epoki; uwzględnia także overdue active, jeżeli maintenance nie zmienił jeszcze statusu na finished. W jednej transakcji finalizer bierze challenge lock, potem sprawdza DB clock > deadline oraz bieżące privacy fences, sharing, seed i wersję reguł. Dokładnie na deadline pozostaje provisional.

Finalizer czeka na wcześniejszą kwalifikowaną mutację posiadającą challenge lock. Po jej commit uwzględnia projekcję, po rollback jej nie ma. Wynik, agregaty obu stron i final status powstają atomowo, raz. Dwa procesy, crash przed COMMIT i restart są bezpieczne; retry odczytuje ten sam istniejący wynik.

Finalizer używa tylko własnych trwałych projekcji, immutable terms i minimalnych privacy fences. Nie odczytuje bieżących Meal, DiaryDay, Weight, Goal, Profile ani general MotivationDay do obliczeń. Nie wywołuje e8_refresh ani późnego podsumowania analityki. Udowodnij to fizycznymi ACCESS EXCLUSIVE blokadami tabel źródłowych podczas finalizacji; SQLAlchemy event nie widzi wewnętrznych zapytań PL/pgSQL.

Po challenge lock nie ma blokady account/counter ani zapisu owner sync H. Wynik ma własną rewizję odczytu Nemesis. FinalResult nie powinien mieć FK do user_accounts: INSERT pobierałby ukryty RI KEY SHARE po challenge i tworzył cykl z deletion account FOR UPDATE → challenge. Wybierz klucz challenge_id + immutable participant role; audytuj również helpery, triggers i inne ukryte blokady.

Nowa migration-owned definicja świadomie dopuszcza provisional → final wyłącznie z pełnym trwałym wynikiem; zachowuje terms, bindings, accepted_at i terminy. Final → provisional odmawia. Cancel po final jest nadal legalny i odcina odczyt, a autoryzowany purge usuwa niedostępne dane. Nie omijaj istniejącego CHECK provisional ani accepted-field immutability przez samo DTO.

Worker ma bounded batch, uczciwe discovery i bezpieczny retry. Stary lub niegotowy niski UUID nie może głodzić dalszych due rekordów. Zwykły restart w tej samej epoche nadrabia maturity/finalization bez przedłużania terminów. O3 dostaje CLI, minimalny LOGIN, minutowy schedule, backlog/health i komendy, lecz wykonawca nie zalicza za O3 wdrożenia.

## 8. Gate, migracje, role, usuwanie i restore

Nowa migracja ma numer co najmniej 0021 po rzeczywiście odebranej0020. Sprawdź linię przed kodem. Opublikowane 0001–0020 pozostają niezmienne. Własne nowe SQL resources i jawny downgrade guard zachowują dane; fresh i populated upgrade muszą działać.

Publiczny Nemesis pozostaje default closed po samym deploy. Capability wiąże bieżącą epokę oraz rzeczywiste zgodne revisions schema, initializer, projector i finalizer. Przygotuj kontrolowaną procedurę aktywacji przez zaufanego operatora z faktycznymi preconditions. API, worker, env, header lub testowa para revisions nie mogą same otworzyć funkcji. Testowe fixtures nie trafiają do wheel. Backend receipt nie zastępuje bramek produkcyjnego rollout/O1/O3.

SECURITY DEFINER ma zamknięty search_path i właściwego ownera bez SUPER. Po DDL jawnie zamknij odziedziczone default grants, PUBLIC/raw DML/internal EXECUTE oraz sprawdź cały role graph/SET ROLE. Finalizer worker nie ma ogólnego source SELECT, consent mutation, identity admin lub DDL; lifecycle worker nie staje się finalizerem przez przypadkowe członkostwo.

Legacy accepted bez właściwego initialization proof zachowuje metadata, receipts i cancel, lecz statistics jest unavailable z HTTP 503. Nie odtwarzaj brakującej kwalifikacji z późniejszej historii ani nie seeduj fikcyjnych zer. Current-epoch accepted wymagające projection nie może dostać ACK źródła przy niesprawnym projector; odmowa cofa cały zapis. Stare challenge po restore nie blokują niepowiązanego poprawnego dziennika nowej epoki.

Rozszerz faktyczny scoped begin/purge chain z 0020. Begin deletion odcina partner read atomowo ze state/generation. Purge usuwa prywatne projections/results i powiązane peer snapshots/receipts/cursors; może zachować najwyżej bezpieczny cancelled marker partnera. Zachowaj naprawę0017, cały parent chain, fences, cleanup intents i anonimowe AI counters. Dowodem jest rzeczywisty Python resume/purge, hardened CLI, minimalny LOGIN SCRAM i COMMIT/retry — nie wywołanie samego helpera z ręcznie wstawionym context.

Restore natychmiast odcina stare read/source refresh/finalizer przez zmianę epoki, zanim bounded cleanup zakończy cancellation. Dawne wyzwanie nie odzyskuje zgody, kwalifikacji ani final result przez reconsent tego ID. Zwykły restart nie jest restore i nie zmienia epoki. Sprawdź zachowanie prawdziwego archive/restore oraz nową pracę dziennika/rankingu.

## 9. Weryfikacja oparta na wykonanych dowodach

Używaj rzeczywistego PostgreSQL 17 tej samej głównej wersji co wdrożenie, osobnych połączeń i nieuprzywilejowanych SCRAM LOGIN. Testy produkcyjnej app factory/HTTP nie zastępują rzeczywistego Keycloak/TLS; raportuj zakres osobno. Mock/fixture nie jest odbiorem funkcji zespołowej.

Wymagane oracles obejmują:

- Fresh/populated migration, owner/path/ACL/default grants, instalowany wheel i Docker z izolowanym Pythonem (-I) bez editable/source fallback.
- Atomowy accept obu stron/all N dates, błąd drugiej strony i raw API EXECUTE bez fake initializer.
- Source hook/savepoint/replay, pełną oś >10000 GoalVersion, przeniesione/usunięte wagi i kilka rywalizacji z różnymi deadline.
- q przed/na/po deadline, commit po terminie, rollback, lock waiter oraz retry z nowym q, bez timestamp authority z callera.
- Kalendarz 7/30/90, DST23/25 i pominiętą datę; maturity bez klienta, profil po end_at i dzień tylko z wagą.
- Punkt1 bez celu, inclusive bonus, brak kcal/celu/E, deficyt20/-50/-15, zero/null/counts i kanoniczne decimals.
- Hidden/insufficient/available, pending przed pierwszą maturity, strict schemas i brak surowych danych partnera.
- Finalizer pod fizyczną blokadą źródeł, wcześniejszą kwalifikowaną transakcją, późnym poison źródła, dwoma procesami/crash/restart i starvation prefix.
- Cancel/deletion/restore po provisional i final, account A/B/admin, no-store na wszystkich odpowiedziach, receipt/cache/304 bez odzyskania sharing.
- Rzeczywisty minimalny purge CLI i cały graph E4–E8 przy COMMIT/rollback/retry, retained repairs/fences i archiwum restore.
- Negatywne raw grants/EXECUTE, fałszywa revision pair, nieaktualna epoka i source ACK przy niedostępnym wymaganym projector.

Test ma sprawdzać skutek, nie kopiować implementację. Przy nowym błędzie zachowaj RED, ustal przyczynę i zastosuj najmniejszą poprawkę z własnym oracle. Nie obniżaj asercji, nie dodawaj skip/retry lub timeoutów w celu uzyskania green. Jeśli porażka pozostaje niewyjaśniona, raportuj ją i ograniczenia nowych obserwacji; sam pojedynczy rerun nie jest wyjaśnieniem. Nie sumuj nakładających się zakresów.

Niezależny nieautor sam wykonuje nowy istotny zakres na zamrożonym source, własnym PG/storage/processes i własnych oczekiwaniach. Minimum 9/10, bez istotnych P1/P2. Poprawiaj do spełnienia tej bramki. Raport przypisuje każdy wynik do source, polecenia, środowiska, node IDs i zachowanych XML/log/hash. Zmieniony runtime wymaga ponownego odbioru właściwego zakresu.

## 10. Git i przekazanie

Przed commitem przejrzyj diff, diff-check i kontrole właściwe dla zmiany. Autor/config Agent2 wyłącznie w swoim checkoutcie/commicie, bez zmiany globalnej tożsamości. Commity `agent 2: <konkretny wynik>`, własny branch → push → jeden PR do aktualnego main. Zachowaj historię zwykłym merge; bez force-push i publikacji bezpośrednio na main.

PR opisuje końcowy rezultat, migracje/zgodność, faktycznie wykonane testy, ograniczenia i działania zespołu. Aktualizuj opis przy zmianie końcowego zakresu. Koordynator, a nie wykonawca, scala dokładny head po odbiorze oraz ośmiu wymaganych rzeczywistych kontrolach aktualnego head/base. Następnie osobny push CI main i odbiór integracji. Lokalny PASS lub push nie potwierdza zdalnego CI.

Dokumentacja: decyzje, raport/recenzja i przekazania E8.4 w istniejącym docs/e8; publiczny jedyny dziennik to docs/KOMUNIKACJA_AGENTOW.md. Numer wpisu uzgodnij przed publikacją, zachowuj całe wpisy wszystkich autorów. Nie twórz drugiej tablicy. Repo zawiera źródła i potrzebne dowody opisowe, bez sekretów, prywatnych raw logs, plików credentiali, SDK paths, buildów lub cache.

O1 otrzymuje finalne DTO i przykłady pending/provisional/final/hidden/unavailable, świeżość zgody, revision/read-poll oraz pairing/terms/status/deadline. Wyniki E8 nie trafiają do starego sync ani Room jako udawany partner. O1 odbiera APK/UI/cache/sesję samodzielnie.

O3 otrzymuje role/provision, migracje, capability activation preconditions, worker/CLI/schedule, backlog oraz purge/backup/restore. O3 wykonuje własny rollout i dowody RPO/RTO. Brak tych dowodów jest konkretnym otwartym odbiorem zespołu, nie powodem zatrzymania niezależnego kodu O2.

Final do koordynatora zawiera exact source/head/base/branch/PR, własne testy i manifesty, wynik niezależnego nieautora, osiem CI aktualnego head/base, stan usług i pozostałe działania O1/O3. Nie deklaruj całego E8 lub E9. E8.5 przeprowadzi koordynator w swoim czacie; potrzebne poprawki wrócą tutaj.
