# Integracja synchronizacji E4 - osoba 2

Punkt odniesienia: Android 0.7.1 / Room 6 z odebranego PR #9 i E3 z migracją
0008. Odczytano AccountBootstrapStore, BootstrapProtocol, LocalOwners,
DiaryRepository, format outbox i [przekazanie E3](../../android/INTEGRACJA_E3.md).
Kod Androida nie jest częścią tej dostawy. Normatywne [DTO](../../backend/openapi.json),
[decyzja v1](DECYZJE_V1.md), [klient referencyjny](../../tools/sync_client/README.md).

1. Potwierdzona sesja/PKCE → bootstrap → pełny pull → push → pull. Bootstrap
   nie importuje gościa. Zbiór gościa wymaga trwałej jawnej decyzji przypisania
   do jednego konta, również dla historii starszej niż 30 dni.
2. Przechwyć local scope, lease generation, account_id/account_generation,
   sync_epoch oraz contextRevision. Sprawdzaj je przed wysyłką i w transakcji
   apply. A→B→A unieważnia stare zadanie mimo powrotu do tej samej tożsamości.
3. Outbox Room pozostaje źródłem lokalnym; materializuj oddzielną wersjonowaną
   wire kopię. create/update, legacy Double, local_revision, brak epoki i porcje
   do 12 miejsc nie są wire Operation. Decimal v1 ma do 6 miejsc: 1.234567000000
   można zachować bezstratnie jako 1.234567; 1.234567000001 i 0.000000000001
   wymagają decyzji. Nie zaokrąglaj do zera. Cel legacy bez czasu/strefy
   pozostaje do uzgodnienia; nie wymyślaj metadanych historycznych.
4. Po materializacji operation_id/hash/epoch/body są niezmienne. Kolejna edycja
   czeka na wynik poprzednika i otrzymuje nowe ID oraz serwerową base_revision.
   Tylko kompletne HTTP200 z jednym wynikiem na operację pozwala na ACK.
   Brak HTTP200 pozostawia całą kolejkę, również przy zatwierdzonym prefixie.
5. Pull utrwala stronę i następny token atomowo w staging/shadow. Oryginały i
   niewysłane zmiany pozostają osobno. Pełny snapshot aktywuj dopiero po końcu;
   checkpoint przed ostatnią stroną jest null. Query recovery_operation_ids
   używa powtórzonych parametrów form/explode, tylko na początku snapshotu.

Profile i DiaryDay mają naturalne klucze. Inny lokalny UUID dla własnego profilu
lub dnia daje konflikt z current kanonicznej encji. Meal może automatycznie
utworzyć dzień: jego zmiana poprzedza posiłek w ChangeLog tej samej transakcji.
Nie ma nowego day_id w Meal. Nie przepisuj już wysłanej operacji dnia; uzgodnij
ją i dopiero utwórz nową operację. Cel jest niezmienny; zależny posiłek czeka
na zaakceptowany goal_id. Konflikt osi nie zmienia przyjętych wersji historii.

| Zdarzenie | Działanie klienta |
|---|---|
| sync_cursor_expired / sync_reconciliation_required w tej samej epoce | Pełny snapshot, zachowanie oryginalnych ID niewiadomych operacji, świadome uzgodnienie; brak wpisu nie oznacza automatycznego create |
| sync_epoch_changed | Zachowanie także potwierdzonych danych; brak receipt nie dowodzi niewykonania, równa revision nie dowodzi równej treści; blokada starego outbox |
| account_generation_changed, epoka ta sama | Pełne uzgodnienie i checkpoint nowej generacji; bez RecoverySource z tą samą epoką |
| account_deleting | Trwała blokada; nie otwieraj recovery/importu |
| 401 / 503 | Sesja lub bezpieczny retry z Retry-After; zachowanie kolejki |

requiresRecovery nie znika przez ponowny bootstrap. O1 musi dodać kontrolowany
tryb snapshotu i świadomych nowych recovery operacji przy tej fladze; zwykły
push nadal blokowany. Zakończenie recovery ma transakcyjnie sprawdzić pełny
kontekst i decyzje. Narzędzie O2 demonstruje regułę, nie wykonuje mobilnego
requireReady ani WorkManager.

Recovery recreate_missing ma nowe UUID/base_revision=null; resolve_existing
aktualne UUID i revision. Serwer zapisuje UNIQUE(owner,source_epoch,source_uuid)
bez typu w kluczu, weryfikując typ i własność źródła. Dwa urządzenia mogą dostać
ten sam mapping. result.entity_id pozostaje proponowany; autorytatywny target
pochodzi z recovery_mapping.target_entity_id. Przepisuj tylko nowe zależne
referencje, po potwierdzeniu rodzica; zachowaj niezmienne wysłane payloady.

Odbiór Room/APK, KO-31 i produkcyjnego restore pozostaje zadaniem O1/O3.
Własne testy SQLite/HTTP O2 nie są ich potwierdzeniem. Odbiorcy sami dopisują
odczyt do [wspólnego dziennika](../KOMUNIKACJA_AGENTOW.md).
