# Master E9-O2 — backend korekt zapotrzebowania energetycznego

Wersja 1, 13 października 2026 r. Autor przygotowania: agent 3, na bezpośrednie polecenie właściciela w tej rozmowie: po domknięciu obecnego zadania wykonać E9-O2 wskazane przez Agenta 2. To nowe zlecenie zastępuje wcześniejsze zapisy „E9 niezlecone” wyłącznie dla niniejszego zakresu. Nie zmienia roli/autora commitów na agenta 2.

Podstawa: main `821a4e8a5d5bd019032651de05c5c8e76e834145`, migracja0021. PR51 i PR52 oraz ich osobne push main zaliczyły po osiem kontroli; odbiór821a4e8: CI38391897032,1658unit/49infra/1265PG/28Keycloak/126JVM/131device, rzeczywista integracja i restart. Ten dokument opisuje przyszłe wykonanie, nie potwierdza działania E9. Przed implementacją opublikuj/odbierz master przez docs PR, wymagane CI, zwykły merge i osobny main.

## 1. Rezultat, właściciel i zależności

Dostarcz **E9-O2**, czyli backend: wersjonowane oszacowania utrzymania masy, deterministyczne `energy_adjustment_v1`, prywatne agregaty/propozycje, wyjaśnienie modelu, przyjęcie/odrzucenie/undo, domyślnie wyłączony automat, wspólne limity E7/E9, audyt, purge/restore oraz rzeczywiste testy PostgreSQL. Nie wystarcza funkcja licząca procent lub szkic endpointów.

Wykonawca w tej rozmowie zachowuje swoją ustaloną tożsamość agenta3. Własna gałąź `codex/backend-e9-korekty-agent3` z main zawierającego odebrany master; własny izolowany checkout, bazy, porty i procesy. Nie otwieraj drugiej implementacji, nie przełączaj cudzych checkoutów. Przed startem sprawdź aktualny main, status/remote, PR-y, gałęzie E9 i dziennik. Odczyt cudzej gałęzi nie oznacza jej scalenia.

Obowiązkowo przeczytaj [AGENTS](../AGENTS.md), [wymagania](../WYMAGANIA_PROJEKTOWE.md), [architekturę](ARCHITEKTURA.md), [plan](PLAN_PRAC.md), [workflow](WORKFLOW.md), [koordynację](MASTER_PROMPT_KOORDYNACJA.md), [jedyny dziennik](KOMUNIKACJA_AGENTOW.md) i [master E7](MASTER_PROMPT_E7.md). Szczególnie WF-10/13,11.5/11.6, KO-15/24/25 oraz ochrona KO-32. Starszy zakaz E9 dla wykonawcy E7 dotyczył tamtego zlecenia; nie usuwa bieżącej ludzkiej autoryzacji.

Backend E5/E7/E8 jest dostępny i odebrany. E7-R/live, realny APK/O1 i produkcja/O3 to osobne odbiory. Demo katalogu pozostaje demo; potwierdzanie producentów zostało odłożone przez właściciela. Nie rozpoczynaj official katalogu, płatnych usług, produkcyjnego wdrożenia lub E10. Automatyzacje pozostają PAUSED. Brak live konfiguracji nie blokuje tego backendu z rzeczywistym PG i jawnym mockiem.

## 2. Istniejąca podstawa i granice zgodności

- `profiles.service.estimate_energy` i istniejący endpoint kalkulatora już realizują `mifflin_pal_v1`. `GoalVersion.payload.estimate` zawiera świadomie zapisane oszacowanie. Nie zastępuj celu spożycia tym oszacowaniem i nie nazywaj skorygowanej liczby niezmienionym wynikiem równania Mifflina.
- E5/`analytics.repository` i `app.e8_day_facts` mają kompletność, dojrzałość dnia i źródła. Użyj tych reguł i jednostek; nie wprowadzaj alternatywnej kompletności lub zera za brak.
- `UserConsent.automatic_energy_adjustment` już istnieje i jest domyślnie false. Zachowaj zgodność istniejącego odczytu/PUT zgód, szczególnie równoległej pracy O1 z PR50. E9 wymaga także własnej świadomej aktywacji/kwalifikacji; stare placeholder true bez odpowiedniego wejścia nie uruchamia automatu.
- `app.ai_jobs` ma wspólny purpose i unikalny aktywny job na konto, lecz FK wskazuje obecnie wyłącznie analizę zdjęcia. Rozszerz ten sam mechanizm o rzeczywistą relację do analizy energii. Nie twórz drugiej kolejki poza wspólnym indeksem ani fikcyjnego zdjęcia/ścieżki magazynu.
- Zachowaj `e7_admit`, `e7_reserve`, `ai_pools`, attempts/permits i restore gate. Worker E9 nie otrzymuje superusera, roli API/migratora, DDL lub bezpośredniego dostępu do surowego dziennika/tożsamości.
- Nemesis używa obecnie oszacowania z historycznego celu. Nowa oś E9 musi być poprawnym źródłem zapotrzebowania dla właściwych dat; zachowaj stare oszacowania jako fallback historii. Zmiana oszacowania nie zmienia punktów `regularity_v1`, celu, klasy lub zaakceptowanych warunków wyzwania.

Rozdziel moduł `modules/energy` na schematy, reguły/agregaty, repozytorium, serwis/receipt i worker. Współdziel transport/limiter AI, nie kopiuj ich do niezależnej implementacji. Najpierw zapisz krótki dokument decyzji z rzeczywistymi nazwami endpointów, osi wersji, lock order, źródłami i granicami transakcji.

## 3. Wersje oszacowania i historia

Zastosuj osobną, prywatną oś oszacowania utrzymania, z monotoniczną rewizją osi i niezmiennymi wersjami: owner/generation, ID, wartość E, metoda/reguły, dane pochodzenia, effective_from, strefa decyzji, decided_at, actor/reason, powiązania z analizą i poprzednią wersją. Jedna efektywna wartość na lokalną datę; kolejne decyzje na ten sam przyszły dzień mają jawny deterministyczny porządek i zachowaną historię.

Początkową wartość/reference można przyjąć z faktycznie zaakceptowanego historycznego `GoalVersion.payload.estimate`, z dowodem jego tożsamości. Brak takiego dodatniego oszacowania nie upoważnia do użycia celu kcal jako E. Zapewnij świadome ustawienie/reanchor przez istniejący kalkulator i osobną decyzję E9. Nie importuj arbitralnie nowej wartości z klienta jako korekty AI.

Resolver dat rozróżnia historyczny artefakt oszacowania i własną wersję E9. Zmiana samego celu z tym samym artefaktem nie udaje nowej wersji zapotrzebowania. Inny artefakt/wersja w oknie blokuje liczbowe przyjęcie; jawna ponowna decyzja ustala nową bazę. Zapis początkowej osi nie przepisuje wartości wcześniejszych dni. Nowe korekty, reanchor i undo obowiązują od początku następnego dnia w aktualnej strefie profilu.

Undo przywraca poprzednią świadomie wskazaną wartość jako nową decyzję i wersję; nie usuwa historii. Odróżnij je od nowej propozycji wyliczonej z konsumpcji. Przyjęcie ręczne i świadome przywrócenie ustalają punkt odniesienia automatu; automatyczna korekta go nie przesuwa. Nie zmieniaj kcal/B/T/W celu, klasy aktywności ani dat/historycznych payloadów starego sync-v1.

Kalkulator/korekta v1 dotyczy dorosłych i zakresu11.5. Zachowaj wybór wariantu równania i możliwość ręcznego celu bez kalkulatora. Kwalifikacja E9 wymaga świadomego potwierdzenia odpowiedniego zakresu; nie zbieraj diagnoz i nie wyprowadzaj kwalifikacji z imienia, pseudonimu lub domysłów.

## 4. Reguły energy_adjustment_v1

1. Okno: ostatnie14 zamkniętych dat w strefie profilu, bez dnia bieżącego. Zamknięcie sprawdzaj również wobec rzeczywistych `matures_at` źródeł/stref. Minimum analizy:10 efektywnie kompletnych dni i masa w4 różnych datach, po minimum2 w każdej połowie7 dni. Brak warunków daje czytelny wynik bez korekty.
2. Masa: mediana nieusuniętych pomiarów każdej daty, następnie mediana dostępnych dziennych median w każdej połowie. Wiele pomiarów jednej daty nie zwiększa jej wagi. Nie używaj float/percentile_cont.
3. Liczbowa propozycja wymaga14 kompletnych dni, jednej wersji oszacowania w oknie, M1>0 i `abs(M2-M1)/M1 <= 0.005`. Kandydat to średnie zapisane kcal z14 dni. Pozostałe wystarczające dane dają opis/`manual_review_required`, bez przelicznika kg→kcal.
4. Ogranicz kandydata do±5% bieżącego E. Dla automatu dodatkowo do±10% ostatniego E świadomie zaakceptowanego przez użytkownika. Różnica poniżej1% bieżącego E daje `no_change`. Granice0,5/1/5/10% są testowane dokładnie, także wartości tuż po obu stronach.
5. Obliczenia i porównania zachowują dokładność Decimal/Fraction; zaokrąglij raz przy granicy reprezentacji, według istniejącej konwencji12 miejsc/half-up. Zaokrąglenie nie może przekroczyć ograniczenia lub błędnie zmienić werdyktu na progu.
6. Propozycja zawiera zakres dat, wersję reguł, liczby kompletnych dni i dni pomiarowych, ograniczenia, niepewność, datę wygaśnięcia, wersję E i rewizje/digest wejścia. Nie zapisuj propozycji dla obcego konta ani wyników częściowego, niespójnego odczytu.
7. Gemini wyjaśnia agregaty. Wiążąca liczba pochodzi wyłącznie z reguł backendu. Sugestię klasy można zapisać osobno jako niewiążącą; jej przyjęcie wymaga osobnej decyzji profilu/celu.

Źródłem kompletności jest WF-10: deklaracja, niepusty dziennik, znana energia wszystkich pozycji i dodatnia suma. Pustych/niepełnych dni nie zamieniaj w zero, nie interpoluj masy i nie traktuj nadesłanych agregatów jako źródła.

## 5. Snapshot, kontekst, zgody i transakcje

Pobierz ograniczony snapshot rzeczywistych danych serwera pod właściwą izolacją/locks. Zapisz rewizje lub deterministyczny digest obejmujący istotne dane: dziennik/deklaracje/masę, profil/strefę, cel i oś oszacowania, kwalifikację/zgodę oraz generation/epoch. Hash samych sum bez rewizji nie wykrywa wszystkich zmian.

Przed claim, każdą rezerwacją/outbound i przed zapisem wyniku/aplikacją ponownie sprawdź kontekst. Zmiana danych, inne E w oknie, utrata kwalifikacji, cofnięcie zgody lub wygasła propozycja blokują stary wynik. Nie przyjmuj go ponownie pod nowym kluczem. TTL propozycji to24h według DB UTC; automat działa nie częściej niż336h od ostatniej zastosowanej korekty, z uwzględnieniem także ręcznej decyzji/undo. Stosuj `clock_timestamp()`, nie zegar klienta.

Zgoda automatu jest online, afirmatywna i domyślnie wyłączona. Pokaż stan, revision i wersję notice; zmiana nie modyfikuje ranking consent. Cofnięcie przez istniejący endpoint zgód również odcina zakolejkowaną automatykę. Ponowienie starego receipt nie reaktywuje zgody. Aktualna kwalifikacja i zgoda muszą być prawdziwe w tej samej transakcji, która stosuje E.

Zachowaj idempotencję: owner/context+operation key+semantic hash, identyczny retry zwraca receipt, inny body pod kluczem jest konfliktem. Replay nie tworzy drugiego joba, admission lub wersji. Przypadki utraty odpowiedzi/COMMIT i równoległego manual/auto/undo muszą mieć rzeczywiste dowody PG.

Lock order respektuje istniejące account→counter→cały uporządkowany zbiór challenge locks→projekcje. Nie trzymaj transakcji przy provider IO. Nie dopisuj energii do starego wire sync-v1. Jeżeli potrzebny jest nowy wewnętrzny source kind/position, udokumentuj go, kwalifikuj w DB i przetestuj stare pull/checkpoint/recovery bez nieznanej encji lub zgubionych zmian.

Propagacja dat/osi do aktywnych projekcji Nemesis ma jednego właściciela locks i atomowy, kwalifikowany zapis; nie zostawiaj jej do przypadkowej późniejszej naprawy. Zachowaj deadline, frozen wynik, source savepoint, zgody i brak rekwalifikacji starym ticketem. Błąd projekcji cofa także nową wersję E/receipt. Nieznane SQL błędy nie stają się trwałą odmową; bounded retry używa nowej transakcji.

## 6. Wspólna kolejka, model i limiter

Rozszerz rzeczywisty job E7 o purpose energii i osobne poprawne relacje/FK/CHECK. Zachowaj wszystkie istniejące zdjęcia/jobs/receipts i jeden aktywny job na konto dla obu purpose. Worker/CLI ma prawdziwe discovery/claim/fences, bounded cleanup/lease recovery i czytelne zdrowie; martwy worker nie powoduje ponownego niepewnego wywołania.

Admission:1 nowa analiza energii na ruchome336h, wspólne z E7 reguły receipts i1 active/konto. Ten sam provider/project/model/environment scope i rejestr RPM/TPM/RPD, najwyżej2 outbound na środowisko. Nie twórz E9-specific puli tego samego modelu, nowego scope wskutek zmiany promptu albo resetu przez rotację klucza/restart/purge.

Obowiązują limity11.6/E7:≤8192 wejścia/≤2048 wyjścia z reasoning,≤45s próba/120s całość,≤2 próby, deadline kolejki5min; preflight/countTokens także rezerwuje wspólną pulę. RPD Pacific/DST, moving60s, pełna konserwatywna rezerwacja przy unknown/missing usage. Unknown timeout/utrata workera nie oznacza retry. Jawny transient429 lub błąd przed wysłaniem wymaga nowej rezerwacji i bounded Retry-After; daily/unknown429 kończy zadanie.

Do providera trafia tylko mały allowlisted zestaw agregatów potrzebnych wyjaśnieniu. Bez dziennika, owner UUID, issuer/sub/JWT, pseudonimu, diagnoz lub listy source IDs. Rewizje/digest pozostają po stronie serwera; treści użytkownika/output traktuj jako dane, nie instrukcje. Ścisły provider-compatible JSON Schema, bounded parser, odrzucenie duplicate keys, extra fields, NaN/Infinity, niespójnego statusu/kontekstu i propozycji liczby poza serwerowym wynikiem. Błędny/safety-blocked wynik nie tworzy nowej wersji.

Domyślnie mock, przez tę samą kolejkę/limiter/parser i logikę. Dodaj syntetyczne scenariusze prawidłowy, no-change, descriptive, malformed/mismatched, safety, timeout, transient/daily/unknown429 i unknown result. Mock nie jest testowym bypassem auth lub źródeł.

Przygotuj adapter tekstowych agregatów na podstawie obecnego zatwierdzonego REST profilu E7; nie kopiuj transportu multipart zdjęcia. Właściwe zasoby prompt/schema muszą działać z zainstalowanego wheel i obrazu. Live pozostaje osobnym, datowanym wejściem O3: klucz poza Git, projekt/model/limity, free-only, dostępność i brak billing. Użycie konsumenckie w EOG jest nadal zamknięte. Development live używa wyłącznie zatwierdzonych niesensytywnych danych syntetycznych; nie wysyłaj prywatnych agregatów użytkowników do unpaid usługi.

## 7. Migracja, ACL, purge, restore i API

Nowa migracja0022 z niezmiennymi migration-owned zasobami SQL; nie zmieniaj0001–0021 lub ich opublikowanych SQL. ORM/metadata, schema head/readiness, router/OpenAPI, katalog schematów i instalowany pakiet wskazują tę samą linię. Upgrade0021→0022 zachowuje stare kolumny/wiersze, cele, checkpointy/receipts, epokę i tożsamość oraz nie otwiera dispatch/automatu.

Endpointy muszą pozwolić na prywatny odczyt bieżącego E i paginowanej historii, świadome ustalenie bazy, utworzenie/odczyt analizy, przyjęcie/odrzucenie, undo oraz odczyt/zmianę automatu. Wszędzie rzeczywista autoryzacja/owner/context, no-store, ścisłe DTO i ograniczenia zasobów. Nie przyjmuj owner_id, daty provider qualification lub gotowych sum od klienta jako zaufanych.

API, AI worker, deletion operator i zwykły worker zachowują minimalne rozdzielone uprawnienia. SECURITY DEFINER ma stały search_path i kwalifikację źródła/kontekstu; helpery prywatne bez EXECUTE dla public/API/workera. Worker dostaje minimalny descriptor i uprawnienia do własnej operacji, bez DDL, raw source, SET ROLE lub bazy Keycloak.

Purge usuwa wszystkie nowe prywatne wersje/propozycje/notice/audyt/receipts dla właściwego owner/generation w rzeczywistym scoped begin/purge/COMMIT. Attempts/pool usage pozostają anonimowe do końca okien. Nie dopuść pozostawionego FK lub kasowania puli użytkownika pośrednio.

Restore/new epoch natychmiast odcina pending stare analizy/confirm/automat, również przy nowym idempotency key. Nie wysyła starych jobs i nie przywraca zgody przez retry. Zachowaj historię świadomych decyzji jako historię, oddzielając ją od pending pracy. AI dispatch pozostaje zamknięty do fizycznego fencing/reconciliation lub wygaśnięcia wszystkich niepewnych okien, w tym336h. KO-32 backend nie jest odbiorem Room/APK lub produkcyjnego RPO/RTO.

## 8. Dowody i odbiór

Testy dobieraj do ryzyk, nie do samej konstrukcji kodu:

- Reguły: brak/10/13/14 kompletnych dni, efektywne cofnięcie kompletności, zamknięcie/DST/różne source zones, deleted masa,4 daty/po2 na połowę, wiele pomiarów jednej daty i mediana, mixed estimate versions, granice0,5/1/5/10%, duża precyzja i zaokrąglenie raz.
- PG/API: owner A/B, realne snapshot/rewizje, daty następnego dnia i historia, cele/makra/klasa nieprzestawione, ręczny/auto anchor, domyślny opt-out/afirmacja/cofnięcie przed i podczas IO/przed COMMIT, stale wynik/24h/336h, replay/inny hash, równoległe przyjęcia i rollback/utrata odpowiedzi.
- E7/E9: wspólny aktywny job i ostatnie sloty quota obu purpose, retry/countTokens/unknown, worker lease/crash/fences, ograniczony zakres uprawnień i SQL errors, brak resetu po restart/rotation/purge.
- Projekcje: nowy E dla właściwych dat zmienia wyłącznie zapotrzebowanie/deficyt, zachowuje punkty/zgody/termin/frozen wynik; failure cofa całą operację. Stary sync/checkpoint/recovery pozostaje zgodny.
- Upgrade/purge/restore: rzeczywiste0021→0022 na reprezentatywnych danych, prawdziwy scoped COMMIT/usunięcie konta, nowa epoka i stare jobs/receipts pod nowym kluczem, quota preservation.
- Zainstalowany wheel/obraz: schema/prompty, routery/readiness i oba rodzaje workera, bez repo-source fallback. Pełna właściwa regresja backendu/PG/E7/E8 i wymagane zdalne osiem kontroli final-head/base oraz osobne main.

Niezależny nieautor ocenia istotne ryzyka z dowodami i uruchamia właściwe testy; minimum9/10, zero nierozwiązanych istotnych usterek. Lokalny wynik i poprzedni zielony commit nie zastępują końcowego CI. Przy poprawce odbierz dokładny nowy freeze; nie powtarzaj pełnych długich testów po samym komentarzu bez nowego ryzyka, obowiązkowe CI zachowując.

Raport `docs/e9/RAPORT_E9_O2.md` podaje źródło/head/base/PR, migracje/kontrakty, wykonane WF/KO/testy/review/CI, ograniczenia O1/O3/live i cleanup własnych procesów. Przekazanie O1 zawiera rzeczywiste przykłady i role dat/zgód/receipts; O3 — CLI/role/bounded scheduling/health/restore. Jedynym dziennikiem pozostaje KOMUNIKACJA_AGENTOW. Commit/push/PR, zwykły merge po odebraniu, osobny main; nigdy force/direct push main lub globalna zmiana tożsamości.

## 9. Źródła i zakres interpretacji

[Wymagania11.5](../WYMAGANIA_PROJEKTOWE.md#115-zapotrzebowanie-i-korekty) ustalają reguły produktu i ograniczenia automatyzacji; progi korekty nie są klinicznie zwalidowaną metodą lub zaleceniem diety. [Mifflin1990](https://pubmed.ncbi.nlm.nih.gov/2305711/?dopt=Abstract) opisuje podstawę istniejącego równania; [FAO/WHO/UNU](https://www.fao.org/4/y4249e/y4249e0j.htm) podaje przedziały PAL. Mapowanie klas/połączenie z Mifflinem jest przybliżeniem aplikacji. Nie twórz arbitralnego przelicznika7700kcal/kg.

Ponownie odczytane13.10.2026 [warunki Gemini](https://ai.google.dev/gemini-api/terms) nadal rozdzielają development od udostępnienia w EOG i ograniczają unpaid dane. E7-R/realny model oraz pełny E9/Android/produkcja mają osobne dowody. Samo wykonanie PG/mock oznacza E9-O2, nie publiczne uruchomienie Gemini.
