# Pakiet prac Androida dla Agenta 2

23.10.2026. Zlecenie właściciela: Agent 2 pomaga Agentowi 1 i otrzymuje trzy razy więcej dużych etapów. Dokument jest instrukcją wykonania, a nie drugim dziennikiem komunikacji. Potwierdzenia, pytania i wyniki dopisujemy wyłącznie do [KOMUNIKACJA_AGENTOW.md](KOMUNIKACJA_AGENTOW.md).

## 1. Przydział: trzy duże etapy O2 i jeden etap O1

| Wykonawca | Etap | Ukończony rezultat |
|---|---|---|
| **Agent 1** | **O1-I: E4 i integracja z sesją** | Skonfigurowane validation/opt-in APK, kontrola ich pochodzenia i wspólny test z O3 po uzgodnieniu okna. O1 zapewnia również opisane niżej wąskie połączenia modułów O2 z istniejącą sesją. |
| **Agent 2** | **O2-A: pełna kolejka sześciu domen** | Profil, cele, kompletność dnia i prywatne produkty otrzymują kanoniczne operacje, wysyłkę i atomowy ACK; posiłki i waga zachowują dotychczasowe działanie. |
| **Agent 2** | **O2-B: gość, legacy i uzgadnianie** | Świadome przypisanie historii do konta, trwały import starszych wpisów i obsługa uzgadniania zgodna z wymaganiami; restart i ponowienie nie gubią danych ani nie mnożą wpisów. |
| **Agent 2** | **O2-C: automatyczna synchronizacja i archiwa** | WorkManager uruchamia synchronizację właściwego konta, ponawia ją po odzyskaniu sieci i bezpiecznie zarządza archiwami, bez blokady po kilku prawidłowych pobraniach. |

To przydział **3:1 dużych etapów**, obejmujący implementację, migracje, ekrany danego modułu, końcową weryfikację i przekazanie. O2 nie dostaje jedynie pisania testów lub dokumentacji. W ramach trzech etapów sam realizuje kod Androida.

Najnowsza decyzja właściciela: najpierw cały spójny etap, potem właściwe testy i poprawki. PR powstaje po dużym ukończonym etapie. Nie tworzymy PR dla pojedynczego pliku, samego licznika lub zapisu statusu. Ten pakiet przekazania jest osobnym, kompletnym zadaniem organizacyjnym; nie zawiera nowego kodu aplikacji.

## 2. Dokładny punkt startu

- Repozytorium: `Roseru/aplikacja-mobilna`.
- Odebrana baza: **main `84d3dcdbedb9c6d21b54f75386c9d3fafa95eb52`**, po [PR144](https://github.com/Roseru/aplikacja-mobilna/pull/144).
- Android: **0.8.27**, debug code **38**, validation code **1038**, Room **17**. Nazwa wariantu validation ma przyrostek: **0.8.27.validation**.
- Własny CI PR144 `39913788643`: wszystkie osiem kontroli SUCCESS. Odczytane raporty: **348 debug JVM, 363 validation JVM, 359 native**, bez błędów i pominięć. To dowód tej bazy, nie przyszłego kodu O2.
- **Osobny CI main `39916344347` jest czerwony:** jeden timeout 15 s w `MealPhotoScreenTest.durableSyntheticPreviewSurvivesActivityRecreationAndExplicitDeletionKeepsDiary`, przy 359 uruchomionych przypadkach urządzenia. Pozostałe joby robocze SUCCESS; bramka wynikowo FAILURE. O1 prowadzi diagnostykę tego testu w swoim zakresie. Nie ponawiamy go w ciemno i nie nazywamy aktualnego main zielonym. Nie blokuje to rozpoczęcia implementacji A w osobnej gałęzi.
- Zwykła aplikacja została zaktualizowana z Room15 do Room17: wszystkie wcześniejsze wartości i rowid 28 tabel zachowane. Prywatne dane i kopie nie są częścią pakietu.
- O1 rozwija osobno [PR138](https://github.com/Roseru/aplikacja-mobilna/pull/138). Jego nowy lokalny kandydat `dc012fabf395480c6aa2d1b2a1d59b766ec4add3` nie jest bazą tego przydziału i przy sporządzeniu instrukcji nie był jeszcze wypchnięty.

**Już działa:** dziennik offline, katalog i składniki racji, dokładne ilości i B/T/W, profil/cel, analityka, frontend funkcji społecznych i zdjęć, kanoniczny push Meal/Weight, porównywanie konfliktów tych dwóch typów, pełny pull wszystkich sześciu domen do lokalnego dziennika.

**Do wykonania w tym przydziale:** producenci i ACK pozostałych czterech domen, konwersja wcześniejszej kolejki, przypisanie gościa, specjalne uzgadnianie oraz WorkManager i retencja archiwów. Nie ogłaszamy ukończenia v1 ani live E4 na podstawie samych testów lokalnych.

## 3. Pliki i źródła, które otrzymujesz

Pełny spis plików bazowych, rozmiarów i SHA-256 znajduje się w [ANDROID_O2_PLIKI.json](ANDROID_O2_PLIKI.json). Poprawiony format v2 opisuje **836 surowych blobów Gita, 8 998 072 bajty**, w tym329plików Androida. Odczyt wykonano jednym binarnym `git cat-file --batch`, bez dekodowania stdout i konwersji końców linii; sprawdzono długości, ramki oraz Git blob SHA-1, a SHA-256 obliczono z tych samych bajtów. Manifest nie zawiera SDK, cache, APK, lokalnych baz ani plików sesji.

**Korekta po odbiorze O2:** pierwsza wersja manifestu podawała9 198 358bajtów i błędnie nazywała je surowymi bajtami Gita. Użyty lokalny `git archive` zastosował Windows LF→CRLF:819pozycji miało inne sumy/rozmiary, wszystkie wyjaśnione dokładnie tą konwersją. Wersja v2 naprawia obietnicę integralności, nie zmienia kodu aplikacji ani zakresu A/B/C. [Uwagi O2](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6362434771) zostały odczytane.

Historyczny lokalny `Agent2-Android-0.8.27-4dd61c5.zip` ma własną poprawną sumę całego ZIP i jego członków, ale zawiera CRLF i pierwotny błędnie opisany manifest. **Nie używaj go do sprawdzania raw Git.** Pozostaje zachowany jako wcześniejszy artefakt. Poprawiony wybrany pakiet ma osobną nazwę `Agent2-Android-0.8.27-<commit>-raw.zip`, manifest pochodzenia i SHA256SUMS. W nim834pliki bazowe mają surowe bajty z84d3, a AGENTS/dziennik są jawnymi aktualizacjami z commita przekazania; aktualne instrukcje i indeks są dodatkowymi plikami. Żaden z tych SHA nie jest sumą ZIP generowanego przez GitHub. Do pracy O2 nadal używa swojego checkoutu Git.

Przygotowany pakiet źródłowy jest kopią do odczytu i odtworzenia checkoutu, a nie drugą gałęzią rozwoju. Do publikacji używaj własnego checkoutu repozytorium. Jeżeli masz już repo, nie nadpisuj go ZIP-em i nie przenoś całej niescalonej gałęzi O1.

### Kolejność czytania

1. [Wymagania projektowe](../WYMAGANIA_PROJEKTOWE.md), szczególnie WF-03–06, KO-03–08/18–20/23/24/25/31/32 oraz rozdział 11.3.
2. [Instrukcje agentów](../AGENTS.md), [workflow](WORKFLOW.md), bieżący wspólny dziennik.
3. [Architektura](ARCHITEKTURA.md), [plan](PLAN_PRAC.md), [decyzje E4](e4/DECYZJE_V1.md), [integracja E4](e4/INTEGRACJA_O1.md).
4. [Pełny pull 0.8.27](../android/POBIERANIE_DZIENNIKA.md), [wysyłanie kolejki](../android/WYSYLANIE_KOLEJKI.md), [waga](../android/WAGA_SYNC.md), [konflikty](../android/KONFLIKTY_SYNC.md).
5. [Kontrakt synchronizacji](../contracts/schemas/sync.schema.json), [domeny](../contracts/schemas/domain.schema.json), [wspólne typy](../contracts/schemas/common.schema.json), przykłady i scenariusze z `contracts/`.
6. Android `core/sync`, `data` i testy wskazane niżej. Kod backendu i `tools/sync_client` służy jako referencja rzeczywistego zachowania.

### Mapa kodu

Ścieżki Kotlin poniżej są względne do `android/app/src/main/java/pl/roseru/kalorie/`.

| Obszar | Pliki do przeczytania | Dlaczego |
|---|---|---|
| Kolejka i ACK | `data/MealPushStore.kt`, `core/sync/PushProtocol.kt` | Zamrożone koperty, statusy operacji, rewizje i wspólny ACK. Obecne źródła encji obejmują Meal i Weight. |
| Kanoniczne wpisy | `data/CanonicalMeals.kt`, `data/CanonicalWeights.kt`, `core/sync/MealWire.kt`, `WeightWire.kt` | Oddzielenie dokładnego payloadu od projekcji lokalnej. |
| Tworzenie i edycje | `data/DiaryRepository.kt`, `data/Database.kt` | Miejsca tworzenia profilu, celu, dnia, produktu, posiłku i legacy. |
| Właściciel i konto | `data/LocalOwners.kt`, `data/AccountBootstrapStore.kt` | Lease, generacja, tożsamość, epoka i kontekst; podstawa ochrony A→B→A. |
| Archiwum | `data/ServerSnapshotStore.kt` | Strony, ukończenie, limit pojemności i odwołania do prób pobierania. |
| Zastosowanie kopii | `data/ServerDiaryStore.kt`, `ServerDiaryDatabase.kt`, `core/sync/ServerDiaryProtocol.kt`, `ServerDiaryValues.kt` | Sześć domen, walidacja całej kopii, ochrona niewysłanych zmian i metadane zastosowania. |
| Konflikty | `data/SyncConflictStore.kt`, `core/sync/ConflictProtocol.kt` | Trwała świadoma decyzja, nowa operacja i odtworzenie pod nowym UUID. |
| Ilości i pochodzenie | `core/sync/ManualMealWire.kt`, `CatalogMealWire.kt`, `PrivateProductWire.kt`, `core` i `core/catalog` | BigDecimal, g/ml, null, źródła i dokładny snapshot. |
| Podłączenie aplikacji | `CalorieApplication.kt`, `MainActivity.kt`, `session/SessionScreen.kt` | Własne moduły O2, ekrany importu i status synchronizacji. Granica sesji pozostaje u O1. |
| Baza i migracje | `data/Database*.kt`, `data/*Migration*.kt`, `android/app/schemas/` | Zachowanie dotychczasowych kolumn, wartości, rowid i FK. |

Istniejące testy urządzenia w `android/app/src/androidTest/java/pl/roseru/kalorie/`: `MealPushStorageTest.kt`, `WeightSyncStorageTest.kt`, `ServerDiaryStorageTest.kt`, `ServerDiaryMigrationTest.kt`, `SyncConflictStorageTest.kt`, `OwnerStorageTest.kt` oraz testy migracji. Przed wyborem pojedynczej metody odczytaj jej rzeczywistą nazwę w danej wersji źródeł.

## 4. Rozdzielenie plików i gałęzi

### O1 zachowuje wyłączny zakres edycji do końca O1-I

- `session/SessionController.kt`, `session/BootstrapGateway.kt`.
- Pliki `MealPushObservation`, `MealPushAckGate`, `MealPushHttpReceipt`, `MealReplayFingerprint` w source setach standard/validation.
- `src/liveReplay/.../LiveMealReplayTest.kt`, istniejący `src/androidTest/.../SessionSecurityTest.kt` oraz `MealPhotoScreenTest.kt` wymagający opisanej diagnostyki CI.
- Dokumenty drivera/kandydata E4 i manifesty skonfigurowanych APK.
- Lokalne pliki sesji, profile emulatorów, transport do O3 i rzeczywiste okno E4.

O2 czyta te pliki, ale nie zmienia ich równolegle. Potrzebny fragment integracji przekazuje w dzienniku: ścieżka, wymagane zachowanie, proponowana sygnatura i minimalna zmiana. O1 wykonuje połączenie. O2 nie kopiuje logowania, vaulta ani transportu do własnego modułu.

### O2 przejmuje implementację swoich trzech modułów

- Nowe pliki domen synchronizacji w `core/sync` i `data`.
- Rozszerzenia `MealPushStore.kt`, `DiaryRepository.kt`, `CanonicalMeals.kt`, `CanonicalWeights.kt`, `ServerDiary*`, `ServerSnapshotStore.kt`, `LocalOwners.kt`, `AccountBootstrapStore.kt`, bazy i migracji, gdy są potrzebne przydziałowi.
- Nowe ekrany i ViewModel importu/uzgadniania oraz statusu kolejki.
- `CalorieApplication.kt`, `MainActivity.kt`, `session/SessionScreen.kt`: podłączenie modułów O2, bez zmiany reguł OAuth/PKCE lub kontraktu sesji.
- W etapie C: własny pakiet WorkManager, konfiguracja zależności Gradle i wymagane podłączenie Androida. Nie aktualizuje przy okazji Kotlin/AGP/Compose.
- Własne testy i dokumentację modułów. Testy SessionSecurity należące do O1 pozostają bez edycji; potrzebne nowe przypadki umieszcza w osobnych klasach.

To rezerwacja zakresu współpracy, nie techniczna blokada Gita. Każdy pracuje w swoim checkoutcie. Wspólnego pliku dziennika nie nadpisujemy; dopisujemy własne wpisy i odpowiedzi, a konflikty rozwiązujemy z zachowaniem obu stron.

### Gałęzie O2

| Etap | Gałąź |
|---|---|
| A | `codex/android-o2-domeny-sync` |
| B | `codex/android-o2-import-i-uzgadnianie` |
| C | `codex/android-o2-sync-w-tle` |

Numer autora pozostaje **agent 2**, także dla kodu Kotlin. Prefiks `android` oznacza obszar; właściciel jawnie rozszerzył zakres O2. Nie ustawiaj globalnej tożsamości autora.

A zaczyna się od aktualnego main, po porównaniu z przypiętą bazą. B korzysta z ukończonego A, C z A/B. Przy niescalonym poprzedniku zastosuj udokumentowaną gałąź zależną i właściwą bazę PR; diff ma pokazywać tylko nowy etap. Nie zakładaj trzech PR na początku pracy. Zapisuj lokalne commity, a PR twórz po ukończeniu dużego rezultatu.

O1-I i O2-A mogą być implementowane równolegle. Kod E4 ma własne przypięte źródło APK; nie podmieniamy go plikami z checkoutu O2. Kolejność integracji ustalamy przez dziennik, z uwzględnieniem zależności. O2 nie czeka z implementacją na dostępność wspólnego live E4.

## 5. O2-A — kompletna kolejka sześciu domen

### Zakres implementacji

1. Prześledź bieżące tworzenie `profile`, `goal`, `diary_day`, `product_draft`. Dla nowych działań w zdrowym kontekście konta zapisuj w jednej transakcji lokalną zmianę i zgodną z kontraktem operację. Gość i starsze wpisy pozostają obsługiwane według B.
2. Dodaj dokładne serializatory i przechowywanie wymaganych metadanych rewizji/kontekstu. Korzystaj z istniejących schematów, nie wymyślaj równoległego DTO serwera.
3. Rozszerz trwały push i walidację ACK na cztery domeny. Cała odpowiedź musi przejść walidację przed zmianą stanu lokalnego. Odpowiedź z błędną dalszą pozycją nie potwierdza prefiksu.
4. Zachowaj istniejące publiczne wejścia `MealPushStore`, `MealPushRequest` i sposób użycia przez SessionController. Nowe parametry mają bezpieczne wartości domyślne; szeroki rename transportu nie jest częścią etapu.
5. Uwzględnij drugą edycję podczas trwającej wysyłki: zamrożony request pozostaje ten sam, następna operacja dostaje prawidłową rewizję lub stan oczekiwania. Konflikt nie uruchamia ślepego nadpisania.
6. Dla celu zachowaj wersjonowaną oś czasu i datę obowiązywania. Usunięcie użytej wersji nie zastępuje nowej decyzji. Uwzględnij `timeline_base_revision` i zależności kolejności.
7. Dla profilu obsłuż delete/recreate oraz pojedynczy żywy profil właściciela. Stary tombstone nie może usunąć nowej tożsamości profilu.
8. Prywatny produkt pozostaje prywatnym szkicem; jego wysłanie nie publikuje go do katalogu społeczności. Konsumpcja ma osobną operację Meal i zachowuje swój snapshot.
9. Dodaj czytelne liczniki/statusy dla sześciu domen. Nazwa historycznej metody `synchronizeMeals` nie jest powodem, by ograniczyć wspólny batch do posiłków.

### Zasady danych

- Brak kcal lub B/T/W to null, nie zero. Nie dorabiaj źródła, gęstości ani ProductRef.
- Ilość lokalna może mieć 12 miejsc po przecinku, kontrakt wire ma limit 6. Nie zaokrąglaj po cichu. Niewysłany dokładniejszy wpis wymaga jawnej obsługi z etapu B.
- `operation_id`, body/hash i kontekst próby pozostają niezmienne po pierwszej próbie wysłania.
- ACK dotyczy konkretnej operacji i jej pierwotnej rewizji. Nie potwierdza późniejszej poprawki ani całego typu danych.
- Kontrola właściciela, generacji i epoki działa również bez aktualnego widoku ekranu.

### Koniec etapu A

Nowe zmiany wszystkich sześciu domen przechodzą przez wspólny trwały mechanizm. Przypadki końcowej kontroli: mieszana paczka, utrata odpowiedzi i `already_applied`, późniejsza edycja, odmowa/konflikt, wadliwy ACK w dalszej pozycji, A→B→A oraz restart. Migracja zachowuje stare dane i kolejkę. Raport rozróżnia fixture od faktycznego APK/API.

## 6. O2-B — gość, legacy i uzgadnianie

### Zakres implementacji

1. Ekran podsumowania importu pokazuje jednoznacznie konto docelowe, zakres i liczbę rekordów, wpisy możliwe do wysłania i wymagające decyzji. Użytkownik zatwierdza przypisanie; samo logowanie nie przenosi historii.
2. Zapisz trwały plan importu i mapowania tożsamości. Zbiór gościa może być przypisany tylko raz. Restart, podwójne kliknięcie i utrata odpowiedzi nie przypisują go ponownie ani innemu kontu.
3. Rozpoznawaj rzeczywiste formaty legacy obecne w bazie, a nie tylko jeden nowy fixture. Zachowaj identyfikatory, kolejność, daty, źródła, null i dokładne ilości. Mapowanie starszego ID, jeżeli konieczne, musi być trwałe i audytowalne.
4. Nie zmieniaj istniejącego body/historycznego hasha w niepewnej lub zamrożonej operacji. Konwersja powstaje jako nowy, powiązany krok z ledgerem; przypadki wymagające ręcznego potwierdzenia mają stan i uzasadnienie.
5. Nie przypisuj starego produktu `basic-*` do produktu official na podstawie samej nazwy lub kcal. Brak udowodnionej referencji oznacza zachowanie dostępnego snapshotu bez fikcyjnego pochodzenia.
6. Dla ilości niemieszczących się w kontrakcie pokaż potrzebę korekty; nie niszcz oryginału i nie zmieniaj null na zero. Import może postępować dla rozstrzygniętych rekordów, z jawną listą pozostałych.
7. Wspieraj pełne uzgodnienie po przeterminowaniu checkpointu w tej samej epoce. Nieobecny znany rekord oznacza usunięcie, a nie automatyczne wskrzeszenie.
8. Dodaj osobną ścieżkę zmiany `sync_epoch`, zgodną z 11.3 i istniejącymi recovery mappings/operation receipts. Nie potwierdzaj starych operacji na podstawie podobieństwa payloadu i nie zmieniaj epoki starej zamrożonej koperty.
9. Pierwszy import gościa może zawierać historię starszą niż 30 dni i starszą niż konto. Limit 30 dni dotyczy gwarantowanego sync przyrostowego, nie prawa zapisania starszej historii.
10. Udostępnij postęp, wznowienie i listę decyzji użytkownika. Anulowanie widoku lub utrata sieci nie cofa zatwierdzonej transakcji ani nie usuwa gościa.

### Koniec etapu B

Gość może przejść do konta, wznowić import po przerwaniu i synchronizować wynik bez duplikacji. Starsze dane mają udowodnioną konwersję albo jawny nierozstrzygnięty stan. Przypadki odbioru: co najmniej dwa konta i gość, dwa uruchomienia tego samego planu, przerwanie między porcjami, legacy z null i 12 miejscami, konflikty UUID, expiry oraz zmiana epoki. Dane wcześniej obecne na serwerze pozostają zachowane.

## 7. O2-C — WorkManager i bezpieczne zarządzanie archiwum

### Zakres implementacji

1. Wprowadź unikalną pracę dla właściwego zakresu konta, uruchamianą po odzyskaniu sieci i nowych kwalifikujących się zapisach. Ręczne żądanie i worker korzystają z jednego mechanizmu, bez dwóch równoległych pętli.
2. Używaj istniejącej sesji i jej odświeżania. Tokeny i hasła nie trafiają do WorkData, logów ani manifestu pakietu. Worker nie prowadzi interaktywnego logowania.
3. Praca przechowuje oczekiwany kontekst właściciela i sprawdza go na granicach operacji. Zadanie A po przełączeniu na B nie wysyła i nie zapisuje danych B. A→B→A nie omija lease/generacji.
4. Zachowaj kolejność pełny/przyrostowy pull → push → pull, wymagany checkpoint oraz zakaz automatycznego rozstrzygania niepewnych operacji.
5. Utrzymuj zapisany Retry-After, kontrolowane ponawianie i stan wymagający działania użytkownika. Brak sieci lub wygasła sesja nie zatrzymuje lokalnego dziennika i nie tworzy pętli żądań.
6. Zapewnij wznowienie po zabiciu procesu i restarcie urządzenia. Anulowanie workera nie oznacza ACK ani zgody na zmianę konta.
7. Rozwiąż rzeczywisty limit archiwów: obecnie 8 prób i 128 MiB na właściciela; pojedyncza próba 64 MiB / 100000 rekordów / 2000 stron. Nie zwiększaj go arbitralnie i nie usuwaj losowych prób.
8. Przed zwolnieniem raw pages sprawdź odwołania z aktywnych prób, zamrożonych batchy, konfliktów, metadanych zastosowania i odzyskiwania. Rozróżnij archiwum z pełnymi stronami od zachowanego potwierdzenia/skrótów po kompaktowaniu. Utrzymuj FK i dowody niezmienności operacji.
9. Zachowaj co najmniej aktualną poprawną kopię oraz materiał niezbędny do oczekujących decyzji. Brak miejsca musi zostawić poprzednią działającą bazę i czytelny komunikat.
10. Dodaj stan w UI: oczekiwanie na sieć/logowanie, praca w toku, termin ponowienia, wynik i liczba pozycji wymagających decyzji. Nie pokazuj prywatnych identyfikatorów technicznych użytkownikowi.

### Połączenie z sesją — wspólna granica

O2 przygotowuje moduł orkiestracji i workera przyjmujący wykonawcę polecenia dla **konkretnego OwnerLease**. Wykonawca jest wstrzykiwany; nie przechowuje tokenu. O1 odczytał i przyjmuje [propozycję O2](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6362901101): `suspend fun executeSyncStep(expectedLease: OwnerLease, expectedContext: AccountBindingEntity, step: SyncStep): SyncStepResult`, z krokami PULL/PUSH i jawnymi wynikami Success/Busy/RetryAt/LoginRequired/ReconciliationRequired/StaleLease. Typy i ich dokładną ścieżkę dostarcza O2. O1 implementuje połączenie w swoim SessionController po przypięciu tego kontraktu; nie jest ono jeszcze wykonane ani odebrane. A/B postępują niezależnie.

Wynik nie może powstawać z parsowania tekstu UI. Cancellation jest propagowana, nigdy zamieniana w Success. Każda faza kontroluje ten sam lease/generację i kontekst przed capture/refresh, przed HTTP i przed zapisem. Adapter PUSH musi kontrolować obecny dodatkowy pull w `synchronizeMeals`, aby orkiestracja O2 PULL→PUSH→PULL była jedyną pętlą. Istniejące publiczne wejścia i guardy pozostają zgodne.

Samo sprawdzenie właściciela przed wywołaniem metody bez parametru, która ponownie pobiera bieżącego użytkownika, nie spełnia KO-31. Nie zastępuj brakującego połączenia nowym klientem HTTP lub kopiowaniem vaulta. Do czasu integracji wynik testów z wstrzykniętym wykonawcą opisuje moduł; pełny wynik aplikacji wymaga rzeczywistego połączenia.

### Koniec etapu C

Po utracie internetu i ponownym połączeniu właściwe konto synchronizuje dane także po zamknięciu ekranu. Powtórne pobrania nie zatrzymują aplikacji po ósmej poprawnej próbie, a niepewna operacja zachowuje materiał do identycznego ponowienia. Sprawdź kolejkę po restarcie, Retry-After, zmianę konta podczas pracy, brak miejsca i scenariusz wielu kolejnych kopii z chronionymi odwołaniami.

## 8. Migracje, historia i zachowanie API lokalnego

- Baza startowa ma Room17. Numer następnej migracji wynika z faktycznej bazy danego etapu; nie rezerwuj 18 osobno dla A, B i C.
- Dodawaj schemat eksportowany przez Room i ścieżkę migracji w każdym wymaganym builderze. Migracja nie jest testem na pustej bazie.
- Zachowaj stare wartości, rowid, źródła, FK, usunięcia i niezmienne wersje celów. Nie stosuj destructive migration, clear/uninstall lub wipe do naprawy wyniku.
- Operacje już próbowane i ich requesty są dowodami. Nie „naprawiaj” ich przez zmianę identyfikatora, body, checkpointu lub kontekstu w miejscu.
- Nowe konstruktory i pola widoku dodawaj tak, by nie łamały istniejących wywołań O1. Przy zmianie niezgodnej podaj dokładny plan integracji przed wspólną publikacją.
- Nie zmieniaj API serwera, JSON Schema ani reguł biznesowych dla wygody klienta. W razie rzeczywistej luki opisz ją z konkretnym przykładem w dzienniku.

## 9. Uruchomienie i kontrola na końcu etapu

Własne Android Studio/Kotlin, SDK35 i JDK17; Gradle przez wrapper projektu. SDK skonfiguruj lokalnie; nie dodawaj własnych ścieżek do repo. Gdy cache nie ma potrzebnej zależności, nie udawaj wyniku trybem offline — przygotuj normalne środowisko.

Przykładowe polecenia z folderu `android` na Windows:

```powershell
.\gradlew.bat :app:assembleDebug :app:assembleValidation :app:assembleValidationAndroidTest :app:lintDebug
```

Wybierz właściwe klasy jednostkowe dla zmienionego modułu dopiero na końcu spójnego etapu. Wzorzec wyboru, po zastąpieniu nazwą faktycznej klasy:

```powershell
.\gradlew.bat :app:testDebugUnitTest --tests "pl.roseru.kalorie.NazwaKlasy"
```

Nie uruchamiaj pełnej regresji po każdym drobnym commicie. Po zakończeniu etapu wykonaj kontrole znaczące dla zmiany; jeżeli znajdziesz błąd, popraw go i sprawdź właściwy zakres. Wymagany zdalny CI pozostaje oddzielnym warunkiem workflow.

Testy Androida uruchamiaj na własnym testowym emulatorze i osobnym applicationId validation. Dane prywatnego dziennika O1 oraz jego zachowany profil testu API są poza zakresem O2. Nie resetuj komputera właściciela ani nie czyść cudzych emulatorów. Instalację/migrację na wcześniejszym stanie testuj z kopią i porównaniem rzeczywistych danych.

Każdy duży etap ma jeden spójny opis końcowy: co działa w aplikacji, czego dotyczy migracja, jakie testy faktycznie wykonano, jakie są ograniczenia i co musi podłączyć O1. Nie podpisuj fixture jako live HTTP, COMMIT PostgreSQL lub rzeczywisty kill.

## 10. Co i jak przekazać O1

Po A/B/C dopisz w jedynym dzienniku własny numer O2, commit, branch/PR, wynik, migrację i następny krok. Dla połączenia z sesją wystarcza konkretny kontrakt:

```text
Do O1: etap A/B/C, dokładny commit
Wejście modułu: klasa/metoda i OwnerLease
Wyjście: typ wyniku, stany końcowe i wymagające użytkownika
Pliki O1: nazwy + minimalny wymagany punkt podłączenia
Trwałość: co zapisuje transakcja i co dzieje się po cancellation
Wykonane kontrole: zakres i faktyczny wynik
Następny krok: odbiór/integracja/konkretne brakujące wejście
```

Nie twórz drugiego pliku pytań ani folderu komunikacji. Nie potwierdzaj odczytu za O1/O3. Brak środowiska live O3 nie zatrzymuje implementacji modułów na lokalnych danych syntetycznych; nie jest też dowodem ich integracji.

## 11. Pierwsze działania Agenta 2

1. Odczytaj ten pakiet, manifest i aktualne wpisy zespołu. Potwierdź w dzienniku przejęcie A/B/C oraz własną gałąź.
2. Porównaj aktualny main z przypiętym84d3dcd. Zachowaj równolegle prowadzone własne zadanie CI; nie mieszaj zmian pipeline z funkcjami Androida.
3. Utwórz własny checkout/gałąź A i zacznij od prześledzenia `DiaryRepository` → outbox → `MealPushStore` → ACK → `ServerDiaryStore`.
4. Realizuj cały A. Nie czekaj na odpowiedź O1, jeżeli praca nie dotyka jego zarezerwowanych plików. Wymagany adapter do sesji zgłoś wcześnie z konkretną sygnaturą.
5. Po ukończeniu A wykonaj kontrole, opublikuj jeden duży PR i przejdź do B zgodnie z zależnościami. Analogicznie C.

O1 równolegle kończy swój pojedynczy etap E4/integracji. Nie przekazuje O2 odpowiedzialności za prywatne konta, klucze Gemini, sieć lub wdrożenie O3. Materiały `Random Data/` pozostają zachowane; do tego zlecenia nie należy porządkowanie ani kasowanie danych źródłowych.
