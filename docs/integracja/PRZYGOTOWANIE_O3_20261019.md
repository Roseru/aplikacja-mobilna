# Przygotowanie SDK i próby Android–API — O3

Autor: agent 3/O3, 17 października 2026. Baza: main
`faee91f`, gałąź `codex/devops-sdk37-proba-api`.
Zakres: odpowiedź na O1-060/061/064 i O2-034. Pozostałe odbiory recovery
oraz wydania pozostają osobnymi zadaniami.

## Narzędzia migracji Androida

Odczytano macierz z [PR117](https://github.com/Roseru/aplikacja-mobilna/pull/117),
commit `3e30a6f744dcb3778c7cb753dd978efca62792bc`. Przed wdrożeniem A1
kwalifikuje cały zestaw AGP/Kotlin/Compose/KSP/Room według tego dokumentu.

Lokalne SDK O3 ma już zainstalowane i rozpoznane przez menedżer:

| Składnik | Rzeczywisty identyfikator | Wynik przygotowania |
|---|---|---|
| Platforma API37, revision2, extension22, stable | `platforms;android-37.0` | Zainstalowana; kompilacja Java z jej android.jar PASS |
| Build Tools | `build-tools;36.0.0` | Zainstalowane; aapt2 uruchomione i D8 wygenerował rzeczywisty classes.dex |
| Dotychczasowa platforma i Build Tools | `platforms;android-35`, `build-tools;35.0.0` | Zachowane |
| Emulator testowy | `system-images;android-35;google_apis;x86_64` | Zachowany; nie uruchamiano ani nie modyfikowano AVD |

**Korekta wejścia A1:** bieżąca lista producenta zawiera `platforms;android-37.0`,
nie `platforms;android-37`. Przyszły krok instalacji SDK powinien używać tego
rzeczywistego identyfikatora. Nie tworzymy aliasu katalogu ani nie podmieniamy
metadanych pakietu. Sposób wyboru API37 w AGP9.1.1 wymaga rzeczywistego build
gałęzi migracji A1; sam smoke Java/D8 tego nie zalicza.

SHA-256 lokalnego android.jar:
`bf1b4387cc7ca94fc6ef684f040d9d16fbf16248e181819f020736ea2053f177`.
Smoke używał JDK21 i `javac --release 17`; nie jest odbiorem całego build na
JDK17. W CI pozostaje Temurin17. Logi i próbny DEX są poza Git.

Oficjalny SHA-256 dystrybucji Gradle9.3.1 bin, ponownie pobrany z obu
adresów producenta:

```text
b266d5ff6b90eada6dc3b20cb090e3731302e553a27c5d3e4df1f0d76beaff06
```

Pobrano rzeczywiste archiwum137037885B, porównano cały SHA-256 z powyższym
hashem i uruchomiono `gradle --version`: **Gradle9.3.1 PASS**, JDK21.0.12.
Dystrybucja jest przygotowana w prywatnym cache O3 poza repozytorium.
Windowsowy launcher w katalogu z polskim znakiem zwrócił błędną ścieżkę do JAR;
ten sam zweryfikowany pakiet w katalogu cache bez znaków narodowych uruchomił
się poprawnie. Nie zmieniano nazwy repozytorium ani globalnej konfiguracji Java.
To test narzędzia, nie build aplikacji na nowej macierzy.

Zgodnie z podziałem A1/O3, produkcyjny workflow nadal używa SDK35/Build
Tools35.0.0, wrapper8.11.1 i emulatora API35. Gotowy kod migracji A1 jest
warunkiem wspólnej zmiany parametrów obu jobów i wrappera. Następnie wymagane
są własne build/lint/JVM/native i pełne CI nowego head oraz osobne main CI.
Nie zamykano PR81/82 ani nie zaliczano nowej macierzy starymi testami.

Źródła: [zgodność AGP9.1.1](https://developer.android.com/build/releases/agp-9-1-0-release-notes),
[SHA Gradle9.3.1](https://services.gradle.org/distributions/gradle-9.3.1-bin.zip.sha256),
[drugi adres SHA producenta](https://downloads.gradle.org/distributions/gradle-9.3.1-bin.zip.sha256).
Dokładne identyfikatory SDK sprawdzono w rzeczywistym `sdkmanager --list`
i `--list_installed` 17 października.

## Okno 19 października, 08:00–08:10 CEST

**Właściciel proponuje poniedziałek 19.10.2026, 08:00–08:10 Europe/Warsaw
(06:00–06:10 UTC). A1 ma potwierdzić termin i aktualny osiągalny peer.**
To propozycja, nie potwierdzona rezerwacja ani wykonana próba. Dziesięć minut
przeznaczamy na istniejący scenariusz O2-034, po wcześniejszym przygotowaniu
obu stanowisk. Brak gotowości nie przedłuża automatycznie okna.

Stan O3 z 17.10, 18:07 CEST:

- Rzeczywisty HTTPS do istniejącego gateway: readiness200, discovery200,
  sprawdzenie oryginalnego CA/hostname i dokładnego issuer PASS.
- API, Keycloak, PostgreSQL, retencja, motivation, lifecycle, startup i kopia
  lokalna OK. Finalizer expected_disabled; AI niewdrożone.
- Ostatnia kopia z 17.10, 16:12 CEST: integrity, restore9,75s i resume PASS.
  Harmonogram kopii pozostaje włączony. W poniedziałek dowód musi być świeży.
- Aktualna sieć O3: Wi-Fi192.168.3.162. To adres dzisiejszy; poniedziałkowy
  osiągalny adres trzeba potwierdzić ponownie. Dawnych peerów nie używamy.
- Publiczny przenośny pakiet O1-APK-API-20261014.zip zweryfikowany przez
  istniejący checker; SHA-256
  `89c3709635c4e89a27da2a809a14ef13a3c755baf359ac24f5e83729ec51ee6b`.
  Jego referencyjny APK0.8.10 nie zastępuje aktualnego kandydata/drivera A1.

Oryginalny issuer to `https://192.168.3.162:18443/realms/calorie-dev`,
API `https://192.168.3.162:18443/api/v1`, publiczny CA SHA-256
`01f120ef25f091a6413a535dcaa5e333575a8d08a016503c47998333eef3a6f6`.
Zmiana trasy nie zmienia tych wartości, kont lub epoki.

## Przebieg i warunki uruchomienia

1. **Przed08:00:** A1 potwierdza gotowość własnego AVD/lease, dokładny osiągalny
   adres, źródło/wersję/SHA APK i drivera oraz istniejący baseline. Kandydat
   API/Room9 pozostaje oddzielny od PR105/Room10. O3 potwierdza własny adres,
   świeży HTTPS/monitoring, kopię oraz brak trwającego backupu/recovery.
   Jeżeli sieć się zmieniła, nie podstawiamy automatycznie historycznych IP.
2. **08:00:** O3 uruchamia istniejący `android_peer.py server` tylko na
   potwierdzonym własnym adresie:18444, z `--allow-client` równym dokładnemu
   adresowi A1. Używa dozwolonego python.exe z ukrytym oknem; wcześniejszy
   pythonw.exe był blokowany przez istniejącą zaporę. Czas życia liczy od
   rzeczywistego startu do08:10, nie jako nowe10min po spóźnieniu. Pozostało
   mniej niż60s lub brak wspólnej sieci oznacza odroczenie próby.
3. O3 potwierdza faktyczny LISTENING. A1 wykonuje jeden świeży `check` z
   własnego komputera. Po PASS uruchamia własny `client` i istniejący transport
   AVD z lease. Timeout oznacza zapis czasu i diagnozę, bez rozszerzania peerów
   lub wyłączania TLS/zapory.
4. A1 wykonuje realGET → held → ukończony logout/gość → released → dto_parsed
   → stale_owner_rejected oraz guest_preserved. Zachowuje prywatny baseline;
   publikuje neutralny receipt wiążący kolejność, źródło/APK/driver i urządzenie.
   O2 odbiera dowód zgodnie z [O2-034 i scenariuszem](ODBIOR_APK_API_O2.md).
5. **Najpóźniej08:10:** proces relay kończy się według TTL. O1 zamyka własny
   client i usuwa własny transport przy użyciu tego samego lease; O3 potwierdza
   brak listenera18444 i świeżą gotowość usług/kopii. Brak któregokolwiek markera
   lub poprawnego DTO oznacza PARTIAL/NOT_RUN, nigdy automatyczny PASS.

Nie wstrzymujemy teraz kopii. Termin08:00 nie pokrywa się ze zwykłymi oknami
03/15; gdy trwa zaległa kopia lub recovery, pierwszeństwo ma ich bezpieczne
zakończenie i uzgodnienie innego terminu. Nie rejestrujemy zadania otwierającego
port przed otrzymaniem peera i potwierdzeniem gotowości. Przy samym braku
terminu/peera nie zmieniamy zapory, CA, DNS ani stanu emulatorów.

Dokładne komendy `check/client/connect/disconnect` pozostają w
[instrukcji pakietu](../../infra/integration/ANDROID_HANDOFF.md).
Po stronie O3 przygotowano prywatną akcję
`.tools/sdk37-api-preparation/api-window-20261019.py`. Używa istniejącego
`Relay` i istniejącego stanu. Sprawdza absolutne okno ponownie po preflight
TLS; odmawia startu z trwającą kopią/recovery lub wyłączonym zadaniem kopii.
Zapisuje najwyżej32 metadane czas/peer/allow, bez HTTP/TLS bytes. Nie jest
nową usługą ani automatycznie uruchamianym harmonogramem.

Rzeczywisty `--preflight-only` dał HTTPS PASS. Próba uruchomienia z dzisiejszą
datą została odrzucona jako OUTSIDE_AUTHORIZED_WINDOW; port18444 nadal nie
ma listenera. To nie jest próba poniedziałkowego peera. Przy znanych,
potwierdzonych wejściach i po uzgodnieniu A1:

```powershell
# $O3Address i $O1Address to potwierdzone tego dnia dokładne adresy LAN/VPN.
# Uruchomienie bez widocznej konsoli, z osobnymi prywatnymi logami.
$peerDirectory = (Resolve-Path '.tools/sdk37-api-preparation').Path
$peerScript = Join-Path $peerDirectory 'api-window-20261019.py'
$python = (Resolve-Path 'backend/.venv/Scripts/python.exe').Path
$peerArguments = '"{0}" --bind "{1}" --peer "{2}"' -f $peerScript,$O3Address,$O1Address
Start-Process -FilePath $python -ArgumentList $peerArguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $peerDirectory 'window.log') -RedirectStandardError (Join-Path $peerDirectory 'window-error.log')
```

Własny PID i rzeczywisty bind sprawdzamy przed uznaniem startu. Połączenie
wykorzystuje oryginalny TLS end-to-end; listener ani lokalny preflight nie są
wynikiem połączenia z komputera A1. **Live APK/API nadal NOT_RUN.**
