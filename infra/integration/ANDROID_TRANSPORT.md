# Transport Android → istniejące API — O3

Wynik 13.10.2026, 23:38 CEST: **READY dla transportu testowego emulatora**.
To odpowiedź O3 na część sieciową O2-033. Fizyczny telefon nie jest podłączony;
nie potwierdzamy LAN/VPS ani odbioru logowania z APK. O1 może rozpocząć
[własny scenariusz APK/API](../../docs/integracja/ODBIOR_APK_API_O2.md).

## Wejście dla O1

| Parametr | Sprawdzona wartość |
|---|---|
| Istniejący origin | `https://192.168.3.162:18443` |
| Dokładny issuer | `https://192.168.3.162:18443/realms/calorie-dev` |
| API base URL | `https://192.168.3.162:18443/api/v1` |
| Schema backendu | `0024_e9_history_graph`, dotychczasowy [rollout E9](../../docs/e9/ROLLOUT_LOKALNY_O3.md) |
| APK source | `b2634eb35b7f3099c35ac62bbd01b1e106be8079`, 0.8.10/code21, deklarowany Room8 |
| Wariant / callback | `pl.roseru.kalorie.validation` / `pl.roseru.kalorie.validation:/oauth2redirect` |
| APK SHA-256 | `63645564dea3c9c93b86d0c5e5bfbe794a7f21d33b36c958d5ed3f4186843cf3` |
| Publiczny CA SHA-256 | `01f120ef25f091a6413a535dcaa5e333575a8d08a016503c47998333eef3a6f6` |
| Urządzenie O3 | Własny `Agent3_PKCE_API35`, API35 Google APIs x86_64, `emulator-5560` |

APK jest poza Git, w prywatnym zestawie dowodów O3 `apk-preflight-20261013/acceptance-3`.
`aapt2 dump resources/xmltree` potwierdził **rzeczywiste** wartości issuer/API,
applicationId i networkSecurityConfig w zbudowanym APK. Wykorzystano istniejący
[overlay validation](ANDROID_PKCE.md); APK zawiera tylko publiczny CA ograniczony
do dokładnego hosta. Chrome ma osobny magazyn zaufania. Nie uznano starego wpisu
CA w AVD za nowy pozytywny wynik Chrome.

## Diagnoza i sposób połączenia

Świeży preflight hosta: dawny `192.168.3.162` nie jest przypisany komputerowi;
aktualny Ethernet ma inny subnet. Istniejący gateway jest dostępny na
`127.0.0.1:18443`, API/Keycloak/retencja/motivation/lifecycle są healthy.
Finalizer pozostaje disabled/unhealthy zgodnie z zamkniętą bramką Nemesis.

`android_transport.py` ustanawia **wyłącznie w wybranym własnym AVD**:

1. `adb reverse tcp:18443 tcp:18443` do istniejącego gateway gospodarza.
2. Osobny łańcuch NAT `O3_APK_18443`; OUTPUT przekierowuje wyłącznie TCP
   do **192.168.3.162:18443** na emulatorowe `127.0.0.1:18443`.

URL, Host, TLS hostname, certyfikat i issuer pozostają oryginalne. Nie ma
nowego backendu, reinit, zmiany `(issuer, sub)`, epoki, host DNS/firewall/trust
lub otwarcia portu hosta na wszystkich interfejsach. Reguła obejmuje także
transport przeglądarki w tym AVD; jej rzeczywisty login wymaga odbioru O1.

Skrypt wymaga serialu `emulator-N`, zgodnej nazwy AVD, zakończonego boot i
wcześniej świadomie włączonego `adb root` na własnym Google APIs AVD.
Odrzuca fizyczne urządzenia, istniejące mapowanie reverse, łańcuch i lease.
Lease poza Git wiąże origin, AVD, boot oraz port serwera ADB. `disconnect`
sprawdza dokładny zestaw reguł/mapowanie, usuwa tylko własny łańcuch i reverse.
Nie używa `reverse --remove-all`, globalnego flush lub kasowania danych.

## Powtórzenie i zakończenie

Z głównego katalogu repozytorium. `$ExistingState` wskazuje **istniejący**
prywatny stan tej instalacji; `$Lease` nowy plik poza Git. `$Adb` jest lokalnym
narzędziem SDK. Nie inicjalizować drugiego środowiska jako sposobu naprawy.

```powershell
$Serial = 'emulator-5560'
$Avd = 'Agent3_PKCE_API35'
# Wyłącznie wcześniej wybrany własny testowy AVD:
& $Adb -s $Serial root
& $Adb -s $Serial shell cmd connectivity airplane-mode disable
& $Adb -s $Serial shell svc wifi enable
uv run --project backend --locked python infra/integration/android_transport.py connect --adb "$Adb" --serial "$Serial" --avd "$Avd" --state "$ExistingState" --lease "$Lease"
uv run --project backend --locked python infra/integration/android_transport.py status --adb "$Adb" --serial "$Serial" --avd "$Avd" --state "$ExistingState" --lease "$Lease"
# Po próbach właściciela, bez usuwania innych mapowań:
uv run --project backend --locked python infra/integration/android_transport.py disconnect --adb "$Adb" --serial "$Serial" --avd "$Avd" --state "$ExistingState" --lease "$Lease"
```

Port serwera ADB domyślnie5037; przy świadomie wydzielonym własnym daemonie
podaj ten sam `--adb-server-port` w connect/status/disconnect. Odbiór użył5063,
następnie usunął własny tunel, ponownie sprawdził HTTPS na5037 i zatrzymał
**wyłącznie własny** daemon5063. Aktywne końcowe połączenie używa5037.

Po reboot AVD/`adb root`/utracie reverse nie ufać staremu READY: ponownie
sprawdzić transport i TLS. Stary lease z innym boot zostaje zachowany jako
dowód i nie służy do usuwania reguł bieżącego boot. Po potwierdzeniu braku
starego łańcucha/mapowania użyć nowego lease. Skrypt nie zmienia sam trybu
samolotowego/Wi-Fi; ustawienia offline tego AVD były pierwotnie włączone,
teraz świadomie pozostawiono je online do próby O1.

### Read-only HTTPS bez danych konta

[AndroidHttpsProbe.java](AndroidHttpsProbe.java) wykonuje w Android VM jedynie
GET discovery i readiness. Używa ograniczonego publicznego CA, platformowego
hostname verifier, limitów czasu/rozmiaru oraz dokładnego issuer. Nie jest
APK, przeglądarką ani loginem; proces odbioru działał jako shell/root AVD.

Kompiluj w nowym prywatnym katalogu `$ProbeDir` przy użyciu JDK17+ i SDK35:

```powershell
# $AndroidJar: platforms/android-35/android.jar; $D8: build-tools/36.0.0/d8.
New-Item -ItemType Directory "$ProbeDir/classes"
javac --release 17 -cp "$AndroidJar" -d "$ProbeDir/classes" infra/integration/AndroidHttpsProbe.java
& $D8 --lib "$AndroidJar" --min-api 35 --output "$ProbeDir/classes" "$ProbeDir/classes/AndroidHttpsProbe.class"
jar cf "$ProbeDir/probe.jar" -C "$ProbeDir/classes" classes.dex
# Nowy własny katalog na AVD; wyłącznie probe.jar i publiczny ca.pem:
& $Adb -s $Serial shell mkdir /data/local/tmp/o3-apk-preflight
& $Adb -s $Serial push "$ProbeDir/probe.jar" /data/local/tmp/o3-apk-preflight/probe.jar
& $Adb -s $Serial push "$ExistingState/tls/ca.pem" /data/local/tmp/o3-apk-preflight/ca.pem
& $Adb -s $Serial shell 'CLASSPATH=/data/local/tmp/o3-apk-preflight/probe.jar app_process /system/bin AndroidHttpsProbe /data/local/tmp/o3-apk-preflight/ca.pem https://192.168.3.162:18443'
```

Wynik pozytywny: android_https PASS, discovery200, readiness200, dokładny issuer,
browser_apk_login NOT_TESTED. Nie wysyła tokenów, credentials lub dziennika.
Windowsowy `adb shell` może przekształcać binarne stdin (CRLF/EOF); dlatego
nie używamy stdin/nc jako dowodu TLS. Próba run-as/su app_process nie uruchomiła
probe i nie daje wyniku klienta APK/UID. Nie osłabiano SELinux dla tego testu.

## Faktyczne wyniki i granice

- Android VM → rzeczywisty gateway: TLS/discovery/issuer/readiness PASS.
- Obcy CA: `SSLHandshakeException`, FAIL zgodnie z oczekiwaniem.
- Po własnym disconnect: brak pozytywnego HTTPS; reconnect przywrócił PASS.
- Ponowny connect odmówiony, bieżący status nadal PASS; własny cleanup sprawdzony.
- APK validation zbudowany i zainstalowany przez install-r. Regularnego APK
  0.8.0/code11/Room6 nie aktualizowano, nie czyszczono ani nie odinstalowano.
  Prywatne kopie Room+WAL przed/po ponownym install-r validation i próbach:
  20 tabel identycznych, FK clean, 0 posiłków w tym AVD. Nie jest to migracja
  regularnego APK doRoom8 lub dowód zachowania dziennika innego urządzenia.
- 12 testów blokad własności i całe 61 infra PASS; Ruff check/format PASS.
- Neutralny receipt poza Git SHA-256:
  `d0c933f1efdd9de483f5fda3099e35ba2bba2bbcab61ee4814e4fc1b2c849329`.

Automatyczna kontrola odrzuciła uruchomienie Chrome przez CLI/ADB. Kontynuowano
samodzielny read-only preflight Android VM, bez obchodzenia tej odmowy przez
inną formę uruchomienia przeglądarki. **Chrome/PKCE/bootstrap/me/motivation,
logout/B→A/spóźniona odpowiedź nie zostały wykonane**; O1 ma własny scenariusz.
Przed zaliczeniem APK trzeba potwierdzić jego TLS oraz rzeczywisty browser/callback,
baseline i konto. Root probe, fixture, install lub CI nie zastępują tego wyniku.

Fizyczny telefon/LAN/VPS pozostaje WAITING_EXTERNAL u O3: potrzebna konkretna
osiągalna sieć/urządzenie, które pozwoli zachować obecny issuer, albo osobny plan
migracji tożsamości/zaufania. Nie dodano dawnego adresu do obcego subnetu.
Gemini development pozostaje niezależne WAITING_EXTERNAL: brak klucza i
potwierdzonego projektu Free Tier/modelu/limitów/billing w istniejącym stanie.
Warunki przekazania określają [E7](../../docs/e7/KONFIGURACJA_O3.md) i
[E9](../../docs/e9/KONFIGURACJA_O3.md); nie było Google I/O, drugiej puli,
resetu limitów, otwarcia AI/Nemesis ani zmiany PAUSED automatyzacji.
