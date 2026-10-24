# Kalkulator zapotrzebowania — Android0.8.33

24.10.2026, Agent1. Gałąź `codex/android-kalkulator-zapotrzebowania`, jawna
zależność od `72d74d58b3db8dd43be77eace0c107e50d83525a`. Zakres wymagań:
WF01/02 i11.5, zgodny z istniejącym `GoalPayload.estimate`. Nie zmieniamy API,
obrazu backendu, providerów AI ani metody. [Rezerwacja6387552610](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6387552610).

## Działanie

Ustawienia otwierają kalkulator dostępny dla gościa i konta bez sieci. Użytkownik
wpisuje wiek18–120, dodatni wzrost do300cm i masę do1000kg, do6miejsc dziesiętnych.
Sam wybiera wariant `plus_5`/`minus_161` i klasę używaną w oszacowaniu.
Formularz może podpowiedzieć ostatnie własne dane, zachowując ich cyfry;
nie zaokrągla źródłowego pomiaru do prezentacyjnej jednej cyfry.
Potwierdzenie zakresu v1 jest domyślnie wyłączone i nie jest odtwarzane
po ponownym utworzeniu ekranu. Nie zbieramy daty urodzenia lub diagnozy.

`MaintenanceEstimate` wylicza dokładnie metodę z11.5 w BigDecimal:
R=10×kg+6.25×cm−5×wiek+s, s=5 albo−161; PAL1.5/1.8/2.2 daje E=R×PAL.
Nie zaokrągla audytu do skali wejściowej6. Do pokazania liczby używa najwyżej
dwóch miejsc; początkowa propozycja celu jest zaokrąglona HALF_UP do1kcal.
Nie nadaje samoczynnie deficytu lub nadwyżki. Przykład: R1780, Linia/PAL1.8
daje E3204, a użytkownik może świadomie zapisać cel2500.

Obliczenie i podgląd nie zapisują celu. W drugim kroku użytkownik wybiera
cel kcal, zamiar i opcjonalne B/T/W, a następnie zatwierdza podsumowanie.
Wersja od dzisiaj zapisuje E i cel jako osobne wartości, z niezmiennym
audytowalnym wejściem, metodą, PAL i czasem. Klasa/zamiar wybrane w kalkulatorze
opisują tę decyzję; istniejący profil i jego wcześniejsze ustawienia nie są
automatycznie zmieniane. Ręczny cel nadal jest dostępny bez kalkulatora.

Zapis jest jedną transakcją pod captured owner lease: nowy Goal, audyt i
outbox. Wcześniejsze wersje, wcześniejsze kcal/B/T/W, operacje attempted,
UUID/body/hash i inne konta nie są przepisywane. Odrzucony zapis nie tworzy
połowy decyzji. E nie jest wyliczane z arbitralnie ustawionego celu kcal.

## Pamięć, import i protokół

Room23→24 dodaje tylko nullable `goals.estimateJson TEXT DEFAULT NULL`.
Istniejące pola/rowid i wszystkie pozostałe tabele pozostają zachowane.
Nie wykonuje historycznego backfillu E. Dotychczasowe update/delete guardy
chronią nową kolumnę, a osobny trigger blokuje również REPLACE samego audytu.

Nowy kanoniczny Goal zawiera zwalidowany estimate oraz świadomy goal_type
i activity_class tej decyzji. Legacy outbox zachowuje ten sam audyt/intent.
Import kopiuje istniejące, spójne oszacowanie; brak pozostaje null, a konflikt
lub niespójne wyliczenie wymaga jawnej decyzji. Nie nadpisuje oryginalnych
requestów. Dodanie pustej kolumny nie zmienia fingerprintu już przechwyconego
legacy źródła: usuwamy wyłącznie nowy NULL i jego wpis typu z wyciągu.
Niepusty estimate zawsze pozostaje częścią tożsamości źródła.

Nowa projekcja serwerowa/importu zachowuje estimate. Stary niezmienny Goal
może mieć dokładny audyt już w canonical sidecar; odczyt dla UI bierze go
wyłącznie z własnego bieżącego kontekstu. Nie aktualizuje dawnego Goal i
nie wyprowadza E z kalorii. Ponowny PULL tego samego payloadu uwzględnia
brak nowej kolumny w dawnym wierszu, zachowując sprawdzenia pozostałych pól
i dokładny kanoniczny kontekst/body.

Starsze rejestracje migracji otrzymały tylko końcowy krok i bieżący numer24.
Historyczne porównania nadal sprawdzają wszystkie dawne kolumny i rowid;
nowy helper najpierw wymaga NULL audytu starej fixture, a potem porównuje
dawny zakres. Nie ignoruje niepustej wartości lub innych nowych pól.

## Granice i kwalifikacja

Robocza wersja0.8.33/code44/validation1044, Room24. Driver24 ma nadal39tabel:
nowa kolumna istniejących goals jest hashowana ściśle. Obsługa wymaga tej
samej podłączonej izolacji runtime; bez attach odmawia przygotowania.
Nieznany25 pozostaje odrzucony. Źródło drivera23/22bb639/remote72d74d5
nie jest podmieniane i nie staje się zależne od tego etapu.

O2 nadal posiada SyncWork/SyncCoordinator/SyncWorkPresentation oraz trzy
delegowane porty. Żaden z tych sześciu plików nie jest edytowany. Nie ma
Gemini/admission AI, automatycznych korekt E9, nowego consent/automatu,
energy_estimates_v1 sync lub nowej akceptacji pełnego E9. To działający
przepływ oszacowania początkowego, potrzebny do jego dalszej implementacji.

Zgodnie z decyzją właściciela cały przepływ powstał przed uruchomieniem
kontroli. Pierwszy build validation/opt-in testAPK, standard Kotlin i lint
zakończył się PASS; lint ma0error/fatal,8warning/2info. Wykonano wyłącznie
4celowane JVM kalkulatora i6zmienionych testów zakresu drivera:10PASS,
bez pominięć. Pierwsze wykonanie urządzenia:2PASS/2FAIL. Zaliczone były
account/canonical/owner oraz rzeczywista migracja23→24 ze sprawdzeniem
wszystkich starych kolumn, rowid i requestów.

Poprawiono odczyt zagnieżdżonego audytu w legacy: dotychczasowy parser
cytuje liczby dla dokładnej konwersji starych pól, co zamieniało wiek
w string. Dla audytu przechodzimy ten sam ścisły preflight, po czym
zachowujemy jego oryginalne typy JSON. Dwie dodatkowe regresje JVM
(poprawny audyt oraz nieprawidłowe typy/konflikt) przeszły. Build obu APK,
standard Kotlin i lint po tej poprawce również PASS, bez zmiany schematów.

Powtórzono wyłącznie dwa niezaliczone przypadki: zapis/restart/import
gościa PASS, UI FAIL na oczekiwaniu tekstu. Ekran pokazał poprawne
3204 kcal / dzień; fixture oczekiwała całego tekstu równego3204.
Poprawka fixture sprawdza dokładny pełny tekst, bez zmiany aplikacji.
Budowa wyłącznie testAPK zakończyła się PASS248,281s,5zadań wykonanych,
41up-to-date; APK aplikacji pozostał byte-identical. Ponowiono tylko UI:
**1PASS/0FAIL/0SKIP**,20,926s instrumentacji. Trzy zaliczone przypadki Room
nie były ponawiane. Cztery różne scenariusze urządzenia są więc zaliczone
w jawnie opisanych zakresach; nie podajemy ich jako jednego przebiegu4/4.

Wszystkie trzy wykonane zakresy urządzenia zachowały hashe oryginalnych APK i trzech
plików bazy. Próby odbywały się offline w osobnym maintenancecheck,
bez live API/E4, nowego android_acceptance lub gotowej dostawy dla O3.
Logi i binaria pozostają poza repozytorium; dokładne receipty są
w jedynym [dzienniku](../docs/KOMUNIKACJA_AGENTOW.md).
