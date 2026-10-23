# Synchronizacja w tle — etap C

## Aktualny stan

Wersja0.8.31/code42/validation1042, Room22. Aktualna integracja lokalna
`60fd3e693bfeeaf9d47f54dfd56d29c60e5c2348` zawiera B z poprawką fixture
`906c562544f6659a304222addb02c96a13ff2d1e` oraz zaakceptowaną poprawkę
trwałego recovery `d08627f1`. SOURCEPASS archiwów, koordynatora, runtime/UI
oraz ograniczonej delty recovery bez materialnychP1/P2. Oddzielne dowody:
51native i417debug/457validationJVM/lint/build na bc0e oraz pojedyncza delta
fixture na60fd:1/1PASS. E0 i diff-check PASS.
C pozostaje przed publikacją, końcowym FULLCI i odbiorem main; B ma osobny
[PR156](https://github.com/Roseru/aplikacja-mobilna/pull/156).

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
