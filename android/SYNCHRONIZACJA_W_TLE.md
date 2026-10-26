# Synchronizacja w tle — runtime i historia etapów

## Stan bieżący — 25 października 2026

Lokalnie zakwalifikowany konsument jednej polityki sieci, rzeczywisty port
zapisanych dowodów i pełna granica `SyncRuntimeAdmission`. **54/54 native,
6/6 JVM, kompilacja validation i standardowego Debug oraz lint PASS**;
we wszystkich końcowych testach 0 failure/error/skip. Room22 i istniejące
zależności pozostają bez zmian. To przekazanie do niezależnego odbioru
koordynatora i integracji O1, bez merge do main, nowego PR lub kwalifikacji APK/live.

Baza O1: `4f6bb841818daa5b0823132a2120106dd97c3c61`, dalsza własna gałąź
`codex/android-o2-polityka-runtime` po WIP `be6c4230`. Przyjęto **wyłącznie**
27 linii interfejsu O1 `be21a9ac2794faf34b1cda548bbedbe01f50a1a0`,
cherry-pick `3700ee02bc9ea2a5ca54764f85c14acdf20ef4c7`, bez community/drivera/migracji.
[Delegacja portów](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6386626395),
[interfejs admission](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6387420883)
i [sygnał watchdoga](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6390371437)
pochodzą od O1. Dodatkowy lifecycle zgłoszono konkretnie w
[6396976118](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6396976118).
Zastosowanie i kwalifikacja tej minimalnej delty na odseparowanej gałęzi O2
wynikają z decyzji koordynatora na podstawie ludzkiego zlecenia z 25.10;
**nie przypisujemy temu osobnego ACK O1 ani zgody na integrację za O1**.

### Kontrakt i podłączenie O1

```kotlin
val coordinator = SyncCoordinator(
    database, syncSchema, sessions,
    networkGate = networkPolicy,
    savedEvidence = sessions,
)
val runtime = SyncWorkRuntime(
    database, coordinator, SyncWorkScheduler(workManager),
    admission = syncRuntimeAdmission,
)
```

O1 podaje tę samą `app.networkPolicy` co katalog/API/AppAuth i jedną instancję
admission. Domyślne `ClosedNetworkAccessGate` oraz `OpenSyncRuntimeAdmission`
pozostają odpowiednio zamkniętą bramką sieci i standardowym admission.
Runtime wywołuje `attach(1)`, a `admission.run` otacza całe `current`, `signal`,
`manual`, `execute`, `reschedule` i pojedyncze reakcje obu obserwatorów.
Scheduler czeka na commit operacji WorkManager wewnątrz tej granicy.
Paused nie inicjalizuje gościa, nie zapisuje Room i nie enqueue/cancel;
nie konsumuje zdarzeń session/config/outbox. Samo `changes` ponawia ocenę.

`NetworkAccessGate.changes: StateFlow<NetworkAccessSnapshot>` udostępnia
`state` i `issuance: NetworkIssuance(instanceId, generation)`.
`NetworkPermit.issuance` wiąże capture z pierwotną instancją i generacją.
Dotychczasowe `state`, `captureAllowed` i `requireCurrent` pozostają.
Ticket i unique chain obejmują owner/lease, hash wireContext, revision i issuance;
stary job/reschedule nie otrzymuje nowego wydania po ABA ani restarcie providera.
Anulowanie dotyczy wyłącznie przechwyconej starej chain oraz jej legacy name.

`SessionController` implementuje
`SavedSyncEvidenceDrainer.drainSavedSyncEvidence(OwnerLease, AccountBindingEntity)`.
Wyniki to `APPLIED / NO_LOCAL_WORK / BUSY / STALE_CONTEXT / FAILURE`.
Pod mutexem sesji i jedną transakcją Room stosuje wyłącznie kompletne zapisane
raw/recovery ACK najnowszego zatwierdzonego matching planu. Zwykły ACK jest
już atomowo zastosowany razem z zapisaniem odpowiedzi, więc jego historia nie
jest reaktywowana jako nowa praca. Wygasły token i przyszły Retry-After nie
blokują lokalnego draina; nie ma refresh/GET/POST nawet po APPLIED lub braku
dowodów. `APPLIED` nie zastępuje świeżego PULL ani nie kończy cyklu/planu.

`NetworkOperationCancellation(operation: Job)` jest wewnętrznym markerem
jednej operacji, bez preferencji i bez zmiany zgody urządzenia. Powstaje
wewnątrz `async` executora i przenosi ten sam Job przez kolejne konteksty I/O.
Callback początku cancellation zamyka konkretny delegate połączenia i jego
watcher; handle jest zwalniany przy close i wyścigu inicjalizacji. Dzięki temu
owner/context/admission kończą również blokujący read przy stałym Allowed,
zanim oddadzą finally/mutex. Stary callback nie zamyka nowej operacji.
Nie edytowano AppAuth, providera, root/DI lub transportu; nie kwalifikuje to
AppAuth/refresh na obcych wątkach.

### Dowody końcowe i granice

| Końcowy zakres | Liczba metod | Wynik |
|---|---:|---|
| SyncNetworkPolicyStorageTest | 21 | PASS |
| SyncCoordinatorStorageTest / SyncWorkStorageTest / SyncWakeStorageTest | 8 / 5 / 4 | PASS |
| SyncRecoveryResumeTest / SyncSessionIntegrationTest | 2 / 1 | PASS |
| SyncSavedEvidenceSessionTest / SyncRuntimeAdmissionStorageTest | 6 / 7 | PASS |
| NetworkAccessGenerationTest / NetworkOperationCancellationTest JVM | 3 / 3 | PASS |

Native wykonano na własnym API35 z rzeczywistą Room/WorkManager/SessionController
i syntetycznymi bramkami/połączeniami, bez usług zewnętrznych. Offline przed/po.
Surowy finalny XML native SHA256: `62e76a1d6a04d5762197df439ed5af9d76cd52d90f02650000b15ecbb4068bba`.
Lint końcowy: 0 error/fatal, 8 warning i 1 information.
`lintReportValidation` był UP-TO-DATE: użyto zachowanego identycznego XML
SHA256 `a733f734ee1b9599bc92fe54c4a301a378791355c3522e2217dd68f5ab951b99`; nie deklarujemy ponownej generacji raportu.
Niezależny przegląd końcowego zakresu: **9/10**, bez otwartych
materialnych P1/P2; integracja i odbiór O1 pozostają osobnym krokiem.

Zachowane wcześniejsze przebiegi nie są sumowane jako nowy pełny PASS:
50 native miało 49 PASS/1 FAIL fixture (executor został anulowany przed jego
samodzielnym powrotem na konto); poprawione sterowanie z testu i dwie regresje
następnie 3/3 PASS. Odwracalne mutanty starego sygnału watchdoga i pominiętego
admission wykryto jako 2/2 FAIL. Dodatkowe realne kontrpróby lifecycle przy
stałym Allowed miały 3/3 FAIL przed naprawą i wszystkie przechodzą w końcowych54.
Oryginały źródeł mutantów odtworzono dokładnym SHA; raw logi/XML zachowano poza Git.
Historyczne serie WIP z 24.10 opisane niżej zachowują swój osobny zakres.

Pierwsza końcowa kompilacja testów natrafiła na pusty 24-bajtowy moduł metadanych
Kotlin mimo istniejącego getter-a DATABASE_GUARDS w bytecode. Bez zmiany kodu,
asercji, bazy lub zależności wymuszono pełną sekwencyjną kompilację obu wariantów
z wyłączoną inkrementalnością. Metadane wróciły do1557B, a native/lint przeszły.
Zachowano setup FAIL oraz pierwotny przerwany build. Nie maskowano błędu skipem.

Powtarzalne komendy z `android`, po przygotowaniu własnego SDK/JDK i sprawdzeniu
tożsamości dedykowanego validation AVD/`ANDROID_SERIAL`:

```powershell
.\gradlew.bat :app:compileValidationKotlin :app:compileDebugKotlin -Pkotlin.incremental=false --rerun-tasks --max-workers=1 --offline --no-daemon
.\gradlew.bat :app:testValidationUnitTest --tests pl.roseru.kalorie.NetworkAccessGenerationTest --tests pl.roseru.kalorie.NetworkOperationCancellationTest -Pkotlin.incremental=false --max-workers=1 --offline --no-daemon
.\gradlew.bat :app:connectedValidationAndroidTest "-Pandroid.testInstrumentationRunnerArguments.class=pl.roseru.kalorie.SyncNetworkPolicyStorageTest,pl.roseru.kalorie.SyncCoordinatorStorageTest,pl.roseru.kalorie.SyncWorkStorageTest,pl.roseru.kalorie.SyncWakeStorageTest,pl.roseru.kalorie.SyncRecoveryResumeTest,pl.roseru.kalorie.SyncSessionIntegrationTest,pl.roseru.kalorie.SyncSavedEvidenceSessionTest,pl.roseru.kalorie.SyncRuntimeAdmissionStorageTest" :app:lintValidation -Pkotlin.incremental=false --max-workers=1 --offline --no-daemon
```

To zakres komponentu O2, nie powtórka całego A/B/C ani pełny GitHub CI.
Nie kwalifikuje Room23/24/25, skonfigurowanych APK, telefonu, live E4/PULL/PG,
OIDC/TLS, Gemini, wdrożenia lub pełnego v1. O1 musi zintegrować wspólne DI,
przeprowadzić właściwe kontrole aktualnego head/base i przekazać O3 nową
zgodną dostawę; nie zastępujemy jej starszym Room20 PASS.

## Historia etapu C i snapshotu WIP

Poniższe zapisy opisują wcześniejsze piny. Ich oczekiwania i liczby nie są
aktualnym stanem końcowego konsumenta z 25.10.

### Etap C — zapis historyczny

### Stan odnotowany dla etapu C

Wersja0.8.31/code42/validation1042, Room22. Aktualna integracja lokalna
`60fd3e693bfeeaf9d47f54dfd56d29c60e5c2348` zawiera B z poprawką fixture
`906c562544f6659a304222addb02c96a13ff2d1e` oraz zaakceptowaną poprawkę
trwałego recovery `d08627f1`. SOURCEPASS archiwów, koordynatora, runtime/UI
oraz ograniczonej delty recovery bez materialnychP1/P2. Oddzielne dowody:
51native i417debug/457validationJVM/lint/build na bc0e oraz pojedyncza delta
fixture na60fd:1/1PASS. E0 i diff-check PASS.
B [PR156](https://github.com/Roseru/aplikacja-mobilna/pull/156) jest scalone do
main50e56d368c5defb474e112adcfe9c25a570c5d48 po exactFULLCI8/8SUCCESS;
root odczytał433/433native i417/457JVM bez fail/skip. Zwykły merge tego main
do C zachował identyczne drzewo b8c317a5, więc testów nie powtarzano.
Publikowany jest jeden PR C na rzeczywistym main; jego FULLCI i osobny main
pozostają wymagane. Równoległy BmainCI jest dodatkową obowiązkową bramką
przed scaleniem C przez koordynatora.

## Jeden trwały przepływ

`CalorieApplication` implementuje `SyncWorkRuntimeOwner`: Room, koordynator,
rzeczywisty `SessionController` O1 i WorkManager korzystają z jednego runtime.
Ręczne wywołanie i import używają `manual(capturedLease)`, tak samo jak worker.
`SyncCoordinator` współdzieli procesowy mutex oraz zapisuje owner/generation,
pełny kontekst, cykl, `pull_before → push → pull_after`, wersje zgłoszeń,
liczniki i termin ponowienia. Wyniki typowanego executora nie są komunikatami UI.
Guard lease/kontekstu działa przed i po kroku; O1 nadal chroni fizyczny send
oraz commit odpowiedzi. A→B→A nie przywraca ważności wcześniejszej pracy.

PULL wymaga kompletnego aktualnego runa i pełnej walidacji przed publikacją
checkpointu; zastosowanie do dziennika jest idempotentne. Po PUSH następuje PULL.
`Completed` PUSH nie oznacza pustej kolejki: jej SQL COUNT i wersje zgłoszeń
sprawdzane są atomowo. Brak postępu po ukończonym PULL wznawia PUSH z jego
checkpointem po backoff. Nie resetuje niepewnego wysłania. Cancellation
propaguje się bez ACK, nowego operation_id lub zmiany frozen bytes/hash.

Termin jest maksimum zapisanej granicy i Retry-After zamrożonych paczek.
Restart, kliknięcie i nowy lease go nie skracają; worker sprawdza go także
po przedwczesnym wybudzeniu. Retry-After teraz/przeszły otrzymuje rosnący
trwały backoff10s,20s,…; wycinek pracy jest ograniczony do32kroków.
Login, uzgodnienie, brak konfiguracji i pojemność są osobnymi stanami.
Stan oraz postęp widać na koncie i ekranie importu; oczekiwanie nie jest sukcesem.

## Wybudzenia i zakończenie recovery

Nowe/zmienione kwalifikujące się operacje, aktualny lease/context Room
oraz publiczny sygnał sesji O1 wybudzają maszynę. Usunięcie ACK z kolejki
samo nie jest nową operacją. Runtime anuluje wyłącznie poprzedni własny
łańcuch przy zmianie owner/generation; opóźniony sygnał starej sesji jest odrzucany.
Konfiguracja zwalnia tylko `not_configured`, właściwe przejście dostępności
sesji/lease zwalnia `login`. Storage wymaga jawnej próby użytkownika.

Recovery wymaga trwałego dowodu przyczynowego. Rzeczywisty B finish zapisuje
monotoniczny lokalny numer w `reconciliation_completions` w tej samej
transakcji co complete, zastosowanie pełnej kopii i zdjęcie requiresRecovery.
Ponowienie zakończonego planu zwraca istniejący wynik bez nowego numeru.
Nowa blokada zapamiętuje aktualny numer jako `reconciliationBaseline`.
Request/run zwalniają ją tylko dla nowszego zatwierdzonego zakończenia
tego samego właściciela/pełnego kontekstu i powiązanej zastosowanej kopii.
Sama flaga, historyczny plan, login, konfiguracja lub zegar nie są dowodem.
Wznowienie zaczyna nowy PULL i zachowuje Retry-After.

Migrowana zdrowa blokada z nieznaną granicą NULL pozostaje zablokowana do
jawnej próby użytkownika. Jeśli nadal wymaga recovery, zapisuje granicę przed
przyszłym zakończeniem. Nie dopisujemy fikcyjnych potwierdzeń dawnym planom.

WorkManager2.10.5 ma CONNECTED, unikalny SHA owner/generation oraz
APPEND_OR_REPLACE; zdarzenie podczas kończenia pracy nie przepada.
Jeden trwały watch15min umożliwia powrót po zakończeniu procesu, pozostawiając
zatrzymane stany bez transportu. WorkData zawiera tylko zakres/generację/kontekst,
bez tokenów, payloadów lub haseł. Android może opóźnić wykonanie.
[Warunki pracy](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work).

CONNECTED nie jest trwałą blokadą sieci wybieraną przez użytkownika.
Preferences przechowuje obecnie tylko motyw; wspólny network gate pozostaje
osobną uzgadnianą integracją O1/O2. C nie deklaruje ukończenia całego WF-05/v1.

## Archiwum i migracje

Limity pozostają8prób/128MiB na właściciela oraz64MiB/100000rekordów/2000stron
jednej próby. Liczone są rzeczywiste bajty UTF-8 zapytań i odpowiedzi.
Kompaktacja wybiera najstarsze bezpieczne ukończone/wygasłe próby i atomowo
zastępuje rawpages niezmiennym manifestem/hashami oraz zwalnia identities.
Zostają run, kontekst, tokeny/checkpoint, liczniki, FK i dowody. Chronione są
aktywne/pending, ostatnie zastosowanie, frozen requests, nierozstrzygnięte
konflikty/pending_local oraz wszystkie nieukończone zatwierdzone grupy recovery,
evidence i awaitingSnapshot. Brak kandydata/pojemności cofa transakcję.

Identyczna późna strona skompaktowanego runa sprawdza digest i nie publikuje
historycznego checkpointu. Historyczny ServerDiaryApplication zwraca zapisany
wynik przed odczytem raw i nie cofa późniejszej lokalnej edycji. Stary receipt
nie zastępuje świeżej typed kopii potrzebnej po recovery ACK.

### Jawne przerwanie starych pobierań

Od0.8.37 ustawienia profilu konta udostępniają lokalny przegląd niedokończonych
ordinary odczytów z nieaktualnej dzierżawy/kontekstu. Sam przegląd nie zmienia
danych. Użytkownik może anulować lub jawnie zatwierdzić konkretną listę prób.
Zatwierdzenie ponownie sprawdza dzierżawę, binding, pełne wiersze i aktualny graf
dowodów w jednej transakcji. Zmiana konta A→gość→A, kontekstu, strony lub nowy
dowód odrzucają całą decyzję. Bieżące pending, wszystkie recovery pulls i próby
powiązane z dowodami/batches nawet draft/historycznych planów są wyłączone.

Jedyną zmianą jest pending→expired wybranych prób. Ich UUID, zakres, query,
body, hash, strony i identities zostają. Domyślne reserve nadal chroni każde
pending; dopiero późniejsza presja może skompaktować wycofany, niechroniony run
do istniejącego niezmiennego manifestu z hashami. Nie ma czyszczenia dziennika,
kolejki, potwierdzeń, zmiany forceFull albo automatycznej akceptacji recovery.
Nie powstaje nowy schemat. Operacja nie wykonuje HTTP i działa także przy
blokadzie poligonowej. Kolejna próba synchronizacji wymaga działania na ekranie
konta i przechodzi dotychczasowy wspólny gate, Retry-After oraz bariery sesji.

### Centrum synchronizacji konta

Od0.8.38 ekran konta prowadzi do centrum stanu i pomocy. Samo otwarcie
obserwuje lokalną bazę i niczego nie wysyła. Jedna transakcja sprawdza aktywną
dzierżawę i zbiera liczbę niepotwierdzonych operacji, podział domen, oczekujące
kroki, konflikty/odmowy, starszy format, wysłaną próbę bez końcowego wyniku,
datę ostatniego zastosowania kopii i liczbę niedokończonych pobierań. ACK,
superseded i local_only nie zwiększają kolejki. Liczniki dotyczą operacji,
nie liczby posiłków; pusta kolejka nie jest dowodem aktualności kopii serwera.

Stan zadania wymaga zgodności owner/lease/context, a data zastosowania kopii
zgodności bieżącego kontekstu. Stary wynik idle po A→gość→A lub zmianie epoki
nie potwierdza nowej synchronizacji. Główny banner również filtruje lease i
pełny kontekst. Wiadomość zadania ma datę zapisu i jest osobna od bieżącej
blokady poligonowej. Po pięciu sekundach bez subskrypcji obserwator zatrzymuje
się i usuwa poprzedni podgląd. Powrót po zmianie kontekstu zaczyna się od
odczytu bieżącego stanu zamiast odtworzenia starego wyniku idle z pamięci.

Pomoc kieruje do logowania, połączenia konta, uzgadniania, wspólnych ustawień
sieci lub lokalnego przeglądu pobierań0.8.37. Retry jest jawny, dostępny również
przy pustej kolejce i wywołuje istniejący driver, bez drugiego gate/admission.
Przycisk nie omija blokady konta/recovery, braku sesji/konfiguracji, polityki
sieci, aktywnej pracy lub najpóźniejszego zapisanego Retry-After. Zegar terminu
działa tylko przy STARTED; poza ekranem nie wykonuje dodatkowego odpytywania.
Przejście do lokalnego przeglądu, powrót i anulowanie decyzji nie wysyłają HTTP.

Addytywne20→21 dodaje stan pracy i receipts archiwum;21→22 dodaje nullable
granicę blokady oraz niezmienny ledger zakończeń. Użyty schemat21 i migracja
20→21 pozostają zachowane; blob21=`1c8b2f9458bdc4d80fef222c14aa82f4a81607b0`.
Wszystkie45starych encji zachowane; jedynym nowym polem starej tabeli jest
nullable granica. Nie ma wipe/fallbackToDestructiveMigration lub zmiany frozen wire.

## Weryfikacja i granice dowodów

Końcowe51native/0fail/error/skip obejmuje Archive5, Coordinator8, Work5,
Wake4, rzeczywistą sesję1(wariant manual+worker), trwałe recovery2, importnav1,
firstGoal1, migracje4, Snapshot9, Diary10 i ochronę archiwum recovery1.
Rzeczywisty kontroler O1 z syntetycznym Vault/gateway wykonał PULL→PUSH→PULL,
ACK/revision1/82.125kg oraz finalny checkpoint. Recovery używa realnego B finish,
zamknięcia/otwarcia plikowej Room i nowego runtime/workera; stary complete
nie zwalnia nowszego konfliktu. Oryginały/private/history/frozen/hash zachowane.
Test pojemności obejmuje rzeczywisty SQLiteFull, nie tylko wyjątek fixture.

JVM417debug/457validation bez fail/error/skip, oba lint bez error/fatal,
assembleDebug i E0 PASS na tym samym źródle. Wcześniejsze przypięte przebiegi
oraz red/green i błędy fixture są w jedynym dzienniku O2-055/056/057;
nie sumujemy powtórzeń jako unikalnych przypadków.

Powtarzalne sprawdzenie z katalogu android na własnym validation emulatorze:

```powershell
.\gradlew.bat :app:testDebugUnitTest :app:testValidationUnitTest :app:lintDebug :app:lintValidation :app:assembleDebug
.\gradlew.bat :app:connectedValidationAndroidTest
```

Powyższy drugi rozkaz uruchamia pełny zestaw, nie tylko lokalnie wybrane51.
Końcowe FULLCI dokładnego head/base i main są osobnymi bramkami.
Lokalne fixtures nie kwalifikują zewnętrznego HTTP/OIDC/PG, live E4/kill/replay,
Gemini lub wdrożenia. E4driver O1 nadal celowo odmawia Room21/22; jego późniejsza
kwalifikacja jest oddzielna od tego odbioru C. Nowy publiczny katalog O1 poza PR.


### Osobna delta fixture po pierwszym CI B

Pierwszy CI B/head0ee miał433native/432PASS+1FAIL/0skip: zarezerwowany
manualConsumptionAndAckGate fixture nadal oczekiwał jednej operacji zamiast
prawidłowej pary product_draft+Meal. Po O1ACK i niezależnym SOURCEPASS poprawka
B906c dotyczy tylko tej metody i dokumentacji. Zwykły merge do C60fd nie zmienia
kodu aplikacji, Room, archiwów, koordynatora lub durableproof. Ten jeden
przypadek na C5564/Room22:1/1PASS,0fail/error/skip. Wcześniejsze51native oraz
417/457JVM/lint zbc0e są osobnym dowodem; nie uruchamiano ich ponownie bez zmiany.
Nowy exactCI B i późniejszy C/main pozostają wymagane. To lokalny test
fixture ACKgate/cancel/replay, nie kwalifikacja live E4driver/fingerprintRoom22.


### Publikacja C na scalonym B

Na decyzję koordynatora50e56d→C dołączono zwykłym mergee9b7a1ec.
Drzewo786a837145f1cd9ba440c6cb090e2d55c0a36959 jest identyczne z b8c317a5;
po nim zmieniono tylko ten opis i własny wiersz/wpis O2 w dzienniku.
SOURCEPASS i lokalne51na bc0e, osobna1na60fd oraz417/457JVM/lint zachowują
swoje rzeczywiste zakresy i przypięte dowody. Nowy FULLCI PR C jest wymagany;
C można scalić dopiero po jego PASS, BmainCI PASS i odbiorze root.
Nowe WIP O1 ec75df9/katalog/provider/addytywne rootDI nie są częścią tego PR.


## Historyczny snapshot WIP — 24 października 2026

Stan snapshotu robót: **WIP / WAITING_O1_PORTS**, bez pełnego PASS.
Udostępnienie źródeł na własnej gałęzi zostało zlecone przez właściciela.
Nie jest to odebrany konsument ani kwalifikacja WF-05. **Nie scalać tego
snapshotu do main ani dużej gałęzi O1 przed naprawą obu otwartych P2 ABA,
dostawą adaptera i końcowym odbiorem.**
Baza to niescalony pin O1 `4f6bb841818daa5b0823132a2120106dd97c3c61`,
gałąź O2 `codex/android-o2-polityka-runtime`. Pozostaje Room22; brak migracji23.
Poprzednie wyniki C powyżej dotyczą swoich historycznych pinów.

`SyncCoordinator` przyjmuje `networkGate: NetworkAccessGate = ClosedNetworkAccessGate`
oraz opcjonalny `savedEvidence: SavedSyncEvidenceDrainer?`. O1 musi przekazać
**tę samą** `app.networkPolicy`, którą już współdzielą katalog, API i AppAuth.
`SyncWorkRuntime(db, coordinator, scheduler)` pobiera gate z koordynatora.
Nie tworzy preferencji ani drugiego providera. Domyślny brak DI jest zamknięty.
Statusy `network_unavailable`, `network_blocked`, `network_changed` pochodzą
z trwałego stanu pracy; nie stanowią osobnego ustawienia trybu.

Manual/worker/watch/outbox zachowują fazę, frozen request, deadline i blokady
biznesowe. Lokalny drainer działa przed deadline i kontrolą dostępu do sieci;
każdy wynik po oczekiwaniu przechodzi kontrolę lease/context. `APPLIED` nie
zastępuje świeżego PULL i nie kończy cyklu. Port obecnie zwraca jeden z
`APPLIED / NO_LOCAL_WORK / BUSY / STALE_CONTEXT / FAILURE`; brak adaptera O1
oznacza brak lokalnej pracy, bez wywołania mieszanej metody sieciowej.

Ograniczony eksperyment z rzeczywistym kontrolerem sesji i syntetycznym gateway
wykazał, że zwykły PULL przy zapisanym raw może rozpocząć nowy GET albo refresh.
Dlatego nie wolno użyć go jako lokalnego drainera. Do finalnej integracji
potrzebny jest typowany port O1, wykorzystujący istniejące session guards
i wyłącznie zapisane ACK/raw. Obecne testy hooka używają prawdziwych lokalnych
store, lecz nie potwierdzają jeszcze brakującego adaptera sesji O1.

Niezależny przegląd i trzy natywne kontrpróby wykazały również dwa otwarte
problemy **P2 ABA**: bilet zapisuje samą revision, a executor obserwuje StateFlow
stanu bez widocznej generacji. Dozwolone przez interfejs
Allowed(7) → Blocked → Allowed(7) unieważnia permit, lecz stary bilet może
przechwycić nowy permit; sklejone zdarzenia nie muszą anulować zawieszonego
executora. Potrzebny jest obserwowalny znacznik generacji/instancji O1 oraz
powiązanie execute/reschedule z pierwotnym uprawnieniem. Nie zakładamy,
że monotoniczne revision realnego providera zastępują kontrakt interfejsu.
[Uzgodnienie obu portów](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6382259951).

Trzecią uwagę poprawiono lokalnie: revokeScheduled anuluje wyłącznie
przechwycony stary łańcuch i jego legacy name. Nowa nazwa obejmuje owner,
lease generation, hash wireContext i revision. Opóźnione anulowanie nie
kasuje łańcucha innej rewizji ani nowego bindingu. Surowe logi/XML i hashe
pozostają zachowane poza repozytorium. Publikacja roboczej gałęzi udostępnia
źródła i negatywne testy do przeglądu; nie zastępuje napraw ani odbioru root.

### Lokalne zakresy tego snapshotu

Każdy przebieg jest osobnym dowodem na swoim wariancie źródeł. Nie sumujemy
ich jako nowego pełnego PASS i nie przypisujemy im zdalnego CI:

| Zakres | Faktyczny wynik | Ograniczenie |
|---|---|---|
| Trzy kontrpróby niezależnego przeglądu przed poprawkami | 3 testy, 0 PASS / 3 FAIL, 0 error/skip | Anulowanie nowej chain, stary bilet po ABA, koalescencja i zawieszony executor |
| Seria koordynatora/runtime/WorkManager/sesji po zawężeniu cancel | 33 testy, 29 PASS / 4 FAIL, 0 error/skip | Dwa P2 ABA i dwa błędy fixture; wszystkie FAIL zachowane |
| Dotknięte przypadki po wireContext i poprawkach fixture | 12 testów, 11 PASS / 1 FAIL, 0 error/skip | Pozostał błędny oracle restartu; dwa znane ABA nie były w tym zakresie |
| Ostatnia izolowana poprawka fixture restartu | 1 test, 1 PASS / 0 FAIL, 0 error/skip | Log: poprzednik ENQUEUED, następnik BLOCKED; po constraint świeży poprzednik wykonuje executor dokładnie raz i zapisuje login |

Manual/worker/watch w poprawionym fixture są wywoływane sekwencyjnie przed
obserwatorem outbox, z zachowaną ścisłą asercją oczekiwania na politykę
i zera wywołań executora. Fixture restartu śledzi request IDs i zależność
APPEND, zamiast liczby historycznych rekordów, które WorkManager może przyciąć.
Test anulowania z barierą potwierdza zachowanie dwóch świeżych chain:
innej revision oraz nowego wireContext, przy anulowaniu starej.

Lint aktualnego kodu produkcyjnego, w tym poprawki wireContext: **PASS,
0 error/fatal, 46 warning i 1 information**. Ostatnia późniejsza zmiana to
wyłącznie oracle fixture BLOCKED, sprawdzony powyższym pojedynczym testem;
lint nie był dla niej powtarzany. Końcowy `git diff --check` PASS.
Nie ponawiano całego A/B/C, JVM, zewnętrznego HTTP/OIDC/PG, E4 ani FULLCI.
Testy negatywne ABA pozostają w źródłach aktywne, bez skip/ignore lub
zmiany oczekiwanego wyniku na aktualne błędne zachowanie.

Następny krok: O1 dostarcza uzgodnione dwa porty (local-only drainer oraz
obserwowalna generacja/instancja jednego gate), O2 wiąże bilet z pierwotnym
uprawnieniem i zalicza oba kontrprzykłady, następnie wspólne DI i celowany
odbiór rzeczywistego adaptera. Dopiero po naprawach i odbiorze można
integracji nadać finalny commit i właściwy pełny wynik CI.
