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
