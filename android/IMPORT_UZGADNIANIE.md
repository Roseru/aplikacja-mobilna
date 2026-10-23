# Import i uzgadnianie — port sesji B/C

Stan: lokalny milestone B dla równoległej integracji O1. To nie odbiór całego B.
Cztery konkretne uwagi koordynatora są poprawione i mają regresje; ekran,
pełna regresja i końcowy przegląd pozostają w realizacji. Nie używać tego checkpointu
jako gotowej dostawy aplikacji ani dowodu live.

`pl.roseru.kalorie.sync.SyncExecution.kt` definiuje zwykłe PULL/PUSH,
FULL_SNAPSHOT_RECEIPTS/PUSH_APPROVED i wspólny jawny wynik. Completed(PUSH)
oznacza pełny atomowy ACK, bez dodatkowego pull. TransientFailure pozostawia
niepewne requesty i wymaga backoff O2. NotConfigured nie uruchamia pętli retry.
Anulowanie propaguje wyjątek; nie jest Completed ani odmową operacji.

O1 zachowuje mutex/rezerwację, lease/context/ticket/refresh/beforeSend i guard
przy zastosowaniu. O2 nie tworzy transportu ani dostępu do tokenu.

## Kontrolowane uzgadnianie

- `ReconciliationStore(db,schema)` jest trwałym store dla istniejącego transportu.
- `nextSnapshot(lease,context,planId)` zwraca następną grupę receipts (do100ID),
  wznawia tę samą stronę. Wszystkie strony przez istniejący SnapshotGateway
  i ServerSnapshotStore; na końcu kroku O1 wywołuje
  `acceptCompletedSnapshot(lease,context,planId,runId)` pod guardem.
- `preparePush(lease,context,planId)` zwraca `ReconciliationPushRequest?`.
  `batch` jest PushBatch dla obecnego MealPushGateway. Przed send wymagane
  `requireCurrent` oraz `markAttempted`; Retry-After przez `defer`.
- `prepareAck(request,httpStatus,bytes)` waliduje całą odpowiedź; `applyAck`
  w guardzie utrwala wynik. Nie potwierdza żadnego prefiksu błędnej odpowiedzi.
- Jeśli `request.needsAckRevalidation`, **bez HTTP POST** użyj
  `request.savedResponse()` i ponów prepareAck/applyAck po nowej pełnej kopii.
  Walidowany mapping innego urządzenia może potrzebować typed target proof;
  wynik ACK ma `awaitingSnapshot=true` i zero potwierdzonych operacji.
- Completed przekazuje runId/batchId i liczniki. Busy, RetryAt, LoginRequired,
  ReconciliationRequired(code), StaleContext, TransientFailure i NotConfigured
  są osobnymi wynikami; code nie zawiera prywatnej treści odpowiedzi.
- `finish(lease,context,planId)` jest lokalnym jawnie zleconym krokiem O2.
  Wymaga rozstrzygniętych źródeł i aktualnej pełnej kopii po ACK. Ostatnia
  transakcja stosuje kopię i dopiero końcowo usuwa requiresRecovery.
  Nie obchodzi bramki chwilowym wyzerowaniem tej flagi.

Zwykły MealPushStore zachowuje publiczne wejścia. Recovery ma własny wariant
walidacji: wynik entity_id identyfikuje proponowane ID, mapping może wskazać
inny autorytatywny target; compact receipt revision może być starsze od
mapping.target_revision. Same-epoch expiry tworzy nową powiązaną kopertę,
operacje pozostają identyczne; epoch recovery ma nowe ID i RecoverySource.
Brak receipt nie jest ACK ani dowodem niewykonania.

Kontrole milestone: pełne395debugJVM/410validationJVM i15celowanych Room/native
PASS na własnym emulatorze, bez HTTP/PG. To nie pełna regresja urządzenia B,
nie test końcowego ekranu i nie integracja z sesją O1. Zmiana dwóch typów
wyniku zgodnie z O1 dodatkowo przechodzi kompilację przed checkpointem.

## Poprawki po odbiorze checkpointu

- Źródło ma trwały ImportOrigin i fingerprint niezależny od planu oraz postępu
  kolejki. Niezmienione źródło pomija projekcję/outbox także po edycji targetu,
  zamrożonej próbie, restarcie i pełnym pull. Zmienione źródło wymaga decyzji;
  osobna kopia dostaje nowy localId i wireUUID. Pierwsze powiązanie jest niezmienne.
- Room18→19 zachowuje opublikowany i rzeczywiście użyty checkpoint9tabel.
  Migracja19→20 dodaje origin/fingerprint i uzupełnia powiązania z ledgeru;
  test zachowuje wszystkie wcześniejsze komórki/rowid42tabel i frozenbody/hash.
  Bez wipe ani zmiany zwykłej instalacji użytkownika.
- Historyczny mapping pozostaje rezerwacją także dla deleted/retained targetu;
  nie blokuje archiwizacji pełnej kopii. Żywy typed proof jest wymagany dopiero
  przez operację, która chce go użyć. Usunięty target nie upoważnia do recreate.
- ACK replay_original potwierdza tylko frozen operację. Późniejsza lokalna
  intencja istniejąca przed begin pozostaje bez zmian w kolejce i powoduje
  jawną decyzję later_local_intent; finish nie nadpisuje jej danymi serwera.
- SourceOperationId ma rewizję swojego własnego zapisanego ACK/receipt.
  Wcześniejsza rewizja projekcji pozostaje oddzielnym dowodem. Zgodny receipt
  update2/revision2 daje dokładną rewizję2; brak receipt zachowuje null dla
  niepewnej próby, a sprzeczna odmowa blokuje odzyskiwanie.
- Reconciliation raw pages są staging. acceptCompletedSnapshot publikuje aktywny
  checkpoint i typed ledger dopiero po pełnej walidacji całej kopii w jednej
  transakcji. Zwykły snapshot zachowuje dotychczasowe wejście.

Regresje15native obejmują także oba rodzaje późniejszej intencji (create oraz
update z potwierdzoną bazą), >100receipts, target innego urządzenia, poprawną
historyczną rezerwację i jej niedopuszczalne użycie, brak/zgodny/odmowny receipt.
Pierwsza wersja rozszerzonej regresji wykryła pomieszanie knownProjectionRevision
z SourceRevision; odrębny dowód wcześniejszego ACK nadal chroni same-epoch absence.

## Formularze i dalsza weryfikacja B — checkpoint O2-053

`ImportScreen`, `ImportViewModel` i `LegacyImportForm` udostępniają normalne pola
zgody, postępu i decyzji. Konto docelowe ma pełny issuer/subject, osobny checkbox
oraz sprawdzenie źródłowego fingerprintu przy zgodzie. Model jest przypisany do
konkretnego lease; stary callback po A→B→A lub zmianie epoki nie zapisuje decyzji
ani nie wywołuje portu sieciowego. Wartości źródłowe są osobno od korekty; brak
nie staje się zerem, nie ma zaokrąglania do wire ani edytora JSON. Zapisany plan
wznawia się po restarcie, a queued/NotConfigured/Retry nie oznaczają complete.

- Podgląd rozpoznaje brak metadanych i nadmierną precyzję przed zgodą, a kolizje
  także w pełnej kopii, której jeszcze nie zastosowano do projekcji. Konflikt
  pojedynczego profilu lub dnia wymaga jawnej decyzji, bez cichego nadpisania.
- Osobna kopia zmienionego źródła dostaje trwałe, osobne UUID składników, także
  dla poprawnych UUID źródła. Pierwszy import zachowuje źródłowe wireUUID.
- Poprawiony własny cel ma nową lokalną projekcję; historyczny rekord pozostaje
  niezmienny, bez podwójnego liczenia. Pierwszy import inicjuje oś z pełnej kopii.
- Powiązany cel recovery zachowuje historyczny payload/axis. Nowa decyzja wymaga
  aktualnej osi i nowej projekcji. Końcowa transakcja archiwizuje poprzednią oś,
  przełącza kontekst i zachowuje zakaz regresji w tej samej epoce. Rozstrzygnięty
  oryginał pozostaje historią i nie wraca jako nowy import ani blokada osi.
- Jawne accept_server znanej nieobecności profilu usuwa lokalną projekcję,
  zachowuje tombstone i frozen request; później można utworzyć nowy profil.

Weryfikacja checkpointu:409debugJVM/424validationJVM i27Room/native/UI PASS,
lint0Error/0Fatal/28Warning/1Information. Następne3celowane native PASS rozszerzają
pokrycie o pełne18→19→20 oraz zachowują19→20 i6domen historycznych. Migracje
porównują wszystkie stare komórki/rowid/FK (33/42tabele), w tym wcześniejsze
legacy i zamrożony request/hash. Bieżące28unikalnych przypadków nie oznacza
pełnej regresji urządzenia aplikacji. E0 PASS. Syntetyczna paczka sześciu domen
z rzeczywistego importu Androida przeszła backendowy PushRequest/preflight;
trzy celowo wadliwe Decimal zostały odrzucone. Bez HTTP/PG/live.

Nadal WIP: ekran jest komponentem z przetestowanym modelem; ostateczne
osadzenie w nawigacji/DI oraz transport wymagają zweryfikowanego commita O1,
którego SessionController realizuje oba uzgodnione executory. Nie używamy
stubu jako odbioru integracji. Dalej: właściwe podłączenie, brakujące przypadki
końcowe, niezależny review, pełna regresja i jeden PR B z CI/odbiorem.
C pozostaje kolejnym etapem całego przydziału A→B→C.
### Poprawki trzech uwag odbioru checkpointu1e15

- Wersje lokalna i serwera są pokazane przed decyzją, z jednostkami i jawnym
  brakiem danych. VM używa aktualnej zweryfikowanej pełnej kopii planu, również
  gdy nie ma RecoveryMapping. Brak kopii nie jest przedstawiany jako nieobecność.
  Stary widok dowodu nie może zapisać decyzji po zmianie aktywnej kopii.
- Uszkodzony historyczny snapshot pojedynczego składnika nie blokuje całego
  podsumowania. Taki wpis ma komunikat i opcję zachowania lokalnego; sprawny
  pomiar nadal może być zaimportowany. Oryginał i sourceHash pozostają identyczne,
  nie podstawiamy pustego snapshotu ani zerowej wartości odżywczej.
- Po preserve_local i zakończeniu nowej epoki zachowany historyczny cel nie jest
  automatycznie correction_of nowej operacji. Nowa zwykła decyzja odwołuje się
  tylko do żywego celu bieżącego kontekstu z dowodem lub własną bieżącą kolejką;
  inaczej stanowi osobną decyzję, zachowując historię. Legalne powiązanie celu
  bieżącej epoki nadal działa.

Regresje poprawek:417debugJVM/432validationJVM,36celowanych native/UI i lint
bez błędów PASS. Scenariusze obejmują widoczne82kg/80kg bez mappingu przed
wyborem, brak domyślnego przyjęcia serwera, blokadę przy braku dowodu,
uszkodzony posiłek z poprawną wagą i nową zwykłą decyzję po preserve_local.
Pierwszy red test potwierdził niedozwolone correction_of starej epoki.
Dodatkowy celowany kontrprzypadek sprawdza legalne referencje bieżącej epoki.
To nadal poprawki B w toku odbioru; rzeczywista sesja O1/nawigacja/DI i pełne
CI jednego końcowego PR B pozostają osobne. C ma własny checkout od1e15;
po poprawkach dostanie zwykły merge B. Przyszłe migracje C wymagają osobnego
własnego AVD, z zachowaniem testowego Room20 B.
### Atomowy dowód decyzji po odbiorzeb9d8

UI przekazuje `expectedProofRunId` do `ReconciliationStore.decide`; sprawdzenie
odbywa się w tej samej transakcji co append decyzji i zmiana źródła. Zapisany
`decision_proof` zawiera runId, sourceHash oraz dokładną obserwację serwera
(tożsamość, obecność/usunięcie, rewizja, payload) i jej SHA-256. Pozostałe
wejścia lokalne zachowują zgodność, ale także utrwalają bieżący dowód w transakcji.
Przygotowanie nowych operacji i finish sprawdzają zapisany dowód. Nie zmieniają
zgody na inną wersję: zmiana daje `server_proof_changed` i ponowne porównanie.
Wznowienie istniejącego frozen request zachowuje jego własną kopertę i dowody.

Deterministyczna regresja: pokazanaR1 → opublikowanaR2 → zapis ze starym runId
odrzucony bez zmian decyzji/outbox/projekcji. AktualnaR2 zapisuje właściwy dowód.
PóźniejszaR3 nie może zostać przyjęta podczas finish bez nowego wyboru; jawna
zgoda naR3 działa. Frozenbytes/hash i wcześniejsze decyzje pozostają identyczne.
Kontrola:417/432JVM,23celowane native/UI i lint bez błędów PASS. Formularz ma
jawną akcję zakończenia edycji, zgodę i zapis; test weryfikuje ich stany,
zamiast klikać dowolny ostatni checkbox przy otwartej klawiaturze.