# Zgodność API, katalogu i synchronizacji — O2

Nowy etap O2_LEDGER_20261017_V1: schema `0026_ledger_review` na bazie
`615fb6b3`, [kontrakt](REJESTR_USUNIEC_O2.md) i [raport](RAPORT_REJESTR_USUNIEC_O2.md).
API mobilne `/api/v1`, E9 opt-in i okno30dni zachowane. Zmienia się operacyjny
protokół usunięć: nowy operator/eksporter, obowiązkowe ACK i cutoff z niezależnym
fence_pin. Starszy CLI i pełny rollback obrazu wymagają kwalifikacji O3;
0026 do0024 zachowuje ochronę/evidence, głębszy downgrade odmawia.
Poniższe historyczne receipty opisują wcześniejsze źródła, nie odbiór0026.

Stan17.10.2026: **FIX1 PASS** po trzech poprawionych P2 koordynatora.
[Nowy C2/image/schema, scratch rollback i8/8CI39031423976](ODBIOR_RECOVERY_O2.md#odebrany-zestaw-wykonawczy-c2).
[Zmiany oraz mutacje RED/GREEN](ODBIOR_RECOVERY_O2.md#fix1--odbiór-koordynatora-i-nowe-źródło-c2).
Lokalnie92unit/runner i36PG E4 PASS; pełny CI1364PG/167infra PASS.
Nie jest to odbiór APK. Pełne KO32: **WAITING_EXTERNAL**, O1/O3.
Dostawa odpowiada [masterowi](../MASTER_PROMPT_O2_ZGODNOSC_RECOVERY.md);
aktualny wspólny stan pozostaje w [dzienniku](../KOMUNIKACJA_AGENTOW.md).

## Wybrane wersje i granice dowodów

| Warstwa | Dokładne źródło / format | Co sprawdzamy | Stan i właściciel |
|---|---|---|---|
| Backend bazowy main | `a6e239558a4ab664e3f9d3b6635657876878b412` | API `/api/v1`, pojedynczy Alembic head `0024_e9_history_graph` | Odczyt i heads PASS; wynik runtime przypisany osobno do C |
| Poprzednik migracji | E8 main `a522471140150271d853d66aa06f11d868699e49`, `0021_e8_nemesis_results` | Rzeczywista migracja 0021→0024 na niepustych danych; wybór ostatniego E8 przed E9, nie fikcyjnego poprzedniego wydania | PASS lokalnie, O2; nie jest to upgrade instalacji zespołu |
| Sync legacy | protocol_version=1, sześć typów profile/goal/meal/weight/diary_day/product_draft | Brak E9 w legacy, niezmienne operacje i hash, ACK oraz snapshot | Regresje E4/E9; stan końcowego CI poniżej |
| Sync opt-in E9 | ta sama v1, `X-Sync-Capability: energy_estimates_v1` | Jawna negocjacja, osobne checkpointy/snapshoty, siódmy typ energy_estimate | Regresje `test_e9_sync.py`; nie deklarujemy obsługi przez APK |
| Katalog | schema_version=1, min_reader_version=1; demo release1/package `47bdff67-e58b-5437-919b-ec00159afbc5` | gzip SHA `65f4aae8002fd5522d0edb4689e05682103b80fbe3e6dbc68f4bf02c645b2bef`, g/ml, null, dokładne UUID+revision | Istniejący manifest `backend/data/demo/export/manifest.json`; importer w CI; demo nie jest official |
| Android scalony main | 0.8.10/code21/Room8 na a6e23955 | Odczyt Gradle, Database.kt i źródeł czytnika | Tylko odczyt, APK/API NOT_RUN, O1 |
| Android PR73 | `0228ba40d3eb4ec77cc12897793d4e5601881529`, 0.8.12/code23; validation code1023 | Odczyt Gradle; oracle spóźnionego GET w istniejącym protokole | Niescalone; rzeczywisty receipt O1 NOT_RUN |
| Android PR105 | `1e9ee1c9719378a281cfd58e250cd83c42ff3d02`, 0.8.15/code26; validation code1026 | Odczyt Gradle i aktualnej dostawy O1-054–058 | Niescalone; nie potwierdza v1 sync/Room recovery ani E9 |
| Faktycznie zainstalowany APK | Brak odczytanego w tym zadaniu artefaktu i urządzenia | versionName/code/Room/reader/APK SHA muszą pochodzić z odbioru O1 | NOT_RUN, O1; deklaracja Gradle nie jest odbiorem instalacji |

APK/reader version jest osobnym polem receipt O1 wymaganym przez
[release.py](../../infra/integration/WYDANIE.md). O2 nie przypisuje wartości readera
na podstawie samego `schema_version` katalogu. Kolejka PR61→64→73→96→105
pozostaje osobnym zakresem O1; żadnego jej kodu nie przeniesiono do backendu.

## Macierz zachowań i wykonywalne oracles

| Reguła | Oracle i dowód | Granica |
|---|---|---|
| Dokładnie 30×24h | `test_e4_tokens.py::test_checkpoint_exact_30_days_and_next_microsecond`: granica ważna, następna mikrosekunda odrzucona, więc również +1s | Unit PASS; pull410/sync_cursor_expired i push409/sync_reconciliation_required, full_snapshot |
| Zachowanie kolejki po expiry | `test_e4_client.py`: brak ACK przy błędzie, pełny snapshot zachowuje originals/outbox; legacy payload bez metadata wymaga adaptacji | Referencyjny klient O2 PASS, Room/UI NOT_RUN |
| Powrót po 61 dniach | Nowy `test_o2_return_after_61_days_reconciles_without_duplicate_create_or_resurrection` w `test_e4_push.py`: real PG prune, odmowa starego checkpointu, pełny snapshot, te same operacje create/delete ponawiane osobno | Lokalnie PASS; posiłek jeden, weight nadal deleted; nie cofamy epoki i nie resetujemy idempotency |
| Historia i hashe | `test_e4_push.py`, `test_e4_snapshots.py`, `test_e4_client.py`: minimalizacja receipt zachowuje hash/ACK, oryginalne źródło i wysłane bajty | Nowy envelope z aktualnym checkpointem nie zmienia operation_id/payload |
| Null i jednostki | Kontrakty v1, nutrition_v1 oraz nowa migracja: 150g×87/100 + 250ml×42/100 = 235.5 kcal, null makr napoju zachowany | Null nie jest zerem; bez density brak konwersji g↔ml |
| Nieznane pola | Wejściowe DTO i wersjonowane JSON Schema odrzucają nieznane pola; klient nie wysyła nieznanego payloadu automatycznie | Serwer nie obiecuje tolerowania dowolnych rozszerzeń v1; E9 ma opt-in |
| E9 legacy/opt-in | `test_e9_sync.py`: legacy pomija energy i przesuwa checkpoint, opt-in wymaga nowego snapshotu, mieszanie kontynuacji odmówione | Bez reinterpretacji dawnych goal payloadów; stare operacje pozostają historyczne |
| Epoka i generacja | `test_e4_tokens.py`, `test_e4_client.py`, `test_e4_restore.py`: podpis/owner/install/protocol, epoch przed generation/age; bootstrap nie kasuje recovery | Stary checkpoint jest odrzucany także z nową epoką nagłówka/operacji |
| Odtworzenie posiłku | Nonnull mapping accepted/already_applied, jeden SQLtarget/mapping i dokładny HTTPpayload; [dowód C2](ODBIOR_RECOVERY_O2.md#odebrany-zestaw-wykonawczy-c2) | PASS serwera; mutacje null6FAIL/duplikat7FAIL, telefon osobno |
| Scratch rollback0021 | Obraz exacta522471, backup21→upgrade24→restore21, readiness/API/dane/nowaepoka/sesje | PASS C2; produkcyjny zestaw O3 WAITING_EXTERNAL |
| Rzeczywisty APK/API | [Istniejący oracle O2-034](ODBIOR_APK_API_O2.md), poprawny DTO→logout→release→odrzucenie przez guard | WAITING_EXTERNAL O1/O3, po uzgodnieniu nowego okna 19.10 lub później |

30 dni oznacza gwarancję **przyrostowej synchronizacji**, nie retencję historii,
limit pierwszego importu gościa, wykresów lub Nemesis90dni. Po 61 dniach lokalne
dane i niewysłana kolejka nadal istnieją; po restore do nowej epoki backend nie zamienia braku w kopii na
usunięcie. W tej samej epoce obowiązuje istniejąca semantyka tombstone/snapshot;
recovery po restore wymaga jawnego uzgodnienia i nowego UUID. Zbiór gościa jest przypisywany świadomie do konta, nie ma serwerowego
konta gościa. Próbę uwierzytelnienia A/B zapewnia prawdziwy Keycloak w runnerze;
`Principal` w lokalnych testach PG jest fixture i nie dowodzi logowania telefonu.

## Wycofanie kontraktu

O3 rejestruje ostatni checkpoint wystawiony dla wycofywanej wersji, kończy jego
wystawianie i utrzymuje stary kontrakt co najmniej do `last_issued + 30×24h`.
Wystawienie następnego checkpointu przesuwa tę granicę. Deploy nie skraca ważności.
Późniejsza odmowa nadal wymaga jawnego błędu i bezpiecznej migracji/reconciliation
kolejki klienta. API v2 wymaga osobnej decyzji i odbioru O1/O2/O3.

## Powtarzalna kontrola

```text
uv sync --project backend --locked
uv run --project backend --locked python -m pytest backend/tests/unit/test_e4_tokens.py backend/tests/unit/test_e4_client.py infra/integration/tests/test_recovery_o2.py -q
uv run --project backend --locked python -m pytest backend/tests/integration/test_e9_migration.py -k o2_populated -q
```

Druga komenda PG wymaga Docker PG17 fixture albo własnego prywatnego
`E8_4_POSTGRES_CREDENTIALS` przygotowanego istniejącym helperem
`tests/support/e8_3_postgres.py::initialize_empty_cluster`. Nie używa się credentiali
instalacji zespołu. Pełny job postgres dostarcza odpowiednią własną bazę
`TEST_DATABASE_URL`; brak bazy powoduje błąd, nie pominięcie testu.
