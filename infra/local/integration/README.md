# Natywny, odseparowany backend do integracji Androida

Adapter dla stanowiska Windows bez Docker/WSL uruchamia własne PostgreSQL 17,
Keycloak i HTTPS. Współdzieli konfigurację, CA, realm i konta z
[`infra/integration/run.py`](../../integration/run.py), a rzeczywiste logowanie
Code/PKCE, nonce i callbacky z [`verify.Probe`](../../integration/verify.py).
API i jego verifier są niezmienione. Zależności muszą odpowiadać `backend/uv.lock`.
To osobny lokalny stan; nie kwalifikuje historycznego środowiska lub podpisu O1/O3.

Nie zastępuje Dockerowego runnera CI, checkera wydania ani przygotowawczego
assemblera z PR190. Nie zmienia ich kontraktów lub znaczenia `PREPARATION_ONLY`.
Natywny odbiór nie potwierdza kontenerowego UID, read-only filesystem, SMTP,
produkcji, backup/restore lub rzeczywistego Google. AI pozostaje `mock`;
adapter nie odczytuje klucza Gemini i nie otwiera domyślnych bramek/zgód.

## Przygotowanie i lifecycle

Wymagane są jawnie wybrane istniejące dystrybucje PG, JDK i Keycloak oraz
Python 3.13 z zależnościami dokładnie zgodnymi z lockfile. Parametry wskazują
dystrybucje do odczytu. Keycloak otrzymuje własny writable home w nowym stanie;
stare `data` nie są kopiowane. Hasła są generowane wyłącznie na tę próbę,
pozostają pod ignorowanym `.tools` i nie są argumentami procesów.

Polecenia wykonuj w wybranym własnym checkoutcie. Zmienne `$Python`, `$PgBin`,
`$JavaHome` i `$KeycloakHome` wskazują uzgodnione narzędzia; `$HostIPv4` to
rzeczywiście przypisany prywatny IPv4 stanowiska. Nie zmieniaj hosts/firewalla.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = '.;backend/src'
$NativeState = Join-Path (Get-Location) '.tools/native-demo'
$SourceCommit = git rev-parse HEAD
& $Python infra/local/integration/native.py init --state $NativeState `
  --host $HostIPv4 --port 28443 --pg-port 25432 `
  --keycloak-port 28080 --management-port 29000 `
  --pg-bin $PgBin --java-home $JavaHome --keycloak-home $KeycloakHome `
  --python $Python --source-commit $SourceCommit
& $Python infra/local/integration/native.py up --state $NativeState
& $Python infra/local/integration/native.py status --state $NativeState
& $Python -m infra.local.integration.verify_runtime --state $NativeState --scope bootstrap
& $Python -m infra.local.integration.verify_runtime --state $NativeState --scope sync
& $Python infra/local/integration/native.py down --state $NativeState
```

`init` odmawia istniejącego katalogu. Stan musi leżeć pod `.tools` tego
checkoutu, bez symlinków/junction. `up` odmawia kolizji portów i istniejących
markerów procesów; po awarii najpierw sprawdź własne logi i wykonaj jawne `down`.
Nie kasuj ani nie inicjalizuj ponownie danych jako sposobu naprawy. Częściowy
błąd provisioningu wymaga diagnozy; adapter nie resetuje ról lub baz.

PG i Keycloak nasłuchują na własnych portach loopback. HTTPS nasłuchuje wyłącznie
na wybranym IPv4 i loopback, z jednym certyfikatem dla wybranego IPv4. Bramka
przekazuje ścieżki Keycloak do jego stałego upstreamu loopback; pozostały ruch
obsługuje istniejące `create_app()`, wraz z jego lifecycle. Nie ma access logów.
Nie instaluje CA w Windows ani na urządzeniu i nie wyłącza walidacji TLS.

Każdy helper działa z ukrytym oknem. Markery wiążą PID, czas utworzenia i plik
wykonywalny; `down` sprawdza cały zestaw przed zatrzymaniem pierwszego procesu.
Własne drzewo Keycloak/gateway jest zatrzymywane wyłącznie po tej kontroli,
a PG przez `pg_ctl` wskazujący własny katalog danych. Bazy, CA, konta, epoka,
artefakty i wcześniejsze dowody pozostają. Blokada OS odmawia równoległego
`up`/`down`. `status` podaje kwalifikację generacji procesu, nie odbiór APK.

Generacja startu wiąże dokładny backend/kontrakty z commitem, lock i hashe
adaptera z działającymi procesami. Weryfikacja odmawia starego źródła,
zmienionych markerów lub zakończonych procesów przed tworzeniem kont.
Powiązanie obejmuje też współdzielone `run.py`, `verify.py`, `init-db.sh`
i szablon realm oraz współdzielony SQL obserwatora E4. Zmiana któregokolwiek
wymaga zgodnego pinu i nowej generacji. Wersjonowane profile JSON adaptera
mają osobne hashe; zastosowana konfiguracja providera jest związana z generacją.
Po zmianie adaptera wymagany jest restart. Nie zmieniaj backendu/kontraktów
w trakcie próby; przy nowym pinie potrzebne jest osobne jawne uzgodnienie.

## Dowody i kolejność integracji

Każda próba tworzy nowy katalog `evidence/<czas>-<losowy-id>`. Zachowuje FAIL
oraz neutralny receipt, rzeczywiste wersje i hashe narzędzi. Access/ID tokeny,
kody, hasła i checkpointy nie trafiają do receiptów. Prywatne logi i dane
syntetycznych kont pozostają poza Git.

`bootstrap` sprawdza rzeczywisty HTTPS/discovery/issuer, odmowę obcego CA
i złego hostname, oba callbacky, nonce, błędne PKCE/replay/ID token,
idempotencję bootstrapu, konta A/B, pierwszy PULL oraz migrację PG.

`sync` dodatkowo wysyła sześć domen. Trzyma połączenie bez odczytania HTTP ACK,
niezależnie obserwuje commit w PG, zamyka połączenie i ponawia identyczny wire.
Wymaga sześciu `already_applied`, zapisuje sześć rzeczywistych receipts PG
z ID/hash/rewizją, wykonuje oddzielny PULL i sprawdza dokładne payloady A/B.
Niezależny oracle: 150 g × 87/100 + 250 ml × 42/100 = 235,5 kcal; brakujące
makra pozostają null. Po `down/up` wymaga nowego logowania, pełnego PULL,
identycznej epoki, danych, CA i dokładnych receipts PG.

Wynik ma zakres `BACKEND_BOOTSTRAP_PASS` albo `BACKEND_SIX_DOMAIN_PASS`.
`full_user_flow=false`, `android=WAITING_ANDROID_LEASE` i
`release_authorized=false` pozostają jawne. Statyczny lub stary receipt
nie jest wejściem pozwalającym podnieść ten zakres.

Dopiero po przekazaniu wyłącznej dzierżawy Gradle/AVD i kwalifikowanego pinu
Androida użyj istniejących [`android_overlay.py`](../../integration/android_overlay.py)
i [`android_transport.py`](../../integration/android_transport.py). Jedno
`https://<HostIPv4>:28443` musi pozostać identyczne w discovery/JWKS, API,
APK i przeglądarce emulatora. `127.0.0.1` i `10.0.2.2` nie są zamiennymi
issuerami. Ewentualny istniejący tunel AVD zachowuje oryginalną tożsamość TLS.
Overlay zawiera tylko publiczny CA dla dokładnego hosta; Chrome ma osobne
zaufanie, którego poprawność trzeba sprawdzić w rzeczywistym logowaniu.

Następny odbiór: gość offline → jawne logowanie/przypisanie → sześć domen
z aktualnego APK → PG receipt → osobny PULL → restart. Osobno pozostają
konflikt/recovery, community, ranking opt-in/out, Nemesis accept/cancel/cache
i E9 przy mocku. Nie zmieniaj zamrożonych planów Room23/obrazów w celu
przypisania im tego nowego odbioru natywnego.

## Kontrole źródeł adaptera

Użyj tego samego kwalifikowanego interpretera oraz konfiguracji Ruff backendu.
Świeży katalog tymczasowy pod własnym `.tools` unika odziedziczonych blokad ACL
globalnego katalogu pytest. Nie wskazuj istniejącego stanu usług jako `basetemp`.

```powershell
$TestTemp = Join-Path (Get-Location) ('.tools/native-tests-' + [guid]::NewGuid())
& $Python -m ruff check --config backend/pyproject.toml infra/local/integration/native.py infra/integration/tests/test_native_runtime.py
& $Python -m ruff format --check --config backend/pyproject.toml infra/local/integration/native.py infra/integration/tests/test_native_runtime.py
& $Python -m pytest infra/integration/tests/test_native_runtime.py --basetemp $TestTemp -q
```

Testy źródeł helperów celowo zmieniają każdy z pięciu plików w osobnym
repozytorium tymczasowym. Wymagają odrzucenia starego pinu i innego skrótu po
nowym commicie; nie zmieniają działającego checkoutu ani usług.

## Jawny profil rejestracji i resetu

Domyślny realm nadal ma zamkniętą rejestrację i reset. Na własnym działającym
stanie można jawnie zastosować wersjonowany `provider-registration.json`.
Najpierw przygotuj nowy, prywatny [sink SMTP](MAIL_SINK.md), korzystając
z kwalifikowanego archiwum Mailpit; nie używaj zewnętrznej skrzynki.

```powershell
& $Python -m infra.local.integration.mail_sink init --state $MailState --archive $MailpitZip
& $Python -m infra.local.integration.mail_sink up --state $MailState
& $Python -m infra.local.integration.provider configure --state $NativeState --mail-state $MailState --opt-in-registration-reset
& $Python -m infra.local.integration.provider status --state $NativeState
```

Profil obejmuje weryfikację e-mail, formularze pl/en i wyłącznie podstawową
domyślną rolę API `user`. Odczyt przed/po chroni istniejący issuer, realm,
publiczne klucze, użytkowników, klienta Code/S256/callbacks i epokę aplikacji.
Narzędzie zapisuje próby i częściowe skutki bez automatycznego resetowania.
`CONFIGURED` oznacza konfigurację; `PARTIAL` i `FAIL` pozostają widoczne.
Żaden z tych wyników nie potwierdza WF01. Rejestrację, wiadomość/link,
logowanie, reset i zachowanie historii trzeba odebrać przez rzeczywisty UI.
Nie publikuj skrzynki, haseł, linków akcji ani prywatnych descriptorów.

Descriptor pod `config-generation/provider-profile.json` i nowa generacja
runtime wiążą konfigurację z istniejącymi źródłami/procesami. Kolejne `up`
uwzględnia zachowany descriptor. Zmiana źródłowego JSON lub helpera wymaga
nowego sprawdzonego pinu i jawnego restartu własnego stanu.

## Własny świadek serwera dla Room27

`observe.py` przyjmuje nowy format `calorie-native-meal-plan/v1` z rzeczywistego
`LiveMealReplayTest` guard2/Room27. Nie przyjmuje kwalifikacji starego Room23
ani zastępczego `api_image`. Wszystkie wyjścia muszą być nowymi plikami
wewnątrz prywatnego `$NativeState`; przygotuj tam katalog dowodów przed poleceniem.

```powershell
& $Python -m infra.local.integration.observe --state $NativeState prepare --driver-prepared $DriverPrepared --trial $Trial --output $Plan
& $Python -m infra.local.integration.observe --state $NativeState capture --plan $Plan --phase C0 --output $C0
# C1: dopiero po realnym commit i przed zabiciem procesu z zatrzymanym ACK.
& $Python -m infra.local.integration.observe --state $NativeState capture --plan $Plan --phase C1 --output $C1
# C2: dopiero po replay tego samego zapisanego batcha w nowym procesie APK.
& $Python -m infra.local.integration.observe --state $NativeState capture --plan $Plan --phase C2 --output $C2
& $Python -m infra.local.integration.observe --state $NativeState compare --plan $Plan $C0 $C1 $C2 --output $Verdict
```

Każda faza wymaga tej samej aktualnej generacji, źródeł/binarnych plików/PID,
schematu, epoki i niewygasłego triala. PG jest read-only od połączenia;
osobno porównywane są obce konta i niezmieniane domeny właściciela.
`server_observations=PASS` obejmuje wyłącznie świadectwa serwera C0/C1/C2.
Rzeczywisty HTTP/Room/bariera/kill/replay/osobny PULL oraz zwolnienie izolacji
wymagają własnych dowodów. Publiczny validator i SQL starego obserwatora
pozostają zgodne; nie przypisuj nowych wyników zamrożonym próbom.
