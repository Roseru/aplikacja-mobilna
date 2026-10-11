# Raport Androida 0.8.2 — Agent 1

Wersja 0.8.2 / versionCode 13 / Room 6. Zmiana: jawny odczyt profilu serwerowego po bootstrapie, bez nadpisania lokalnych danych i celu kalorii. [Opis i granice integracji](ODCZYT_PROFILU.md).

Gałąź `codex/android-odczyt-profilu`, zależna od `42763f8` / PR26; osobny PR porównuje nowy etap z `codex/android-sesja`. Rzeczywisty bootstrap/API nie jest odebrany na podstawie zastępczych transportów.

Kod `0522824990a35c0b54bec9cceaa4d3a8e9c7b069`, [PR31](https://github.com/Roseru/aplikacja-mobilna/pull/31). CI tej gałęzi jest odrębnym odbiorem od zielonego PR26.

## Weryfikacja lokalna

- `assembleDebug`, `testDebugUnitTest`, `lintDebug`, `assembleValidationAndroidTest`: BUILD SUCCESSFUL, 4 min 15 s.
- Pełne `connectedValidationAndroidTest`: **86/86 PASS**, bez pominięć/błędów; rzeczywisty Room/Keystore i komponenty UI, zastępcze HTTP/ID tokeny. **87 JVM PASS**, bez błędów i pominięć.
- Bieżący raport lint: **0 błędów, 4 ostrzeżenia, 1 informacja**. Bez dodawania suppressions/baseline; nie jest to odbiór aktualności wersji bibliotek.
- Emulator API35/Android15: 1080×2400, density420, font1, tryb samolotowy. Emulowane AC i StayOn=true utrzymały ekran aktywny; brak zmiany timeoutów UI/testów.
- Przed aktualizacją z 0.8.1 wykonano prywatny snapshot wszystkich kolumn **18 tabel Room6 i 2 istniejących posiłków**, bez publikacji wartości. Aktualizacja oraz pierwsze uruchomienie zachowały wszystkie te kolumny, outbox i FK; brak migracji schematu/clear-data/uninstall pakietu właściciela.
- APK poza Git: `output-apk/Racje-i-kalorie-0.8.2-debug.apk`, SHA-256 **`ffac4d261e6cab14a564db54b78deaa1c842e54314133ea5939ce0a199cb6128`**. VersionCode13; pakiet właściciela `pl.roseru.kalorie`, testy w osobnym `.validation`.
- Przykład profilu w testach JVM i urządzenia jest bajtowo identyczny z `contracts/examples/valid/profile-read.json` O2.

Nowe próby obejmują ścisły kontrakt i transport GET, pusty profil, brak nadpisania lokalnego profilu/osi/celu/outbox, przed-bootstrap/gościa/recovery, logout A→B→A, double tap, odnowienie podczas GET, pojedyncze odnowienie 401 i jego niepowodzenie, expiry, 403/niepoprawny JSON/account_id, trwały Retry-After współdzielony z bootstrapem, zmianę epoki oraz anulowanie. Dwa testy Compose sprawdzają pusty podgląd/blokadę recovery i zniknięcie danych serwerowych po przejściu do gościa.

Na komputerze O1 nie odnaleziono Docker/uv/lokalnego stanu integration. Rzeczywiste APK/TLS/Keycloak/bootstrap/GET i KO-31 nadal wymagają środowiska O3; nie włączono fikcyjnych adresów ani wyłączenia TLS. CI PR26 dla dokładnego `42763f8` ma osiem success (w tym ci-required); CI nowej gałęzi/PR jest osobnym odbiorem.

## Scenariusze manualne

1. Domyślne APK, bez serwera i internetu: dziennik, produkty, racje, profile/cele i historia nadal działają; logowanie nie jest dostępne.
2. W wydzielonym środowisku O3: konto A → Połącz konto → Pobierz profil. Serwer bez profilu pokazuje jego brak; nie usuwa lokalnego profilu.
3. Profil serwera ma inną klasę/wzrost: podgląd pokazuje dane serwera, lokalny cel kcal i lokalny profil zachowują poprzednie wartości.
4. Odczyt podczas logout/A→B→A: stara odpowiedź nie pojawia się w nowej sesji. Powtórny klik podczas pobierania nie wysyła kolejnego żądania.
5. Błąd sieci/403/niepoprawna odpowiedź: brak potwierdzonego podglądu, dziennik nadal dostępny. 401 pozwala na pojedyncze odnowienie tej samej osoby.
6. Zmiana epoki: brak podglądu, trwała informacja o potrzebie uzgodnienia, brak wyczyszczenia danych lub kolejki. 503/429: respektowany Retry-After także po restarcie.

Punkty 2–6 opisują wymagany odbiór rzeczywistego APK/API; nie stanowią twierdzenia, że został wykonany.

CI PR31 nie uruchamia się automatycznie przy bazie codex/android-sesja: Project CI ma pull_request.branches=[main] i push.branches=[main]. W API check-runs dla 8f285a3 brak kontroli. Po odbiorze/merge PR26 i retarget PR31 na main trzeba uruchomić oraz odczytać wymagane kontrole nowego head. Nie zmieniano workflow O3 ani bazy PR dla obejścia zależności.

Aktualizacja 12.10.2026/O1: PR26 scalony normalnym merge na main c59e6d68d18bbafd157a9d1383aae8d36fa1b893 po osmiu success dla42763f8 i zerze reviews/comments. Zgodnie z docs/WORKFLOW.md odbior rzeczywistego bootstrapu/GET pozostaje kolejnym etapem integracyjnym; merge nie zamyka E3/KO-31. PR31 skierowano na main, nastepnie dolaczono main zwyklym merge; zrodla android/app pozostaly identyczne z przetestowanym0522824. Wczesniejsze uwagi o bazie zależnej/nieuruchamianiu CI sa historyczne; nowy push uruchamia wymagane CI PR do main.
