# Poczta i dostęp do lokalnego demo — O3

Właściciel ograniczył bieżący odbiór do demo lokalnego. Potrzebne są działający
APK, logowanie i próby funkcji z lokalnym API. VPS i domena pozostają poza tym
odbiorem. Zakres produkcyjny z wymagań nadal wymaga osobnego wykonania.

## Skrzynka do resetowania hasła

[`compose.demo-mail.yaml`](compose.demo-mail.yaml) dodaje Mailpit 1.32.0 do
**istniejącej** sieci integracyjnej. Obraz jest przypięty SHA256. Nie przebudowuje
API i nie uruchamia migracji. Przed użyciem sprawdź nazwę własnej sieci; poniżej
nazwa użytej instalacji O3, nie automatyczne wykrywanie dowolnego projektu:

```powershell
$env:DEMO_NETWORK = 'calorie-integration_default'
docker network inspect $env:DEMO_NETWORK --format '{{.Name}}'
docker compose --project-name calorie-o3-demo-mail --file infra/integration/compose.demo-mail.yaml config --quiet
docker compose --project-name calorie-o3-demo-mail --file infra/integration/compose.demo-mail.yaml pull
docker compose --project-name calorie-o3-demo-mail --file infra/integration/compose.demo-mail.yaml up --detach --no-build --pull never
```

Wiadomości czytaj na [http://127.0.0.1:18025](http://127.0.0.1:18025), wyłącznie
na komputerze gospodarza. SMTP jest dostępne wewnątrz sieci Docker jako
`calorie-demo-mailpit:1025`; nie ma portu SMTP opublikowanego na gospodarzu.
Dozwoleni są wyłącznie odbiorcy w domenach `invalid.example`, `example.test`
i `calorie-demo.test`. Usługa przechwytuje wiadomości i nie ma skonfigurowanego
przekazywania poczty do zewnętrznego dostawcy.

Rzeczywista próba SMTP RCPT TO potwierdziła `250` dla adresu testowego
i `550` dla adresu spoza tych domen; w tej próbie nie wysyłano treści wiadomości.

Kontener ma UID 10001, read-only rootfs, brak capabilities i tymczasową bazę
na tmpfs. Limit wynosi 100 wiadomości; restart kontenera usuwa skrzynkę.
Wiadomości zawierają aktywne linki resetowania hasła: nie publikuj ich ani
widoku skrzynki w GitHubie. Dane kont demonstracyjnych przechowuj prywatnie.

## Konfiguracja istniejącego Keycloak

Administrator ustawia w realm `calorie-dev` sekcję Email:

| Pole | Wartość lokalnego demo |
|---|---|
| Host | `calorie-demo-mailpit` |
| Port | `1025` |
| From | `noreply@calorie-demo.test` |
| From display name | `Kalorie demo lokalne` |
| Authentication, SSL, StartTLS | wyłączone, tylko prywatna sieć kontenerów |

W Login włącz **Forgot password** (`resetPasswordAllowed=true`). Konto do próby
ma mieć zweryfikowany adres z jednej z domen testowych i rolę API `user`.
Nie potrzebuje uprawnień administratora. Rejestracja publiczna pozostaje
wyłączona. Zmiana dotyczy działającego realm; ponowny start z plikiem importu
nie aktualizuje już istniejącego realm.

Zapisz te same ustawienia w prywatnym szablonie `realm/calorie-dev.json` stanu
instalacji, zachowując pozostałe pola. W prywatnym `demo-mail.env` zapisz
`DEMO_NETWORK`, dokładny `DEMO_MAIL_IMAGE` z Compose i SHA256 pliku Compose
jako `DEMO_MAIL_COMPOSE_SHA256`. Istniejący backup kopiuje pliki `*.env`,
`realm/`, TLS i obie bazy. Źródło Compose zachowaj na odebranym commicie.
Reguła `.gitattributes` zachowuje jego bajty LF również na Windows.
Po odtworzeniu uruchom osobny projekt poczty powyższymi poleceniami w tej
samej sieci; zawartość skrzynki jest celowo nietrwała.

## Powrót do demo po restarcie emulatora

Zachowaj dane własnego AVD i uruchom go ponownie bez `-wipe-data`.
Po pełnym starcie i `adb root` użyj `android_transport.py ensure` z tym samym
`--adb`, `--serial`, `--avd`, `--state` i prywatnym `--lease` co wcześniej.
Oryginalny adres HTTPS, issuer i CA pozostają takie same.

`ensure` sprawdza istniejące połączenie z bieżącego uruchomienia. Po restarcie
może odtworzyć transport, jeśli stary zapis ma dokładnie tę samą tożsamość
AVD i adresu, inny boot ID, a jego łańcuch NAT i mapowanie reverse już nie
istnieją. Najpierw zachowuje cały stary plik jako `*.stale-<sha256>.json`.
Istniejący plik archiwum, obce reguły lub inne dane właściciela zatrzymują
operację. Nie usuwa istniejących tras w celu wymuszenia połączenia.

Po pokazie użyj `disconnect` z tymi samymi argumentami, a potem zatrzymaj AVD.
`connect`, `status` i `disconnect` zachowują ścisłą kontrolę bieżącego boot ID;
`ensure` jest osobnym działaniem do wznowienia. Próba na własnym emulatorze
po restarcie komputera oraz 18 testów kontroli właściciela przeszły
24 października 2026. Sam transport nie potwierdza logowania ani synchronizacji.

## Wykonany odbiór O3, 23 października 2026

Na istniejącym API/schema `0024_e9_history_graph` wykonano prawdziwy formularz
**Forgot password**, dostarczenie jednej wiadomości przez SMTP, użycie linku
z oryginalnym TLS/issuer i logowanie nowym hasłem przez Code + PKCE S256.
Nonce i podpis JWT sprawdzone. Stare hasło odrzucone; stary refresh token
otrzymał `HTTP 400 invalid_grant`. Wynik **PASS**, 17:30:46 UTC, 2,032 s.
Własna jednorazowa tożsamość testowa została usunięta. Hasła wcześniejszych
kont pozostały zachowane. Osobne konto demo z rolą `user` ma sprawdzone PKCE;
jego dane początkowe są dostępne wyłącznie prywatnie u właściciela.

Po tych zmianach ręcznie uruchomiono zainstalowany, przypięty runtime backupu
0024, z pominięciem kontroli terminu kolejnej kopii. Nowa spójna kopia obu baz
i konfiguracji przeszła integralność oraz rzeczywiste odtworzenie offline
**PASS, 11,191 s**, 17:39:06 UTC. Usługi wznowione. To lokalna kopia nowego
stanu; nie jest potwierdzeniem jej nowego uploadu offsite ani przejścia na 0026.

Świeży własny AVD API35 przeszedł próbę HTTPS do API i discovery z właściwym
CA, hostname i issuer; błędne CA odrzucone, transport zamknięty po teście.
Ta próba sprawdza łączność Android VM. Końcowy skonfigurowany APK oraz
logowanie z aplikacji, synchronizacja i E4 wymagają odbioru właściwej wersji
Androida. Lokalna poczta nie potwierdza dostarczania email w produkcji.

## Odbiór lokalnego APK, 24 października 2026

Oryginalny pakiet A1 `5b283e4`, 0.8.29.validation/code1040/Room20, przeszedł
niezależną kontrolę czterech APK, podpisów oraz rzeczywistej konfiguracji CA,
issuer i API. [Manifest wejścia](../../android/KANDYDAT_E4_0_8_29.json) zachowuje
sumy dostarczonych plików. [Neutralne dowody operatora O3](https://github.com/Roseru/aplikacja-mobilna/releases/tag/untagged-d85ad9133083bfcca3ca)
są w roboczym wydaniu wymagającym dostępu do repozytorium.

Na własnym AVD i używanym API05/schema0024 wykonano Chrome/PKCE, bootstrap
i pełną kopię. Profil zapisano przed pierwszym celem; użytkownik jawnie podał
2300 kcal. Normalny interfejs utworzył offline profil, cel, wagę, produkt
prywatny, posiłek i kompletność dnia. Kolejka przetrwała restart. Jedna partia
otrzymała sześć `accepted`, revision1 i sześć trwałych lokalnych ACK.
Pełna treść w PostgreSQL odpowiada utrwalonym operacjom, w tym wartościom null.

Osobny E4 dotyczył jednej nowej operacji Meal. Po HTTP200 i niezależnym PG C1
rzeczywiście zatrzymano proces przed ACK. Restart wysłał identyczną partię,
otrzymał `already_applied`/revision1 i zapisał ACK; kontrola33tabel przeszła.
PG C2 zachował stan C1. Dopiero osobny późniejszy pełny PULL zmaterializował
nowy DiaryDay. Przed nim dnia nie było lokalnie; po nim payload i revision1
odpowiadały serwerowi, bez kolejnego POST lub duplikatu.

Te wyniki kwalifikują wskazane APK/Room20 do opisanych lokalnych prób.
Nie zastępują odbioru nowszego Room22, WorkManagera z docelową polityką sieci,
fizycznego telefonu, Gemini, pełnego KO32 lub wdrożenia produkcyjnego.
Historyczny FAIL E4 Room17 pozostaje osobnym wynikiem.

Źródła konfiguracji Mailpit: [Docker](https://mailpit.axllent.org/docs/install/docker/),
[API skrzynki](https://mailpit.axllent.org/docs/api-v1/),
[wydanie 1.32.0](https://github.com/axllent/mailpit/releases/tag/v1.32.0).
