# Pakiet dla Androida na drugim komputerze

Pakiet jest przenośny. Zawiera APK validation0.8.10/code21, publiczny CA,
minimalne host/port, skrypty i hashe. Nie zawiera haseł, tokenów, kluczy prywatnych,
baz, danych dziennika, ścieżek O3 ani lease jego emulatora. Nie jest nowym backendem.
APK/issuer/API/callback pozostają zgodne z `handoff.json`.

## Pobranie i weryfikacja

ZIP należy pobrać z linku przekazania O3 i porównać jego SHA-256 z wpisem O3.
Rozpakuj do nowego prywatnego katalogu. Dalej `$Bundle` oznacza jego absolutną
ścieżkę. Verify, peer i transport używają wyłącznie standardowej biblioteki Python
3.13; nie wymagają Docker lub credentiali O3. Do generatora overlay użyj
Python z istniejącego środowiska backendu (`uv sync --project backend
--locked`) ma potrzebną bibliotekę cryptography. Wykonuj z checkoutu projektu:

```powershell
uv run --project backend --locked python "$Bundle/android_handoff.py" verify --bundle "$Bundle"
uv run --project backend --locked python "$Bundle/android_handoff.py" overlay --bundle "$Bundle" --output "$LocalOverlay"
```

`$LocalOverlay` jest nowym katalogiem poza Git **na komputerze O1**. Nie kopiować
starego init.gradle O3: zawierał jego absolutną ścieżkę. Generator ustawia lokalną
ścieżkę i dodaje CA tylko do validation oraz dokładnego hosta, bez cleartext lub
globalnego zaufania. Chrome ma osobny magazyn zaufania; odbiór przeglądarki/CA jest
własnym krokiem O1. Overlay można zastosować do aktualnych źródeł O1, zachowując ich
wersję/commit/hash; gotowe APK0.8.10 jest jedynie oznakowanym punktem odniesienia.

## Połączenie dwóch komputerów

Najpierw O1/O3 uzgadniają **rzeczywiste osiągalne adresy LAN/VPN**. O3 uruchamia
ograniczony relay tylko na swoim dokładnym adresie i dopuszcza jeden adres O1:

```powershell
uv run --project backend --locked python "$Bundle/android_peer.py" server --bundle "$Bundle" --peer-host "$O3Address" --allow-client "$O1Address"
```

Proces najpierw weryfikuje HTTPS/issuer istniejącego gateway127.0.0.1:18443.
Domyślny port relay18444 i czas życia1h; `--lifetime` może wynosić60..86400s.
Nie zmienia backendu, issuer, CA, kont lub epoki. Nie kończy TLS i nie zapisuje
ruchu. O3 ewentualnie dodaje **osobną** regułę zapory TCP18444 ograniczoną
LocalAddress=O3, RemoteAddress=O1, bez wyłączania zapory lub przekierowania routera.
Zakończenie procesu zamyka relay; usuwa się tylko własną nazwaną regułę.
W tym pakiecie nie ma automatycznej zmiany zapory.

Na O1 najpierw rzeczywisty preflight z jego komputera, następnie relay loopback:

```powershell
uv run --project backend --locked python "$Bundle/android_peer.py" check --bundle "$Bundle" --peer-host "$O3Address"
uv run --project backend --locked python "$Bundle/android_peer.py" client --bundle "$Bundle" --peer-host "$O3Address"
```

O1 zachowuje terminal procesu client. Binding jest wyłącznie127.0.0.1:18443;
istniejący port jest odrzucany, bez nadpisywania. Przekazywane bajty są oryginalnym
TLS. Preflight sprawdza hostname192.168.3.162 i dokładny issuer, chociaż routing
prowadzi do innego adresu O3. Nie używać adresu relay jako nowego issuer.
Brak wspólnego LAN/VPN oznacza WAITING_EXTERNAL; samo pobranie ZIP nie daje sieci.
Adres100.64/10 jest dopuszczony wyłącznie jako osiągalny adres uzgodnionego VPN.

## Własny emulator O1

`$Adb`, `$Serial`, `$Avd` muszą wskazywać **własny Google APIs AVD O1**. Serial5560,
boot i lease O3 nie są przenoszone. `$Lease` jest nowym lokalnym plikiem poza Git.
Po świadomym włączeniu adb root na wybranym testowym AVD:

```powershell
& $Adb -s $Serial root
uv run --project backend --locked python "$Bundle/android_transport.py" connect --adb "$Adb" --serial "$Serial" --avd "$Avd" --state "$Bundle" --lease "$Lease"
uv run --project backend --locked python "$Bundle/android_transport.py" status --adb "$Adb" --serial "$Serial" --avd "$Avd" --state "$Bundle" --lease "$Lease"
```

Skrypt łączy oryginalny host18443 przez adb reverse z relay O1, który prowadzi doO3.
Nie obsługuje fizycznego telefonu i nie udostępnia ADB przez sieć.
Do zbudowania aktualnego APK O1 używa swojego overlay oraz parametrów:

```powershell
./gradlew.bat :app:assembleValidation -I "$LocalOverlay/init.gradle" -PCALORIE_OIDC_ISSUER=https://192.168.3.162:18443/realms/calorie-dev -PCALORIE_API_BASE_URL=https://192.168.3.162:18443/api/v1
```

Przed instalacją wykonać własny baseline; install-r dotyczy uzgodnionego validation
bez clear/uninstall. Nie podpisuje zachowania danych regularnego APK za O1.
Transport/preflight nie są odbiorem PKCE/bootstrap/GET/profile/motivation/B→A.
O1 wykonuje istniejący `docs/integracja/ODBIOR_APK_API_O2.md` i dopisuje własny wynik.
Credentiale kont uzgadnia się prywatnym kanałem; nie są w tym ZIP ani Git.

Po próbie, na tym samym własnym AVD i lease:

```powershell
uv run --project backend --locked python "$Bundle/android_transport.py" disconnect --adb "$Adb" --serial "$Serial" --avd "$Avd" --state "$Bundle" --lease "$Lease"
```

Zatrzymać własny client/server. Nie usuwać cudzych reguł, reverse, wolumenów lub kont.
