# Pierwszy odbiór APK → PKCE → bootstrap → prywatne odczyty - osoba 2

Przygotowanie O2, 13.10.2026. Źródła odczytane z main `2fc70f7ae612c031f63d53c04d3c81b4402b72c5` w osobnym checkoutcie koordynatora. Odrębny zakres od aktywnego E9/PR54; bez zmian kodu, journalu, kont lub środowiska. Status: **PREPARED / WAITING_EXTERNAL**, bez realnego APK PASS.

## Aktualny odbiór — 19.10.2026

Poniższe PREPARED/WAITING_EXTERNAL i NOT_RUN opisują historyczne przygotowanie
oraz decyzję z15.10. Wynik późniejszych prób i niezależny odbiór O2:
[R2/R3 oraz oracle kolejnej próby E4](ODBIOR_R2_R3_ORACLE_E4_O2.md).
R2 late-GET/guard PASS, R3 świeże odczyty B/A4/4 PASS według receipts O1,
transport/zamknięcie PASS niezależnie O3; całość PARTIAL w granicach raportu.
Nowa próba zapisu E4 pozostaje NOT_RUN. Zachowujemy poniżej pierwotny oracle
i historię bez przypisywania nowych dowodów wcześniejszym próbom.

## Automatyczny odbiór statyczny kompletu czterech APK — O3, 25.10.2026

[apk_delivery.py](../../infra/integration/apk_delivery.py) sprawdza **jeden kompletny,
niezmienny zestaw** przed instalacją. To rozszerzenie sprawdzonego prywatnego
preflightu pojedynczego APK: zachowuje kontrolę skompilowanych API/issuer/CA,
powiązania manifestu z polityką sieci i ścisłego trust, a dodaje role, pary,
metadane, podpisy i definicje drivera. Nie uruchamia Gradle, APK, AVD, adb,
sieci, usług, kopii ani próby E4. Regresje korzystają z syntetycznych ZIP/DEX
i wyjść SDK; nie są nowym odbiorem rzeczywistego kandydata.

Wejścia operatora: nowy oczekiwany manifest formatu1, cztery pliki APK w tym
samym katalogu, jeden publiczny CA PEM oraz przypięty checkout źródeł.
Niezależnie od manifestu operator podaje jego oczekiwany SHA-256, source commit
i tree katalogu `android`. Muszą pochodzić z uzgodnionego przekazania O1;
obliczenie nowego hasha po nieuzgodnionej podmianie nie ustanawia zaufania.
Kontrakt operatora Room23 i nadal otwarte wejścia opisuje
[przygotowanie E4](PRZYGOTOWANIE_REPLAY_E4_O3.md), na podstawie
[przypiętego kontraktu drivera ccb614e](https://github.com/Roseru/aplikacja-mobilna/blob/ccb614ed6ffeff314a17e8a4d65cac012fb1624b/android/DRIVER_REPLAY_E4.md).
Ten pin kontraktu nie zastępuje poprawionego source commita dostarczanych APK.

Manifest ma **dokładnie** następujące pola; dodatkowe pola, duplikaty kluczy,
NaN/Infinity, błędny UTF-8, brakujące wartości i nieznane role oznaczają odmowę.
Starszy manifest kandydata bez targetów/podpisów nie spełnia tego formatu.
Narzędzie nie uzupełnia braków historycznymi receiptami.

| Obiekt | Wymagane pola i znaczenie |
|---|---|
| Korzeń | `schema_version`: liczba1; `source`, `configuration`, `artifacts` |
| `source` | `commit`: pełny40-znakowy SHA; `android_tree`: pełny40-znakowy tree; `room`: dodatnia liczba całkowita |
| `configuration` | `api_base_url`, `oidc_issuer`: dokładne HTTPS bez credentials/query/fragment, API ze ścieżką `/api/v1` lub `/api/v1/`; `ca_sha256`: hash dokładnych bajtów dostarczonego PEM; `ca_entry`, `network_xml_entry`: względne ścieżki POSIX wewnątrz APK |
| Każdy z4rekordów `artifacts` | `role`, `filename`, `bytes`, `sha256`, `signer_sha256`, `application_id`, `version_code`, `version_name`, `endpoints`, `instrumentation` |
| Tożsamość pliku | `filename`: zwykła nazwa ASCII zakończona `.apk`, bez ścieżki/ADS/nazwy urządzenia; dodatnie `bytes`; wszystkie SHA-256 mają64małe znaki hex |
| `endpoints` aplikacji | Dokładnie `api_base_url` i `oidc_issuer`. Validation musi odpowiadać `configuration`. Debug deklaruje obie wartości puste albo tę samą parę co validation; testAPK mają `null` |
| `instrumentation` testAPK | Dokładnie `target_role`, `target_package`, `runner`. Oba testAPK mają własną jawną deklarację; aplikacje mają `null` |

Role występują po jednym razie, bez dodatkowych APK w manifeście. Nazwy, bajty
i fizyczne pliki ról muszą być odrębne. Nie sumujemy ani nie łączymy receiptów
z innych dostaw. W katalogu mogą pozostać inne dowody, ale nie są członkami zestawu.

| `role` | Pakiet / wersja | Target i driver |
|---|---|---|
| `debug` | Regularny applicationId i wersja z przypiętej deklaracji Gradle | Bez instrumentacji i obu driverów live; bez overlay validation, jawny zakaz cleartext i systemowe CA przy targetSdk≥24 |
| `validation-configured` | ApplicationId z sufiksem validation; osobny versionCode/versionName z deklaracji wariantu | Bez instrumentacji i driverów live; skompilowane endpointy, dokładny CA i ścisła polityka O3 |
| `test-default` | Własny jawny applicationId i metadane wersji testAPK | Jawny target `debug` **albo** `validation-configured`, zgodny z tą konkretną kompilacją; bez driverów live |
| `test-liveReplay-optin` | Własny jawny applicationId i metadane wersji testAPK | Wymaga targetu `validation-configured` i zdefiniowanej klasy `LiveMealReplayTest`; bez dodatkowego `LiveApiLateReceiptTest` |

Dla testAPK `version_code`/`version_name` mogą być `null` wyłącznie jako jawne
oczekiwanie braku danego atrybutu w binarnym manifeście. Nie kopiować do nich
wersji aplikacji. Każdy test jest osobno porównywany z binarnymi `targetPackage`
i nazwą runnera, także gdy oba testy deklarują ten sam target. Podpis testAPK
musi odpowiadać podpisowi jego wskazanej aplikacji. Samo jednakowe applicationId
obu testAPK nie dowodzi zgodności targetów. Gradle generuje osobny manifest
instrumentacji; [zasady Androida](https://developer.android.com/studio/test/advanced-test-setup#configure-instrumentation-manifest-settings)
pozwalają konfigurować wariant testowany. Dlatego źródłowe `testBuildType` jest
raportowane oddzielnie, a oczekiwanie dla każdej rzeczywistej pary wymaga
uzgodnionego manifestu dostawy, uwzględniającego użyte nadpisania builda.

Przykłady kształtu rekordów (placeholdery wymagają zastąpienia danymi O1;
to **nie jest** manifest ani receipt istniejącej dostawy):

```json
{
  "role": "validation-configured",
  "filename": "validation-configured.apk",
  "bytes": 123,
  "sha256": "<64 lowercase hex>",
  "signer_sha256": "<64 lowercase hex>",
  "application_id": "pl.roseru.kalorie.validation",
  "version_code": 1042,
  "version_name": "0.8.31.validation",
  "endpoints": {
    "api_base_url": "https://<approved-host>:<port>/api/v1",
    "oidc_issuer": "https://<approved-host>:<port>/realms/calorie-dev"
  },
  "instrumentation": null
}
```

```json
{
  "role": "test-liveReplay-optin",
  "filename": "test-liveReplay-optin.apk",
  "bytes": 123,
  "sha256": "<64 lowercase hex>",
  "signer_sha256": "<same signer as target>",
  "application_id": "pl.roseru.kalorie.validation.test",
  "version_code": null,
  "version_name": null,
  "endpoints": null,
  "instrumentation": {
    "target_role": "validation-configured",
    "target_package": "pl.roseru.kalorie.validation",
    "runner": "androidx.test.runner.AndroidJUnitRunner"
  }
}
```

Znany profil źródeł jest odczytywany przez `git show`/`rev-parse` dla konkretnego
commita, bez checkoutu obcej gałęzi i wykonywania skryptów źródłowych. Weryfikuje
tree Androida, deklaracje wariantów, runner, domyślnie wyłączoną bramkę Gradle
liveReplay, deklarowany Room i jego eksport JSON. Nieobsługiwany lub
niejednoznaczny zapis blokuje kontrolę. Źródłowy Room i zgodny tree są
**deklaracjami pochodzenia**, a nie dowodem rzeczywistego Room z APK,
migracji, fence, admission lub działania drivera. Bez odtwarzalnego builda
sam podpis/hash również nie dowodzi, że APK zbudowano z deklarowanego commita.

Inspekcja binarna używa wyłącznie odczytów `aapt dump` oraz
`java -jar <apksigner.jar> verify --verbose --print-certs`. Wskazać pełne ścieżki
zaufanych narzędzi, na Windows pliki `.exe`, nie skrypty powłoki. Nazwa APK jest
przekazywana jako osobny argument, z jego katalogiem jako cwd;
obsługuje to polskie ścieżki starego aapt bez kopiowania APK. Każdy signer jest
kryptograficznie sprawdzany; pusty/wielokrotny/inny signer nie przechodzi.
Driver jest wykrywany przez indeks **definicji klas** wszystkich `classes*.dex`,
bez wykonywania kodu. Wystąpienie nazwy w stringach nie wystarcza. Obsługiwany
jest standardowy little-endian DEX035/037/038/039/040; uszkodzony, ukryty lub
nieobsługiwany DEX blokuje wynik. To czytnik indeksu, nie pełny walidator bytecode;
[format DEX](https://source.android.com/docs/core/runtime/dex-format#file-layout)
rozdziela stringi, typy i definicje klas.

W validation każda skompilowana konfiguracja `string/api_base_url`,
`string/oidc_issuer`, `raw/o3_local_ca` i `xml/o3_network_security` musi wskazywać
oczekiwane dane. Manifest musi wiązać sprawdzony zasób sieci. Polityka O3 wymaga
jednego base-config z wyłącznie system CA, dokładnych hostów endpointów z
wyłącznie wskazanym CA, jawnego zakazu cleartext/subdomains oraz braku
userCA/debug-overrides/nested lub dodatkowych polityk. Osobne debug endpointy
także są sprawdzane we wszystkich konfiguracjach. Debug bez override trust
korzysta z [domyślnego zaufania Androida targetSdk≥24](https://developer.android.com/privacy-and-security/security-config#base-config).
Statyczny PASS nie dowodzi działania łańcucha TLS w procesie APK/Chrome.

Limity odmowy: manifest/CA/źródłowy plik JSON lub tekst do1MiB, APK do256MiB,
pojedynczy DEX do64MiB i suma DEX do256MiB, do100000 wpisów ZIP; wyjście narzędzia
do16MiB, stderr do1MiB, każde wywołanie do30s. Odczyty i potoki mają ograniczenia
przed parsowaniem. Surowe diagnostyki pozostają wyłącznie w pamięci i nie trafiają
do stdout/raportu. Zmienne opcji Java są usuwane z procesu inspekcji.

Z własnego checkoutu O3, po przygotowaniu zależności backendu z lockfile:

```powershell
uv run --project backend --locked python infra/integration/apk_delivery.py `
  --manifest "$Delivery/delivery.json" --expected-manifest-sha256 "$ApprovedManifestSha256" `
  --source-commit "$ApprovedSourceCommit" --source-android-tree "$ApprovedAndroidTree" `
  --checkout "$OwnCheckout" --ca "$Delivery/ca.pem" `
  --aapt "$AaptExe" --java "$JavaExe" --apksigner-jar "$ApksignerJar" --git "$GitExe" `
  --report "$PrivateEvidence/new-static-report.json"
```

Manifest, APK, CA i narzędzia są tylko odczytywane; hashe wejść są porównywane
przed/po. Alias dwóch ról, hardlink do innego wejścia, symlink lub junction
w ścieżce są odrzucane. Raport ma nową zwykłą nazwę `.json` i istniejący katalog
nadrzędny. Kompletny raport po fsync jest publikowany wyłącznym hardlinkiem
NTFS/POSIX; plik roboczy jest usuwany także po błędzie. Odmowa zapisu nie zostawia
częściowego raportu PASS. Publikacja nigdy nie nadpisuje pliku, linku, narzędzia
lub wcześniejszego dowodu. Nie przekierowywać stdout do wejść ani do wcześniejszych
receiptów. Błąd zapisu/wyścig o istniejący plik nie daje PASS.

| Wynik / exit code | Znaczenie |
|---|---|
| `STATIC_PASS` /0 | Wszystkie wymagane inspekcje wykonane i zgodne z przypiętym manifestem |
| `STATIC_FAIL` /1 | Kompletna inspekcja wykazała niezgodność; zapisany raport zachowuje FAIL |
| `STATIC_BLOCKED` /2 | Brak danych/narzędzia, niejednoznaczność, limit lub niepełna inspekcja; nie tworzy nowego raportu |

Raport zawiera hash oczekiwanego manifestu, źródłowe deklaracje, hashe narzędzi,
wyniki kontroli i tożsamość bajtów4APK. Zawsze pozostawia
`android_acceptance=NOT_CREATED`, `live_trial=NOT_RUN`, `driver_execution=NOT_RUN`,
`room_runtime=NOT_CHECKED`, `runtime_tls_chain=NOT_CHECKED`,
`apk_source_provenance=DECLARED_NOT_REPRODUCED`, `deployment_authorized=false`.
Nowe poprawione driver/runtime/DI, rzeczywiste4APK, osobny android_acceptance,
live E4/PG/PULL i pakiet z kopią pozostają kolejnymi odbiorami właściwych właścicieli.

## Krótki stan i największa niewiadoma

- O1-023 określa pierwszy przebieg: APK, rzeczywiste konto A/Chrome/PKCE, bootstrap, GET me/motivation, potem logout/restart i B→A. Same odczyty nie potwierdzają zgody ani nie synchronizują dziennika.
- O3 `docs/e8/ROLLOUT_LOKALNEJ_INSTALACJI_O3.md`: zachowany origin `https://192.168.3.162:18443`, issuer z końcówką `/realms/calorie-dev`; gateway związany z `127.0.0.1:18443`. Historyczny operatorski HTTPS/PKCE/200 nie jest dostępem telefonu. `infra/integration/ANDROID_PKCE.md` dotyczy starszego APK 0.8.0 bez bootstrap/API; nie zalicza tego scenariusza.
- Wczesny mały eksperyment: telefon musi otworzyć discovery pod **dokładnym issuer** z poprawnym TLS, bez ostrzeżenia Chrome, i osiągnąć readiness API. Dopiero wtedy wykonać poniższy przebieg. Pozwala oddzielić routing/trust od kontraktu i Room.
- Bieżąca próba O2, 13.10.2026 około 16:24 CEST: `ipconfig` nie pokazał przypisanego `192.168.3.162`; Wi-Fi disconnected. Próby .NET TCP do `127.0.0.1:18443` i `192.168.3.162:18443`, każda z limitem2500ms, zakończyły się `SocketException / AccessDenied`. CIM `Get-NetIPAddress` także odmówił dostępu. **To ograniczenie wykonania lokalnej próby, nie connection-refused, timeout serwera ani dowód niedostępności portu.** Nie wykonano HTTPS, discovery, PKCE lub uwierzytelnionego GET. Nie eskalowano, nie zmieniano trust/sieci/usług.

Dodatkowy preflight koordynatora po dopuszczeniu odczytu sieci: TCP `127.0.0.1:18443` zwrócił `ConnectionRefused`; `192.168.3.162:18443` osiągnął timeout po 2500 ms. Odczyt przypisanych adresów potwierdził `historicalOriginAssigned=false`. To faktyczny wynik tej próby, odrębny od wcześniejszego sandboxowego AccessDenied. Nie potwierdzono HTTPS/discovery, gotowości całego środowiska ani APK; nie zmieniano usług. [Przekazanie O3](https://github.com/Roseru/aplikacja-mobilna/pull/51#issuecomment-6147961766) prosi o gotowy wariant origin/issuer/CA i stan istniejącej instalacji.

## Bramka środowiska i istniejące komendy

O3 dostarcza aktualny origin/issuer/publiczny CA oraz osiągalność z telefonu i zgodność deploymentu. Nie zmieniać jednostronnie issuer na loopback/10.0.2.2 lub nowy LAN IP; `(issuer, sub)` to tożsamość. Przy nowym issuer potrzebny odrębny uzgodniony plan. Nie stosować reinit, resetu kont, trust-all, cleartext ani obchodzenia ostrzeżeń TLS.

O1 potwierdza SHA256, commit, applicationId i faktyczne resources APK. `CALORIE_API_BASE_URL` musi mieć ścieżkę `/api/v1` lub `/api/v1/`; sam origin zostanie odrzucony przez `BootstrapHttpProtocol.endpoint`. Domyślne obie właściwości Gradle są puste, więc sam install-r APK5234edb nie dowodzi konfiguracji API. Room8/version0.8.7/code18 to odczyt źródeł main; bieżący artefakt wybiera O1.

Po wskazaniu **istniejącego** prywatnego stanu przez O3, z właściwego checkoutu O3:

```powershell
uv run --project backend --locked python infra/integration/run.py status --state "$ExistingState"
uv run --project backend --locked python infra/integration/run_e8.py status --state "$ExistingState"
```

To status operatora, nie receipt telefonu. `run.py verify` nie jest read-only preflight: wykonuje bootstrap i inne scenariusze mutujące. Nie uruchamiać go na współdzielonych kontach jako zamiennika odbioru APK. `android_scope.py` przypisuje scope administracyjnie; także nie jest read-only i pozostaje u O3.

Jeżeli O3/O1 wybierają istniejący wariant validation z lokalnym publicznym CA, wykorzystują dotychczasowy overlay zamiast nowego harnessu. Przygotowanie **nowego, nieistniejącego** katalogu overlay i build wykonują właściwi właściciele:

```powershell
uv run --project backend --locked python infra/integration/android_overlay.py --state "$ExistingState" --output "$NewOverlay"
# W android/ checkoutu odebranego commita O1; wartości publiczne od O3:
.\gradlew.bat :app:assembleValidation --init-script "$NewOverlay/init.gradle" "-PCALORIE_OIDC_ISSUER=$ApprovedIssuer" "-PCALORIE_API_BASE_URL=$ApprovedOrigin/api/v1"
Get-FileHash -Algorithm SHA256 .\app\build\outputs\apk\validation\app-validation.apk
```

Nie wykonywano tych komend w tym zadaniu. Validation to inne applicationId/dane niż zwykły APK; odbioru validation nie podpisywać jako zachowania istniejącego dziennika regularnego APK. APK ufa ograniczonemu publicznemu CA dla dokładnego hosta, Chrome ma osobny trust. Zaufanie urządzenia uzgadniają O1/O3; brak publicznego CA nie oznacza prawa do jego instalacji lub zmiany w tym podtasku.

## Minimalny przebieg i oracle O2

1. O1 zapisuje prywatny baseline gościa/A/B oraz zainstalowanego artefaktu: aktywny owner, dziennik/składniki, profile, cel i jego historię, wagi, kompletność, outbox; kopia Room razem z WAL, nie sam niepełny plik SQLite. Brak clear/uninstall. Snapshot po bootstrapie stanowi baseline dla kolejnych odczytów; bootstrap może legalnie utworzyć serwerowe konto/receipt.
2. Rzeczywisty login A przez Chrome: publiczny `calorie-android`, `openid profile`, Code+PKCE S256, state/nonce i dokładny callback applicationId (`pl.roseru.kalorie:/oauth2redirect` albo validation). Discovery/JWT/API mają zgodny issuer, token audience `calorie-api`; bez client secret w APK.
3. APK wysyła `POST /api/v1/me/bootstrap`, Bearer oraz `Idempotency-Key` kanoniczny UUID; **bez body**. Oczekiwane200 `Bootstrap`: `account_id`, `sync_epoch`, `account_generation` dodatnia revision, `server_time`. Replay tego samego key zachowuje pierwotny receipt/czas, nie tworzy drugiego konta; nie wymuszać replay przez ręczne zmiany bazy/Vault. Tożsamość pochodzi z tokenu.
4. APK `GET /api/v1/me`:200 `ProfileRead`: te same `account_id`, `sync_epoch`; `profile` może być null; `consents` ma booleany ranking/automatic_energy_adjustment, dodatnią revision i updated_at; goal_timeline_revision może być0. ProfileRead nie zawiera account_generation. Nie wymagać ETag GET jako oracle zgód: ETag ustawia PUT.
5. APK `GET /api/v1/me/motivation` bez query:200 `MotivationRead`, zgodne `account_generation`/`sync_epoch`; regularity_v1, revision/source_position to 64-bit county, status pending_backfill/pending_materialization/final, cztery odznaki. Pending/null nie prezentować jako finalnych0pkt. `ranking.requested/effective/pending_consent_refresh/consent_epoch/own_position` zachować zgodnie z DTO. Dla konta z ranking=false pozostaje brak implicit opt-in; istniejącego ranking=true nie resetować dla testu.
6. Oba GET i API errors mają `Cache-Control: no-store` oraz `X-Request-ID`. Porównać pełny baseline Room po bootstrapie z po obu GET: dziennik, cel/historia i outbox niezmienione. Zmiana materiału/projekcji serwera lub czasu motywacji nie oznacza zmiany lokalnego dziennika. Nie powinno być PUT zgód ani operacji import/push z samego loginu/odczytu.
7. Logout A, restart aplikacji; zalogowanie B, następnie A. Nie widać A ani jego prywatnego profilu/motywacji/cursorów w B/gościu; B używa własnego bootstrap identity. Wszystkie zapisane zbiory każdego ownera pozostają jego zbiorami, gość bez automatycznego importu. Po powrocie A świeży GET, nie reaktywacja starego cache.
8. Spóźniona odpowiedź A po logout/przełączeniu: O1 używa własnej odebranej techniki kontrolowanego opóźnienia w osobnym środowisku; O3 odpowiada za transport. Jeśli nie dostarczono realnej odpowiedzi po zmianie ownera, oznaczyć **NOT_RUN**, nie zastąpić fixture PASS. Wynik nie może odtworzyć session/podglądu A w B/gościu. Opóźniony refresh z dawnego APK nie dowodzi tego konkretnego GET/code-exchange.

Świadomy PUT opt-in/opt-out, realny ranking, E4/push/ACK/import/WorkManager, KO31, recovery i Nemesis są kolejnymi odrębnymi odbiorami. Nie rozbudowywać pierwszego scenariusza, aby zamknąć je pozornie.

## Doprecyzowanie punktu 8 — decyzja O2 z 15.10.2026

Odpowiedź na O3-035, po przeglądzie PR73/head
`4b54b107b04ff2ab8456aedaccecb889dccde627`; pełne przekazanie w O2-034
w [dzienniku](../KOMUNIKACJA_AGENTOW.md). To ustalenie techniki i dowodu,
nie wynik wykonania: próba spóźnionego GET pozostaje **NOT_RUN**.

Dopuszczamy zatrzymanie jednego rzeczywiście odebranego HTTP200/body GET A
po ograniczonym odczycie HTTPS, przed zwrotem z gateway do istniejącego kontrolera.
Po ukończonym rzeczywistym logout do gościa uwalniamy ten sam wynik. Dla ochrony
przed zastosowaniem starego wyniku nie jest potrzebne opóźnianie strumienia HTTP.
Bramka jest wyłącznie validation, jednorazowa, poza mutexem/transakcją Room,
ograniczona do 10 s i pozostałego pierwotnego deadline. Nie podmienia danych,
nie osłabia TLS/CA/parserów/guardów i nie wymusza dostawy przez NonCancellable.

PASS wymaga dowodu kolejności: realny GET/body A → held → ukończony logout/guest
→ release → poprawne parsowanie tego samego wyniku i odrzucenie go przez istniejącą
kontrolę sesji/właściciela/operacji → brak odtworzenia A i zachowany baseline.
Samo `released` wewnątrz transportu ani zakończenie `readProfile()` zwracającego
Unit nie wystarcza: kontroler przechwytuje też błąd formatu DTO. O1 dodaje minimalny
dowód validation albo równoważną obserwację prywatną, która odróżnia te przypadki;
bez drugiego parsera, drukowania body/identity/tokenów lub zmiany zachowania guardów.

Jeśli cancellation/expiry odcina dostawę przed kontrolerem, rozliczamy bezpieczne
anulowanie osobno, a punkt 8 pozostaje **NOT_RUN**. Niepoprawne DTO albo brak dowodu
konkretnego odrzucenia nie daje PASS ochrony przed starym kontekstem. Ujawnienie A
w gościu/B daje FAIL. Receipt podaje źródło, APK SHA, urządzenie i neutralną kolejność;
wartości Room/Vault są prywatne. Równość 15 tabel danych w driverze nie oznacza
niezmienności wszystkich 23 tabel po celowym logout.

O1 kończy dowód w swoim istniejącym PR73, O3 uzgadnia nowe okno dla gotowego
artefaktu, O1 wykonuje próbę, O2 odbiera wynik. Okno z 14.10 do 17:25 CEST wygasło.
To nie zastępuje odrębnych przypadków A/B, code-exchange/refresh ani KO-31/WorkManager.

## STOP, PASS i odpowiedzialność

- STOP przed loginem: brak stabilnego osiągalnego issuer/origin, certyfikat/trust mismatch, pusty/nieprawidłowy api_base_url, inne applicationId/callback albo brak jednoznacznego artefaktu/baseline. Nie naprawiać przez czyszczenie danych.
- 401: odnowienie przez istniejący mechanizm O1, najwyżej jego przewidziana próba, bez nieskończonej pętli; prywatny stan i lokalny zapis zachowane. 403 account_bootstrap_required wymaga bootstrapu, account_deleting blokuje online. 409 generation/epoch jest fence/recovery, nie zgodą na blind retry/import. 422 traktować jako niezgodność żądania/DTO. 429/503 respektują retry/backoff; nie są200/PASS. Do diagnozy O2 przekazać status, code, request_id i zanonimizowany kształt, bez tokenu/body prywatnego dziennika.
- PASS minimalnej ścieżki: faktyczne APK+browser PKCE+bootstrap+oba GET, zgodne DTO/kontekst, no-store, niezmieniony baseline i potwierdzony logout/restart/B→A. Spóźniona odpowiedź ma osobny wynik; cały rozszerzony scenariusz PASS wymaga także jej faktycznego odbioru.
- O1: APK/UI/Room/Vault/cache i receipt urządzenia. O3: działające deployment/origin/issuer/CA/routing bez zmiany tożsamości. O2: oracle HTTP/DTO, poprawa ujawnionego backendowego błędu na własnej gałęzi. Każdy podaje własne dowody; samo przygotowanie nie przejmuje odbioru innej osoby.

## Neutralny receipt (wypełnić dopiero po próbie)

```text
Data/strefa, wykonawca i scope:
App commit / versionCode / applicationId / APK SHA256 / Room version:
Deployment commit / schema / origin i issuer zgodność / public CA SHA256:
Urządzenie / sieć / trust potwierdzone bez TLS warning:
Przed/po baseline (prywatna lokalizacja dowodu; tylko equality/counts w publicznym opisie):
Discovery/readiness: NOT_RUN | PASS | FAIL, powód:
APK browser PKCE A / bootstrap200 / me200 / motivation200 / DTO-context / no-store:
GET bez implicit consent/import/push; cel/dziennik/outbox zachowane:
Logout/restart / B→A / izolacja i świeży read:
Spóźniona odpowiedź A: NOT_RUN | PASS | FAIL; rzeczywisty typ odpowiedzi i kolejność:
Pierwsza odmowa/status/code/request_id (bez credentials/tokenów/account identity):
Wynik: WAITING_EXTERNAL | PARTIAL | PASS | FAIL; następny krok i właściciel:
Granica: operator API smoke, fixtures, CI oraz starszy APK nie zastępują realnego APK wyniku.
```

Credentiale, tokeny, identity/sub, Room/WAL, prywatny dziennik i surowe logi poza Git. Receipt nie zawiera niepotwierdzonych wyników. Po niepowodzeniu: reprodukcja → jedna hipoteza → pomiar → jedna zmiana właściwego ownera → ta sama próba; historię odmowy zachować.

Dokument powiązany: [review zgód i uwaga E9](RECENZJA_ZGOD_O2.md). Samodzielne techniczne źródło uruchomienia: [infra/integration](../../infra/integration/README.md).
