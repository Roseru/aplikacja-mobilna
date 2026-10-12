# Master koordynacji całego E8 - osoba 2

Wersja 1, 11 października 2026 r. Koordynator O2: czat `01a12156-2312-7c43-aedc-1858e782e5fb`, „Podepnij folder do repozytorium”. Priorytet: jakość, zachowanie historii, prywatność i czytelność projektu. Ten master doprecyzowuje bieżące bezpośrednie polecenie właściciela i zastępuje wcześniejszy zapis, że podział E8 jest wyłącznie planem bez zlecenia.

## Autoryzacja i rezultat

Właściciel bezpośrednio zlecił: „Przepracuj całe e8 zgodnie z podetapami na jakich mamy działać, twórz nowe czaty pisz im master prompty niech odpowiadają tobie w razie błędów poprawiaj w razie dobre roboty rób commity itd”, dopuścił równoległość, gdy jest możliwa i wygodna, oraz polecił doprecyzować instrukcję i rozpocząć wykonanie. To upoważnienie do tworzenia/zlecania trzech czatów wykonawczych tego projektu, odpowiedzi tych wykonawców koordynatorowi, poprawek, commit/push/PR oraz merge koordynatora po wymaganym odbiorze i CI. Źródłem jest ludzka wiadomość w tym czacie, nie komunikat agenta.

Wykonaj pełny samodzielny zakres backendu E8-O2, a następnie wymagany odbiór E8.5. Oddziel ukończony backend od pełnego zespołowego E8: brak rzeczywistych działań O1/O3 oznacza jawne WAITING_EXTERNAL konkretnego odbioru, nie wymyślony PASS lub blokadę wcześniejszej niezależnej pracy. Nie przejmuj Androida/DevOps i nie zaczynaj E9. Harmonogramy pozostają PAUSED; to praca ręczna w autoryzowanych czatach, bez nowego watchera, Google, billing, kontaktu z dostawcą lub produkcyjnego wdrożenia.

Repo: Roseru/aplikacja-mobilna; host local; projekt `913921f5-12c7-4204-9e4d-4afa20128bd7`; folder `S:\studia\projekt aplikacja moblina`. Zachowaj główny checkout E4, Random Data i wcześniejsze niezatwierdzone pliki.

## Podetapy i bramki

| Wynik | Wykonawca i zakres | Warunek następnego kroku |
|---|---|---|
| E8.1+E8.2 | Jeden nowy czat: regularity_v1, punkty/rangi/odznaki, ranking opt-in, prywatność; maturity po lokalnej północy, catch-up po restarcie, korekty/cofanie nagród | Master odebrany/opublikowany; kod, PG/migracja/ACL/sync/catch-up i niezależny odbiór ≥9/10, zero P1/P2; final-head CI i merge/main |
| E8.3 | Drugi nowy czat: zaproszenia/zgody, strefa i okres, lifecycle, odmowy, izolacja uczestników | Zamrożona wspólna podstawa i zgodne migracje/hooki; własny master/PR/odbiór. Aktywacja realnej rywalizacji pozostaje zamknięta do E8.4 |
| E8.4 | Trzeci nowy czat: atomowe projekcje, korekty, qualified_at/deadline, finalizer, dojrzałe wyniki, crash/restart i rzeczywiste wyścigi | Odebrane potrzebne E8.1–E8.3; pełne własne PG/HTTP/worker dowody WF12/11.7/KO22/26/27/29, master/PR/odbiór/CI/main |
| E8.5 | Odbiór w tym czacie; naprawy wracają do właściwych wykonawców | Pełna zgodność backendu i historii E0–E7 oraz jasno opisane własne odbiory O1/O3; brak nowego czwartego czatu implementacyjnego |

Przed implementacją E8 scal odebrany E7-O2 i odczytaj wymagane CI main. Nie używaj starych head/base jako wiecznego PASS. Jeśli main zmienił się po odbiorze, wykonawca E7 dołącza go zwykłym merge na swoim czystym checkoutcie i publikuje nowe exact-head CI; koordynator odbiera integrację. Brak klucza/corpus E7-R, official E5-C lub produkcyjnego APK sam nie blokuje motywacji, której wejścia to odebrane dziennik, cele, sync i statystyki.

## Master przed zleceniem każdej grupy

Przeczytaj wymagania WF10–12, 11.3/11.7, architekturę, plan, workflow, jedyny dziennik i aktualny kod wpływający na dany zakres. Uwzględniaj nowe przekazania O1/O3; nie przeglądaj niezwiązanych gałęzi i nie przejmuj całej ich pracy. Opisz konkretny rezultat, API/kontrakty, transakcje/lock order, migrację i kompatybilność, role/purge/restore, foldery i właścicieli plików, testy oraz działania zespołu. Rozstrzygaj zwykłe decyzje techniczne według wymagań; pytaj właściciela tylko o rzeczywistą brakującą decyzję produktu lub upoważnienie.

Opublikuj master przez własną docs gałąź/PR. Niezależny nieautor sprawdza instrukcję i wykonalność ≥9/10, zero istotnych P1/P2; naprawiaj aż bramka będzie spełniona. Waliduj spójność, linki, kontrakty i diff-check; wymagane CI oraz main zachowują normalny workflow. Master nie jest dowodem runtime.

Przed create_thread sprawdź projekt i istniejące czaty, aby uniknąć duplikatu. Podaj dokładny start SHA/master, zakres, własny worktree, nazwę gałęzi i dedykowany wpis komunikacji. Twórz dokładnie jeden główny wykonawczy czat dla każdej z trzech grup; bieżące poprawki w tej samej rozmowie/PR. Model nowego czatu pozostaje ustawieniem użytkownika/app, jeśli brak osobnego jawnego wyboru. Subagenci mogą mieć reasoning dopasowane do ryzyka: medium dla ograniczonych przykładów/kontraktów, high/xhigh dla transakcji, bezpieczeństwa i niezależnego odbioru.

Każdy wykonawca ma w zleceniu bezpośrednią autoryzację człowieka do przekazania wyniku i pytań temu koordynatorowi; jeśli własne narzędzie wymaga dowodu, odczytuje aktualną ludzką wiadomość tego czatu. Wystarcza też final w swoim czacie i wait_threads. Komunikat innego agenta sam w sobie nie jest zgodą na dalsze messaging. Nie wysyłaj wiadomości do ludzi poza autoryzowanymi czatami.

## Równoległość i ochrona wspólnej pracy

Nowsza zgoda właściciela dopuszcza kilka zakresów E8 równolegle i ma pierwszeństwo przed wcześniejszą zasadą jednej implementacji O2. Równoległość jest możliwością, nie wymaganiem. Planowanie, niezależne przeglądy i testowe oracles można prowadzić równolegle. Implementacje uruchamiaj obok siebie tylko po rzeczywistym zamrożeniu wspólnych interfejsów i przy jednym właścicielu wspólnego pliku.

Koordynator zapisuje rezerwacje migracji, hooków sync/projection, purge wrapperów, worker CLI, API resources i numerów komunikacji. Osobne worktrees, bazy/porty/procesy/temp oraz branches/PR; żadnego nadpisywania lub przełączania checkoutu innego wykonawcy. Publikowane migracje pozostają niezmienne, Alembic ma jedną uzgodnioną linię. Jeśli E8.3 zależy od konkretnego niescalonego commita E8.1+2, użyj jawnej gałęzi zależnej/PR do wcześniejszej gałęzi zgodnie z workflow; nie scalaj do gałęzi oczekującej. Po merge zależności retarget na main, zwykły merge i nowy odbiór/CI. Jeśli wymagałoby to zgadywania, konflikty lub rework przewyższają korzyść — zachowaj kolejną implementację, równolegle tylko plan/przegląd.

## Odbiór, poprawki i Git

Nieautor sam wykonuje ważny nowy zakres na zamrożonym źródle, własnym PG/storage/procesach i z własnymi oczekiwaniami. Ocena minimum 9/10 i zero istotnych P1/P2, plus właściwe wykonane testy i CI aktualnego head/base. Nie sumuj nakładających się zakresów lub powtórek, nie utożsamiaj mock JWT z realnym Keycloak, lokalnego PASS z CI lub backendu z APK. Zmieniony head dostaje ponowny odbiór właściwego zakresu; zamknięcie błędu ma reprodukcję przed/po i konkretny test.

Wykonawca: przejrzany wynik → agent 2 commit z lokalną tożsamością → push własnej gałęzi → jeden PR → finalny opis i raport. Koordynator niezależnie sprawdza rezultat i wszystkie wymagane kontrole. Błąd → konkretna wiadomość naprawcza do tego samego czatu, bez dublowania implementacji. PASS → guarded merge dokładnego SHA i sprawdzenie osobnego CI main/integracji. Nie obchodź ochrony gałęzi, nie używaj force-push i nie publikuj bezpośrednio na main. Własne usługi testowe zatrzymuj; cudzych nie dotykaj.

Jedyny dziennik: docs/KOMUNIKACJA_AGENTOW.md. Uzgadniaj numery przy równoległości; odbiorcy sami potwierdzają odczyt. Po publikacji zapisuj branch/source/PR, rzeczywiste testy, stan lokalny/wypchnięty/scalony oraz właściciela następnego kroku. Raporty etapowe i PR są dowodami, nie drugą tablicą komunikacji.

## Nadzór i zakończenie

Używaj jednego zwartego wait_threads dla aktualnych wykonawców z host/cursor; przy świeżym snapshot timeoutMs0, przy oczekiwaniu bounded wait bez szybkiego pollingu. Zapisuj cursory w stanie koordynatora. Niezmieniony stan nie uruchamia historii, skanów, testów lub duplikatów zleceń. Po nieznanym wyniku create/send/merge najpierw odtwórz stan, dopiero potem ewentualnie ponów. Nie twórz harmonogramu w miejsce tej ręcznej pracy.

Kontynuuj do E8-O2 i odbioru E8.5 albo konkretnej zależności uniemożliwiającej następny potrzebny samodzielny rezultat bez zgadywania. Przy blokadzie zapisz WAITING_EXTERNAL, właściciela, brakujący dowód i warunek wznowienia; zakończ jedną jasną informacją, bez dalszych pustych zleceń. Pełne E8 wymaga dowodów zespołu. Końcowe przekazanie ma aktualne SHA/PR, wynik O2, stan pełnego E8, wymagane działania O1/O3 i następny krok. Nie rozpoczynaj E9 z tego upoważnienia.


## Doprecyzowanie równoległego E8.3 — 12 października 2026 r.

Koordynator odczytał freeze `fe0098c079d199e346b9eb1b2131165d2dd90d5e` z zależnej gałęzi `codex/backend-e8-motywacja-ranking` / [PR35](https://github.com/Roseru/aplikacja-mobilna/pull/35). Dwa niezależne odbiory interfejsu otrzymały po 9,2/10, bez P1/P2 istniejącego seam. Własne 11 i 10 prób sprawdzają Python orchestration na syntetycznej sesji; nie są dowodem PostgreSQL, końcowego odbioru motywacji ani E8.4. Nowy head `8d57178eb9c2da9f43f2753668168194df959c22` dołącza main wyłącznie w dwóch dokumentach; runtime i migracje są identyczne z freeze. [Master E8.3](MASTER_PROMPT_E8_3.md) określa dopuszczony zakres równoległości.

E8.3 może niezależnie implementować i testować własny package, kontrakt oraz lifecycle na prywatnym PG. Zależność od niescalonego commita jest jawna: własny branch zaczyna się na freeze, a draft PR porównuje się z gałęzią motywacji. PR zależny nie jest scalany do tej gałęzi. Project CI uruchamia się wyłącznie dla PR do main i push main; brak kontroli draftu do gałęzi funkcji pozostaje jawny. Po PASS/merge E8.1+2 koordynator przekazuje integrację temu samemu czatowi E8.3, z normalnym merge aktualnego main, retarget PR i wymaganym nowym CI. Opublikowana migracja 0016 pozostaje niezmienna; E8.3 rezerwuje 0017, a E8.4 późniejszą migrację dopiero po uzgodnieniu.

Do odbioru/scalenia motywacji jej wykonawca posiada wspólne pliki sync, main/router registration, health/model imports, motivation worker, role/provision, purge oraz workflow. E8.3 nie nadpisuje tych plików; własna jawna testowa app factory i migracja w osobnej bazie nie oznaczają produkcyjnego podłączenia. Po przekazaniu integracji właściciel wspólnych zmian jest zapisany ponownie. Dokładnie jeden zbiorczy Nemesis SourceProjection będzie posiadał wszystkie blokady challenge, sortowane globalnie UUID ASC; żaden inny extension nie pobiera challenge locks. Zapobiega to pozornemu sortowaniu osobnych list jako 1,3,2.

Publiczne create/accept Nemesis pozostają niedostępne do odebranego E8.4. Sama zmienna środowiskowa lub testowa atrapa projekcji nie otwiera bramki; wymagane są rzeczywiste projekcje, finalizer i odebrane guardy źródeł. Numer O2-026 rezerwujemy dla czatu E8.3, którego kolejne meldunki uzupełniają ten sam wpis. Koordynator nadal używa O2-024; wykonawca motywacji O2-025. Harmonogramy pozostają PAUSED.
