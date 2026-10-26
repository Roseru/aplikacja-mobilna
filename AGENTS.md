# Instrukcje dla agentów pracujących w repozytorium

## Aktualne przejęcie O1 przez O2 — 26.10.2026

- Na jawne polecenie właściciela Agent 2 przejmuje bieżący etap MRE0.8.40
  i dalszy backlog Androida opisany w
  [przekazaniu O1→O2](docs/PRZEKAZANIE_O1_DO_O2_2026_10_26.md).
  Ten nowszy przydział zastępuje wcześniejsze rezerwacje O1 w zakresie
  plików wymienionych w tym przekazaniu; rezerwacje innych wykonawców
  i zamrożona dostawa Room23 pozostają osobnymi zakresami.
- O2 tworzy własną gałąź `codex/android-o2-mre-2026` z przypiętego commita
  przekazania i nadal podpisuje `agent 2: ...`. O1 po przekazaniu nie edytuje
  równolegle tych źródeł. ACK pina/przejęcie/zwrot utrwalamy w jedynym
  dzienniku i uzgodnionym kanale, bez nowej tablicy komunikacji.
- Kod MRE przy przekazaniu nie przeszedł jeszcze builda/testów. Push służy
  przekazaniu niedokończonych źródeł na polecenie właściciela; nie jest
  wydaniem lub odbiorem funkcji. O2 domyka cały etap, sprawdza go i dopiero
  wtedy tworzy jeden duży PR według aktualnego workflow.

- Przed zmianami zapoznaj się z `WYMAGANIA_PROJEKTOWE.md`.
- Folder `Random Data/` przechowuje dane źródłowe, z których powstanie baza danych całej aplikacji. To materiały projektowe, nie tymczasowe pliki ani losowe dane testowe. Nie usuwaj ich w ramach porządkowania repozytorium.
- Organizuj kolejne zbiory w osobnych podfolderach. Zachowuj źródła, daty, wersje, jednostki oraz informacje o brakach i niepewnych dopasowaniach.
- Przy projektowaniu bazy i importu korzystaj z tych materiałów, ale weryfikuj ich ograniczenia. Brak danych nie oznacza zera; alternatywnych wariantów produktu nie należy sumować.
- `Random Data/MRE/` zawiera zestaw menu amerykańskich MRE 2026 i wartości odżywcze. Zacznij od jego `README.md`; dane do przetwarzania są w `mre_2026.json`.


## Wspólny sposób pracy z GitHubem

- Repozytorium: `Roseru/aplikacja-mobilna`; docelowa gałąź integracyjna: `main`. Stosuj [docs/WORKFLOW.md](docs/WORKFLOW.md): własna gałąź → commit/push → PR → kontrole → merge → odbiór integracyjny. Na decyzję właściciela z 10 października 2026 review jest opcjonalne: wymagane jest 0 zatwierdzeń i nie obowiązuje akceptacja przez inną osobę niż autor ostatniego pusha. Można scalić własny PR po zaliczeniu wymaganych kontroli i rozwiązaniu istotnych uwag. Nie publikuj zadania bezpośrednio na main. Starsze instrukcje wymagające obowiązkowego zatwierdzenia ustępują tej decyzji; nie zwalnia ona z testów i przeglądu zmian.
- Przed pracą sprawdź `git status`, aktualną gałąź, remote i otwarte PR-y. Pobierz aktualny main oraz zmiany zespołu; przeczytaj nowe wpisy komunikacji. Zachowaj cudze i wcześniejsze niezatwierdzone zmiany. Pobranie gałęzi do odczytu nie oznacza jej scalenia.
- Dla nowych zadań stosuj `codex/<obszar>-<krótki-temat>`: małe litery i myślniki. Obszary: `android` dla Agenta 1, `backend` dla Agenta 2, `devops` dla Agenta 3, `docs` dla wydzielonej dokumentacji. Przykłady: `codex/android-analityka`, `codex/backend-synchronizacja`, `codex/devops-android-ci`, `codex/docs-komunikacja`. Jeden PR ma jeden spójny rezultat; rozdziel niezależne zmiany kodu i organizacji pracy.
- Istniejące gałęzie zachowują nazwy: Android O1 jest na `codex/android-offline-racje` ([PR #1](https://github.com/Roseru/aplikacja-mobilna/pull/1)), komunikacja O1 na `codex/komunikacja-agentow` ([PR #5](https://github.com/Roseru/aplikacja-mobilna/pull/5)), katalog O2 na `codex/e2-katalog-offline`. To wskazanie miejsca prac, nie potwierdzenie odczytu, CI lub akceptacji tych PR-ów.
- Kontynuuj istniejącą gałąź z otwartym PR, gdy kolejny commit domyka ten sam rezultat. Po scaleniu lub przy niezależnym zadaniu utwórz nową gałąź z aktualnego main. Nie zakładaj drugiego PR z tymi samymi zmianami i nie przenoś całej niescalonej gałęzi innego agenta, aby pobrać pojedynczy dokument lub artefakt. Zależność od niescalonego commita opisz jawnie.
- Jeśli kolejny wydzielony etap wymaga kodu z własnego niescalonego PR, dopuszczalna jest gałąź zależna od jego konkretnego commita i PR skierowany na tę wcześniejszą gałąź. Podaj zależność i kolejność odbioru; diff pokazuje wyłącznie nowy etap. Przykład O1: `codex/android-analityka` ([PR #6](https://github.com/Roseru/aplikacja-mobilna/pull/6)) zależy od `20f474e` / PR #1 i porównuje się z `codex/android-offline-racje`. Najpierw scalamy wcześniejszy PR po recenzji, następnie zmieniamy bazę kolejnego na aktualny main i sprawdzamy integrację. Nie scalaj zależnego PR do gałęzi oczekującej ani nie przepisuj opublikowanej historii.
- Przed dołączeniem nowego main sprawdź czystość checkoutu. Stosuj zwykły merge aktualnego `origin/main`, zachowując wpisy i kod wszystkich autorów. Nie przepisuj wspólnej opublikowanej historii, nie używaj force-push do rozwiązania konfliktów i nie nadpisuj cudzych plików z innego katalogu roboczego.
- Commity oznaczaj `agent N: <konkretny wynik>`, np. `agent 1: dodaj importer katalogu E2`. Autor ma odpowiadać ustalonemu lokalnie numerowi; konfigurację autora ustaw dla swojego commita/checkoutu, bez zmieniania globalnej tożsamości innych osób. Dla zmiany organizacji dopisz w opisie commita, po co ją wprowadzasz.
- Publikuj po ważnym, zweryfikowanym kroku. Przed commitem przejrzyj diff, uruchom `git diff --check` i kontrole właściwe dla zmiany. PR opisuje końcowy problem/wynik, migracje i zgodność, faktycznie wykonane testy, ograniczenia oraz potrzebne działania O1/O2/O3. Aktualizuj opis PR, gdy zmienia się jego końcowy zakres. Sam push ani test lokalny nie potwierdza zielonego zdalnego CI.
- Do GitHuba trafiają źródła i potrzebna dokumentacja. Nie publikuj sekretów, tokenów, plików tożsamości, lokalnych ścieżek SDK, buildów/cache ani prywatnego dziennika. APK dostarczaj jako uzgodniony artefakt z wersją, commitem i SHA-256, zgodnie z zasadami O3.
- Przed końcowym pushem pobierz nowe wpisy komunikacji; po publikacji dopisz w `docs/KOMUNIKACJA_AGENTOW.md` swój wynik, branch, commit/PR, testy i następny krok. W odpowiedzi użytkownikowi podaj aktualną gałąź i link do PR oraz rozróżnij stan lokalny, wypchnięty, w recenzji i scalony.

## Komunikacja między agentami

- Decyzją właściciela z 24 października 2026 r. bieżące pytania, blokady i przekazania prowadzimy w [prywatnym livechacie zespołu](https://calorie-coord-o3-20261024.roseru.chatgpt.site). Przed pracą odczytaj nowe wiadomości oraz aktualny [dziennik](docs/KOMUNIKACJA_AGENTOW.md). Ten dziennik pozostaje jedynym wersjonowanym zapisem trwałych decyzji i odbiorów; po zadaniu dopisz w nim wynik według istniejącego schematu. Nie twórz drugiej tablicy wyników.
- Agent korzysta z narzędzi czatu: `read_messages(after_id)` do odczytu od ostatniego otrzymanego ID, `send_message(body, client_message_id)` do odpowiedzi i `set_status` do deklaracji własnego stanu. Przy ponowieniu wysyłki zachowaj `client_message_id`. Odczytuj czat przy rozpoczęciu i przekazaniu pracy oraz przed końcowym pushem. Strona nie uruchamia ani nie budzi zatrzymanej sesji agenta.
- Autor wynika z zaproszonego konta. Przeglądarka podpisuje człowieka: A1 — Kamil, A2 — Benek, A3 — Johnny; narzędzia podpisują odpowiednio Agent 1, Agent 2, Agent 3. Nie wybieraj innej roli ani nie wysyłaj jako człowiek, aby zastąpić brakujące narzędzie agenta. Gdy brakuje dostępu lub narzędzi, zgłoś konkretny problem w dotychczasowym wątku GitHub i uzgodnij dostęp z właścicielem. Adresy kont, poświadczenia i przypisania serwerowe pozostają poza repozytorium.
- Podawaj krótko aktualny commit, wykonywany krok, konkretną blokadę i najbliższą dostawę. Obecność w czacie oznacza niedawny sygnał z klienta, a stan pracy jest deklaracją. Nie potwierdzaj odczytu lub pracy za innego agenta. Ustalenia zmieniające interfejsy, rezerwacje plików albo kryteria odbioru utrwal w dzienniku i właściwym PR; sam wpis na czacie nie jest dowodem testu lub scalenia.

## Przydział Androida O1/O2 — historia i aktualny podział

- Na jawne zlecenie właściciela z 23 października 2026 Agent 2 otrzymał trzy duże etapy Androida: A — pełna kolejka sześciu domen, B — import gościa/legacy i uzgadnianie, C — WorkManager i zarządzanie archiwami. A/B/C zostały wykonane i scalone do mainb245077 przez PR148/156/157. Agent 1 nadal prowadzi osobny etap E4/integracji z sesją; ukończenie A/B/C nie oznacza pełnego v1 lub live E4. Szczegóły, baza i kryteria odbioru: [pakiet prac O2](docs/ANDROID_O2_PAKIET_PRAC.md), [manifest plików](docs/ANDROID_O2_PLIKI.json).
- O2 używa `codex/android-o2-domeny-sync`, następnie zależnych gałęzi B/C z pakietu, i nadal podpisuje commity `agent 2: ...`. Jest to jawny wyjątek od wcześniejszego przypisania obszaru Android wyłącznie O1. Każdy korzysta z własnego checkoutu.
- W historycznym przydziale O1 edytował SessionController, BootstrapGateway, obserwatory/bariery E4, liveReplay, SessionSecurityTest i diagnostykę MealPhotoScreenTest; O2 implementuje dane, migracje, własne ekrany i WorkManager w zakresie pakietu. Potrzebną zmianę w zarezerwowanym pliku zgłasza z konkretnym punktem integracji w jedynym dzienniku. Nie nadpisuje drugiego checkoutu.
- Aktualny uzgodniony zakres po A/B/C: O1 prowadzi katalog, jedyny device-wide provider polityki sieci, API/AppAuth oraz addytywne MainActivity/CalorieApplication/ui/App/Settings. O2 prowadzi konsument tego samego gate w SyncWork/SyncCoordinator/SyncWorkPresentation, konieczne testy i własny opis. Bez drugiej preferencji lub równoległej edycji zarezerwowanych plików. Przypięty kontrakt i warunki przekazania są w jedynym dzienniku oraz [zakresie O1/O2](https://github.com/Roseru/aplikacja-mobilna/blob/065ebdd38bf8c29e78ae4005b7dc623086a71fa3/android/AKTUALIZACJA_KATALOGU.md).
- Najnowsza decyzja właściciela: najpierw duży spójny etap, potem właściwe testy i poprawki; PR dopiero po dużym ukończonym rezultacie. Nie tworzymy małych PR dla samych checkpointów lub statusów. Wymagane kontrole końcowe i GitHub CI pozostają obowiązujące.
- Ten pakiet jest instrukcją zadania. Bieżące odpowiedzi i postępy przekazujemy na livechacie, a trwałe decyzje i wyniki utrwalamy w `docs/KOMUNIKACJA_AGENTOW.md` według zasad powyżej.

## Ograniczona delegacja dwóch portów O1 do O2 — 24.10.2026

- Końcowe przekazanie25.10: O2 zwrócił rezerwacje źródłem325446b0b762f1088822d296455d522fbe8fe10d, gałąź odbioru11fac87ab9c3e01b793671ff5fdf1f0599854f29. O1 przyjął pin oraz helper NetworkOperationCancellation i lifecycle konkretnego PolicyConnection w komentarzu6398434885. Rezerwacje są zakończone; poniższe zakazy równoległej edycji opisują okres delegacji. O1 integruje zwykłym merge na rodzicu Room23, zachowując community/session i migracje. DI ma jedną networkPolicy, savedEvidence=sessions i tę samą admission co driver. Room24/25 i lokalny dalszy opt-in E9 pozostają osobno. Wspólny odbiór i4skonfigurowane APK nadal wymagane; wynik komponentu O2 ich nie zastępuje.

- Rozszerzenie25.10.2026: [prośba O2 6390318696](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6390318696) i [potwierdzenie O1 6390371437](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6390371437) dodają wyłącznie źródło sygnału watchdoga PolicyConnection w core/network/PolicyConnectionFactory.kt. O2 przełącza je na tę samą obserwowalną generację/wydanie NetworkAccessGate i oddaje regresję blokującego połączenia; requireCurrent, disconnect/finally, TLS/hostname i pozostałe zachowania pozostają. Do finalnego pina O2 O1 nie edytuje tego pliku równolegle; dochodzi on do sześciu dotychczasowych rezerwacji. Nie rozszerza to delegacji na AppAuth/root/provider/DI lub migracje.
- O1 jawnie przekazał O2 wyłącznie addytywny local-only drainer w SessionController/SyncExecution oraz obserwowalny znacznik wystawienia/generacji w core/network/NetworkAccessGate.kt, wraz z koniecznymi osobnymi testami. Dokładny zakres i wejścia: [delegacja6386626395](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6386626395).
- O2 kontynuuje codex/android-o2-polityka-runtime od be6c42303b5af5c6e62cafb804b38b558a5ddb09, na bazie4f6bb841818daa5b0823132a2120106dd97c3c61. Oddaje finalny spójny commit portów i konsumenta, podpisy DI, wyniki obu ABA i rzeczywistego lokalnego adaptera. Applied lokalnych dowodów nie kończy PULL lub całego cyklu.
- Od przekazania do zwrotu rezerwacji O1 nie edytuje SessionController.kt, SyncExecution.kt ani NetworkAccessGate.kt. O1 ma już zapisaną i zamrożoną odrębną deltę communitySession/withCommunitySession/deferCommunity przy apiSession w swoim dziecku; O2 nie nadpisuje pliku z innego checkoutu. Po odbiorze O1 wykona zwykły merge obu fragmentów. Trwający build O1 jest odczytem źródeł, nie równoległą edycją.
- Pozostałe provider/factory/AppAuth/root, moduł community oraz jedyna migracja22→23 pozostają O1. Zmiana poza wydzielonymi portami wymaga konkretnego zgłoszenia. Bez drugiego gate/preferencji, migracji23 O2, przejęcia SessionSecurityTest/drivera lub małego PR statusowego.
- Dodatkowy punkt integracji drivera: [6387175572](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6387175572). O1 prowadzi nowy SyncRuntimeAdmission.kt, wariantowe fabryki, ReplayRuntimeIsolation i driver/odciski; O2 w swoim SyncWork dodaje domyślny parametr admission oraz pełną granicę runtime zgodną z tym interfejsem. O1 nie edytuje SyncWork. Po finalnej dostawie O2 to O1 podłącza jedną instancję w Application; samo attach bez ochrony wszystkich wejść/schedulera nie spełnia kryteriów odbioru. Do integracji driver21–23 odmawia przygotowania próby. Szczegóły i fazy są w android/DRIVER_REPLAY_E4.md.
- O1 prowadzi osobny kalkulator mifflin_pal_v1/GoalPayload.estimate na codex/android-kalkulator-zapotrzebowania, baza72d74d5. Rezerwacja migracji23→24 (nullable goals.estimateJson) i zakres danych/UI: [6387552610](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6387552610), [opis](android/KALKULATOR_ZAPOTRZEBOWANIA.md). O2 kontynuuje dotychczasowy be6/4f+kontraktbe21, bez przenoszenia całej gałęzi kalkulatora lub konkurencyjnej migracji24. O1 zachowuje wszystkie sześć rezerwacji O2; opublikowany driver23/72d74d5 pozostaje niezmieniony dla bieżącego składania dostawy E4.
- Aktualizacja25.10: historyczny driver72d74d5 ma kwalifikowaną poprawkę expiry/rollback526deb4, końcowy rodzicccb614e i normalny merge do kalkulatora8140ba1. Rodzic nadal Room23, kalkulator Room24; nie podmienia to dawnej dostawy0.8.29/Room20. Obowiązuje siedem rezerwacji O2 wraz z wyłącznie sygnałem watchdoga PolicyConnectionFactory opisanym wyżej. Końcowy odbiór połączonego runtime nadal po finalnym pinie O2; osobnych wyników nie przedstawiamy jako pełnego liveE4.
- Następny duży etap O1: codex/android-korekty-energii z dokładnego17c388edfd915355d398d7b33deb65a1f7a0d5d3. O1 prowadzi moduł energy, jego UI/REST/cache/niezmienne próby mutacji, zgodnie z docs/e9/INTEGRACJA_O1.md; rezerwuje addytywną migrację24→25 dla lokalnego stanu tego modułu. To rezerwacja, nie potwierdzenie wykonania migracji lub pełnego E9. Siedem plików O2 nadal zamrożone; bez konkurencyjnej migracji O2, drugiej sesji/gate lub przenoszenia całej nowej gałęzi do jego be6/4f. Integracja energy_estimates_v1 i końcowy odbiór pozostają jawną częścią dalszego etapu, bez cichej zmiany zakresu istniejącego sync-v1.
- Lokalna aktualizacja etapu E9: REST/cache/UI i migracja24→25,0.8.34/code45/Room25, mają build/lint/4nowe JVM/6zmienionych odcisków/6native PASS w granicach opisanych w android/KOREKTY_ZAPOTRZEBOWANIA.md/O1-129. Granica API/sesji native była syntetyczna. Pełne E9 nadal wymaga encji/capability energy_estimates_v1, migracji signed scope i rzeczywistego odbioru po finalnej dostawie O2; nie uznajemy REST za pełne E9. Przed uruchomieniem definicji EnergyPullResponse O1 poprawi jej wzorzec UnicodeText; obecne ścieżki REST nie używają tej definicji. Siedem rezerwacji O2 nadal obowiązuje.

## Nowa wąska delegacja ETag klienta E9 — 25.10.2026

- Aktualizacja: O2 zwrócił rezerwację pinem4cc2d4db43b5022244772e43313d63e45a7c9b9c, jedyny rodzic e16f317, dokładnie4pliki. Przekazanie6400515465 i ACK O1 6401008024. Podane przez O2:13native PASS i niezależny przegląd9,5/10; to wynik komponentu, bez nowego live/CI O1. O1 włączy pin zwykłym merge po domknięciu aktualnego dużego merge/odbioru synchronizacji. Poniższa rezerwacja opisuje zakończony okres delegacji.

- O1 przekazał O2 poprawkę P3 z przeglądu6398655282 w komentarzu6398843748. Baza to dokładny e16f317f75379ced9ac1d8e2241fdffaab9316f3 / source50eb470; osobna gałąź O2 od tego pina, bez przenoszenia Room25 do carrier runtime Room22 i bez małego PR statusowego. Potwierdzenie przyjęcia przez O2 jest jeszcze oczekiwane.
- Do finalnego zwrotu O1 nie edytuje EnergyGateway.kt, EnergyRepository.kt ani androidTest/EnergyTransportTest.kt w module energy; O2 może dodać wyłącznie nowy androidTest/EnergyConsentReceiptTest.kt. Zakres: przeniesienie rzeczywistego ETag, ścisłe cytowane ETag=revision po PUT zgód i zachowanie unknown/tego samego UUID/body/fingerprint przy brakującym lub błędnym nagłówku. Bez zmiany migracji, UI, root/session/sync, wersji lub automatycznej afirmacji.
- EnergySchema, EnergySnapshotProtocol i jego test, dalszy opt-in/scope/projekcja pozostają O1. Istniejące EnergyFixture/JSON tylko do odczytu. Najpierw cała poprawka, potem mały odbiór jej transportu i trwałego retry; bez ponawiania zamkniętych54runtime lub całego REST. Końcowy commit/pin/wyniki wracają do O1 do zwykłego merge.
- To osobna rezerwacja3istniejących plików i1nowego testu. Wcześniejsze7rezerwacji runtime zakończyło się przyjęciem325446b/11fac87 w6398434885 i nie pozostaje organizacyjną blokadą integracji Room23.

## Kontynuacja pełnej synchronizacji E9 — O1

- O1 kontynuuje codex/android-korekty-energii i rezerwuje migrację25→26: utrwalenie zakresu protokołu w snapshotach/próbach ordinary/recovery, fazy draining/snapshot/active oraz niezależna niezmienna oś canonical_energy_versions. To lokalny WIP; brak nowego odbioru, eksportu26 lub uruchomionego opt-in. Dotychczasowy kwalifikowany Room23 pozostaje osobnym czystym checkoutem do dostawy4APK.
- O2 nadal ma wąską rezerwację ETag powyżej. O1 nie edytuje tych3plików. Nowa migracja nie przepisuje starego body/hash/UUID/rowid ani nie uznaje parsera lub nowego nagłówka za pełną synchronizację. Aktywacja nowego scope wymaga atomowego pełnego odczytu7domen oraz zachowania starej kolejki i prób.

- Kontynuacja O1: po oddaniu runtime podłączono pełny/przyrostowy odczyt, stały scope transportu i freeze/restore ordinary/recovery, atomową projekcję oraz historię offline. Room26 dodatkowo utrwala readMode/baseRunId/startingCheckpoint/forceFull. Bieżący odbiór lokalny jest w toku; żadne nowe APK lub PULL nie mają jeszcze potwierdzenia O3. Wąska rezerwacja ETag powyżej już zwrócona, lecz jej pin jeszcze nie jest scalony z tym WIP.

- Odbiór lokalnego Room26 po złożeniu przepływu: oba warianty kompilują się,
  lint ma 0 Error/0 Fatal, osiem unikalnych JVM i sześć unikalnych native
  mają wyniki pozytywne w rozdzielonych uruchomieniach. Ostatni ponowiony
  zakres zawierał wyłącznie dwa poprawione fixture; produkcyjny APK był
  identyczny. Wyeksportowano 26/54 encje, identity17cc6b884e81274ad78ed315d3c69d06.
  To wyniki syntetycznych granic API/sesji, bez live TLS/PKCE/Gemini.
  Pin ETag4cc2d4d jest gotowy do zwykłego merge; Room23/2319357 nadal
  pozostaje osobnym czystym źródłem uzgodnionej dostawy czterech APK.

## O1 po scaleniu PR175 — 25.10.2026

- PR175/08884f7 jest scalony zwykłym merge143bf0a do main po ośmiu zielonych
  kontrolach ProjectCI40233320875. ETag4cc2d4d O2 i runtime są zintegrowane;
  wcześniejsze opisy WIP i niezwróconych rezerwacji pozostają historią.
- O1 kontynuuje codex/android-wznowienie-kopii od main143bf0a: nowe
  SnapshotMaintenanceStore.kt, sync/SnapshotMaintenanceViewModel.kt,
  ui/SnapshotMaintenancePanel.kt, ich test SQLite/UI oraz addytywne
  MainActivity/ui App/Settings. W SnapshotArchiveStore wyodrębnia wspólny graf
  dowodów; domyślna ochrona wszystkich pending w reserve pozostaje. Nie
  edytujemy równolegle tych plików do zwrotu zakresu w jedynym dzienniku.
- To lokalna, jawna decyzja użytkownika bez transportu lub nowego schematu.
  Nie zmienia SyncWork O2, gate lub recovery ACK. Room23/2319357 jest nadal
  osobnym czystym źródłem dostawy4APK po aktualnej konfiguracji/oknie O3;
  scalenie175 nie potwierdza live E9 ani pełnego wydania1.0.
- Kontynuacja tego samego większego etapu O1: AccountSyncOverviewStore.kt,
  sync/AccountSyncOverviewViewModel.kt, ui/AccountSyncOverviewScreen.kt,
  androidTest/AccountSyncOverviewFlowTest.kt oraz addytywne SessionScreen/
  MainActivity/ui App. O1 nie zmienia SyncWork/SyncCoordinator ani prezentacji
  O2; nowe centrum tylko odczytuje istniejące fakty i wywołuje już podłączony
  driver po jawnym działaniu użytkownika. Bez nowego schematu/gate/preferencji.

- Aktualizacja integracji ETag: cztery pliki pina4cc2d4d włączone zwykłym
  merge do Room26, bez konfliktów. Odbiór złożenia: oba warianty i APK testowe
  PASS, lint0Error/0Fatal, tylko dwa wybrane przypadki zgód2PASS/0FAIL/0SKIP.
  Wcześniejsze osiem JVM, sześć E9 native i13komponentu O2 mają osobne
  zakresy; nie uruchamiano ich ponownie. Brak nowego live lub4APK O3.
