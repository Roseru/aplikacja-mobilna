# Import i uzgadnianie — port sesji B/C

Stan: lokalny milestone B dla równoległej integracji O1. To nie odbiór całego B.
Cross-plan idempotencja źródeł ma otwartą uwagę P1 koordynatora; ekran i pełna
regresja/migracje/review pozostają w realizacji. Nie używać tego checkpointu
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

Kontrole milestone: pełne395debugJVM/410validationJVM i8celowanych Room/native
PASS na własnym emulatorze, bez HTTP/PG. To nie pełna regresja urządzenia B,
nie test końcowego ekranu i nie integracja z sesją O1. Zmiana dwóch typów
wyniku zgodnie z O1 dodatkowo przechodzi kompilację przed checkpointem.
