# Trwały klient referencyjny synchronizacji E4 - osoba 2

Klient Python działa na osobnym pliku SQLite każdego urządzenia i rzeczywistym
HTTP `/api/v1/sync/push` / `/api/v1/sync/pull`. Wymaga zainstalowanych zależności
backendu Python 3.13. Nie zastępuje Room, APK, WorkManager ani integracji OIDC O1.
Nie zapisuje access tokenów w bazie lub outbox. Token dostarcza sesja wywołująca,
związana z przechwyconą dokładną tożsamością. HTTPS jest obowiązkowy poza loopback.

Po poprawce E4 domyślny `SyncHTTP.push` dobiera jedną porcję do 100 operacji
i 1 048 576 rzeczywistych UTF-8 bajtów CAŁEJ koperty, wliczając checkpoint,
pola i separatory. Pomiar i transport używają `encode_json`:sort_keys,
ensure_ascii=False, kompaktowe separatory, strict UTF-8. Kolejne wywołania
kontynuują kolejkę; CLI `push` wysyła do `no_operations`. Niewybrane pozostają
queued, wybrane przechodzą na sent atomowo. Regrouping nie zmienia operacji,
ID, epoki, base_revision lub hashów. Pojedynczy oversized wire daje
`operation_too_large` z zachowaniem danych. Nie ma osobnego ID paczki.

Goal recovery drugiego urządzenia zachowuje oryginalny timeline_base_revision.
Wyjątek od osi nowej decyzji wymaga potwierdzonego mapping tego samego scope,
account/generation/epoch/lease/contextRevision i identycznego żywego Goal targetu
z właściwą revision. Inna treść/typ/źródło/target oznacza odmowę. Globalna
kontrola osi pozostaje. Addytywna SQLite `mapping_contexts` nie przepisuje
starych danych; stare mapping bez dowodu bieżącego kontekstu wymagają
nowego ukończonego pull. Tylko nowe zależne Meal używają target aliasu.

Uruchamiaj polecenia z katalogu repozytorium po `uv sync --project backend --locked`:

```text
uv run --project backend --locked python -m tools.sync_client --database backend/var/device-a.sqlite register --issuer ISSUER --subject SYNTHETIC_SUB
uv run --project backend --locked python -m tools.sync_client --database backend/var/device-a.sqlite select LOCAL_SCOPE_UUID
uv run --project backend --locked python -m tools.sync_client --database backend/var/device-a.sqlite bootstrap-result BOOTSTRAP_RESPONSE_FILE
uv run --project backend --locked python -m tools.sync_client --database backend/var/device-a.sqlite pull --api http://127.0.0.1:8000 --full
uv run --project backend --locked python -m tools.sync_client --database backend/var/device-a.sqlite source weight ENTITY_UUID create contracts/examples/valid/weight.json
uv run --project backend --locked python -m tools.sync_client --database backend/var/device-a.sqlite materialize SOURCE_UUID
uv run --project backend --locked python -m tools.sync_client --database backend/var/device-a.sqlite push --api http://127.0.0.1:8000
uv run --project backend --locked python -m tools.sync_client --database backend/var/device-a.sqlite pull --api http://127.0.0.1:8000
uv run --project backend --locked python -m tools.sync_client --database backend/var/device-a.sqlite status
```

Najpierw utwórz prywatny katalog `backend/var`. Wynik bootstrapu pochodzi
z rzeczywistego E3 aktualnej sesji, bez importu danych gościa. Dostarcz token
przez środowisko `SYNC_ACCESS_TOKEN`, z prywatnego magazynu sesji; nie podawaj go
w argumentach, nie drukuj ani nie wersjonuj pliku z tokenem. Narzędzie zakłada,
że operator potwierdził jego zgodność z wybranym kontekstem. W kodzie adaptera
`token_supplier(context)` musi sprawdzać tę zgodność przed wywołaniem.
Drugi klient używa `backend/var/device-b.sqlite`, nigdy wspólnego pliku A.

## Trwałe dane i transakcje

`SyncStore` ma WAL, `synchronous=FULL`, FK oraz `BEGIN IMMEDIATE` do mutacji.
Wywołanie `close()`/ponowne otwarcie pliku zachowuje cały stan. Źródła
`originals` są append-only: dokładny dawny JSON, UUID, format i SHA-256 bajtów.
`drafts` zapisuje stan wymagający uzgodnienia. `wire_ops` utrwala osobną
wersję adaptera v1, operację, hash, epokę, wynik i stan kolejki. Trigger odmawia
zmiany treści/ID/hash/epoki i fizycznego usunięcia źródeł lub wire. Zwykła pierwsza
materializacja zachowuje UUID źródłowej operacji (`source_id`); nowe świadome
recovery otrzymuje nowy ID operacji.

Późniejsza edycja jest kolejnym źródłem/draftem. Czeka na wynik poprzednika,
a jej `base_revision` pochodzi z shadow/ACK serwera, nigdy z local_revision.
HTTP bez 200, przerwanie po server commit lub spóźniona odpowiedź nie wydają ACK.
Retry zachowuje wire. Wszystkie wyniki i kolejność są walidowane przed
zatwierdzeniem odpowiedzi; błędny wynik wycofuje całe lokalne zastosowanie paczki.
Zaakceptowane operacje pozostają dowodem zamiast zniknąć z bazy.

`pull_sessions` i `pages` zachowują przechwycony kontekst, tryb, limit, request,
strony oraz następną pozycję. `staged_entities` pozostaje oddzielony od shadow.
Jedna transakcja zapisuje stronę i token. Ostatnia strona atomowo publikuje
shadow/mapowania/żądane receipts/checkpoint; oryginały i outbox pozostają
niezmienione. `resume-pull --api API SESSION_UUID` kontynuuje po restarcie.
Przerwany/wygasły snapshot wymaga nowego pełnego odczytu, zachowując stare
strony. Limit obejmuje sumę trzech tablic. Odpowiedź HTTP jest ograniczona
do 4 MiB; błędny UTF-8, powtórzone klucze i NaN są odrzucane.

## Źródło Androida i decyzje

Lokalne `create`/`update`, Double, brak epoki i porcje do 12 miejsc nie są
wire. `adapt_source` kopiuje dane, mapuje podstawowe nazwy profilu/wagi/celu
Androida 0.7.1 i normalizuje wyłącznie rozpoznane pola Decimal. Brak metadanych
pozostaje błędem wymagającym uzgodnienia, nie fikcyjnym timestampem/strefą.
Legacy posiłek/szkic z dawnymi snapshotami wymaga jawnego ekstraktu pełnego
payloadu v1 przez `materialize(..., reviewed_payload=..., confirmed=True)`.
Zachowany oryginał umożliwia kontrolę ekstraktu bez użycia dzisiejszego katalogu.
O1 ma wdrożyć i przetestować ten ekstrakt w migracji/adapterze Room.

| Wektor źródłowy | Wynik |
|---|---|
| `1.234567000000` | `1.234567`, dokładna wartość bez straty |
| `0.000001000000` | `0.000001`, dokładna wartość |
| `1.234567000001` | trwały `precision_review`, brak wire |
| `0.000000000001` | trwały `precision_review`, bez zaokrąglenia do zera |
| dawny Double `80.0` | `80` z zachowanym oryginalnym JSON |
| NaN/Infinity, liczba ujemna | `decimal_review`, brak wire |
| legacy cel bez czasu/strefy | `legacy_goal_metadata_review`, zachowane źródło |

`metadata` dostarcza rzeczywiste ustalone brakujące dane, np. strefę dnia,
serwerową oś celu i deklarowane informacje profilu. Payloady są walidowane
normatywnymi schematami i regułami E3 przed materializacją. Istniejący własny
profil/dzień o innym UUID wymaga `natural_key_review_required`; po świadomym
uzgodnieniu nowa operacja używa kanonicznego target_id i aktualnej rewizji.
Zależny posiłek czeka na cel w potwierdzonym shadow. Nie przepisujemy wysłanych
referencji. `resolve_conflict(..., confirmed=True)` zachowuje obie wersje
i umożliwia osobny poprawiony draft z nową operacją po pull.

## Gość, konta i recovery

`bind_guest(guest_scope, context, confirmed=True)` utrwala pojedynczą decyzję
gość→konto. Zbioru nie można przypisać do B. Nie ma limitu wieku historii.
Bootstrap nie przypisuje zbioru. Najpierw pełny snapshot i checkpoint,
następnie materializacja. Scope, lease generation, account UUID/generation,
epoch i contextRevision mają osobne znaczenia. `Context` jest niezmienny;
kontrola przed wysyłką i w transakcji odpowiedzi odrzuca także A→B→A.

Zmiana epoki/generacji utrwala `requires_recovery`; bootstrap i pełny snapshot
jej nie kasują. Zwykły push jest zatrzymany. Kontrolowany tryb dopuszcza full
snapshot, odczyt zachowanych receipts i nowe świadome operacje recovery.
`materialize(..., recovery=RecoverySource, confirmed=True, target_id=NEW_UUID)`
przy recreate wymaga nowej epoki i nowego UUID, `base_revision=null`.
`prepare_push(..., recovery_only=True)` wysyła wyłącznie te operacje.
Resolve_existing wymaga aktualnego ID/revision. Stare operacje pozostają
niezmienione; `retire_old_operation(..., confirmed=True)` utrwala decyzję ich
zachowania bez ponawiania. Brak receipt nie oznacza niewykonania.

Mapowanie serwera jest autorytatywne: `result.entity_id` może być proponowanym
ID, a target w mapping rzeczywistym ID drugiego urządzenia. `aliases` zachowuje
target; jego późniejsza zmiana jest odrzucana. `remap_new_references` kopiuje
nowy payload zależności, nie modyfikuje wire/originals. Przy nowej epoce obie
treści shadow i wcześniejsze ACK pozostają; taka sama revision nie oznacza
tej samej treści. W tej samej epoce nieobecność po ukończeniu snapshotu zapisuje
konflikt usunięcia, bez automatycznego recreate tego UUID.

`finish_reconciliation(..., confirmed=True)` jest osobną atomową decyzją
po checkpointcie bieżącej epoki i rozstrzygnięciu starych operacji oraz nowych
recovery. Sama zmiana generation przy tej samej epoce wymaga full snapshot
i nowego checkpointu, bez RecoverySource tej samej epoki. Deleting utrwala
blokadę obejmującą także full pull i recovery. O1 musi oddzielnie zaimplementować
transakcyjne zakończenie tego procesu z requireReady/WorkManager.

## Wykonywalne scenariusze

```text
uv run --project backend --locked python -m pytest backend/tests/unit/test_e4_client.py
uv run --project backend --locked python -m pytest backend/tests/integration/test_e4_client_http.py
```

Integracja wymaga PostgreSQL 17 z migracjami i `TEST_DATABASE_URL` dedykowanej
bazy zakończonej `_test`. Wspólna fixture czyści wyłącznie tę bazę; uruchamiaj
autora i recenzenta na osobnych bazach, bez równoczesnych destrukcyjnych fixture.
Testy tworzą żywy uvicorn/loopback TCP, runtime rolę API i dwa pliki urządzeń:
lost ACK→restart→already_applied, konflikt dwóch edycji, przerwany snapshot
i restart stron oraz zmianę epoki z zachowaniem kolejki. Auth tych testów jest
syntetyczna; prawdziwy provider/PKCE i rzeczywisty restore starszej bazy mają
oddzielne testy E4 i dowody w raporcie. Unit z MockTransport sprawdza wyłącznie
zachowanie transportu przy awarii, nie jest wynikiem integracji HTTP/PostgreSQL.
