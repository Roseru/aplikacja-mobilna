# Przygotowanie obserwacji PostgreSQL dla replay E4 — O3

21.10.2026. **Zgodność źródłowa kandydata138+139 PASS; runtime PARTIAL,
próba APK/API NOT_RUN.** O2 odpowiedział na O1-092 w O2-048
[jedynego dziennika](../KOMUNIKACJA_AGENTOW.md). Konkretne źródło APK,
zakres sprawdzenia oraz brakujące wejścia opisuje końcowa sekcja tej instrukcji.
Połączony kandydat offline został przekazany; oddzielny skonfigurowany APK
z aktualnymi issuer/API/CA i nowym manifestem pozostaje do dostarczenia.

## Ostatnia opisana instalacja O3 — historyczne potwierdzenie

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

Źródłowe porównanie konkretnego kandydata znajduje się poniżej. Nadal trzeba
potwierdzić aktualny obraz, jego kolumny i osiągalność; ten zapis nie jest
nowym odczytem instalacji.
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


## O2: kandydat138+139 — ocena źródłowa 21.10.2026

**PASS zakresu źródłowego i małej próby offline; PARTIAL runtime;
BLOCKED start wspólnej próby na wejścia O3/O1.** Nie znaleziono błędu
wymagającego zmiany obserwatora z2a8dd57 ani kodu Androida.

Dokładne kwalifikowane źródło APK to
`d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075`;
[publikacja i manifest czterech hashy](https://github.com/Roseru/aplikacja-mobilna/blob/f7cf71e670154b3d5452532693526a3aa4925444/android/KANDYDAT_E4.md)
na PR138/head`f7cf71e670154b3d5452532693526a3aa4925444`.
Diff d3f6dba→f7cf71e obejmuje tylko KANDYDAT_E4.md, android/README.md
oraz dziennik; kod i wejścia kompilacji są identyczne. Rodzic to
PR139/a1f547a398e878b4f6429ffdb1b7a99f0903e51d, zależny od129;
PR140 jest odrębnym producentem i nie jest tym kandydatem.
O1 raportuje329/329native offline,330debug/369validation JVM i opt-in build;
O2 nie powtarzał Gradle, emulatora, instalacji ani tych testów.
Pakiet0.8.23/code34/validation1034/Room14 nadal nie ma issuer/API/CA overlay.

### Sprawdzona ścieżka w dokładnym kodzie

Linki kodu poniżej wskazują niezmienny source APK d3f6dba, nie późniejszy head.

| Zakres | Odczytany kod i wniosek |
|---|---|
| Normalny producent konta | [DiaryRepository:85–138,225–237](https://github.com/Roseru/aplikacja-mobilna/blob/d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075/android/app/src/main/java/pl/roseru/kalorie/data/DiaryRepository.kt#L85): ownerTransaction wiąże lease; nowe Meal/Item/operation oraz lokalny produkt/szkic są atomowe. Kanoniczny wariant wymaga prywatnego produktu konta, zdrowego binding, bez catalogJson. Gość/legacy/recovery i ilości7–12miejsc pozostają lokalne. |
| Treść i UUID | [ManualMealWire:15–34](https://github.com/Roseru/aplikacja-mobilna/blob/d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075/android/app/src/main/java/pl/roseru/kalorie/core/sync/ManualMealWire.kt#L15) oraz [MealWire:28–58](https://github.com/Roseru/aplikacja-mobilna/blob/d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075/android/app/src/main/java/pl/roseru/kalorie/core/sync/MealWire.kt#L28): Decimal jako string, null osobno od0, g/basis g dla tego formularza, mikrosekundy/UTC/strefa/lokalna data. item_id i operation_id trwałe; upsert/base_revision=null/epoka binding. product=null, nutrition_origin=manual, formula_version=nutrition_v1, goal/ration/density=null. Lokalny productId i opis źródła pozostają w Room, nie są referencją katalogową na wire. |
| Freeze i ponowienie | [MealPushStore:96–169](https://github.com/Roseru/aplikacja-mobilna/blob/d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075/android/app/src/main/java/pl/roseru/kalorie/data/MealPushStore.kt#L96): konto/generacja/epoka/contextRevision i ukończony snapshot z checkpointem są bramką; prepare utrwala kopertę/hash i operacje przed siecią, open odczytuje tę samą kopertę z pierwotnym checkpointem. [PushProtocol:28–97](https://github.com/Roseru/aplikacja-mobilna/blob/d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075/android/app/src/main/java/pl/roseru/kalorie/core/sync/PushProtocol.kt#L28) wymaga identycznych kanonicznych bajtów przy restore. |
| POST i ACK | [BootstrapGateway:178–250](https://github.com/Roseru/aplikacja-mobilna/blob/d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075/android/app/src/main/java/pl/roseru/kalorie/session/BootstrapGateway.kt#L178) wysyła push.body jako POST/api/v1/sync/push, Bearer i JSON, bez Idempotency-Key lub batch ID na wire; brak redirect, no-store i bounded body. [SessionController:2033–2039](https://github.com/Roseru/aplikacja-mobilna/blob/d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075/android/app/src/main/java/pl/roseru/kalorie/session/SessionController.kt#L2033) wywołuje hold po prepareAck, przed atomowym applyAck. MealPushStore:213–287 i PushProtocol:78–97 akceptują accepted/already_applied z pierwotną revision1, zgodnymi ID i recovery_mapping=null; revision/outbox/response są zapisywane razem. Lokalny replay=false przy pierwszym ACK jest legalny. |
| Driver i oracle | [LiveMealReplayTest:111–210](https://github.com/Roseru/aplikacja-mobilna/blob/d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075/android/app/src/liveReplay/java/pl/roseru/kalorie/LiveMealReplayTest.kt#L111) wymaga jednej wskazanej świeżej operacji, zapisuje request/hash, kontroluje brak ACK/revision0, HTTP200/no-store, inny PID/start i niezależny czas kill przed deadline; replay wymaga tej samej koperty oraz already_applied/revision1. [Test łączący funkcje:2663–2717](https://github.com/Roseru/aplikacja-mobilna/blob/d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075/android/app/src/androidTest/java/pl/roseru/kalorie/SessionSecurityTest.kt#L2663) używa producenta, ale fixture transport i cancellation; jawnie pusty HTTP receipt nie dowodzi realnego HTTP/COMMIT/kill. |

Backendowy klucz to `(owner_id, operation_id)`;
[fingerprint i replay:71–112](https://github.com/Roseru/aplikacja-mobilna/blob/8ff7c0c1f0df7b579136cf6877b20717eb5ae6a4/backend/src/calorie_app/modules/sync/service.py#L71)
wiążą operację i pierwotną rewizję. Router ustala właściciela z Principal,
a context sprawdza generację/epokę/podpisany checkpoint. `storageScope` z planu
drivera jest lokalnym zakresem, nie automatycznie `owner_id` PG. O2/O3 muszą
prywatnie powiązać `binding.accountId` z rzeczywistym UUID konta backendu
używanego przez token. Batch ID i envelope_sha256 nie zastępują operation_id
ani backendowego fingerprint.

### Referencja instalacji i próba offline

Ostatni opis O3 wskazuje image ID
`sha256:05c1792f3551725f0303cc3786892771392532a25edc18ff710faad9e6b7e9a9`
i schema`0024_e9_history_graph`. O3 porównał14 plików obrazu z
`8ff7c0c1f0df7b579136cf6877b20717eb5ae6a4`; to referencja wskazanych plików,
nie dowód source commita całego obrazu ani dzisiejszego stanu instalacji.
O2 teraz porównał po LF te same14 plików z HEAD93894a9 i maine651fea:
7 sync(router/service/repository/models/tokens/schemas/transport),
diary models/service, catalog validation, core wire i3schematy
sync/common/domain — wszystkie identyczne. Trzy assets sync kandydata APK
również identyczne z referencją. Mapowanie Meal/Item w diary/service i kolumny
modeli odpowiadają projekcji meal_content obserwatora: pełna treść,
pozycja/kolejność, Decimal/null, UTC, provenance i snapshoty. Nowa projekcja
nie została tutaj wykonana na używanej schema24; historyczny odczyt O3
wcześniejszego SELECT nie stanowi jej bieżącego odbioru.

Mała próba O2: **949B publicznego syntetycznego wektora, ręcznie odtworzonego**
z ManualMealWire i danych SessionSecurityTest (150.5g,100.5kcal/100g,
protein=null/fat=0/carbs=12.25, manual/product=null). Nie jest eksportem
Room ani uruchomionym wynikiem serializatora Kotlin/Android. W istniejącym
runtime backendu użyto rzeczywistych parse_push, preflight_structure,
fingerprint oraz prepare_plan obserwatora: **PASS**; expected_meal równy
wejściu. Zmiana whitespace zmieniła hash koperty, zachowując hash operacji;
null→0 zmieniło hash operacji i oczekiwaną treść;7miejsc ilości odrzucono.
Checkpoint był jawnie syntetyczny i niepodpisany, image ID planu syntetyczny;
nie sprawdzano uprawnień, podpisu/terminu tokenu, HTTP, SQL lub DB.
Źródła normatywnego parsera/preflight/fingerprint w tej próbie są zgodne
ze wskazaną referencją14plików; pełnego starego obrazu nie uruchamiano.

### Konkretna odpowiedź na O1-092 i następne wejścia

1. **O3:** potwierdza aktualny image ID/wersję schematu i zgodność nowej
   projekcji meal_content na docelowej instalacji albo wskazuje osobne
   środowisko syntetyczne. Dostarcza aktualne publiczne issuer/API i zaufane
   CA z identyfikacją; prywatnie wskazuje lokalizację danych konta
   syntetycznego i sposób uzyskania sesji. Żaden dawny adres, pomiar readiness
   lub zamknięte okno nie jest tu przyjęte jako aktualne. O2 nie ma tych
   bieżących wejść i nie ogłasza gotowości używanego runtime.
2. **O1:** po tych wejściach buduje oddzielny skonfigurowany validation APK
   i opt-in testAPK, przekazuje nowy manifest/commit/applicationId/code/Room/SHA
   i właściwą kwalifikację zmienionych wejść. Zachowuje osobny profil testowy.
   Po sesji/bootstrapie/pełnym pull tworzy normalnym formularzem jeden nowy
   ręczny Meal konta, bez seed SQL, importu lub Gemini. Eksportuje prywatnie
   dokładne utrwalone bajty żądania i hash; operator nie rekonstruuje JSON.
3. **O1/O2/O3:** uzgadniają właściciela, epokę, checkpoint i plan przed C0.
   O3 wykonuje niezależny PG C0; O1 hold po HTTP200 przed ACK; O3 C1;
   operator realny force-stop dedykowanego validation przed45s deadline
   z niezależnym czasem; O1 nowy proces i identyczne retry/ACK; O3 C2/compare.
   Pozostałe minimum20s po sprawdzeniach drivera musi pomieścić C1 i kill;
   timeout/release/brak czasu oznacza NOT_RUN. Nowe ograniczone okno wymaga
   osobnego uzgodnienia, żadnego nie otwarto tym odbiorem.

**Live E4/prepare/hold/replay/kill/PG C0C1C2, Gemini/E7-R/recovery/KO32 NOT_RUN.**
Kwalifikacja źródłowa nie zamyka PR129, pełnego E4 ani zgodności pozostałych
producentów. Nie uruchamiano usług O3/API/Gemini, nie zmieniano baz,
kont/epoki/instalacji, nie kontaktowano A1 i nie testowano LAN/relay.
