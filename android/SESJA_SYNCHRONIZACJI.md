# Polecenia synchronizacji wykonywane w sesji Androida

O1, 23.10.2026. Implementacja części sesyjnej dla modułów Androida O2-B/C.
Baza zawiera scalony [etap sześciu domen](DOMENY_SYNC.md). Publiczne połączenie
z planem uzgadniania i orkiestratorem O2 pozostaje do podłączenia po dostawie
przypiętych typów/store. Ten dokument opisuje kod; wspólny dziennik pozostaje
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

Orkiestrator O2-C zarządza PULL→PUSH→PULL. Pojedynczy PUSH nie uruchamia
ukrytego odczytu ani nie uznaje nowych zmian powstałych po ACK za potwierdzone.
Zapisany Retry-After przeżywa odtworzenie kontrolera i zmianę aktywnego konta.

Dotychczasowe ręczne `synchronizeMeals` zachowuje odświeżenie kopii po ACK.
`synchronizeMealsWithoutPull` służy osobnej obserwacji tego samego zapisu ACK
przez opt-in driver; nie tworzy innego parsera ani drogi omijającej guardy.

Zwykłe polecenia workera odmawiają przy `requiresRecovery`. Ręczny odczyt
archiwum w tym stanie nie usuwa flagi i nie importuje go do dziennika.
Kontrolowane `runReconciliationStep` ma wykorzystywać zatwierdzony trwały plan
O2-B i jego osobne `prepareAck/applyAck`; nie wolno chwilowo wyłączać flagi,
zmieniać starej epoki koperty ani przepuszczać recovery ACK przez zwykły parser.
To połączenie pozostaje w implementacji, nie jest potwierdzonym odbiorem B/C.

## Stan sprawdzeń

Przypadki urządzenia zapisano dla zmiany kontekstu podczas refresh/HTTP,
oczekiwanego braku binding, A→B→A, trwałej koperty po utracie odpowiedzi,
Retry-After, cancellation, busy, rozdzielenia push/pull i przyczyn odnowienia.
Samo istnienie tych przypadków nie jest wynikiem PASS. Końcowy build i właściwe
wykonanie następują po ukończeniu spójnego etapu; bez powtarzania całego JVM
po każdej zmianie. Pełny zdalny CI i rzeczywisty E4 pozostają osobnymi bramkami.
