# Rozwiązywanie konfliktów posiłków i pomiarów wagi — Agent 1

Wersja implementacji: **0.8.26 / code 37 / Room 16**. Zakres: WF-06, UC-12 i KO-06 dla zwykłej synchronizacji `Meal` i `Weight` w bieżącej epoce konta.

Na ekranie **Konto i logowanie → Zmiany do uzgodnienia** użytkownik otwiera listę konfliktów zapisanych po odpowiedzi serwera. Lista jest stronicowana po 20 wpisów; można przechodzić dalej również wtedy, gdy wcześniejsza odmowa wymaga osobnej poprawy danych.

Porównanie pokazuje **ostatnią lokalną wersję** i dostępną wersję serwera. Lokalne zmiany wykonane po wysłaniu pierwotnej operacji są uwzględnione. Dla posiłków widoczne są nazwa, data, godzina, składniki, ilości, kcal i B/T/W; brak wartości odżywczej pozostaje brakiem danych. Pomiar pokazuje datę, godzinę i dokładną masę. Usunięcie ma oddzielny stan.

## Wybór użytkownika

- **Zachowaj wersję lokalną**: zapisuje nową operację z nowym UUID i rewizją porównanej wersji serwera. Późniejsze wysłanie pozostaje oddzielnym krokiem. Jeśli serwer zdąży ponownie zmienić wpis, kontrola rewizji ponownie wykryje konflikt.
- **Przyjmij wersję serwera**: aktualizuje lokalny wpis lub jego znacznik usunięcia. Nie tworzy fikcyjnego ACK dla odrzuconej operacji.
- **Odtwórz lokalną wersję** po usunięciu serwerowym: wymaga jawnego potwierdzenia, tworzy nowy UUID wpisu i nowe UUID składników posiłku. Pierwotny wpis pozostaje usunięty. Zastrzeżonego UUID nie używa się ponownie.

Wybór wymaga drugiego potwierdzenia. Decyzja, obie porównane wersje, ewentualny nowy wpis i zmiany kolejki zapisują się w jednej transakcji Room. Tabela `sync_conflict_decisions` zachowuje powiązanie z pierwotną operacją i niezmienną odpowiedzią partii. Nie ma jeszcze osobnego ekranu przeglądania archiwalnych decyzji.

## Trwałość i zgodność

Room 15→16 dodaje wyłącznie tabelę decyzji i jej indeksy. Nie przebudowuje tabel dziennika, nie zmienia historycznych wartości ani rowid. Wszystkie ścieżki migracji do bieżącego schematu obejmują nowy krok. Nie konwertuje to wcześniejszej kolejki `legacy` do protokołu API.

Niezmienna partia żądania i jej odpowiedź pozostają zapisane. Po świadomym rozstrzygnięciu stare operacje otrzymują stan `superseded`, a nowa operacja ma własną tożsamość. Podwójne zatwierdzenie nie tworzy kolejnego wpisu: decyzja jest unikalna dla pierwotnej operacji.

Podgląd jest związany z aktywnym właścicielem, generacją lokalnego wyboru konta, kontem serwerowym, epoką, stanem bootstrapu i pełnej kopii. Zmiana lokalnego wpisu, kolejki, kontekstu konta lub kopii po otwarciu porównania wymaga ponownego podglądu. Spóźniona decyzja nie nadpisuje nowej edycji. Zmiana konta usuwa podgląd z pamięci kontrolera.

## Brak danych serwera i granice etapu

Skrócona odpowiedź idempotencji z `details_retained=false` nie zawiera domyślnej rewizji ani wymyślonego payloadu. Użytkownik pobiera świeżą pełną kopię i ponownie otwiera porównanie. Można z niej skorzystać wyłącznie w tym samym kontekście konta i epoki oraz jeżeli początek kopii nie poprzedza odpowiedzi konfliktowej. Brak wcześniej znanego wpisu w takiej kopii oznacza usunięcie zgodnie z 11.3. Sama nieobecność nie dowodzi usunięcia nieznanego wpisu.

Automatyczny wybór zwycięzcy nie występuje. Odmowy wymagające poprawienia danych lub specjalnego odzyskiwania pozostają zachowane i opisane jako wymagające dalszego działania. Ten etap nie kończy pełnego pull do dziennika, uzgadniania po zmianie epoki, importu gościa/legacy, synchronizacji profilu/celów/kompletności ani WorkManagera. Nie uruchamia nowego testu live E4, Gemini, wdrożenia czy zmiany środowiska O3.

## Weryfikacja etapu

Implementację kontynuowano bez uruchamiania testów po każdej edycji. Na końcu etapu wykonano **35 wybranych JVM PASS**, build debug/validation/test APK i lint: **0 błędów, 4 ostrzeżenia, 1 informacja**. **41/41 native API35 offline PASS** obejmuje protokół zapisu, starsze migracje, pełną migrację 15→16, kolejkę posiłków/wagi oraz nowy interfejs.

Po przeglądzie poprawiono komunikat dla zgodnego lokalnego i serwerowego usunięcia, dodano scenariusz niewytwarzania operacji i oznaczenie widoczności `copy`. Przebudowano APK i wykonano **10/10 native PASS**: osiem przypadków Room, dwa UI. JVM nie powtarzano. Jedną nazwę metody w nowym teście poprawiono przed rozpoczęciem kompilacji testów; pierwotny manifest i informację o zmianie zachowano w lokalnych dowodach. Natywne wykonanie potwierdziło końcowy test. Nie zmieniano produkcji w trakcie tego builda.

Lokalne APK i końcowe testy pochodzą z **9a041bd5f86d1d937f96324798cf0809ceb9334f**. Następna drobna korekta dotyczy wyłącznie komunikatu błędu odświeżenia: jeżeli decyzja została już zatwierdzona, błąd późniejszego odczytu listy nie może sugerować jej odrzucenia. Pełny CI opublikowanego head jest osobnym wymaganym odbiorem, łącznie z kompilacją tej korekty. Nie utożsamiamy 41 i 10 przebiegów z 51 różnymi przypadkami ani z pełną regresją.

Migracja zachowuje wszystkie **28 dotychczasowych definicji tabel**, ich dane i rowid. Dodaje jedynie tabelę decyzji. Zwykły emulator użytkownika zachowywał podczas tych testów wcześniejszą aplikację 0.8.25; testowano wyłącznie osobny wariant validation na własnym emulatorze. Aktualizacja do najnowszego źródła i odbiór rzeczywistego APK/API pozostają oddzielnymi czynnościami.

Pierwszy pełny CI PR142 na5695 ukończył346native:345PASS, jeden timeout starego testu podglądu zdjęcia po odtworzeniu aktywności. Raport wskazał oczekiwanie na obraz w LazyColumn. Poprawka1b20926 zmienia wyłącznie oczekiwanie testu: odsłania podgląd podczas oczekiwania i dodatkowo sprawdza zachowanie wyboru bez ponownego kliknięcia. Końcowy rebuild oraz13/13native offline PASS obejmują zdjęcie, dostępność i wszystkie10testów konfliktów. Produkcja i Room16 bez zmian, lokalnych JVM nie powtarzano. Nowy pełny CI jest osobnym wymaganym odbiorem; nie zastępujemy nim ani lokalnym wynikiem wcześniejszego niepowodzenia.
