# Przygotowanie obserwacji PostgreSQL dla replay E4 — O3

20.10.2026. **Narzędzia przygotowane; wspólna próba APK/API NOT_RUN.**
O3 odczytał [oracle O2](ODBIOR_R2_R3_ORACLE_E4_O2.md), O2-044 i O3-083
w [jedynym dzienniku](../KOMUNIKACJA_AGENTOW.md).
Źródło sesji/UI/ACK jest opublikowane w PR129. Driver prepare/hold/replay
z PR138 i ręczny Meal z PR139 pozostają odrębnymi draftami. Nadal brak
dostarczonego skonfigurowanego, zintegrowanego i w pełni zakwalifikowanego APK
do wspólnej próby; wcześniejsze320native nie obejmują tych nowych zmian.
O1 ma podać niezmienny commit, manifest,
versionCode/Room/applicationId, SHA256 APK i drivera, technikę przerwania,
gotowość oraz aktualne stanowisko. Wiadomość do O1 została
[wysłana i odczytana zwrotnie](https://github.com/Roseru/aplikacja-mobilna/pull/129#issuecomment-6276564094).
Nie oznacza to, że O1 ją przeczytał lub zaakceptował start.

## Używana instalacja i sprawdzona zgodność

- Rzeczywisty schemat: `0024_e9_history_graph`, PostgreSQL17; API image
  `sha256:05c1792f3551725f0303cc3786892771392532a25edc18ff710faad9e6b7e9a9`.
  Nie wdrażano main/schema26 ani nowych zależności do tej instalacji.
- 14 plików odczytanych z działającego obrazu odpowiada archiwalnemu
  `8ff7c0c1f0df7b579136cf6877b20717eb5ae6a4` po normalizacji CRLF→LF:
  sync router/service/repository/models/tokens/schemas/transport,
  diary models/service, catalog validation, core wire oraz trzy schematy
  sync/common/domain. Te 14 plików jest też bajtowo zgodnych z checkoutem
  main `4228ccafdf01a8936dc39bc1964f5d325504ec04`.
  To kontrola wskazanych źródeł, nie deklaracja pochodzenia całego obrazu.
- Sprawdzono rzeczywiste kolumny tabel obserwacji. Wygenerowany SELECT
  wykonał się w transakcji read-only na schema24, dla losowego nieistniejącego
  właściciela, w około0,64s łącznie z kontrolą kontenerów. To próba zgodności
  SQL bez zapisów, nie baseline C0, próba synchronizacji ani odbiór danych O1.
- Odczyt operatorski o22:29 CEST: readiness/discovery HTTP200, oryginalny
  issuer i CA; wymagany monitoring OK, finalizer expected_disabled,
  AI not_deployed. HTTPS sprawdzono przez loopback z pełną weryfikacją
  oryginalnej tożsamości TLS. Bezpośrednia próba starego adresu issuer
  z tego hosta nie połączyła się. Osiągalność z aktualnego stanowiska O1
  wymaga osobnego uzgodnienia; nie jest potwierdzona tym pomiarem.

Dokładnego kandydata O1 nadal trzeba porównać z tym kontraktem i obrazem.
Jeśli wymaga nowego backendu, potrzebne jest osobne środowisko z syntetycznymi
kontami. Używana instalacja, epoka i jej kopie nie są aktualizowane przy okazji.

## Odczyty C0/C1/C2

[e4_observer.py](../../infra/integration/e4_observer.py) używa wyłącznie
`docker inspect` i `docker exec ... psql -X`. Nie wywołuje Compose,
installerów, migracji, API push ani mechanizmu tworzenia kont. Każde `capture`
otwiera osobne połączenie psql i transakcję `REPEATABLE READ READ ONLY`,
z limitem zapytania5s, oczekiwania na blokadę1s i procesu15s.
Sprawdza etykiety projektu/usługi, stan kontenerów, obraz API, schemat i epokę.
UUID/datę waliduje przed złożeniem SQL; nazwy tabel są stałe.

Plan i wyniki operator zapisuje w prywatnym katalogu z odpowiednim ACL,
poza Git, np. pod `.tools/`. Plik wyniku jest tworzony wyłącznie jako nowy;
istniejący receipt nie jest nadpisywany. Konsola nie wypisuje SQL, body,
kont, surowych wierszy lub błędów psql. Plan zawiera dokładnie:

| Pole | Wartość uzgodniona prywatnie przed rzeczywistą próbą |
|---|---|
| `trial_id` | Nowy UUID próby |
| `owner_id` | Dedykowane syntetyczne konto, aktywne i po bootstrap/pull |
| `operation_id`, `entity_id` | UUID jednej zamrożonej operacji Meal/create |
| `sync_epoch` | Epoka z bootstrapu, zgodna z instalacją i checkpointem |
| `local_date` | Data posiłku w formacie YYYY-MM-DD |
| `operation_sha256` | Wynik `fingerprint(operation)` z rzeczywistego backendu |
| `item_count` | Liczba składników zapisanego posiłku, 1..100 |
| `expected_schema`, `expected_api_image` | Faktyczny schemat i image ID uzgodnionego serwera |
| `envelope_sha256` | SHA256 dokładnych bajtów zamrożonej koperty O1, niezależny od hasha operacji |
| `expected_meal` | Pełny payload Meal z tej samej koperty, zweryfikowany przed C0, nigdy kopia odczytu C1 |

`operation_sha256` jest wynikiem `fingerprint(operation)` serwera,
nie hashem całej koperty ani lokalnym batch ID. Nowe `prepare` używa istniejących
`parse_json` (w tym ochrona przed duplikatami kluczy), `preflight_structure`
i `fingerprint` z **runtime backendu zgodnego z uzgodnionym obrazem**.
Nie uruchamia API ani bazy i nie implementuje drugiego parsera protokołu.
Wymaga dokładnie jednej operacji meal/upsert z base_revision=null,
epoką zgodną z kopertą i poprawnym payloadem Meal. Przed C0 O1/O2/O3
porównują hash bajtów koperty z prywatnym dowodem prepare O1; po restarcie
O1 dowodzi ich niezmienności. Walidacja offline nie potwierdza ważności
checkpointu ani właściciela tokenu — to nadal osobne warunki próby.

Operator przygotowuje prywatny `context.json` z dokładnie czterema polami:
`trial_id`, `owner_id`, `expected_schema`, `expected_api_image` oraz prywatny
`request.json` będący **dokładnym eksportem utrwalonej koperty O1**, bez
rekonstrukcji/edycji JSON. `prepare` tworzy nowy `plan.json`; pozostałe pola
wyprowadza z tego jednego wejścia. Zachowaj wejścia i wynik z prywatnym ACL
poza Git, logami publicznymi i OneDrive. Nie dopasowuj planu do odczytanej bazy.
Hash całego planu w C0/C1/C2 wiąże oczekiwaną treść, operation_sha256 oraz
envelope_sha256; zmiana planu po C0 przerywa porównanie. Sama obecność
request_hash w receipt nie dowodzi treści zapisanej przez serwer.

Przykład poleceń z katalogu repozytorium; pliki wejściowe trzeba najpierw
uzgodnić i przygotować. Tylko `prepare` wymaga zgodnego runtime backendu;
`capture` i `compare` nadal wymagają wyłącznie stdlib:

```powershell
# Offline, w zgodnym runtime backendu; żadnych wywołań HTTP lub zapisów DB.
python infra/integration/e4_observer.py --plan .tools/e4-private/context.json prepare --request .tools/e4-private/request.json --output .tools/e4-private/plan.json
python infra/integration/e4_observer.py --plan .tools/e4-private/plan.json capture --settings .tools/local-integration/operations/settings.json --phase C0 --output .tools/e4-private/c0.json
# C1 dopiero po rzeczywistym HTTP200, gdy O1 nadal trzyma barierę przed ACK.
python infra/integration/e4_observer.py --plan .tools/e4-private/plan.json capture --settings .tools/local-integration/operations/settings.json --phase C1 --output .tools/e4-private/c1.json
# C2 po realnym kill/restart, retry tej samej koperty i trwałym lokalnym ACK.
python infra/integration/e4_observer.py --plan .tools/e4-private/plan.json capture --settings .tools/local-integration/operations/settings.json --phase C2 --output .tools/e4-private/c2.json
python infra/integration/e4_observer.py --plan .tools/e4-private/plan.json compare .tools/e4-private/c0.json .tools/e4-private/c1.json .tools/e4-private/c2.json
```

C0 wymaga braku wskazanego Meal/receipt/składników. C1 sprawdza Meal revision1,
zaakceptowany receipt z właściwym hashem/epoką i brak recovery, a także
**treść względem expected_meal przygotowanego przed próbą**. Odczyt `meal_content`
odwzorowuje mapowanie diary/service: title, occurred_at, time_zone, local_date,
meal_type, goal_id, ration oraz składniki uporządkowane przez position,
z item_id, nazwą, product/revision, quantity/unit, basis_unit, czterema wartościami
nutrition_per_100, density/source, nutrition_origin, formula_version
i ration_component_position. Nie porównuje surowego JSON z całym wierszem ORM:
owner/meal_id, revision i deleted sprawdzane są oddzielnie, a generowany DiaryDay
nie jest polem payloadu. Decimal porównywany bez zaokrągleń (np.150=150.000000),
null pozostaje różny od zera; occurred_at porównywany jako chwila UTC z precyzją
mikrosekund. Nazwy, strefa, data, jednostki, źródła i kolejność są zachowane.
Nowy format snapshotu to **2**; stare plany/snapshoty nie kwalifikują tej kontroli.
Dodanie DiaryDay oraz drugiej zmiany jest legalne. Brak counter w C0 oznacza
pozycję0 i legalne utworzenie jego pierwszego wiersza przy push. C1→C2 wymaga zachowania
rewizji, receipt, counter i odcisków SHA256 wszystkich wierszy tego właściciela
w sześciu tabelach: meals, meal_items, diary_days, sync_receipts,
sync_changes i sync_counters. Wykrywa też mutację treści przy tej samej liczbie
wierszy. Odciski służą obserwacji; nie są kluczem idempotencji protokołu.
Wymagany jest brak równoległych zapisów tego konta; projekcje tła pozostają
poza tym zestawem tabel i wymagają odrębnej interpretacji.

## Granice wyniku i przekazanie

Narzędzie potwierdza wyłącznie `server_observations: PASS`. Nie dowodzi HTTP200,
braku ACK w Room podczas C1, chwili kill/restart, identyczności wire, ani
izolacji gościa/B na telefonie. O1 dostarcza te dowody osobno, w tym
`already_applied` z pierwotną revision1. Pierwsze lokalne przyjęcie takiej
odpowiedzi może poprawnie dać lokalne replay=false.
Brak wymaganego wejścia lub wygaśnięcie bariery przed przerwaniem oznacza
NOT_RUN dla scenariusza utraty ACK. Naruszenie invariantów oznacza FAIL,
bez zmiany UUID/body lub ponownego baseline dla ukrycia wyniku.

Testy narzędzia obejmują walidację wejść, ochronę wcześniejszego receipt
i błędów prywatnych oraz rzeczywisty PG17: nowy/istniejący DiaryDay,
commit→osobny odczyt→replay i wykrywanie mutacji przy tej samej liczbie
wierszy. O2 potwierdził kontrprzykład starego head c0aef367: błędny C1
utrzymany w C2 dawał PASS przy poprawnych licznikach i receipt/hash. Nowa
regresja zmienia treść już przed C1 (makro null→0, ilość lub źródło), zachowuje
receipt i identyczny błędny C2, a porównanie wymaga odmowy. To testy
infrastruktury na oddzielnej syntetycznej bazie schema26;
nie zastępują odbioru APK lub wspólnej próby na schema24.

O1 odpowiada na O2-044/O3-084 we własnym wpisie dziennika. Po otrzymaniu
kandydata O3/O2 domykają jego zgodność, O1 potwierdza czas na C1 i restart,
a O3 uzgadnia nowe ograniczone okno dla aktualnego peera. Oba końce zamykają
je osobno z receipt. Nie otwarto ponownie dawnych portów18444/18446.
