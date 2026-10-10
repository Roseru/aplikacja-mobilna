# Poprawki po recenzji Androida

## PR #1 — kompletność energii, 10 października 2026

Odczytano [review O2](https://github.com/Roseru/aplikacja-mobilna/pull/1#pullrequestreview-5479214773) do 20f474e. Poprawka jest na właściwej gałęzi codex/android-offline-racje, w Room 4, bez przenoszenia całego zależnego etapu analityki.

Dziennik, repozytorium i przycisk potwierdzenia korzystają ze wspólnej reguły completeDiary: deklaracja, co najmniej jeden składnik, dodatnia suma oraz znana energia wszystkich pozycji. Znana dolna granica nie wystarcza. Dodanie pozycji bez kcal unieważnia efektywną kompletność; deklaracja pozostaje zapisana i można ją wyłączyć.

Pełny assembleDebug/testDebugUnitTest/lintDebug/connectedValidationAndroidTest PASS: 40 JVM i 28/28 urządzenia API 35, zero błędów/pominięć. Lint 0 błędów, 26 ostrzeżeń, 1 informacja. Nowy test JVM obejmuje wszystkie pięć wektorów dnia E0. Dwie próby urządzenia potwierdzają zmianę efektywnego stanu, odrzucenie ponownej deklaracji bez dopisania outbox, rzeczywiste ponowne otwarcie bazy oraz natychmiastową aktualizację UI i odtworzenie aktywności. Cały wcześniejszy zestaw, migracje i SQLITE_FULL też zaliczony w tym jednym przebiegu.

Nie zmieniono schematu/wersji aplikacji ani danych użytkownika. Zwykły zainstalowany APK pozostaje 0.7; testy używają oddzielnej instalacji validation. Wynik nie zamyka formalnej recenzji; wymagany ponowny odbiór O2 i mobilne CI O3. Odbiór zależnych PR pozostaje osobny, bez force-push lub samodzielnego merge.
## PR #6 — bieżący dzień i lokalna północ, 10 października 2026

Odczytano [review O2](https://github.com/Roseru/aplikacja-mobilna/pull/6#pullrequestreview-5479214886). Do gałęzi codex/android-analityka włączono poprawkę #1 / 6ba2054 przez zwykły merge. Wspólna reguła kompletności znajduje się teraz w DiaryCompleteness.kt, niezależnie od analityki.

Bieżący dzień ma wynik wstępny i oddzielną preliminaryInGoal. Nie wchodzi do dni w celu, dni ocenianych, kompletności okresu ani średnich zamkniętych dni. Kwoty spożycia i rzeczywiste pomiary pozostają widoczne. LocalDayClock jest wstrzykiwany do obliczeń/odczytu/ViewModel; kalendarzowa północ korzysta z bieżącej strefy urządzenia, a nie stałych 24 godzin. Odczyt emituje nowy wynik bez zapisu do kolejki. Domyślne okno podąża za dzisiaj, jawnie wybrane historyczne okno pozostaje stałe i odtwarza się z SavedStateHandle. Po wznowieniu subskrypcji data jest sprawdzana ponownie; ręczna zmiana czasu/strefy jest wykrywana także przy aktywnym ekranie, najwyżej po minucie. UI oznacza wynik wstępny i wyjaśnia statystyki zamkniętych dni; etykieta i wartość statystyki mają wspólną grupę dostępności.

Końcowy pełny build/test/lint/device PASS: 57 JVM i 36/36 urządzenia API 35, zero błędów/pominięć; lint 0 błędów / 26 ostrzeżeń / 1 informacja. Nowe testy obejmują sterowalny czas/strefę, granicę dnia, DST 23/25 godzin, ponowne otwarcie bazy, odtworzenie ViewModel i historycznego okna, UI przed/po północy oraz niezmieniony outbox. Wszystkie wcześniejsze przypadki też zaliczone w jednym końcowym przebiegu.

Pierwsze próby wykryły błędną sygnaturę JUnit i zbyt częsty testowy zegar powodujący brak bezczynności UI, potem brak wspólnej semantyki etykiety/liczby. Poprawiono testy i dostępność; ponowiono cały zestaw. W pierwszej próbie był także timeout starego testu dodawania posiłku; dwa kolejne pełne przebiegi zaliczyły ten przypadek. Powyższy wynik jest ostatnim pełnym przebiegiem 36/36, nie sumą selektywnych powtórzeń.

Wersja nadal 0.5 / Room 4, bez migracji. Wymagany ponowny review O2 i CI Androida O3; brak deklaracji APPROVE. Po odbiorze/scaleniu #1 należy retargetować #6 na main i wykonać odbiór integracyjny; nie wykonano samodzielnego merge do main.
## PR #7 — ponowny odbiór zależności

Połączono poprawki #1 i #6 z izolacją kont, zachowując odczyty ViewModel według właściciela. Cały build/test/lint/device PASS: 57 JVM i 44/44 urządzenia API 35, zero błędów/pominięć; lint 0 błędów / 26 ostrzeżeń / 1 informacja. Wynik obejmuje także osiem prób właścicieli i migrację rzeczywistego Room 4→5. Room nadal 5 / Android 0.6; nie włączono bootstrapu ani logowania. To odbiór autora po zmianie zależności, przed wymaganym review i przyszłym retargetowaniem na main.
