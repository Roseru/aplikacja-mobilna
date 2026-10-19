# Driver wybranej partii E4 — przygotowanie O1

19.10.2026, gałąź `codex/android-replay-ack`, [PR138](https://github.com/Roseru/aplikacja-mobilna/pull/138).
Kontynuacja [bariery validation](REPLAY_ACK_VALIDATION.md). **Próba urządzenia
i wspólny E4 NOT_RUN**. Ten dokument nie jest poleceniem uruchomienia testu.

## Wejście i osobny build

`LiveMealReplayTest` włącza się wyłącznie właściwością Gradle
`O1_LIVE_E4_REPLAY_TEST=true`; domyślne testy urządzenia nie zawierają drivera.
Każda faza wymaga również argumentów instrumentacji `live_e4_replay=true`,
`synthetic_account=true`, wybranego `phase` i nowego UUID `trial_id`.
Nie podaje się haseł/tokenów w argumentach. Test używa istniejącej sesji APK,
bootstrapu, pełnego snapshotu, prawdziwego transportu i trwałego ACK.

Wymagany jest **istniejący, jawnie wybrany kanoniczny Meal/create** dedykowanego
syntetycznego konta: jedna pending operacja, base_revision=null i mały payload.
Przygotowanie wskazuje jego `meal_id` i `operation_id`. Driver nie tworzy
produktu/posiłku, nie konwertuje legacy, nie seeduje SQL i nie aktualizuje API.
Zwykły historyczny wpis legacy nie spełnia tego warunku; źródło testowej
operacji trzeba ustalić przed próbą. Brak operacji nie jest gotowością.

Potrzebne są później oddzielny skonfigurowany APK validation, opt-in test APK,
manifest z dokładnym commitem/applicationId/versionCode/Room i SHA256 oraz
pełna kwalifikacja. Obecne APK 0.8.23 z manifestu rodzica nie zawierają drivera.
Nie zmieniono numeru wersji lub schematu Room w tym kroku przygotowania.
Próbę trzeba wykonać w osobnym środowisku urządzenia. Nie instalować nowego
APK na zachowanym O1Api35 z oryginalnym APK R2/R3 ani nie zastępować zwykłego
prywatnego dziennika. Sam wspólny applicationId validation nie daje izolacji.

## Fazy uruchamiane osobno

| Faza | Zachowanie i wynik lokalny |
|---|---|
| `prepare` | Sprawdza jeden wskazany pending Meal/create i korzysta z normalnego `MealPushStore.prepare`. Zamraża kopertę bez HTTP; odmawia wykorzystania partii z wcześniejszą próbą sieciową. Prywatnie zapisuje dokładne body/hash/kontekst i odciski chronionych danych. |
| `hold` | Otwiera tę samą partię i porównuje baseline. Uzbraja barierę dla UUID/hash, uruchamia `synchronizeMeals`. Po poprawnym parserze ACK potwierdza HTTP200/no-store z poprawnym request_id, attempted=true, nadal brak trwałego ACK i serverRevision0. Zapisuje marker oraz prywatny PID/start procesu/deadline. Operator wykonuje osobny PG C1, potem zabija rzeczywisty proces aplikacji przed deadline. |
| `replay` | Wymaga innego PID i późniejszego startu procesu oraz niezależnego `external_kill_utc` z receipt operatora, między odebraniem odpowiedzi i deadline hold. Sprawdza zachowaną kopertę, kolejkę i dane. Istniejący kontroler ponawia tę samą partię. Driver zwalnia dopiero zweryfikowaną odpowiedź replay i wymaga already_applied/revision1 oraz trwałego ACK. Zapisuje wynik wyłącznie lokalnych obserwacji. |

Faza hold ma zakończyć się zewnętrznym przerwaniem instrumentacji, a nie
zielonym JUnit. Jeżeli nie osiągnie poprawnej bariery w90s albo proces przeżyje
hold, zapisuje NOT_RUN i kończy jako pominięta próba. Naruszenie invariantów
jest FAIL. `not-run.json` blokuje późniejsze podszycie tej próby pod udany kill.
Driver dodatkowo wymaga co najmniej20s pozostałych na C1 i kill po lokalnym
sprawdzeniu. Operator musi zapisać niezależny czas rzeczywistego kill;
sam nowy PID ani podany argument nie są dowodem serwerowego C1.

W replay ponowne krótkie użycie bariery służy powiązaniu aktualnego receipt
z tą samą kopertą przed zwolnieniem do normalnego zapisu ACK. **Tylko pierwsza
faza hold testuje utratę ACK**; release w replay nie jest zastępstwem kill.
Zwykły wariant aplikacji nadal nie zawiera wywołania obserwatora w bytecode.

## Prywatne dane i porównanie

Przygotowanie, hold i wynik trafiają do `noBackupFilesDir/e4-replay/<trial_id>`.
Pliki są tworzone wyłącznie jako nowe, z fsync, bez nadpisywania istniejących
dowodów. Częściowy plik po awarii nie stanowi poprawnego dowodu. Są tam raw
body i lokalne identyfikatory; ewentualny odbiór przez operatora musi trafić
do prywatnego katalogu poza Git/OneDrive. Nie publikować plików lub raw logów.

Odciski obejmują19 tabel danych, ich rowid, wszystkie konta/gościa i wspólny
katalog, z kontrolą FK. W wybranych wierszach normalizuje się **tylko**:

- meals.serverRevision — osobno wymagane0 przed ACK i1 po replay;
- outbox.status — osobno wymagane pending/acked;
- sync_push_batches.attempted/responseJson/state — sprawdzane osobno według fazy.

Wszystkie pozostałe kolumny i wiersze, w tym selected Meal/wire i inne partie,
pozostają w odciskach. Zmiana body/hash/kontekstu koperty jest dodatkowo
sprawdzana wprost. Metadane sesji i archiwum snapshotu mogą legalnie się
zmienić; nie twierdzimy, że wszystkie27 tabel pozostają identyczne podczas sync.
Porównania muszą być wykonane bez równoległych zapisów użytkownika.

## Neutralny receipt HTTP

Validation obserwuje wyłącznie POST `/api/v1/sync/push` dla hasha aktualnie
uzbrojonej partii. Log zawiera run, stałą ścieżkę, UTC, status, flagę no-store
i oczyszczony request_id; brak body, konta, UUID partii, hasha lub tokenu.
Nieprawidłowy request_id zastępuje `invalid`, brak — `missing`.
Historia ma najwyżej4 wpisy; przekroczenie limitu jest flagowane i uniemożliwia
uznanie starego receipt za nowy. Inne żądania i nieuzbrojony transport nie
tworzą tego receipt. Obserwacja nie zmienia odczytu/parsowania odpowiedzi.
Sam HTTP200 lub nagłówek nie stanowią dowodu COMMIT; odpowiada za to osobny PG C1.

## Odbiór pozostający do wykonania

Końcowy wynik: **24/24 JVM PASS**, bez błędów/pominięć (0,445s wykonania),
obejmuje12 testów bariery,7 metadanych HTTP i5 zasad odcisków. Kompilacja
kontrolera/transportu standard21,83s i validation21,95s exit0. Sprawdzono brak
referencji obserwatora w wynikowych klasach standard i obecność w validation.
Driver skompilowano w9,78s; po przeglądzie dodano ochronę rowid i dokładniejszy
czas kill, następnie skompilowano tylko zmieniony driver:8,41s/exit0.
Pozostałe wejścia miały identyczne hashe; nie powtarzano zbędnie całej kontroli.

Pierwszy przebieg miał23 PASS/1 FAIL: syntetyczny request_id zawierał wyłącznie
cyfry, więc uppercase nie zmieniał go w nieprawidłowy UUID. Poprawiono ten
test na UUID z literą, zachowano pierwotny log i wykonano ponownie24/24.
Walidator nie został osłabiony. Weryfikacja używała jednego procesora,
heap256MiB i obniżonego priorytetu. To nie pełny build Gradle, pakowanie/flagi
APK, wykonanie Room, instrumentacja ani rzeczywisty restart.

Sprawdzono12 wejść źródłowych. SHA256 logu24 JVM:
`b818dd6ed4328d98d536829eed11c063956c72b0add6213e0496611e80cb6a3c`.
SHA256 końcowego receipt kompilacji drivera, wiążącego hashe z poprzednimi
wynikami: `3dd507a6042839811dcfc748a45f76c039e16ff6082967eded94496a9ec7f291`.
Najpierw pełny build/native oraz potwierdzenie testowego wejścia, potem
O2/O3 porównują konkretny kandydat z obrazem/schema24, uzgadniają świeży peer,
ograniczone okno i niezależne C0/C1/C2. Lokalny PASS drivera nie zamyka E4:
potrzebne osobne PG C1→C2 bez dodatkowej mutacji, receipt kill i zamknięcia.
Bez importu gościa, legacy, konfliktów/recovery, WorkManager, E7 lub KO32.

Podczas gry właściciela: bez Gradle, emulatora, instalacji, sieci testowej,
Gemini i restartu komputera. Dostęp do serwera nie został otwarty.
