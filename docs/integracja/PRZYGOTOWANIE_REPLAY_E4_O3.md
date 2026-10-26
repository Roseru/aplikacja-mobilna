# Przygotowanie obserwacji PostgreSQL dla replay E4 — O3

## Potwierdzony pin kompilacji Room23 — 26.10.2026

**O3-105: wejścia kompilacji potwierdzone; peer/okno i osiągalność O1 nadal
niepotwierdzone.** [Przekazanie A1 z odczytem kontrolnym](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6411463409)
odpowiada na [prośbę6398540989](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6398540989).
Brak peera nie blokuje budowy. Poniższy pomiar nie kwalifikuje źródeł drivera,
czterech APK ani wykonania E4; starsze wyniki zachowują swój zakres.

| Wejście | Pin |
|---|---|
| `CALORIE_API_BASE_URL` | `https://192.168.3.162:18443/api/v1` |
| `CALORIE_OIDC_ISSUER` | `https://192.168.3.162:18443/realms/calorie-dev` |
| client / audience | `calorie-android` / `calorie-api` |
| callback validation | `pl.roseru.kalorie.validation:/oauth2redirect` |
| CA PEM | `tls/ca.pem`, 1192 B |
| SHA-256 dokładnych bajtów CA PEM | `01f120ef25f091a6413a535dcaa5e333575a8d08a016503c47998333eef3a6f6` |
| źródło Androida / receipt O1 | `eacc8f192ed9c9cd5c8e45e38f44385b18b6774d` / `2319357d06da47af818f2b891bc1efbde486b734` |
| Android tree / wersja | `0c83ee386de48335a49ac3061523befcfe1de073` / 0.8.35, code46, validation1046, Room23 |

### Pobranie i użycie publicznego CA/config

[Istniejący publiczny ZIP](https://github.com/Roseru/aplikacja-mobilna/releases/download/integration-handoff-20261014/O1-APK-API-20261014.zip)
ma 19497599 B i SHA-256
`89c3709635c4e89a27da2a809a14ef13a3c755baf359ac24f5e83729ec51ee6b`.
O3 pobrał go niezależnie 26.10 o08:20:50UTC: wszystkie10 wpisów `SHA256SUMS`
zgodne; `config.json` zawiera dokładnie host192.168.3.162/port18443, a CA
jest identyczny z aktywną instalacją. Używamy z niego CA/config. Dołączony
`validation.apk`0.8.10 pozostaje historyczny; nie instalować go w celu odbioru
Room23 i nie przedstawiać jako jednego z czterech nowych APK.

Pobrać ZIP, porównać jego sumę i rozpakować do nowego katalogu. Sprawdzić
`SHA256SUMS` i osobno pełny hash `tls/ca.pem`. O1 generuje **nowy lokalny overlay**
z tych dwóch publicznych wejść przez
[android_overlay.py na przypiętym źródle operatora](https://github.com/Roseru/aplikacja-mobilna/blob/143bf0aaf86ce924e6ba45140fc2c7838914f4bd/infra/integration/android_overlay.py):

```text
python infra/integration/android_overlay.py --state <rozpakowany-ZIP> --output <nowy-lokalny-overlay>
```

Użyć istniejącego środowiska Python z cryptography. Przy kompilacji źródła
Room23 podać **obie** właściwości Gradle z tabeli i własne
`-I <nowy-lokalny-overlay>/init.gradle`. O3 rzeczywiście wykonał generator
na source143bf0a/tree5d385fadc854c26cd991c99c6a09760c86affbf2 i sprawdził wynik:
validation-only, dokładny host, cleartext=false, includeSubdomains=false,
userCA=false, identyczny hash CA. Nie przenosić absolutnej ścieżki overlay O3.
Regularny debug i domyślny testAPK zachowują role z kontraktu dostawy;
O1 przekazuje cztery artefakty z manifestem i nowym `android_acceptance`.

### Aktywna instalacja i granice pomiaru

Własny pomiar O3 26.10 o08:17UTC, bez wdrożenia lub migracji:

- HTTPS przez loopback przy zachowaniu **oryginalnej tożsamości TLS**:
  readiness200/statusok, discovery200, dokładny issuer i authorization endpoint,
  reklamowane S256. `/api/v1/me` bez tokenu401; nieznane CA i błędny hostname
  odrzucone. To odczyt API/TLS, bez nowej sesji PKCE lub próby APK.
- CA ważny 11.10.2026 09:41:44UTC–10.10.2028 09:46:44UTC; fingerprint DER
  `52af6be4592f8bf4d21e312670cca2e447e05b4e8ccec7712010bf1272d86ea0`.
  CA nie ma SAN. Certyfikat serwera ważny 11.10.2026 09:49:31UTC–09.01.2027
  09:54:31UTC, SAN IP192.168.3.162/DNSgateway, SHA-256 DER
  `af1bff52f9cb7f877a8f6539d8d9100293e5c3a6a7dcdcd478e0670e67677ac4`.
  Fingerprint DER różni się od sumy pliku PEM; pin budowy dotyczy PEM z tabeli.
- Rzeczywisty API image
  `sha256:05c1792f3551725f0303cc3786892771392532a25edc18ff710faad9e6b7e9a9`,
  PostgreSQL17.11, schema `0024_e9_history_graph`, odczyt
  `transaction_read_only=on`. Przyjęcie CI48 nie oznacza wdrożenia tego obrazu.
  Pin konfiguracji kontenera API: SHA-256 canonical JSON `.Config`
  (sort_keys=True, separators bez spacji)
  `9d992a0f414706c0ae759063678582221843df7f1a42cf7f7f26a3415b2caf0e`.
  Surowa konfiguracja pozostaje prywatna; hash nie dowodzi źródeł całego obrazu.
- Identyfikatory/obrazy/config8kontenerów, pliki konfiguracji, epoka i schemat
  zachowane przed/po. API/PG/Keycloak/retention/motivation/lifecycle/TLS OK;
  finalizer `expected_disabled`. Brak deploy, rotacji CA, zmiany kont lub epoki.
- Pierwszy skrypt pomiarowy błędnie wymagał200 z publicznego manifestu
  official; otrzymał404 i zakończył się FAIL. Oryginalny wynik zachowany.
  Router jawnie zwraca404 przy braku official package; parametr `channel=demo`
  nie udostępnia demo i także zwrócił404. Nie publikowano pakietu i nie
  uznawano tych odpowiedzi za PASS pobierania katalogu.
- Monitoring ma nieaktualne referencje ścieżek do receiptów kopii/startu,
  więc odczyt według nich daje failed. Odczyt istniejących receiptów z właściwego
  katalogu: lokalna kopia PASS/verified07:05:43UTC26.10, start PASS/07:04:13UTC,
  offsite PASS/24.10 09:32:45UTC (starszy niż24h). To odczyt wcześniejszych
  dowodów, nie nowe wykonanie kopii/restore/startu ani aktualny odbiór offsite.
  Nie zmieniono prywatnych referencji i nie ponawiano zdrowego demo lub kopii.

### Osobna gotowość transportu i próby

Bezpośredni192.168.3.162:18443 z O3 zakończył się timeoutem. Loopback PASS nie
potwierdza osiągalności O1. W PR146 i livechat27 poproszono O1 o rzeczywiste,
osiągalne adresy obu peerów LAN/VPN oraz krótki termin UTC i długość dzierżawy.
Dopiero po ich potwierdzeniu operator stosuje
[istniejący transport](../../infra/integration/ANDROID_HANDOFF.md), dokładny
bind i jeden dopuszczony adres O1 z krótkim TTL, a O1 wykonuje własny preflight.
Nie zmieniać issuer/API na adres routingu. Nie otwarto relay, zapory, routera,
anonimowego API/ADB ani tunelu internetowego.

Pin kompilacji jest dostarczony. Peer/okno, transport O1, kwalifikacja źródeł,
cztery skonfigurowane APK i ich odbiór pozostają odrębnymi wejściami przed live.
Room26/PR175/PR178 nie zastępują zamrożonego Room23. Historyczne Room20/API24
i dobre kopie zachowane. Nowe E4/PG C0C1C2/PULL/pakiet/kopia nadal NOT_RUN;
nowy pakiet i kopia dopiero po dostawie4APK i jej odbiorze.

## Procedura operatora Room23 — odbiór źródła 26.10.2026

Ta procedura opisuje odbiór nowego drivera z trwałą izolacją runtime.
Jej opublikowanie nie oznacza wykonania próby ani przyjęcia nowych APK.
Poniższe historyczne wyniki Room14/17–20 zachowują swoje źródła i zakresy.

Podstawą jest [zamrożony kontrakt Room23](https://github.com/Roseru/aplikacja-mobilna/blob/2319357d06da47af818f2b891bc1efbde486b734/android/DRIVER_REPLAY_E4.md).
O3 przyjął poniżej źródło integracji i poprawkę P2 w zakresie statycznego
przeglądu. Nie otwiera to okna live: nadal wymagane są rzeczywiste cztery
skonfigurowane APK, `android_acceptance` i uzgodniony pakiet środowiska.

### Przyjęte źródło i zakres odbioru O3-106

Własny odbiór O3 z26.10 obejmuje surowe obiekty Git, graph/tree, odczyt kodu,
kontraktu i regresji. [Dostawa O1](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6399203852)
oraz zapisane wyniki O1/O2 są dowodami odczytanymi, nie własnym wykonaniem
Androida przez O3. W tym odbiorze nie uruchamiano Gradle, AVD, instrumentacji,
Keycloak/TLS, E4/PG/PULL ani instalacji. Nie znaleziono materialnego P1/P2
w opisanym niżej zakresie; nie jest to pełny odbiór native/live lub projektu.

| Pin | Wartość niezależnie sprawdzona przez O3 |
|---|---|
| Source integracji | `eacc8f192ed9c9cd5c8e45e38f44385b18b6774d` |
| Rodzice source | `ccb614ed6ffeff314a17e8a4d65cac012fb1624b` + `11fac87ab9c3e01b793671ff5fdf1f0599854f29` |
| Finalny runtime O2 w historii source | `325446b0b762f1088822d296455d522fbe8fe10d` |
| Receipt O1, jedyny rodzic = source | `2319357d06da47af818f2b891bc1efbde486b734`; delta wyłącznie dziennika |
| Android tree obu pinów | `0c83ee386de48335a49ac3061523befcfe1de073` |
| App tree obu pinów | `5a63736906747d220d3f29394192283ac08e5eec` |
| Wersje źródła | regularny `0.8.35`/46, validation `0.8.35.validation`/1046; Room23 |
| Eksport Room23 | 49 encji, identity `d8e3ed92a9b0fd8af6cc2e57fc644687`; guard obejmuje39 jawnych tabel oraz `__schema__`, nie49 tabel |

**P2/6392899041 zamknięty dla tego źródła w przeglądzie O3.** Historyczny
[source526 i kontrprzykład](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6392899041)
pozostają nieprzyjęte i zachowane jako historia. W nowym
[paused:119](https://github.com/Roseru/aplikacja-mobilna/blob/eacc8f192ed9c9cd5c8e45e38f44385b18b6774d/android/app/src/validation/java/pl/roseru/kalorie/sync/ReplayRuntimeIsolation.kt#L119)
nie ma drugiego odczytu czasu: istniejący nieterminalny fence zawsze blokuje.
[observed:129](https://github.com/Roseru/aplikacja-mobilna/blob/eacc8f192ed9c9cd5c8e45e38f44385b18b6774d/android/app/src/validation/java/pl/roseru/kalorie/sync/ReplayRuntimeIsolation.kt#L129)
przed dopuszczeniem pracy zapisuje `ready=false, terminal=true`; błąd zapisu
propaguje wyjątek. `write:167` używa AtomicFile, fsync i odczytu kontrolnego.
`current:118` odrzuca terminal także po rollbacku, a `read:162` odrzuca
ciągłość dawnego v1. Rekonstrukcja nie odnawia terminu ani tego samego trialu.
[Regresja:116](https://github.com/Roseru/aplikacja-mobilna/blob/eacc8f192ed9c9cd5c8e45e38f44385b18b6774d/android/app/src/androidTest/java/pl/roseru/kalorie/ReplayRuntimeIsolationTest.kt#L116)
wymusza `expires-1 → expires`: najpierw Paused/0 zapisów, potem Admitted/1
i trwały terminal, rollback, rekonstrukcję, odmowę requireHeld/arm starego
trialu i dalszą pracę bez odżycia izolacji. Nie wymaga callbacku timera.
O3 odczytał kod i receipt wykonania O1; nie powtórzył tej regresji native.

**Złożenie runtime:** [Application:24–36](https://github.com/Roseru/aplikacja-mobilna/blob/eacc8f192ed9c9cd5c8e45e38f44385b18b6774d/android/app/src/main/java/pl/roseru/kalorie/CalorieApplication.kt#L24)
ma jedną networkPolicy, `savedEvidence=sessions` oraz jedną admission dla
SyncWorkRuntime i drivera (`LiveMealReplayTest:68`).
[SyncWork:79](https://github.com/Roseru/aplikacja-mobilna/blob/eacc8f192ed9c9cd5c8e45e38f44385b18b6774d/android/app/src/main/java/pl/roseru/kalorie/sync/SyncWork.kt#L79)
wykonuje `attach(1)`; current/signal/manual/execute/reschedule, oba obserwatory
i operacje schedulera pozostają wewnątrz admission, bez zagnieżdżania osłon.
Paused nie konsumuje zdarzenia ani nie planuje retry poza granicą.
`changes` umożliwia ponowną ocenę po otwarciu. Scheduler oczekuje na zakończenie
enqueue/cancel. Testy admission obejmują także pustą bazę bez ensureGuest.

[Drainer sesji:756](https://github.com/Roseru/aplikacja-mobilna/blob/eacc8f192ed9c9cd5c8e45e38f44385b18b6774d/android/app/src/main/java/pl/roseru/kalorie/session/SessionController.kt#L756)
pracuje pod istniejącym mutexem i transakcją, sprawdza lease/kontekst/revision
sesji oraz cancellation. Recovery korzysta z już kompletnego raw i zapisanego
ACK z dowodem targetu; bez nowego run/koperty, refresh lub HTTP. Ordinary
stosuje istniejącą pełną kopię, bez ponawiania historycznych atomowych ACK.
Coordinator drenuje przed blokadą sieci/Retry-After, ale APPLIED nie kończy
PULL ani cyklu. O3 porównał kod sync/network z325446b: identyczny; delta
SessionController dodaje tylko zachowany fragment community O1. NetworkIssuance
wiąże permit/ticket z instancją i generacją także przy conflated ABA, a helper
NetworkOperationCancellation reaguje na onCancelling i zamyka własny
PolicyConnection przy stałym Allowed, z dispose/finally i przywróceniem ThreadLocal.
To przyjęcie integracji źródeł, nie nowy test rzeczywistego transportu/AppAuth.

**Rozdzielone dowody O1/O2:** O1 zachował pierwsze **6PASS+1FAIL**, poprawił
wyłącznie fixture callbacku do logicznego validation i ponowił tylko **1PASS**.
Pierwszy FAIL przed replay i oba zakresy pozostają widoczne; nie zapisujemy
nowego7/7. LogSHA serii: `967e1f4a65534af84ca967e7601a03000d27176011fe9a39c9b91912562630f8`
i `7ab796dd1ef08d534ef725fc45e49720627352ec93d08feebafb25030ac3b598`.
Build/lint O1 i54native+6JVM komponentu O2 pozostają osobnymi odczytanymi
wynikami. Podane przez O1 app/test SHA i zachowanie danych dotyczą jego
izolowanego runtimecheck, nie wymaganej dostawy4APK. Granica API/sesji była
syntetyczna. Receipt nie zmienia Android tree; późniejsze Room26/PR175/178
oraz ich CI nie kwalifikują nowej dostawy zamrożonego Room23.

### Warunki otwarcia nowego okna

Przed instalacją i nową próbą operator zbiera następujące dowody:

- **Źródło:** powyższy zamrożony pin, przyjęty przez O3 w zakresie source/P2/DI.
  [Finalna dostawa O2](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6397556695)
  i [ACK O1](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6398434885)
  kończą dawne WAITING_O1_PORTS i rezerwacje runtime. Nie są już oczekiwaniem
  na implementację; zgodność wykonania nadal musi wynikać z nowych artefaktów.
- **O1:** spójna dostawa czterech APK: regularny debug, skonfigurowany validation,
  domyślny testAPK oraz opt-in liveReplay testAPK. Manifest wiąże ich source/tree,
  applicationId, target instrumentacji, wersję/code/Room, rozmiar, SHA-256 i podpis.
  Operator sprawdza skompilowane API/issuer/CA i nowy `android_acceptance`.
  Nieskonfigurowane pary `replaycheck` lub `expirycheck` nie są tą dostawą.
  Statyczny odbiór rzeczywistych plików wykonuje
  [apk_delivery.py](../../infra/integration/apk_delivery.py) z niezależnymi
  `--source-commit eacc8f192ed9c9cd5c8e45e38f44385b18b6774d` i
  `--source-android-tree 0c83ee386de48335a49ac3061523befcfe1de073`. Role kontraktu to
  `debug`, `validation-configured`, `test-default`, `test-liveReplay-optin`.
  Opt-in musi celować w skonfigurowane `pl.roseru.kalorie.validation`/1046,
  a każda instrumentacja jawnie deklarować target_role/target_package/runner
  oraz zgodny podpis celu. Regularny debug to `pl.roseru.kalorie`/46;
  wersje aplikacji odpowiednio0.8.35 i0.8.35.validation. Wersje testAPK odczytuje
  się z plików, nie wyprowadza z wersji aplikacji. Manifest wiąże aktualny
  publiczny config i dokładne wpisy CA/XML; nie wystarczają deklaracje buildera.
  `STATIC_PASS` nie zastępuje `android_acceptance` ani live E4.
- **Konfiguracja kompilacji:** [publiczny pin O3-105](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6411463409)
  dostarczono26.10. API/issuer, CA/config z istniejącego pakietu i jego sumy
  pozwalają O1 budować4APK; historyczny APK z tego pakietu pozostaje osobno.
  Są to odczytane pomiary drugiego zadania O3. Peer/okno i osiągalność od O1
  nadal wymagają uzgodnienia; sam loopback PASS nie otwiera próby.
- **O3 z zespołem:** aktualny obraz API, schemat, epoka i prywatne powiązanie
  konta syntetycznego z właścicielem PG, uzgodniony peer oraz ograniczone okno.
  Dane logowania pozostają poza Git i argumentami instrumentacji. Odbiór
  transportu/TLS i konta poprzedza trial; dawny adres lub stare okno nie
  potwierdzają dzisiejszej gotowości.

Nie podmienia się numeru Room lub hashy w starym planie. Room24 kalkulatora
i Room25 korekt energii wymagają własnego zgodnego kontraktu i kwalifikacji.

### Argumenty i kolejność operatora

Opt-in testAPK powstaje z `O1_LIVE_E4_REPLAY_TEST=true`. Każda faza jest osobnym
wywołaniem `LiveMealReplayTest` z literalnymi `live_e4_replay=true`,
`synthetic_account=true`, właściwym `phase` i tym samym nowym kanonicznym
`trial_id`. Tylko `prepare` otrzymuje `meal_id` i `operation_id`; tylko `replay`
otrzymuje niezależny `external_kill_utc`; tylko `release` wymaga
`allow_runtime_resume=true`. Nie ma argumentu przedłużającego izolację.

| Krok | Działanie | Dowód przed następnym krokiem |
|---|---|---|
| 1. Sesja | Na osobnym środowisku: sesja, bootstrap i zastosowana najnowsza pełna kopia. | Potwierdzone konto i kontekst, bez tworzenia wybranej operacji przed izolacją runtime. |
| 2. `isolate` | Przed freeze utrwalić prywatną blokadę, anulować dopuszczone wejścia i poczekać na ich finally. | `isolated.json`, gotowa izolacja oraz brak aktywnych mutacji; brak attach lub timeout blokuje baseline. |
| 3. Nowy Meal | Dopiero przy gotowej izolacji normalnym UI utworzyć jedną świeżą pending kanoniczną `Meal/create`, `base_revision=null`. | Dokładnie jedna eligible operacja i jej trwałe `meal_id`/`operation_id`; bez seed SQL/Room. Automatyczny drainer nie może jej wcześniej zamrozić, oznaczyć attempted lub wysłać. |
| 4. `prepare` | Zamrozić wybraną kopertę bez HTTP i zapisać ścisły baseline. | `prepared.json`, `driver_guard_version=2`, ten sam trial/konto/kontekst i stały `isolation_deadline`. |
| 5. Plan PG i C0 | Wczytać `prepared.json` przez `prepare --driver-prepared` i utworzyć osobny plan PG w zgodnym runtime backendu, następnie wykonać niezależny read-only C0. | Plan powstały przed C0, hash koperty i operacji, oczekiwana treść Meal oraz C0 bez docelowej mutacji. |
| 6. `hold` | Wykonać rzeczywisty POST; poprawny ACK zatrzymać przed lokalnym zapisem. | `held.json`, HTTP200/no-store, attempted=true, revision0 i brak lokalnego ACK; zapisany rzeczywisty termin kill. |
| 7. C1 i kill | Osobnym połączeniem PG potwierdzić COMMIT, następnie naprawdę zatrzymać proces przed terminem hold. | C1 oraz niezależny receipt operatora z czasem rzeczywistego kill. Hold kończy się przerwaniem instrumentacji. |
| 8. `replay` | W nowym procesie, przy nadal ważnej izolacji, ponownie wysłać identyczną utrwaloną kopertę i zastosować oryginalną rewizję. | `replayed.json`: inny PID/późniejszy start, świeży HTTP receipt, `already_applied`/revision1, trwały ACK i ścisły guard. |
| 9. C2 i compare | Przed release i wygaśnięciem izolacji zebrać trzeci niezależny odczyt PG i porównać C0/C1/C2 z tym samym planem. | C1=C2 także dla treści i odcisków; osobny wynik obserwatora PG oraz dowody Androida/HTTP/kill. |
| 10. `release` | Po zebraniu dowodów osobno, jawnie wznowić runtime zgodnej próby. | `released.json`; ten receipt nie nadaje PASS replay, PG ani PULL. |
| 11. PULL | Wykonać i odebrać zwykły PULL jako osobną operację, następnie składać pakiet i kopię zmienionego stanu. | Oddzielny wynik PULL; nie dopisywać go do wcześniejszego odcisku ACK. |

### Dwa niezależne terminy

| Termin | Sposób użycia |
|---|---|
| `isolation_deadline` | Epoch millis ustalone przy isolate: domyślnie20 minut, limit mechanizmu30 minut. Obejmuje utworzenie operacji w UI, plan PG, C0, hold, restart/replay i C2. Restart/ponowienie nie odnawia terminu. |
| `held.json.deadline_utc` | Rzeczywisty termin bariery ACK z pozostałego czasu monotonicznego, maksymalnie45 sekund. C1 i kill muszą zakończyć się przed nim. Nie wyliczać `held_utc+45s` ani45 sekund od odczytu pliku. |

Driver wymaga co najmniej20 sekund pozostałych po lokalnych kontrolach hold.
Osobne45 sekund oczekiwania na quiescence,90 sekund na odpowiedź i120 sekund
TTL uzbrojenia bariery nie zastępują terminu kill. Wymagane jest
`held_utc <= external_kill_utc < deadline_utc`. Nowy PID i HTTP200 nie dowodzą
odpowiednio rzeczywistego kill ani serwerowego COMMIT.

### Koperta drivera i osobny plan PostgreSQL

`prepared.json` nie jest planem [obserwatora PG](../../infra/integration/e4_observer.py).
Do przygotowania planu służy bezpośrednie wejście `--driver-prepared`.
Adapter wymaga `driver_guard_version=2` i `room=23`; odczytuje najwyżej
5 000 001 bajtów, odrzucając receipt większy niż5 000 000 bajtów. String
`request` koduje dokładnie jako UTF-8, bez dodawania BOM/newline, usuwania
whitespace lub ponownej serializacji JSON. Żądanie musi mieć od1 do65 536
bajtów, a SHA-256 tych bajtów musi odpowiadać driverowemu `hash`.

Adapter wiąże `trial` z kontekstem PG, `meal` i `operation` z zamrożoną
operacją, a `context.account_id` i `context.sync_epoch` z właścicielem PG
i epoką koperty. Driverowe `owner` to lokalny storageScope i może różnić się
od `owner_id` PostgreSQL. Niejednoznaczny JSON, błędne UTF-8, duplikaty kluczy
i niefinitywne liczby są odrzucane przez wspólny parser backendu.

Prywatny kontekst dla `e4_observer.py prepare` ma dokładnie `trial_id`, `owner_id`,
`expected_schema`, `expected_api_image`. Obserwator wyprowadza pozostałe pola
w zgodnym runtime backendu. `prepared.json.context` jest kontekstem wire
i nie zastępuje tego pliku. `operation_sha256=fingerprint(operation)` jest
odrębny od `envelope_sha256`; `expected_meal` pochodzi z requestu przed C0,
nigdy z odczytu C1. Po C0 nie zmieniać planu.

Interfejs CLI, z prywatnymi plikami dostarczonymi przez operatora:

```text
e4_observer.py --plan <context.json> prepare --driver-prepared <prepared.json> --output <pg-plan.json>
e4_observer.py --plan <pg-plan.json> capture --settings <settings.json> --phase C0 --output <C0.json>
e4_observer.py --plan <pg-plan.json> capture --settings <settings.json> --phase C1 --output <C1.json>
e4_observer.py --plan <pg-plan.json> capture --settings <settings.json> --phase C2 --output <C2.json>
e4_observer.py --plan <pg-plan.json> compare <C0.json> <C1.json> <C2.json>
```

Stare wejście `prepare --request <request.bin> --output <pg-plan.json>` pozostaje
dostępne zamiast `--driver-prepared`. Wtedy operator sam eksportuje dokładne
bajty UTF-8 stringa `request` i sprawdza ich SHA względem `hash`; nie używa
domyślnego PowerShell `Out-File` ani ponownej serializacji obiektu JSON.
Obu wejść nie można podać jednocześnie. Wynikowy format planu pozostaje ten sam;
wyjście jest nowym prywatnym plikiem i nie nadpisuje wcześniejszych dowodów.

Przygotowanie planu działa offline. Sprawdzenie bajtów i powiązań nie odbiera
guardów Room, fence, terminu izolacji, runtime admission, APK ani całej próby.
Warunki otwarcia okna i niezależne dowody Androida nadal obowiązują.

Capture C1/C2 następują wyłącznie w odpowiednich miejscach powyższej sekwencji.
Plany, snapshots i driver receipts mają różne formaty. Raw request, identyfikatory
konta i prywatne pliki dowodowe pozostają poza repozytorium i publicznymi logami.

### Zakres guardów i odmowy

Android Room23 chroni39 tabel oraz dodatkowy `__schema__`: wszystkie wiersze,
kolumny, rowid, konta/gościa, wspólny katalog i definicje tabel/indeksów/triggerów,
także przy pustych tabelach. Listę definiuje [MealReplayFingerprint](https://github.com/Roseru/aplikacja-mobilna/blob/eacc8f192ed9c9cd5c8e45e38f44385b18b6774d/android/app/src/validation/java/pl/roseru/kalorie/session/MealReplayFingerprint.kt).
`sync_work_state`, pozostałe nowe ledgery i `diary_days` pozostają ścisłe.
Normalizacja dotyczy wyłącznie wybranych pól ACK:

- `meals.serverRevision`, z osobną kontrolą0 przed ACK i1 po replay;
- `outbox.status`, z osobnym wymaganiem pending/acked;
- `sync_push_batches.attempted/responseJson/state`, sprawdzanych według fazy.

PG obserwuje sześć tabel serwera. Nie rozszerza się jego listy do39 tabel Room.
PASS jednej strony nie zastępuje drugiej. Wersja prywatnego fence2, driver guard2
i admission contract1 to trzy odrębne oznaczenia. Nowy odebrany driver ma wymagać
`ready=true, terminal=false` podczas chronionej obserwacji oraz nieodwracalnego
zakończenia przed dopuszczeniem pracy po expiry. Dawny fence v1 nie dowodzi
ciągłości izolacji i nie jest aktualizowany w miejscu do gotowego dowodu.

Zachować rzeczywisty wynik instrumentacji. Kontrakt referencyjny zapisuje
`not-run.json` i kończy jako pominięty NOT_RUN po timeout oczekiwania na hold
albo gdy proces przeżył hold. Wygaśnięcie izolacji w `requireHeld`, timeout
bariery podczas replay oraz naruszenia assertions propagują FAIL; nie
reinterpretować ich jako pominięcia. Brak warunków wejściowych przed uruchomieniem
próby oznacza, że próby nie wykonano, bez tworzenia zastępczego driver receipt.
`not-run.json` i `guard-failed-<phase>.json` zachować.
`replayed.json` pozostawia PULL jako `NOT_RUN_SEPARATE_OPERATION`.
Receipts `isolated/prepared/held/replayed/released.json` powstają wyłącznie jako
nowe pliki. Chwilowo pusty lub istniejący plik nie uzasadnia ponownego wysłania
tej samej fazy. Nie nadpisywać dowodów ani nie odnawiać starego trialu/baseline.

Release runtime jest odrębny od wewnętrznego zwolnienia bariery ACK w replay.
Driverowy release/abort wymaga poprawnego `isolated.json`. Gdy isolate utrwali
fence, lecz timeout nastąpi przed zapisaniem tego receipt, zwykłe release nie
jest uniwersalnym abortem: zachować dowody i uzgodnić osobną interwencję O1.
Nie dopisywać ręcznie receipt, nie usuwać fence ani nie czyścić danych aplikacji.
Wygaśnięcie, anulowanie lub disarm bariery nie dostarczają zatrzymanego ACK.

W release fence jest usuwany przed zapisem `released.json`. Brak lub częściowy
receipt po awarii zapisu nie dowodzi, że izolacja nadal trwa: runtime może już
działać. Zachować stan i dowody, uzgodnić interwencję O1 bez automatycznego retry,
odtwarzania fence lub ręcznego dopisywania receipt.

---

Poniżej zachowano historię wcześniejszych odbiorów z ich pierwotnymi datami,
kandydatami i ograniczeniami. Do nowego trialu Room23 służy procedura powyżej.

## Próba operatora O3 — 23.10.2026, 12:53–12:54 CEST

**Jedna rzeczywista próba Meal/utrata ACK/restart/identyczny replay na własnym
świeżym AVD O3: PASS po stronie APK i niezależnego PostgreSQL.** To wynik
konkretnego kandydata Room14. Aktualny kandydat O1 Room17, wspólne okno między
komputerami i pełny odbiór E4/E7-R/recovery/KO32 pozostają osobnymi zadaniami.

O3 zbudował bez edycji źródeł dokładny kandydat O1
`d3f6dba3a58b1d7ee52fb458ce01fc09ed3a4075`, z publicznym overlay TLS i wejściami
z tabeli poniżej. Kompilacja obu APK, podpis, skompilowane issuer/API/CA,
wykluczenie userCA/cleartext i obecność drivera w opt-in testAPK sprawdzone.
Zainstalowane bajty obu APK po próbie ponownie porównano z tymi sumami:

| Artefakt | Wersja / SHA256 |
|---|---|
| validation APK | `0.8.23.validation`, code1034, Room14; `b12a7bd43edd2cbda39a11de3381f006f7b195536a1430cde74739306b173eed` |
| opt-in testAPK | `7822b5cef7170a0b1093f64b541b08922b4f0051f6c3e68d129fe01f5316a892` |
| signer O3 | `313a9f31843fe4955a00569acde836897cff61dcb7bd5760c4726d4291c832a2` |

Użyto nowego, osobnego AVD API35 i nowych kont syntetycznych operatora.
Zwykły Chrome/Code+PKCE S256, bootstrap, pełna kopia i ręczny formularz
utworzyły jeden posiłek. Bez seed SQL/Room, czyszczenia aplikacji ani zmiany
wybranych identyfikatorów. Pierwotne konta integracyjne zachowano.
Używany API image05c1792f/schema0024 i epoka pozostały bez migracji.

| Odczyt / zdarzenie | UTC | Wynik |
|---|---|---|
| C0, osobna transakcja read-only | 10:53:13.721434 | cel/receipt/składniki nie istnieją, pozycja0; pusty licznik utworzony przez bootstrap |
| rzeczywiste HTTP200 / hold | 10:53:47.761056 / 10:53:47.789785 | zweryfikowany ACK zatrzymany przed zapisem lokalnym |
| C1, nowe połączenie PostgreSQL | 10:54:12.007249 | Meal/receipt revision1, pełna treść zgodna z planem sprzed C0 |
| rzeczywisty force-stop | przed 10:54:32.786867 deadline | PID nieobecny, potwierdzony zapas20,553s do deadline |
| nowy proces i identyczny retry | 10:54:14.419873 | nowe HTTP200, `already_applied`, pierwotna revision1, lokalny ACK PASS |
| C2, trzecie połączenie PostgreSQL | 10:54:15.992926 | identyczne treści, liczniki i hashe sześciu tabel jak C1 |

Plan powstał z dokładnych utrwalonych bajtów, parserem/fingerprint rzeczywistego
runtime API, przed C0. SHA koperty:
`d2dc64cb6c319ac7824e67af41cbf6f13c76ced9dcc1d64df76b0cd9643ae8d0`.
Fingerprint operacji:
`5891ce757279891db0953647fc6633acb3c71d031b344e2127151c89633174de`.
Każdy odczyt sprawdził obraz, schemat, epokę, konto, plan i read-only.
C0→C1: jeden Meal, jeden składnik, jeden DiaryDay, jeden receipt, dwie zmiany;
pozycja0→2. C1→C2 bez przyrostu i bez zmiany zapisanej treści.

Driver potwierdził ochronę19 tabel oraz nowy identyfikator procesu.
Po próbie Room14: Meal serverRevision/localRevision1/1, outbox `acked`,
attempted1, FK czyste. Dodatkowe kopie przed/po zachowały identyczne wiersze
i rowid21 z29 tabel. Pozostałe obejmują aktualny kontekst, metadane kopii,
Meal/outbox/batch; nie deklarujemy niezmienności wszystkich tabel.
Hold zakończył się oczekiwanym `Process crashed` po force-stop; odrębny test
replay zakończył się `OK (1 test)`. Własny tunnel/reverse usunięto, AVD
wyłączono bez wipe, nie otwierano nowego listenera LAN.

Historia operatora zachowana: pierwsze prepare zatrzymało się przed freeze/HTTP
przez nieświeżą sesję. Po przerwie ten sam AVD i dane wznowiono bez czyszczenia,
a zwykły ponowny login potwierdził świeżą sesję. Przy drugim prepare poprawiono
wyłącznie zbyt mocne oczekiwanie lokalnego harnessu „wszystkie tabele puste”:
bootstrap już tworzy pusty licznik pozycji0. Nie ponawiano prepare po freeze.
Pierwszy poll pliku hold zwrócił puste bajty; odczytano ten sam trwający hold
i przerwano go w terminie, bez drugiego wysłania operacji hold.

[Roboczy pakiet operatora](https://github.com/Roseru/aplikacja-mobilna/releases/tag/untagged-58fbda4d81b2bc29328c)
zawiera oba APK, manifest, neutralny raport, publiczny CA i SHA256SUMS:
ZIP22234122B, SHA256
`dcd55cd5e1257b202990a764d984af374944a51053ae709a9db2e26ea88945dc`.
GitHub potwierdził rozmiar i ten sam digest po uploadzie. Draft wymaga dostępu
do repozytorium. Bez haseł, tokenów, ownerID, raw HTTP/Room lub prywatnego CA.
APK ma osobny signer O3 i starszy Room14: wyłącznie świeży izolowany AVD,
bez instalacji nad istniejącymi danymi ani obniżania schematu.

Odczytany nowy O1-111/PR138 headc8696b3 dostarcza opis skonfigurowanego
0.8.27/code1038/Room17, źródło dc012fab, manifest i lokalne kwalifikacje.
Fizyczna dostawa tych APK do O3 i aktualny peer/ograniczone okno nadal wymagają
potwierdzenia. Ten starszy wynik operatora nie zastępuje odbioru nowej dostawy.

## Wejścia O3 z 23.10.2026, 07:53 CEST — stan przed próbą

**Kwalifikacja serwera i wejść kompilacji PASS; skonfigurowane APK O1 oraz
wspólna próba E4 nadal NOT_RUN.** PR137 jest scalony jako `167152a`;
bieżący main `b434754` ma własny CI39772774959 **8/8 SUCCESS**.
Starsze sekcje poniżej zachowują swój historyczny zakres.

Odczyt z 23.10, 07:53:38 CEST potwierdził:

- API image `sha256:05c1792f3551725f0303cc3786892771392532a25edc18ff710faad9e6b7e9a9`,
  schemat `0024_e9_history_graph`. Używana instalacja nie została zmigrowana.
- Nowa projekcja `meal_content` z formatu2 obserwatora wykonała się na tym
  schemacie w transakcji read-only, wraz z kontrolą image/schema/epoch,
  w około0,63s. Wskazano losowego nieistniejącego właściciela, brak konta
  i `meal_content=null` potwierdzone. To zgodność SQL/kolumn, **nie C0**,
  porównanie zapisanej treści ani zastępstwo próby COMMIT/kill/replay.
- 14 wskazanych źródeł/kontraktów rzeczywistego obrazu jest zgodnych po LF
  zarówno z archiwalnym8ff7c0c, jak i bieżącym mainb434754. Nie dowodzi to
  pochodzenia całego obrazu ani zgodności wszystkich funkcji nowszego main.
- HTTPS readiness i discovery HTTP200 przez loopback z pełną weryfikacją
  **oryginalnej** tożsamości TLS. Publiczne wejścia pozostają:

| Wejście O1 | Wartość |
|---|---|
| issuer | `https://192.168.3.162:18443/realms/calorie-dev` |
| API | `https://192.168.3.162:18443/api/v1` |
| client / audience | `calorie-android` / `calorie-api` |
| callback validation | `pl.roseru.kalorie.validation:/oauth2redirect` |
| SHA256 publicznego CA PEM | `01f120ef25f091a6413a535dcaa5e333575a8d08a016503c47998333eef3a6f6` |

Adres routingu O3 zmienił się względem historycznego issuer. Aktualne peer
LAN/VPN i ograniczone okno należy uzgodnić przed próbą; nie zmieniamy issuer
na adres relay. [Istniejący transport](../../infra/integration/ANDROID_HANDOFF.md)
zachowuje oryginalny TLS. Nie otwarto nowego listenera ani reguły zapory.

Istniejące techniczne konto syntetyczne A jest włączone w Keycloak;
prywatny plik logowania odpowiada aktualnej prywatnej konfiguracji O3.
Operator przygotował osobny chroniony plik dla validation. O1 uzyskuje sesję
przez Code+PKCE S256, następnie bootstrap/pull. Przed C0 prywatnie wiążemy
`binding.accountId` z rzeczywistym UUID konta backendu. Sprawdzenie enabled
i plików **nie jest nową próbą hasła/PKCE**. Konto ma wcześniejszą historię
syntetyczną; wskazana operacja/encja próby musi być nowa, a konto bez
równoległych zapisów. Nie wykonano seed SQL, API push ani edycji kont.

Publiczny pakiet wejść zawiera CA/config/manifest oraz niezmienione narzędzia
overlay/transportu z mainb434754, bez APK i sekretów. Publiczny CA jest ten
sam co w poprzednim przekazaniu. O1 może użyć posiadanego certyfikatu po
sprawdzeniu pełnej sumy i wygenerować **nowy lokalny overlay** przez
`android_overlay.py --state <publiczny-pakiet> --output <nowy-katalog>`.
Generator rzeczywiście wykonano: validation-only, dokładny host,
cleartext=false, bez zaufania do user CA. Przy kompilacji wymagane obie
właściwości `CALORIE_OIDC_ISSUER` i `CALORIE_API_BASE_URL` z tabeli.
Weryfikacja publicznego ZIP/SHA256SUMS i braku sekretów PASS.
Istniejące testy obserwatora/overlay/peer: **44 PASS**.
Pierwsze wywołanie testów z `-I` nie zebrało dwóch modułów z powodu braku
repozytorium w sys.path; prawidłowe wywołanie pytest z katalogu projektu
wykonało wszystkie44. Nie zmieniano testów ani produktu.

**Następna dostawa O1:** aktualizacja zależnego PR138 do uzgodnionej bazy,
oddzielne skonfigurowane validation APK i opt-in testAPK, dokładny commit,
manifest/versionCode/Room/applicationId/SHA oraz kwalifikacja tych wejść.
Następnie aktualna gotowość i peer, prywatny eksport rzeczywiście utrwalonej
koperty i jej hash, plan przed C0, wspólne C0→HTTP200/hold→C1→realny
force-stop przed45s→nowy proces/retry/already_applied revision1→C2.
Dotychczasowe offline APK nie stają się skonfigurowane przez ten dokument.

Konfiguracja, epoka i identyfikatory/obrazy ośmiu używanych kontenerów zostały
porównane przed/po i zachowane. **Live E4/E7-R/recovery/KO32 NOT_RUN**.

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


## Aktualizacja integracji PR129 — 21.10.2026

PR129 został scalony do main `a919777dc4019f504b4babe56f2118f19edf10b0`.
Powyższa ocena zachowuje przypięte źródło APK d3f6dba i swój zakres;
nie jest odbiorem nowego artefaktu lub używanego runtime. O2-049 w jedynym
[dzienniku](../KOMUNIKACJA_AGENTOW.md) opisuje aktualizację bazy PR137
przed scaleniem. Wejścia O3, skonfigurowany APK O1 i rzeczywiste C0/C1/C2
pozostają wymagane; live E4/E7-R/recovery/KO32 NOT_RUN.
