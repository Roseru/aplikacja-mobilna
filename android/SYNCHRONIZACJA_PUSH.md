# Android — trwałe partie i odbiór odpowiedzi E4

Etap kontynuowany w [PR122](https://github.com/Roseru/aplikacja-mobilna/pull/122),
`codex/android-potwierdzenie-posilku`. Wymagania:
[integracja E4](../docs/e4/INTEGRACJA_O1.md),
[decyzje v1](../docs/e4/DECYZJE_V1.md),
[normatywny schema](../contracts/schemas/sync.schema.json).

## Etap 0.8.20 — Room 12

Partia zwykłych kanonicznych Meal ma trwały request, SHA-256, pierwotny
checkpoint i odwołanie do ukończonego snapshotu, kontekst konta oraz odpowiedź.
Przygotowanie wymaga aktywnego właściciela, potwierdzonego bootstrapu,
pełnego snapshotu z checkpointem i braku blokady/recovery. Jedna transakcja
zamraża operacje outbox oraz zapisuje partię. Kolejne wywołanie lub ponowne
otwarcie bazy odtwarza tę samą partię. Nie zmienia jej nowy odczyt snapshotu.

Pole outbox `attempted` zabezpiecza zamrożone wire już przy tworzeniu partii.
Oddzielne `SyncPushBatch.attempted` zapisuje rozpoczęcie możliwej wysyłki;
bez tego znacznika nie wolno zastosować ACK. Te znaczniki nie dowodzą wywołania
sieci — transport nie jest jeszcze podłączony.

`prepareAck` waliduje pełne HTTP200 i planuje zmiany poza transakcją/guardem
sesji. `applyAck` wykonuje wyłącznie pracę DB, sprawdzając lease, pełny kontekst,
bootstrap/snapshot, partię, niezmienną operację oraz źródłowy Meal i jego kolejkę.
ACK podnosi wyłącznie serverRevision; nie cofa nowszej porcji i localRevision.
Najnowsza intencja waiting_revision dostaje właściwe base_revision oraz pierwszy
wire pod swoim nowym UUID. Usunięcie podczas create czeka na dodatnią rewizję,
a później zachowuje tombstone i historię składników.

Partia i cały wynik są zatwierdzane razem z rewizjami/statusami. Konflikt lub
odrzucenie zachowuje lokalną wersję i odpowiedź serwera do uzgodnienia; nie
uruchamia oczekującej edycji. Awaria zapisu partii wycofuje również ACK encji
i aktywację intencji. Replay już zapisanej decyzji nie zmienia późniejszych
edycji, kolejnych partii ani wyższej rewizji. Stara odpowiedź po zmianie konta,
kontekstu lub A→B→A jest odrzucana.

Migracja 11→12 dodaje jedną tabelę `sync_push_batches` z indeksami i FK do
właściciela oraz snapshotu: łącznie 26 tabel. Definicje wszystkich 25 starych
tabel oraz eksporty 1…11 pozostają identyczne. Legacy outbox i oddzielne
provenance potwierdzenia zdjęcia pozostają zachowane. Wszystkie istniejące
ścieżki migracji prowadzą do 12.

Kod `4786149a1356dcf454bbc2734cd33e469ab55fa0`,0.8.20/code31,
validation1031. Assemble debug/validation/testAPK **PASS**, **308/323 JVM,
lint0error PASS**; pełny build10m35s. Wszystkie247 wejścia źródłowe zgodne
przed/po buildzie i po wykonaniu testów. KSP wygenerował eksport12. Niezależny
SQLite checker potwierdził rzeczywiste kolumny/indeksy/FK oraz niezmienność
25 dawnych definicji i eksportów1…11.

**54/54 native focus PASS** (12 nowych partii/ACK,33 przechowywania zdjęć
wraz z nową migracją11→12,9 snapshotu). Następnie końcowy pełny przebieg
**273/273 API35 PASS**, bez pominięć lub błędów, offline przed/po,
622.405s instrumentacji /626.86s wall. Log SHA-256:
`2e4e67e2a392cbce6219845ed41dc5d28ee63a222d688c8c41ddc7e22d01f7bb`.
Testy obejmują trwały checkpoint i restart, utratę ACK, dwie kolejne porcje,
delete podczas create, kompletną odpowiedź, mieszany konflikt, rollback
po aktualizacji rewizji, CAS po edycji, A→B→A, recovery/kontekst i zachowanie
gościa/innego konta, bramkę pełnego snapshotu, odświeżony snapshot oraz konkurencję.

Pierwszy pełny przebieg został przerwany bez terminalnego wyniku:88PASS,
1timeout istniejącego testu oczekującego na zniknięcie komunikatu profilu.
Po wznowieniu brakowało procesu hosta i emulatorów; nie przypisujemy przyczyny.
Pierwsza izolowana diagnostyka po zimnym rozruchu skończyła się ANR procesu
przed wykonaniem testów. Po potwierdzeniu gotowości usług scenariusz przeszedł
na identycznym APK bez zmiany kodu/timeoutu; następny pełny przebieg zaliczył273.
Oryginalne logi i receipty zachowano. Nie oznaczono niepełnego przebiegu jako PASS.

| Artefakt kodu4786149 | SHA-256 |
|---|---|
| Debug/code31 | `d098bdfd81fcc7e186cf1f2b8073689d67557fa027d7c36cf9e54e27651cbb61` |
| Validation/code1031 | `1a4df75ef0283bc873ab14797068ca4ddd24a223dacd6c79eddc93a086af738e` |
| Domyślny testAPK, bez drivera live | `569c97efe6f127d4a9611f0c5e39222eab94f5b69c1f3b4fab5cff39fb8e5b22` |

Regularny emulator zaktualizowano przez install-r0.8.20/code31. Rzeczywisty
zainstalowany SHA odpowiada debug powyżej. Migracja11→12 zachowała wszystkie
kolumny i wartości25 wcześniejszych tabel oraz rowid składników; FK clean,
nowa26.tabela partii pusta. Prywatny baseline i surowe UI są poza Git/OneDrive.
Pierwszy podgląd pokazał dialog „System UI isn't responding”, przy żywym
procesie aplikacji. Po świeżej weryfikacji wybrano wyłącznie Wait; bez close,
clear, wipe lub reboot. Późniejszy odczyt podczas otwierania dziennika zachowano
jako wczesną obserwację. Końcowa obserwacja po zakończeniu ładowania potwierdza
właściwy pakiet/wersję, kontrolki dziennika i brak ANR. Aplikacja jest otwarta
do testów manualnych. Oddzielnego kandydata APK/API/Room9 nie podmieniono.

## Dostarczony wcześniej protokół — fd1ceaf

`PushProtocol` przygotowuje kanoniczną kopertę zwykłego push z istniejących
operacji wire i otrzymanego checkpointu. Nie tworzy tokenu ani nie przekształca
historycznych wpisów legacy. Wybiera ciągły prefiks kolejki: najwyżej 100 operacji,
1 048 576 bajtów UTF-8 całego żądania oraz 262 144 bajty pojedynczego payloadu.
Druga zmiana tej samej encji kończy paczkę; nie pomijamy jej, aby wysłać późniejsze
zależności. Regrouping koperty nie zmienia operacji. Dla Meal sprawdzane są także
reguły daty/strefy, jednostek, odżywiania i tożsamości składników.

`PushBatch` przechowuje niezmienny JSON i SHA-256 dokładnych bajtów wysyłki.
Zwraca kopie; zmiana wejściowego JSONObject lub otrzymanego ByteArray nie zmienia
żądania. Restore wymaga identycznego kanonicznego zapisu. Baza ma go utrwalić przed
HTTP; ta biblioteka sama nie zapisuje partii ani nie zmienia outbox.

`PushReceipt` powstaje wyłącznie dla kompletnego HTTP200. Walidacja obejmuje
schema, epokę, liczbę i kolejność wszystkich wyników oraz operation_id/entity_id.
Sukces ma pierwotną rewizję base+1, również po replay już wykonanego żądania.
Niepełny ACK lub zły późniejszy wynik nie daje częściowego potwierdzenia.
accepted→already_applied może zachować tę samą decyzję; zmieniona rewizja nie jest
replay. Wynik wiąże hash konkretnej koperty. Odpowiedź nie wydaje checkpointu.

Konflikt/odrzucenie pozostaje pełnym wynikiem wymagającym obsługi; protokół nie
nadpisuje lokalnego posiłku. RecoverySource i mapowania są jawnie niedopuszczone
w tej ścieżce zwykłego push. Mają osobny proces świadomego uzgodnienia.
Diagnostyka nie wypisuje body, checkpointu, prywatnych błędów lub ich przyczyn.

## Poprawka Unicode

Test paczki z maksymalnym checkpointem Unicode wykrył przepełnienie stosu w
rekurencyjnym wzorcu UnicodeText silnika regex JVM. `SyncWireSchema` rozpoznaje
wyłącznie dokładny, przypięty wzorzec z common.schema i sprawdza ten sam język
iteracyjnie: bez NUL i samotnych surrogate, z poprawnymi parami UTF-16/emoji.
Pozostałe wzorce, limity długości liczone w code points i normatywne schematy
pozostają zachowane. Nie zmieniono kontraktu serwera.

## Historyczne dowody biblioteki — fd1ceaf

Kod `fd1ceaf3206a97a2efc9ca538993a6a217b21f95`. Pełne zadania Gradle testDebugUnitTest,
testValidationUnitTest i lintDebug **PASS**: **308/323 JVM**, bez błędów lub
pominięć, lint0error. Przebieg 5m28s; wszystkie 244 wejścia źródłowe porównano
przed/po. Nowe 16 testów push i 1 regresja walidatora. Lekki zestaw push/schema/
snapshot/MealWire: 41 PASS. Pierwsza próba Gradle nie połączyła się z lokalnym
daemonem w sandboxie; zakończyła się exit1 przed zadaniami. Ponowny przebieg
na tych samych źródłach, z dostępem do loopback, zakończył się exit0.

Nie wykonywano assemble nowego APK ani nowych testów urządzenia dla tego
commita. Pełne 260 native i APK 0.8.19 opisane w raporcie materializacji należą
do wcześniejszego kodu 97fff24. Nie przepisujemy ich na bibliotekę push.

Niezależny fixture PushResponse przeszedł również Python jsonschema przeciw
normatywnemu kontraktowi; mutacja revision=0 została odrzucona. To weryfikacja
pliku, nie wykonane wywołanie API.

## Dalsza implementacja

Następne kroki: transport, kontrola sesji/retry/backoff, pełny odczyt po push,
świadome confirm w UI, konwersja legacy, recovery i retencja. Przeterminowany
checkpoint wymaga kontrolowanego przegrupowania koperty po właściwej odmowie
serwera, z zachowaniem pierwotnych operacji; obecny store sam tego nie wykonuje.
Konflikty wymagają osobnego uzgodnienia. Adapter Room obsługuje na tym etapie
kanoniczne Meal; pozostałe historyczne typy nie są automatycznie wysyłane.
To nie kompletne E4/E7/KO32 lub rzeczywisty test API. [Atomowy zapis potwierdzenia](POTWIERDZENIE_POSILKU.md)
ma własny wcześniejszy receipt kodu 97fff24 / APK 0.8.19.
