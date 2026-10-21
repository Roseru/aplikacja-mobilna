# Odbiór R2/R3 i oracle ponowienia E4 - osoba 2

O2, 19.10.2026. Wynik: **PARTIAL — R2 late-GET/guard PASS; R3 świeże
odczyty B/A 4/4 PASS według receipts O1; transport i zamknięcie PASS
niezależnie O3**. Przegląd opublikowanych dowodów oraz dokładnych źródeł
przez O2 i dwóch niezależnych subagentów. O2 nie wykonywał nowej próby
sieciowej i nie odczytywał prywatnych Room/WAL, Vault ani surowych logów O1/O3.

## Źródła i granice odbioru

- Oracle: [pierwszy odbiór APK/API](ODBIOR_APK_API_O2.md), doprecyzowanie
  punktu 8 i O2-034; komunikacja O3-079–083 z main
  `cf47680a09b60727b9434e8983fbd109a246dffa`.
- Raporty O1 odczytane na dokładnym head PR129
  `a41a5cb558b39ee2adde29d731fee60eba07bf8f`:
  [R2](https://github.com/Roseru/aplikacja-mobilna/blob/a41a5cb558b39ee2adde29d731fee60eba07bf8f/docs/integracja/ODBIOR_APK_API_O1_R2_20261019.md),
  [R3](https://github.com/Roseru/aplikacja-mobilna/blob/a41a5cb558b39ee2adde29d731fee60eba07bf8f/docs/integracja/ODBIOR_APK_API_O1_R3_20261019.md).
  To odczyt materiałów z gałęzi O1, bez scalenia całego PR129 lub jego zależności.
- Faktyczna próba: istniejący O1Api35/API35, **0.8.12.validation/code1023/Room9**,
  źródło `e319e53130020b3bbcdb50588ef4a2205a241118`, bez czyszczenia danych.
  SHA256 APK `89164efd5199c8e1329f4fc833107a4045d034533ded6ef0e93f00996c50efcb`;
  drivera `91b788998c3aa20b928e65e3f4d63a5ff3ad9048cc3de8c70f5ba8b86ecc231f`.
  Używana instalacja O3: schema `0024_e9_history_graph`, obraz
  `sha256:05c1792f3551725f0303cc3786892771392532a25edc18ff710faad9e6b7e9a9`.
  Odbiór nie oznacza wdrożenia bieżącego main/schema26.

## Ocena R2 i R3

| Zakres | Opublikowany dowód | Ocena O2 |
|---|---|---|
| R2: rzeczywisty spóźniony GET A | HTTP200/no-store, run `425b7ebe-bf51-4e6e-aa9d-861efb4fe303`, request `56db1ea4-ae7a-466d-bfd5-8c0c64140eec`; driver 1 PASS/0 FAIL/0 SKIP | PASS punktu 8 w uzgodnionej technice validation |
| R2: poprawne DTO odrzucone po logout | Kolejność UTC 06:47:27.987493 held → 06:47:28.064846 logout → .066032 released → .096445 dto_parsed → .112245 stale_owner_rejected → .138190 guest_preserved | Źródło dokładnego APK potwierdza parsowanie przed markerem i odrzucenie przez istniejący guard; samo zakończenie wywołania nie jest oracle |
| R2/R3: zachowanie danych i kontekstów | O1: 15/15 tabel danych równe baseline, FK clean, B odrębne, powrót A z nowym lease, bez importu gościa | PASS według receipt O1; metadane logowania mogą legalnie zmieniać się w bazie 23 tabel |
| R3: świeże GET B/A | Cztery różne HTTP200/no-store i ukończone DTO, tabela poniżej | PASS zmierzonych odczytów i kontroli kontekstu według O1; R3 uzupełnia historyczne NOT_RUN z R2 |
| Transport i zamknięcie | O3: niezależnie 16 połączeń R2 i 13 R3, brak listenera/połączeń18444 po zamknięciu, health/TLS/discovery zgodne | PASS obserwacji O3; liczba TCP sama nie dowodzi PKCE ani DTO |

R3 — receipts UTC:

| Konto / odczyt | UTC 19.10.2026 | X-Request-ID |
|---|---|---|
| B `/api/v1/me` | 07:14:36.096630Z | `878bdebc-ae56-41be-a4ab-4318753626ba` |
| B `/api/v1/me/motivation` | 07:16:08.181707Z | `96ad1f47-69e4-4f49-b235-4b72ba41da6c` |
| A `/api/v1/me` | 07:20:36.086847Z | `8c4fe2d3-bba7-4c40-9da2-0dc9b3d8c94a` |
| A `/api/v1/me/motivation` | 07:21:35.538478Z | `ac59c840-79fe-4af1-8154-c5fa48711dc3` |

W dokładnym źródle APK sprawdzono `LiveApiLateReceiptTest`, `LateReadGate`,
`BootstrapGateway`, `ProfileReadProtocol` i `SessionController`.
Gate obejmuje jeden odebrany HTTPS GET200 po ograniczonym odczycie body,
przed zwrotem do kontrolera; poza mutexem, najwyżej 10 s i pierwotnym deadline,
z zachowaniem cancellation. To dowód odrzucenia starego wyniku, bez twierdzenia
o opóźnianiu pakietów TCP. Markery rozróżniają poprawnie sparsowane DTO
i `StaleOwnerException`; nie obchodzą guarda. ProfileRead nie ma generation:
sprawdzane są account_id/epoch, a motywacja sprawdza generation/epoch.

Pierwsze R1 0 PASS/1 FAIL przy oczekiwaniu na held oraz pośredni R2
0 PASS/0 FAIL/1 SKIP pozostają historią prób. Kolejny udany run po świeżym
logowaniu/refresh nie dowodzi przyczyny pierwotnego niepowodzenia.
R2 zamknął O1 o08:56:47 CEST, a O3 przez auto-close o08:58:41 CEST.
R3 zamknął O1 o09:22:20 CEST, O3 o09:23:43 CEST jako
`OWNER_STOP_AFTER_PEER_DISCONNECT`, przed końcem okna, bez twierdzenia o TTL.

R3 użył profili null i konkretnego wyniku motywacji. Nie odebrano wszystkich
wariantów pending/null, niepustego profilu, pełnego E3/E4, push/import/WorkManager,
Gemini/E7, recovery/retencji ani KO32. Nowy kandydat0.8.23/Room14 pozostaje
osobnym odbiorem; testy CI i lokalne nie zastępują wspólnej próby APK/API.

## Odpowiedź na O3-083: jeden posiłek, utrata lokalnego ACK, ponowienie

**Oracle O2 przygotowany; nowa próba NOT_RUN.** Najpierw jeden syntetyczny
Meal/create w jednej partii, bez recovery i równoległych edycji. Serwer zatwierdza
każdą operację osobno: przy wielu operacjach może zatwierdzić tylko początek
partii. Jedna operacja ogranicza pierwszy eksperyment do jednej niewiadomej.

Podstawa: [kontrakt sync](../e0/SYNCHRONIZACJA.md),
[integracja E4](../e4/INTEGRACJA_O1.md),
[router](../../backend/src/calorie_app/modules/sync/router.py),
[service](../../backend/src/calorie_app/modules/sync/service.py),
[schemat runtime](../../backend/src/calorie_app/modules/catalog/resources/sync.schema.json)
i istniejące [przypadki PG](../../backend/tests/integration/test_e4_push.py).
W `execute_one` transakcja kończy się przed zwrotem wyniku do HTTP.
Nie uruchamiano tych testów ponownie dla zmiany dokumentacji.

### Co musi pozostać takie samo

- Backend używa `(owner_id, operation_id)` i SHA256 `canonical_json(operation)`.
  Lokalny batch ID nie trafia na wire, a push nie używa `Idempotency-Key`.
  Hash operacji nie obejmuje checkpointu; SHA256 całej utrwalonej koperty
  jest osobnym dowodem niezmienności po stronie klienta.
- W tej próbie ponawiamy identyczną utrwaloną kopertę: protocol_version,
  sync_epoch, checkpoint, kolejność i liczba operacji oraz UUID, entity_id,
  action, base_revision i payload operacji. Bez nowego UUID, edycji Room,
  rekonstrukcji body lub przepakowania operacji. Bearer może zostać prawidłowo
  odnowiony dla tego samego konta; nie jest częścią niezmiennego body.
- Właściciel pochodzi z uwierzytelnionego principal, nie z body.
  Generacja/epoka/installation scope pozostają zgodne z checkpointem
  i aktualnym kontem. PushResponse ma sync_epoch, server_time, results;
  **nie wydaje checkpointu ani account_generation**.

### Kolejność i rozdzielenie dowodów

| Krok / właściciel | Wymagany dowód |
|---|---|
| C0 — O1 i operator PG O3 | Prywatny baseline dedykowanego syntetycznego konta: brak wskazanego Meal/receipt na serwerze, stan dnia i counter; Room ma utrwaloną partię/wire/hash, niepotwierdzony outbox, brak trwałego ACK i nowy Meal z serverRevision0. Osobny baseline gościa/B |
| Wysłanie — O1 | Rzeczywisty mechanizm APK i HTTPS. Jednorazowa bariera validation po pełnej poprawnej HTTP200, przed wywołaniem applyAck/utrwaleniem ACK. Czas ograniczony, poza mutexem i transakcją Room; bez drugiego parsera ani zmian TLS/guardów |
| C1 — O3, analiza O2 | Nowa niezależna transakcja read-only PG widzi zatwierdzony Meal, jego składniki/snapshot, receipt `(owner, operation_id)` z hash/epoch/revision1 i właściwe sync_changes. W tym czasie O1 potwierdza brak trwałego ACK w Room, potem rzeczywiście zabija proces klienta |
| Restart — O1 | Przed ponowieniem nadal ta sama utrwalona partia, UUID i wire/hash, brak zapisanego ACK. Bez clear/reinstall/manualnej edycji lub nowej operacji |
| Replay — O1 | Istniejący transport wysyła tę samą kopertę; HTTP200, zgodna sync_epoch i jeden wynik already_applied z pierwotną revision1; trwałe atomowe przyjęcie ACK, outbox potwierdzony, partia zakończona, lokalne serverRevision1 |
| C2 — O3, analiza O2 | Nadal jeden Meal i jeden receipt; w porównaniu C1→C2 brak zmian receipt/hash/revision, posiłku/składników i brak nowych pozycji counter/sync_changes od replay. Historia oraz dane gościa/B zachowane według prywatnego porównania O1 |

C1 musi pochodzić z osobnego odczytu po COMMIT: rozpoczęcie żądania, log
HTTP lub timeout klienta same nie wystarczają. Operator filtruje odczyty po
uzgodnionych prywatnie UUID/owner, bez czyszczenia bazy i eksportu danych.
O2 analizuje przekazany neutralny wynik; ten dokument nie deklaruje dostępu
O2 do PG ani wykonania C0/C1/C2. W czasie próby nie ma konkurencyjnych zapisów
źródłowych tego konta; projekcje tła rozlicza się oddzielnie.

Pierwszy wynik to `accepted`, replay `already_applied`; nie porównujemy
całej odpowiedzi bajt w bajt. Zgodne pozostają operation_id, entity_id,
pierwotna revision1 i recovery_mapping=null; server_time/X-Request-ID mogą
się zmienić. Zapisany status receipt pozostaje accepted. Lokalny
`MealPushAckResult.replay=false` przy pierwszym utrwaleniu odpowiedzi
already_applied jest poprawny: lokalne replay=true dotyczy już zapisanego ACK,
a nie samej deduplikacji serwera.

**Jedna operacja Meal może legalnie utworzyć DiaryDay i dwa sync_changes.**
Nie wymagamy counter+1 ani jednego wiersza zmian w C0→C1; sprawdzamy faktyczny
efekt operacji i ewentualnego dnia. Brak dodatkowych mutacji dotyczy C1→C2.

### Wejścia, wynik i następny krok

- **O1:** publikuje dokładny commit/manifest/versionCode/Room/applicationId
  i SHA256 APK+drivera oraz potwierdza podłączenie transportu do kontrolera
  i trwałego ACK. W odczytanym PR129/head a41a5cb podłączenie nadal jest
  następną częścią [instrukcji O1](https://github.com/Roseru/aplikacja-mobilna/blob/a41a5cb558b39ee2adde29d731fee60eba07bf8f/android/WYSYLANIE_KOLEJKI.md).
  Istniejący gate spóźnionego GET nie dowodzi obsługi POST. O1 potwierdza
  konkretną ograniczoną technikę przerwania, obserwację C1 przed ACK i restartu
  przed retry; ewentualny mały hook pozostaje validation, z osobnym SHA.
- **O2/O3:** przed startem porównują dokładny kandydat/backend/kontrakt
  i rzeczywiste schema24. Zgodność bieżącego main nie dowodzi zgodności
  używanego obrazu. Jeśli trzeba nowszego backendu, O3 przygotowuje odrębne
  środowisko z syntetycznymi kontami, bez aktualizacji używanej instalacji,
  zmiany epoki lub jej istniejących kopii.
- **O3:** po gotowości O1 uzgadnia nowe ograniczone okno i obserwacje PG,
  dostarcza aktualny TLS/issuer/scope oraz receipt osobnego zamknięcia obu stron.
  Kontakt z A1 i nową próbę sieciową właściciel na razie pominął; ten odbiór
  przygotowuje wejścia w repozytorium, bez otwierania okna lub kontaktu.
- **PASS** dopiero po C0/C1/C2, dowodzie braku lokalnego ACK przed zabiciem
  procesu i rzeczywistym replay bez duplikacji. Naruszony invariant to FAIL.
  Brak kandydata/zgodności/deterministycznego przerwania to NOT_RUN.
  Jeśli ACK zdążył się utrwalić albo gate wygasł przed przerwaniem,
  ta konkretna próba utraty ACK pozostaje NOT_RUN; nie nadpisuje to innych wyników.
- Wygaśnięcie checkpointu powyżej30dni (`409 sync_reconciliation_required`),
  zmiana epoki (`409 sync_epoch_changed`) lub generacji
  (`409 account_generation_changed`) przerywa ten scenariusz i wymaga
  osobnego uzgodnienia. Nie zmieniamy klucza/body dla wymuszenia PASS.
  Cudzy/uszkodzony token daje `422 invalid_sync_token`. Testy recovery,
  konfliktów, importu, WorkManager, E7 i KO32 pozostają oddzielne.

Publiczny receipt podaje ID próby, wersje/SHA, UTC, status/code/request_id,
porządek kroków i osobne wyniki Room/PG. Prywatne UUID kont/operacji, body,
tokeny, Room/WAL i raw logi pozostają poza Git. O1/O3 dopisują własne
potwierdzenie i wejścia w [jedynym dzienniku](../KOMUNIKACJA_AGENTOW.md),
w odpowiedzi na O2-044/O3-083; O2 nie potwierdza odczytu za inne osoby.
