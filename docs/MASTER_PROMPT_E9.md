E9_O2_START_FROM_a522471140150271d853d66aa06f11d868699e49_PROJECT_913921f5-12c7-4204-9e4d-4afa20128bd7

Rozpocznij i wykonaj E9-O2 według poniższego mastera. To jedyny wykonawczy czat E9. Właściciel ustalił osobny czat na etap, zaakceptował jeden czat z wewnętrznymi podetapami oraz właśnie zlecił rozpoczęcie E9 zgodnie z tymi ustaleniami w czacie koordynatora 01a12156-2312-7c43-aedc-1858e782e5fb. Nie zmieniaj głównego checkoutu E4. Na początku utwórz swój worktree z origin/main; zachowaj cudze pliki/usługi. Zapisz master w docs/MASTER_PROMPT_E9.md w tym worktree, a dokumenty i kod opublikuj w jednym PR. Nie potrzebujesz wcześniejszego osobnego PR dokumentacyjnego.

Plan został niezależnie oceniony przez nieautora na 9,3/10; po review doprecyzowano, że klient retry nie rezerwuje puli ponownie, natomiast dozwolona kolejna próba dostawcy wymaga nowej rezerwacji. To wyłącznie odbiór planu, nie PASS kodu. Wykonanie ma własne testy i finalny niezależny odbiór. Koordynator odbierze Twój final przez wait_threads; nie scalać samemu, nie uruchamiać watchera, E10 ani Google.

# Master E9-O2: korekty oszacowanego zapotrzebowania - osoba 2

Wersja 1, 13 października 2026 r. Start: `a522471140150271d853d66aa06f11d868699e49`, repo `Roseru/aplikacja-mobilna`. Koordynator: `01a12156-2312-7c43-aedc-1858e782e5fb`. Projekt Codex: `913921f5-12c7-4204-9e4d-4afa20128bd7`.

## Zlecenie i granice

Właściciel zlecił w czacie koordynatora: „Zacznij pracowac zgodnie z odpowiednimi ustalenia nad e9”. Wcześniej ustalono jeden czat wykonawczy, podetapy wewnątrz niego, dopasowanie reasoning, jeden niezależny odbiór kompletnego rezultatu i jeden spójny PR zawierający master, kod, raport i przekazanie. Wykonaj samodzielny backend E9-O2 do publikacji i odbioru. Naprawy kontynuuj w tym samym czacie/PR. Koordynator scala po PASS i wymaganych kontrolach, następnie odbiera main. Starszy zakaz rozpoczynania E9 w masterze E8 dotyczył tamtego zlecenia; obecna ludzka wiadomość uruchamia E9.

Jesteś agentem 2 / O2. E9-O2 to reguły `energy_adjustment_v1`, wersjonowana historia E, API decyzji i cofnięcia, trwałe zadania/automat, wspólna pula E7/E9, ochrona kont i synchronizacji. Pełne E9/R oraz E10 wymagają oddzielnych rzeczywistych dowodów zespołu. Kod rozwijamy na izolowanym PG17, syntetycznych danych i mocku Gemini. Live gate pozostaje zamknięty bez konfiguracji O3; brak live/zdjęć/pełnego APK nie blokuje tego backendu.

Projekt jest obecnie demo: potwierdzanie producentów i official E5-C odłożono przez właściciela. Nie zmieniaj demo w official i nie wymyślaj brakujących mas/wartości. E7-R pozostaje otwarte po stronie konfiguracji O3 i corpus O2. Nie przejmuj Androida, infrastruktury, produkcyjnego wdrożenia, dostawców, billing ani automatyzacji. Istniejące watchery pozostają PAUSED. Nie wykonuj Google I/O.

## Wejście i lekki sposób pracy

Najpierw sprawdź Git/remote/otwarte PR, pobierz main, przeczytaj AGENTS.md, WYMAGANIA_PROJEKTOWE.md (szczególnie WF-13, 11.2, 11.5, 11.6, KO-15/21/24/25/28/32), ARCHITEKTURA, WORKFLOW i aktualne istotne wpisy KOMUNIKACJA_AGENTOW. E8-O2 i E8.5 są odebrane, PR30/main a522 ma odczytane wszystkie osiem wymaganych kontroli. Niescalone PR50 (zgody Androida) i PR51 (restart/diagnostyka O3) czytaj wyłącznie w zakresie wpływu na E9. Failed historycznego main83 pozostaje failed; sukces późniejszego main a522 nie wyjaśnia przyczyny jego awarii.

Zachowaj główny checkout i jego niezatwierdzone pliki. Utwórz własny managed worktree z aktualnego `origin/main` oraz gałąź `codex/backend-e9-korekta-zapotrzebowania`. Sprawdź duplikaty, kontynuuj istniejący własny rezultat jeśli faktycznie powstał. Zapisz ten master jako `docs/MASTER_PROMPT_E9.md` w swoim checkoutcie przed implementacją i aktualizuj go tylko przy rzeczywistej decyzji. Master i decyzje publikuj w tym samym PR co implementację; nie uruchamiaj osobnego pełnego CI dla samych metadanych startu.

Reasoning medium dla zwykłego kodu, DTO, dokumentacji i diagnostyki narzędzi. High dla modelu historii, transakcji, uprawnień, wyścigów oraz finalnej niezależnej recenzji. Xhigh tylko gdy konkretny nierozwiązany problem tego wymaga. Skorzystaj z jednego finalnego recenzenta niebędącego autorem; nie twórz kilku równoległych audytów tego samego zakresu. Po uwagach sprawdzaj poprawki i związane ryzyka, ponawiaj pełne testy przy uzasadnionej zmianie. Nie zastępuj odbioru wysoką deklarowaną oceną.

Realizuj kolejne punkty w jednym czacie. Krótkie aktualizacje podają wynik/ryzyko/następny krok; unikaj powtarzania całej historii. Przy pytaniu użytkownika odpowiedz i kontynuuj. Przy konkretnej brakującej decyzji opisz ją koordynatorowi, a niezależny zakres prowadź dalej.

## E9.1: reguły i stabilne wejścia

Wybierz ostatnie 14 zamkniętych lokalnych dni profilu według zegara bazy, z uwzględnieniem DST. Dzisiaj nie wchodzi do analizy. Użyj źródłowej reguły kompletności z E5/E8; null/puste/0 kcal nie stają się zerowym kompletnym dniem. Zachowaj daty źródłowe, nie przesuwaj ich przy zmianie strefy.

Warunek analizy: minimum 10 kompletnych dni i wagi w co najmniej czterech różnych dniach, po dwie w każdej siedmiodniowej połowie. Najpierw mediana wszystkich nieusuniętych pomiarów danego dnia; potem M1/M2 jako mediany dziennych median w połowach. Nie używaj E5 reprezentanta ostatniego pomiaru ani interpolacji. Obie mediany dodatnie/skończone. Brak wymaganej historii E/zmiana wersji E w oknie uniemożliwia zatwierdzenie liczbowej korekty.

Liczba dopuszczalna tylko przy 14 kompletnych dniach i `abs(M2-M1)/M1 <= 0.005`. Kandydat to średnia kcal tych 14 dni. Przy niestabilnej masie lub 10–13 kompletnych dniach zwróć opis i `manual_review_required`, bez zapisu oszacowania. Przy niewystarczającym minimum zwróć jawny stan braku danych, bez próby modelu i bez fikcyjnego wyniku.

Reguły są deterministyczne i wersjonowane: clamp ±5% aktualnego E, dodatkowo automat ±10% ostatniego świadomie zatwierdzonego E. Po ograniczeniu różnica poniżej 1% aktualnego E to `no_change`. Licz granice dokładnie na Decimal/rational z odpowiednią precyzją; żadnego float ani zaokrąglenia po każdym dniu. Końcowy wire ma dotychczasową kanoniczną precyzję/ROUND_HALF_UP. Testuj same granice i wartości tuż obok.

Model wyłącznie wyjaśnia deterministyczny wynik na minimalnych agregatach, z niepewnością i ewentualną sugestią klasy. Model nie wybiera wiążącej liczby, nie zmienia profilu/klasy i nie zapisuje bazy. Odrzuć niezgodny schemat, nieskończone wartości i próbę przekroczenia zakresu. Błąd/nieznany wynik dostawcy nie daje korekty.

## E9.2: historia, API i kompatybilność

Przed kodem rozstrzygnij i krótko udokumentuj reprezentację E: obecny GoalPayload.estimate akceptuje tylko prawdziwe `mifflin_pal_v1`, a cel ma osobną niezmienną oś. Nie oznaczaj korekty jako obliczenia Mifflina, nie nadpisuj istniejącego JSON i nie zmieniaj celu kcal/B/T/W, goal_type ani activity_class jako efektu przyjęcia E. Brak oszacowania przy ręcznym celu pozostaje brakiem oszacowania.

Dodaj czytelną, właścicielską oś oszacowań z audytem (metoda/reguły, wejścia, źródło, rewizja, data, świadomy baseline, propozycja/uzasadnienie/decider). Integruj istniejące prawidłowe oszacowania bez niszczenia historii, retroaktywnego nadawania zgody lub przypadkowego resetu automatycznego baseline. Zmiana obowiązuje od początku następnego lokalnego dnia według chwili zastosowania w bazie; cofnięcie poprzedniego E tworzy nową decyzję od następnego dnia. Stare wersje pozostają niezmienne.

Decyzje koordynatora zamykające planowanie (uwzględnij je w wymaganiach/kontrakcie w tym samym PR):

- Legacy E jest wersjonowanym źródłem z prawidłowego `GoalPayload.estimate`, rozstrzyganym z uwzględnieniem jego osi/korekt i dat, nigdy z goal.energy_kcal. Bootstrap/backfill ma deterministyczną provenance/idempotencję i nie zmienia źródłowego JSON. Późniejszy sync prawidłowej decyzji z estimate korzysta z tego samego adaptera/resolvera. Cel bez estimate nie zeruje i nie tworzy oszacowania. Przy niepewnym powiązaniu wersji przerwij liczbową analizę, nie zgaduj E.
- Jedna obowiązująca wersja E dla daty, uporządkowana effective_from/revision z jawną provenance/supersedes; żadnego UPDATE starej wersji. Istniejąca planowana zmiana na datę nowej propozycji powoduje jawny409, zamiast cichego zastąpienia. Późniejsze planowane decyzje pozostają zachowane i widoczne. Świadome revert może zastąpić planowaną decyzję przy podanej aktualnej rewizji/ID i audycie.
- Legacy oszacowanie nie stanowi automatycznie świadomego baseline automatu E9. Przed pierwszą automatyczną zmianą wymagana jest jawna online afirmacja konkretnej aktualnej wersji E (albo manual accept/revert), obok zgody automatic_energy_adjustment. Afirmacja nie zmienia liczby, dat historii ani celu. Automat nie rebaselineuje sam; stary sync/restore/off→on nie przywraca utraconej afirmacji. Baseline jest powiązany z aktualną epoką/zgodą.
- Limit nowej przyjętej analizy:336h od accepted_at; niezależny limit zastosowania nowej propozycji AI (manual i auto):336h od ostatniej zastosowanej korekty. Odrzucenie/no_change/błąd nie są zastosowaniem. Świadomy revert jest operacją przywrócenia, może nastąpić wcześniej, ale aktualizuje zegar ostatniej zmiany dla kolejnego zastosowania AI. Nie daje dodatkowego zlecenia Gemini.
- expires_at to created_at gotowej zwalidowanej propozycji +24h; przy clock_timestamp >= expires_at jest expired. Wejścia/fingerprint zamrażamy przed dispatch. Stare wejścia blokują również opóźniony wynik; ready nie odświeża fingerprint. Dzień/source-zone zostają zgodne z istniejącą semantyką dziennika; aktualny profil wybiera okno zamkniętych dat, nie zmienia zapisanych local_date.
- `<1%` sprawdzamy po wszystkich clamp, na dokładnej wartości, przed końcowym wire rounding. `0.005` stabilności włącznie, dokładne1% nie jest no_change. Zmiana na gotowym DTO/wire nie może wyjść poza zakres; testuj też zaokrąglenie granicy.
- Wymagania11.2/WF13 doprecyzuj: korekta oszacowania E używa wspólnego mechanizmu własności/wersjonowania/sync; nie jest automatyczną zmianą celu ani klasy. Zachowaj właściwe wcześniejsze reguły offline celu.

E8 musi używać tego samego resolvera historycznego E: jego SQL obecnie czyta `goal_versions.payload.estimate.maintenance_kcal` (`e8_0021/projections.sql`, `source.sql`, `statistics.sql`). Nowy E wpływa na właściwe nowe dni/projekcje deficytu i odczyty; atomowy hook i granice kwalifikacji nadal respektują deadline, frozen final results i source-authoritative reguły E8. Nie zmieniaj punktów/rang/celów ani dawnych dat E. Weryfikuj porównanie E8 sprzed/po korekcie i spóźnioną operację/worker.

Zamroź additive API/DTO, błędy i decyzję dystrybucji zmian do klienta przez sync. Zachowaj E3/E4 i 30-dniową kompatybilność istniejących klientów: nowa metoda/payload/typ encji nie może zepsuć starego parsera ani istniejącego snapshotu. Jeśli potrzebna jest jawna negocjacja nowego kontraktu, zaprojektuj ją jako opt-in, z testami starego klienta i instrukcją O1. Zachowaj wspólną usługę wersjonowania, blokadę konta, ChangeLog i kolejność zatwierdzeń; nie twórz alternatywnej kolejki konkurującej z E4.

Nowa encja E wymaga opt-in klienta do `energy_estimates_v1`; domyślny legacy sync nie emituje jej ani nowego wariantu starego GoalPayload. Capability/protocol scope wiąż z podpisanymi cursor/snapshot/checkpoint, aby nie mieszać snapshotów ani pominąć historii po zmianie klienta. Pierwsze przejście na nowy zakres wymaga pełnego snapshotu z zachowaniem outbox. Starszy klient nadal dostaje dotychczasowe encje/potwierdzenia, nie wpada w pętlę na pominiętej zmianie E. Udokumentuj additive pole/query oraz zgodne błędy; nie implementuj migracji Room/Androida za O1.

API: zlecenie/status/lista lub odczyt własnych analiz, przyjęcie/odrzucenie, własna historia E i przywrócenie wcześniejszej wartości. Mutacje online używają UUID Idempotency-Key, kanonicznego body/hash, epoki/generacji i oczekiwanych rewizji. Utrata odpowiedzi/restart daje ten sam pierwotny wynik; inny body z tym samym kluczem daje409. Cudze ID nie ujawnia danych, role moderatora/admina nie dają dostępu do prywatnych analiz.

Propozycja wygasa po24h od utworzenia według zegara bazy; do czasu wygaśnięcia i przed zastosowaniem ponownie sprawdź jej zamrożony kontekst. Zmiana profilu/strefy, celu, osi E, pomiarów/posiłków/kompletności w analizowanym oknie, zgody albo epoki/generacji blokuje stare zatwierdzenie i wymaga nowej analizy. Fingerprint/rewizje mają uwzględniać edycję, dodanie i usunięcie; samo porównanie liczby/sumy jest niewystarczające.

## E9.3: trwały worker, automat i ochrona kont

Rozszerz istniejące zadania/runner E7 o `energy_adjustment`, zamiast budować drugą pulę lub backendowy broker. Jedno aktywne zlecenie na konto wspólne ze zdjęciem, globalne limity E7/E9/RPM/TPM/RPD/concurrency, licznik użytkownika energii raz na 14 × 24 h. Osobno pilnuj automatycznego zastosowania nie częściej niż 14 × 24 h od ostatniej korekty. Idempotentne ponowienie żądania klienta nie tworzy analizy ani rezerwacji ponownie. Dozwolona nowa próba dostawcy po jednoznacznym 429/before_send wymaga nowej rezerwacji zgodnie z E7 i 11.6. Brak minimum/gate/config/quota nie wysyła żądania dostawcy.

Istniejąca kolejka jest zdjęciowa (`ai_jobs` FK do ai_analyses, claim i Runner wymagają zdjęcia); migracja ma jawnie uogólnić ten seam bez zniszczenia zdjęciowych zadań/history. Wspólne ai_controls/attempts/physical permits i limiter pozostają jedną ochroną. Nie wystarczy dodać purpose ani GRANT EXECUTE na surowe e7_reserve; worker nie może obejść audytowanego claim/dispatch przez samodzielną rezerwację. Bezpieczny dispatcher wybiera typed payload obrazu lub agregatów, żadne udawane zdjęcie dla energii.

Sieć poza transakcją. Trwały lease/fence/epoch/generation/consent revision chroni claim, dispatch i wynik. Timeout po możliwym wysłaniu oraz utrata procesu po dispatch nie powodują automatycznego ponownego Gemini. Zachowaj reguły retry i niepewnej puli E7, 45s/próbę i120s całości. Wspólna retencja/storage cleanup zdjęć musi dalej działać.

Automat domyślnie off, działa tylko ze zgodą online i aktualnym baseline. Wyłączenie zgody blokuje również już kolejkujący/pracujący job przed zastosowaniem; ponowne włączenie nie reanimuje starego joba. Dwa workery/ręczna akceptacja/zmiana zgody nie mogą zastosować dwóch wersji E. Manual accept ustawia nowy świadomy baseline, automat go nie przesuwa. Jasne statusy, próg no_change, ograniczona kolejka/catch-up i audyt odmów, bez prywatnego dziennika w logach.

Zachowaj usuwanie konta, purge, minimalne receipts i UUID reservations, restore/KO32. Uwierzytelnienie nie otwiera konta deleting. Stare zadanie/opera­cja/propozycja po zmianie epoki nie zapisuje danych ani nie wywołuje modelu. Minimalny worker LOGIN/ACL bez roli API/migratora/superuser i bez bezpośredniego DML do dziennika/celów; potrzebne funkcje mają ograniczone EXECUTE/search_path i izolację właściciela.

## E9.4: migracje, weryfikacja i odbiór

Migracje001–0021 są opublikowane i niezmienne; rezerwuj nową0022 (po ponownym sprawdzeniu main), żadnej drugiej head lub edycji istniejącego SQL. Schemat/ORM/head/health/wheel/Docker i provision workerów muszą być zgodne. Zmiany nowych SQL funkcji publikuj nową migracją. Zachowaj istniejące konta, epokę, role i wszystkie stare dane; zapisz kompatybilność starych obrazów. Testowy downgrade dotyczy własnej efemerycznej bazy, nie operatora/userdata.

Testy mają niezależne oczekiwane liczby i prawdziwe transakcje/procesy, a nie powtarzać implementację. Minimum:

- Reguły:0/9/10/13/14 kompletności, null/0, pomiary wielokrotne/deleted,4dni/2na połowę, mediany parzyste/nieparzyste, dokładne0.5%,1%,5%,10% i sąsiednie wartości, różne E w oknie, DST/północ i następny dzień.
- API/PG: A/B i role, analizy/decisions/revert, historyczny E i niezmienny cel/makra/klasa, brak estimate, expiry, każda kategoria stale input, lost ACK/retry/body conflict, atomowy ChangeLog/pull/snapshot, zgodność obecnego klienta.
- Worker/mock: poprawny/błędny/provider_unknown/429/before_send, crash i stalelease, zdjęcie kontra energia we wspólnej puli, brak model/config, gate/restore bez ponownego I/O, expiry/cooldown, catch-up i zgodaoff/on, dwa procesy i wyścigi akceptacja–automat–sync–delete–epoch.
- Integracja E8/legacy: wspólny resolver E, właściwe nowe projekcje deficytu, niezmienne zamknięte wyniki/punkty; przyszłe wersje oraz bootstrap oszacowań; legacy klient/snapshot/receipt po dodaniu E9 i świadomy upgrade capability bez utraty outbox.
- Upgrade0021→0022 na istniejących danych oraz pusty PG, SQL ACL i konto minimalnego workera. Weryfikacja zainstalowanego wheel/realnego CLI, zgodność generated OpenAPI/schema/examples, E0, Ruff, diff-check. Dotychczasowy zestaw backendu uruchom na odbiór, z właściwymi rolami PG; nie sumuj powtórzeń jako nowych testów.

Zapisuj konkretne błędy RED oraz naprawę/GREEN. Fail lub niewykonany zestaw nie jest PASS. Po zmianie zakresu wykonaj kontrole adekwatne do ryzyka. Przy problemie harnessu diagnozuj właściwą konfigurację, nie osłabiaj oracles/ACL/limitów.

Finalny nieautor ocenia cały rezultat minimum9/10, zero nierozwiązanych P1/P2, z rzeczywistymi dowodami krytycznych scenariuszy. Jego raport wskazuje SHA/zakres/niewykonane przypadki. Napraw istotne uwagi i odeślij zmieniony zakres do tego samego recenzenta. Koordynator dodatkowo sprawdza najważniejsze niezmienniki, diff i final-head/base CI; nie potrzebuje kolejnego pełnego audytu tych samych przypadków.

## Pliki i publikacja

Zachowaj modularny backend. Wybierz jeden czytelny pakiet `modules/energy` (lub zgodną istniejącą granicę), z oddzielnymi rules/schemas/models/repository/service/router; integracja Gemini i runner pozostają w istniejących granicach. Brak nowego frameworka/Redis/brokera bez wykazanej potrzeby. Komentarze tłumaczą nieoczywiste reguły, nazwy mówią o oszacowaniu, nie mylą go z celem.

W jednym PR umieść `docs/MASTER_PROMPT_E9.md`, `docs/e9/RAPORT_E9.md` z decyzjami i oceną, `docs/e9/INTEGRACJA_O1.md` oraz `docs/e9/KONFIGURACJA_O3.md` z potrzebnymi przykładami/komendami/bezsekretową konfiguracją. Nie mnoż dokumentów z tą samą treścią. Aktualizuj PLAN_PRAC i własny wiersz/wpis **O2-028** w jedynym KOMUNIKACJA_AGENTOW, zachowując wpisy i potwierdzenia innych. Powiedz wprost: E9-O2 wykonane/odebrane vs pełne E9 otwarte, demo/official i live bramki.

Przejrzyj diff, git diff --check, kontrole, lokalna tożsamość i commit `agent 2: <konkretny wynik>`; bez globalnej zmiany autora. Pobierz nową komunikację przed końcowym pushem; nowe main integruj zwykłym merge, bez force-push. Nie publikuj prywatnych .review-o2, sekretów, plików usług/local paths/buildów. Otwórz jeden PR do main, załącz go do czatu, opis finalnego wyniku/migracji/zgodności/testów/ograniczeń. Wszystkie siedem wymaganych jobów i ci-required muszą rzeczywiście wykonać się na aktualnym head/base; nie obchodź O3 CI.

Wynik końcowy do koordynatora przez final tego czatu: branch/head/base/PR, zwięzły rezultat, testy/recenzja, ograniczenia i następny konkretny krok. Koordynator odczyta wynik przez wait_threads; nie twórz dodatkowego watchera ani drugiego wykonawcy. Koordynator ma autoryzację właściciela do kontynuowania pracy E9 i przekazywania poprawek temu wykonawcy. Zatrzymaj własne usługi testowe, zachowaj dowody. Nie scalaj PR samodzielnie i nie rozpoczynaj E10.



## Uzupełnienie wykonawcze po odczycie nowego main

W trakcie tego wykonania main przyjął master przygotowania O3/6952c14 i jego
nieautorski odbiór tekstu. Pierwotne zlecenie tego czatu pozostaje wykonawcze:
Agent2, jedna implementacja/PR, bez własnego merge/E10/Google/watcherów.
Nie uruchamiamy kolejnego wykonawcy. W kodzie uwzględniono dodatkowe zabezpieczenia:
jawny manual energy notice (provider/scope/kwalifikacja/serwerowy snapshot),
osobny notice przyszłej automatyki oraz bounded/fair producent współdzielonego
runnera. Odbiór mastera O3 nie jest odbiorem tego runtime.

Odczytano i zachowano w historii Git przygotowanie O3:
[pełny master6952c14](https://github.com/Roseru/aplikacja-mobilna/blob/6952c1418b3a79e4da93803808d40c5097f3a40b/docs/MASTER_PROMPT_E9.md)
oraz [odbiór tekstu](e9/RECENZJA_MASTER_E9.md).
Wskazanie tam Agenta3 dotyczy tamtej instrukcji przygotowania. Wykonawczy master
przekazany do tego czatu ustala Agenta2 i jedną implementację; żadna ocena planu
nie jest odbiorem naszego kodu. Nowe wpisy O3 i jego source/CI pozostają zachowane.


### Odbiór naprawczy po pierwszym freeze

Wypchnięta0022 pozostaje niezmienna. Potwierdzone uwagi odbioru rozwiązuje
liniowa0023_e9_qualification: canonical tożsamość artefaktu Mifflin (nie goal),
kwalifikacja wcześniej zaimportowanych duplikatów bez zmian immutable JSON,
fail-closed pustego przedziału kwantów wire12, scoped54000 odmowa bounded auto
producenta oraz wewnętrzny ACL helpera. Health/runtime/provisioning przyjmują
aktualny head0023; brak automatycznej aktywacji live Nemesis.


0024_e9_history_graph domyka jawne history_correction (nie pomija ich jak clone)
i literalną kwalifikację parent prosrc. Wszystkie opublikowane wcześniejsze
migracje pozostają niezmienne; końcowy head jest liniowy0024. Rozróżnienie zwykłej
zmiany celu i jawnej korekty dat jest potwierdzone niezależnym oracle PG.


Korekta draft003: wyłącznie ACL statement warunkuje REVOKE opcjonalnych runtime
ról ich istnieniem; bez nowych grantów/rol i bez zmian funkcji003,0022 lub001–21.
Wykazana przez istniejące E4 secret/log tests minimalnego legacy bootstrapu.
Drugi bounded context odmawia scoped54000 w004. Requested/effective po ranking
PUT ma jawne przekazanie O1; boolean nie zastępuje świeżej energy affirmation.
