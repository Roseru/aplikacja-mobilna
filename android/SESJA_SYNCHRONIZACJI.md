# Polecenia synchronizacji wykonywane w sesji Androida

O1, 23.10.2026. Implementacja części sesyjnej dla modułów Androida O2-B/C.
Baza zawiera scalony [etap sześciu domen](DOMENY_SYNC.md). Pierwszy milestone
sesji był oparty na O2-B `2798f967da0d82270d684f2ded7bb285bcfb101d` z otwartą P1.
Po zachowaniu tego builda dołączono zwykłym merge poprawione B
`a73f2cbc7f1d8e246b8eb7e103ce5ac1d49f1a8a` (Room20). O2 przekazał poprawki
importu, porównania i atomowego dowodu decyzji; B nadal nie jest scalony ani
odebrany razem z rzeczywistą sesją/DI/nawigacją. `SessionController`
implementuje dostarczone interfejsy `SyncStepExecutor` i `ReconciliationStepExecutor`.
O2 podłącza DI/UI/WorkManager; w konstruktorze kontrolera przekazuje
`reconciliationStore=ReconciliationStore(database, schema)`. Brak tej konfiguracji
daje `NotConfigured`. Ten dokument opisuje kod; wspólny dziennik pozostaje
w [KOMUNIKACJA_AGENTOW.md](../docs/KOMUNIKACJA_AGENTOW.md).

## Zakres właściciela i kontekstu

`SessionController` przechwytuje `OwnerLease` oraz dokładny `AccountBindingEntity`.
W bootstrapie oczekiwany brak binding jest rzeczywistym warunkiem: polecenie
pierwszego połączenia nie może zaakceptować binding dodanego w międzyczasie.
Lease obejmuje generację; przełączenie A→B→A unieważnia wcześniejsze polecenie.

Kontrole działają przy przechwytywaniu sesji, odświeżaniu tokenu, przed HTTP,
przed zastosowaniem odpowiedzi oraz przy zwrocie wyniku. Kontrola kontekstu
i zapis odnowionej sesji należą do jednej transakcji Room pod mutexem sesji.
Odpowiedź starego polecenia nie przechodzi do nowego konta. Zmiana właściciela
lub kontekstu nie usuwa zapisanej koperty ani nie daje ACK.

Nie ma dodatkowego klienta OAuth, vaulta ani transportu. Metody korzystają
z istniejących gatewayów, parserów i trwałych store. Oczekiwanie na sieć oraz
walidacja dużych struktur pozostają poza mutexem i transakcją Room.

## Wewnętrzne wejścia kontrolera

| Wejście | Ukończony krok |
|---|---|
| `executeBootstrapStep(lease, context?)` | Potwierdzony bootstrap i nowy binding |
| `executePullStep(lease, context)` | Kompletna kopia oraz osobna informacja, czy zastosowano ją do dziennika |
| `executePushStep(lease, context)` | Trwałe, atomowe ACK przygotowanych partii, bez dodatkowego pull |

Wewnętrzne `SyncCommandOutcome` służy implementacji kontrolera. Nie zastępuje
wspólnych typów dostarczanych przez O2. Wyniki zawierają `Bootstrapped`,
`Pulled(runId, applied)`, `Pushed(acknowledged, refused, more)`, `Busy`,
`RetryAt(epochMillis)`, `LoginRequired`, `ReconciliationRequired(code)`,
`StaleContext`, `TransientFailure` oraz `NotConfigured`. Kod orkiestratora
nie odczytuje komunikatów UI i nie wnioskuje o sukcesie z powrotu `Unit`.

`Pulled(applied=false)` nie może być mapowane na ukończony krok C. Ręczny
odczyt może zachować poprawne archiwum mimo błędu projekcji; worker musi wtedy
zatrzymać cykl albo zaplanować odpowiednie wznowienie. `Pushed.more` oznacza
osiągnięcie limitu dziesięciu partii, a nie potwierdzenie całej pozostałej kolejki.

Cofnięty refresh token (`invalid_grant`) i brak refresh tokenu zwracają
`LoginRequired`. Błąd połączenia z dostawcą tożsamości pozostaje chwilowy.
Opis błędu dostawcy nie trafia do UI/logów, a dziennik i kolejka pozostają lokalnie.
Anulowanie propaguje `CancellationException`; nigdy nie jest zakończeniem kroku.

## Kolejność i odzyskiwanie

Opóźniony callback ekranu powinien wywołać `bootstrap(expectedLease)` z lease
wyświetlonego konta. Kontroler przechwytuje jego aktualny binding pod guardem;
przełączenie konta przed wykonaniem callbacku go odrzuca. Wariant z jawnym
`expectedContext` pozostaje dla orkiestracji. Do ręcznego pobrania ekrany także
przekazują przechwycony lease, zamiast ponownie wybierać właściciela w callbacku.

Orkiestrator O2-C zarządza PULL→PUSH→PULL. Pojedynczy PUSH nie uruchamia
ukrytego odczytu ani nie uznaje nowych zmian powstałych po ACK za potwierdzone.
Zapisany Retry-After przeżywa odtworzenie kontrolera i zmianę aktywnego konta.

Dotychczasowe ręczne `synchronizeMeals` zachowuje odświeżenie kopii po ACK.
`synchronizeMealsWithoutPull` służy osobnej obserwacji tego samego zapisu ACK
przez opt-in driver; nie tworzy innego parsera ani drogi omijającej guardy.

Zwykłe polecenia workera odmawiają przy `requiresRecovery`. Ręczny odczyt
archiwum w tym stanie nie usuwa flagi i nie importuje go do dziennika.
Kontrolowane `runReconciliationStep` wykorzystuje zatwierdzony trwały plan
O2-B i jego osobne `prepareAck/applyAck`; nie wolno chwilowo wyłączać flagi,
zmieniać starej epoki koperty ani przepuszczać recovery ACK przez zwykły parser.
Pełny odczyt wykonuje jedną trwałą grupę receipts, do100ID. Kolejne strony
sprawdza przed HTTP i zastosowaniem; `acceptCompletedSnapshot` zapisuje dowody
dopiero po ukończeniu kopii. Ukończenie grupy nie oznacza ukończenia całego planu.

PUSH wysyła jeden zatwierdzony zamrożony request. Po utracie odpowiedzi ponawia
te same bajty. `awaitingSnapshot` daje `reconciliation_snapshot_required`, zeroACK
i zachowuje odpowiedź. Po nowej kopii `needsAckRevalidation` ponownie waliduje
zapisany wynik **bez kolejnego POST i bez odnawiania tokenu**. Lokalny zapis
chroni ten sam lease/kontekst, rezerwacja i rewizja zapisanej sesji. Cancellation
zdejmuje tylko własną rezerwację; nie zmienia niepewnego requestu ani stanu ACK.

Końcowy `ReconciliationStore.finish` pozostaje jawnym krokiem O2 po decyzjach
i kopii poACK. Samo `Completed` kroku sieciowego nie zdejmuje `requiresRecovery`.
Podłączenie w tej gałęzi jest przed odbiorem końcowym, nie jest wynikiem B/C PASS.

## Stan sprawdzeń

Przypadki urządzenia zapisano dla zmiany kontekstu podczas refresh/HTTP,
oczekiwanego braku binding, A→B→A, trwałej koperty po utracie odpowiedzi,
Retry-After, cancellation, busy, rozdzielenia push/pull i przyczyn odnowienia.
Samo istnienie tych przypadków nie jest wynikiem PASS. Po ukończeniu części
sesyjnej wykonano jeden `:app:assembleValidationAndroidTest`: **BUILD SUCCESSFUL
w10m1s**. Produkcja i przypadki urządzenia skompilowane, testowy APK spakowany;
źródła kontrolera/gatewaya/testów zgodne z przechwyconymi przed buildem.
SHA256 logu: `63a7bc97e505c05e77f7e38eaddfbb387f3d962edc261266f5001d2cdee6be86`.

W tym pierwszym odbiorze nie uruchamiano JVM ani instrumentacji. Zadanie nie pakuje APK aplikacji;
brak dostawy APK lub instalacji. Testy urządzenia i finalna integracja są
odłożone do dalszego odbioru. Nie tworzymy częściowego PR dla tego milestone.
Pełny zdalny CI i rzeczywisty E4 pozostają osobnymi bramkami.

Kompilujący milestone jest opublikowany jako89766ec; jego receipt dotyczy
wyłącznie zależności2798. Odbiór nowszego B opisano poniżej.
Podczas lekkiej pracy dodano lease dla opóźnionego przycisku bootstrap oraz
ograniczenie odnowienia do jednej próby także po odnowieniu wstępnym.
Ta sama zasada obejmuje odczyty profilu/społeczności, zgodę rankingową,
polecenia Nemesis oraz wysłanie/odczyt/zatwierdzenie/anulowanie analizy zdjęcia:
odnowienie przed HTTP zużywa próbę, więc późniejsze401 nie powoduje drugiego
odnowienia w tej operacji. Bieżący request i jego identyfikator pozostają zachowane.
Przygotowane dalsze przypadki obejmują saved ACK po wygaśnięciu tokenu,
kompletny raw snapshot przerwany przed zapisem receipts i wstępny refresh→401.
Przyjęcie kompletnego raw bez sieci czeka na dodatkowy port O2 przygotowania/
zastosowania kopii; obecny kod nie realizuje jeszcze tej gałęzi. Ten przypadek nie jest PASS.

Podgląd lokalnego zdjęcia rozróżnia wczytywanie i błąd odczytu/dekodowania.
Po błędzie użytkownik może ponowić samo otwarcie obrazu; nie jest wykonywane
wysłanie ani usunięcie zdjęcia. Zmiana zdjęcia lub właściciela modelu resetuje
stan podglądu, a anulowanie korutyny pozostaje anulowaniem. Budowa i celowany
odbiór poniżej obejmują kod tej poprawki; nie oznaczają pełnej regresji interfejsu.
Odczyt obrazu, hash i dekodowanie podglądu działają poza transakcją Room.
Przed zwróceniem bitmapy ponownie sprawdzany jest ten sam lease i dokładny
rekord zdjęcia. Błąd końcowego guardu zwalnia bitmapę i jest propagowany.

### Odbiór na B/Room20, 23.10 po18:30

Źródło kodu `3ac231228fe833cd01c755223b4683d14cd2ab61`, zależność
O2-B `a73f2cbc7f1d8e246b8eb7e103ce5ac1d49f1a8a`. Jeden build
`assembleValidation` i `assembleValidationAndroidTest`: **PASS12m8s**,
APK aplikacji oraz testowy APK. LogSHA256
`647d1a34401096c80282b7cdd48d9db0af7100151da18b37390146fa62072dc6`.

Sześć celowanych native offline API35 **PASS,0fail/skip**: pojedynczy refresh
przed bootstrap/pull→401, lokalne zastosowanie savedACK po typed target przy
wygasłym tokenie bez POST/refresh, trwałość zdjęcia po ponownym otwarciu,
izolacja kont/ABA i dwa istniejące przepływy ekranu zdjęć z odtworzeniem Activity.
LogSHA256 `e6cc8b50fe522f9a631518f3ad591f916d3171fe05e079e6a44067943306dacb`.
JVM/live nie uruchamiano. Nie obejmuje16metod wcześniejszego przekazania O2
ani pending przypadku completed-before-receipts; nie kwalifikuje całego B/C.

Pierwszy start instrumentacji przerwał ANR przed pierwszym przypadkiem.
Zachowany oddzielny log wskazuje Runnable w inicjalizacji korutyny i22,9s
oczekiwania na CPU oraz ANR usług systemowych. Po zmianie zasobów tego samego
własnego świeżego AVD z2CPU/2048MB na4CPU/3072MB przebieg przeszedł na tych
samych APK, z niezmienionymi timeoutami i danymi. Offline przed/po potwierdzone.
Nie kasowano danych ani nie restartowano komputera. To korekta środowiska
odbioru, nie zmiana kodu omijająca błąd. Historyczny CI timeout zdjęcia pozostaje
osobnym wynikiem; ten celowany PASS nie dowodzi przyczyny jego wcześniejszego błędu.

### Dalsza poprawka obserwatora — jeszcze bez odbioru

CI39989059705 pakietu PR146/ce04199 (tested merge1855ee4b) wykonał373native:
372PASS i timeout10s w `privateRoomObserverClearsCachedProfileAndConsentAcrossContextAndOwnerChanges`.
XML i osobny logcat odczytane; nie wskazują, który z trzech warunków oczekiwania
nie został spełniony. Nie ponawiano CI. Analiza kodu wskazuje możliwość przełączenia
właściciela pomiędzy zapytaniami `publish`, zakończoną `StaleOwnerException`
i wyjściem z obserwacji. To hipoteza przyczyny tej próby, nie udowodniony reproduktor.
Lokalna dalsza zmiana obejmuje spójny odczyt publikacji w transakcji Room i wyczyszczenie
profilu także po błędzie obserwatora. Błąd pojedynczej publikacji nie kończy
zdrowej subskrypcji Room; kolejna zmiana może odtworzyć aktualny widok.
Istniejący przypadek wskazuje teraz niespełniony etap bez zmiany limitu10s,
liczby przypadków ani propagacji anulowania. Czeka na wspólny odbiór etapu;
wynik sześciu przypadków źródła3ac2312 nie obejmuje tej późniejszej poprawki.
