# Wysyłanie posiłków z ekranu konta — kandydat 0.8.23

Agent 1 / O1, 19 października 2026, `codex/android-wysylanie-kolejki`,
[PR129](https://github.com/Roseru/aplikacja-mobilna/pull/129). Kontynuacja
[transportu HTTP](WYSYLANIE_KOLEJKI.md) i [trwałego ACK](SYNCHRONIZACJA_PUSH.md).

## Przepływ użytkownika

Po zalogowaniu, połączeniu konta i pobraniu pełnej kopii serwera ekran konta
udostępnia „Wyślij oczekujące posiłki”. Panel pokazuje osobno gotowe operacje,
poprawki oczekujące na poprzednie potwierdzenie, konflikty/odrzucenia oraz
starsze wpisy i inne typy danych. Przycisk przekazuje uchwycony lease;
stary callback nie może uruchomić wysyłki po zmianie konta.

Zapisana partia dostaje przycisk „Ponów zapisaną partię”. Utrata odpowiedzi,
restart i anulowanie zachowują body oraz identyfikatory operacji. Pełny HTTP200
jest walidowany w całości. Dopiero atomowy ACK podnosi rewizję posiłku,
potwierdza kolejkę i uruchamia oczekującą poprawkę z rewizją poprzednika.
Nowsza porcja i identyfikatory składników pozostają zachowane.

Jedno uruchomienie wysyła do dziesięciu partii, po maksymalnie sto operacji
zgodnie z limitem bajtów. Dalsze wpisy pozostają widoczne do następnej próby.
Konflikt lub odrzucenie nie zastępują lokalnego posiłku. Po odebranym ACK
uruchamia się osobny pełny odczyt kopii serwera, z tym samym lease i kontekstem.
Błąd tego odczytu nie cofa ACK ani nie przywraca potwierdzonej operacji do wysyłki.

## Sesja i trwałość

Wysyłka ma jedną rezerwację dla konta i pełnego kontekstu. Pozostałe operacje
serwerowe czekają; jawne logowanie, wylogowanie i ręczne odnowienie sesji
unieważniają zadanie. Zmiana epoki/generacji/kontekstu lub A→B→A blokuje
zarówno fizyczną wysyłkę, jak i zastosowanie późnej odpowiedzi.

Wygasły dostęp może zostać odnowiony, a HTTP401 pozwala najwyżej na jedno
odnowienie łącznie w danym uruchomieniu. Przed kolejną wysyłką ponownie
sprawdzany jest bilet i kontekst. 429/503 utrwalają wspólny `apiRetryAt`;
restart ani ponowne logowanie nie skracają `Retry-After`. Termin jest zapisany
przy partii w Room przed osobnym zapisem wspólnego terminu w magazynie sesji;
wylogowanie albo awaria tego drugiego zapisu nie cofają terminu partii.
Przed fizyczną wysyłką Room sprawdza go ponownie. Nie ma automatycznej pętli retry po błędzie
sieci lub niepełnym ACK.

Przygotowanie partii, parsowanie odpowiedzi i sprawdzanie kontraktu odbywają
się poza blokadą sesji. Przed siecią transakcja sprawdza aktualność i oznacza
próbę. Zastosowanie przygotowanego ACK ma kontrolę biletu i wersji wszystkich
wierszy. Awaria zapisu wycofuje całą zmianę; częściowe HTTP lub zły późniejszy
wynik nie potwierdza nawet pierwszej operacji.

Normatywna odmowa epoki, generacji, checkpointu lub immutable żądania ustawia
trwałe `requiresRecovery` i wiąże odnowienie z ostatnim bootstrapem. Pierwotna
partia, operacje i dane pozostają zachowane. Po nowym bootstrapie można pobrać
kopię do uzgodnienia; sama kopia nie usuwa flagi recovery. `account_deleting`
ustawia trwałą blokadę dostępu. Odmowa i obie zmiany blokady są atomowe.

## Odbiór lokalny — PASS, instalacja zwykłej aplikacji osobno

Wersja kandydująca 0.8.23/code34/validation1034, Room14.
Migracja 13→14 dodaje wyłącznie `sync_push_batches.retryAtMillis`, z domyślnym
zerem dla wcześniejszych partii. Nie zmienia ich body, hashy ani operacji.
Końcowy build i testy JVM: **322 debug / 337 validation**, bez błędów,
pominięć i błędów lint. Końcowy zestaw urządzenia API35 offline:
**22/22 celowane i 320/320 pełne**, bez błędów lub pominięć. Sprawdzono
brak aktywnej sieci przed i po obu przebiegach. Testy wykonano wcześniej;
podczas późniejszej lekkiej pracy nie uruchamiano Gradle ani emulatora.

[Publiczny manifest](ODBIOR_0_8_23.json) podaje SHA256 trzech niezmiennych
APK oraz logów. Sprawdzono zgodność wszystkich **257 wejść źródłowych**
z zapisem sprzed końcowego buildu. Zmiany dokumentacji nie zmieniają tych wejść.
APK debug ma SHA256 `b4d71a91fc95f96cfe474e3b6f09c25e4f6bc13f55117d4bae755a7814257d99`.
Validation: code1034/applicationId `pl.roseru.kalorie.validation`.
Artefakty pozostają lokalne; nie wykonano dostawy wydania ani instalacji
0.8.23 na zwykłej aplikacji. Dotychczasowy dziennik 0.8.22/Room13 zachowano.

Test migracji otwiera rzeczywistą bazę według eksportu Room13, przenosi
syntetyczny stan ze wszystkich 27 tabel i porównuje wszystkie poprzednie
kolumny oraz rowid składników posiłków po migracji.
Sprawdza nowe retryAtMillis=0, indeksy i FK. Nie zastępuje to jeszcze
aktualizacji prywatnego dziennika zwykłej aplikacji.

Zachowano wcześniejsze nieudane próby. Pierwszy kandydat Room13 został
zastąpiony po wykryciu braku trwałości backoff po logout. Pierwszy celowany
przebieg Room14 miał **20 PASS / 2 FAIL**: oczekiwanie testu błędnie liczyło
już potwierdzoną operację jako oczekującą, a generator bazy testowej nie
cytował kolumny `limit`. Poprawiono te dwa testy i wykonano końcowe 22/22
oraz pełne 320/320 na identycznych źródłach. Nie osłabiano parsera/guardów.

Pokryto utratę ACK i odtworzenie kontrolera, 401 bez pętli odnowienia,
429/503 i restart/logout/A→B→A, późne odpowiedzi, zmianę kontekstu,
edycję porcji podczas wysyłki, błędny końcowy ACK i rollback zapisu,
konflikt/odrzucenie, odmowy recovery/deletion oraz awarię pull po trwałym ACK.
UI sprawdzono przy szerokości 320dp i czcionce 150%.

## Następna próba E4 — NOT_RUN

Odczytano O2-044 na main `4228ccafdf01a8936dc39bc1964f5d325504ec04`
i O3-084 na `c0aef36` / [PR137](https://github.com/Roseru/aplikacja-mobilna/pull/137).
Obowiązuje [oracle O2](https://github.com/Roseru/aplikacja-mobilna/blob/4228ccafdf01a8936dc39bc1964f5d325504ec04/docs/integracja/ODBIOR_R2_R3_ORACLE_E4_O2.md)
i [obserwator PG O3](https://github.com/Roseru/aplikacja-mobilna/blob/c0aef36/docs/integracja/PRZYGOTOWANIE_REPLAY_E4_O3.md).
Pierwszy test obejmie jedną syntetyczną operację Meal/create, C0/C1/C2
i rzeczywisty restart procesu przed lokalnym ACK. Ponowienie ma zachować
dokładne bajty koperty i operation_id; serwer ma zwrócić already_applied
z pierwotną revision1, bez kolejnej mutacji Meal/receipt/counter/zmian C1→C2.
Nie wymagamy counter+1 przy pierwszym zapisie: utworzenie DiaryDay jest legalne.

**Nie ma jeszcze drivera POST ani skonfigurowanego APK do tej próby.**
Driver offline z manifestu nie jest driverem utraty ACK. Dotychczasowy gate
GET nie obsługuje POST. Plan kolejnego małego kroku: jednorazowa bariera
wyłącznie validation po odebraniu pełnego HTTP200/no-store, przed przygotowaniem
i zastosowaniem ACK, poza mutexem i transakcją Room. Z góry ograniczony czas
musi objąć osobny odczyt PG C1, potwierdzenie braku ACK i rzeczywiste
zabicie procesu. Dokładny limit, markery, testy timeout/cancellation i SHA
zostaną podane dopiero po implementacji; wygaśnięcie przed kill oznacza NOT_RUN.
Produkcja zachowa tę samą ścieżkę parsera, transportu i guardów.

Po tym kroku O1 przekaże osobny manifest APK/drivera i gotowość do próby;
O2/O3 sprawdzą zgodność konkretnego kandydata z używanym obrazem/schema24.
Sama zgodność z main/schema26 nie wystarczy. Aktualna osiągalność i świeże
ograniczone okno zostaną uzgodnione osobno. Podczas gry właściciela wykonano
wyłącznie lekkie prace, bez buildu, instalacji, nowego transportu lub Gemini.

## Granice

Wysyłane są kanoniczne operacje Meal utworzone przez obecny klient.
Historyczny outbox, profil, cele, waga i deklaracje dni nie są automatycznie
przekształcane ani uznawane za wysłane. Panel pokazuje ten zakres osobno.
WorkManager, pełne recovery, retencja kopii/historii i stosowanie odczytanej
kopii do lokalnego dziennika pozostają dalszymi etapami. Obecny magazyn kopii
ma własny limit przechowywanych przebiegów; odmowa pojemności nie cofa ACK.

Wygasły checkpoint serwer klasyfikuje jako `sync_reconciliation_required`.
Nie wolno go automatycznie podmienić po samym pull: wymagane jest świadome
uzgodnienie niepewnych operacji. Zachowujemy pierwotne ID i pełne żądanie
do tego procesu. Nie dodajemy pozornego obejścia blokady.

To nie rzeczywisty odbiór APK/API/Keycloak/TLS, pełne E4/E7/KO32 ani migracja
używanej instalacji serwera. Nie otwierano relay i nie wywoływano Gemini.
