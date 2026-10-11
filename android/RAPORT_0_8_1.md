# Android 0.8.1 — bootstrap HTTP, raport Agenta 1

Data: 11 października 2026. Gałąź `codex/android-sesja`, [draft PR #26](https://github.com/Roseru/aplikacja-mobilna/pull/26), kontynuacja klienta sesji 0.8.0. VersionCode 12, Room 6 bez migracji. [Konfiguracja i protokół](BOOTSTRAP_HTTP.md).

## Wynik

Potwierdzona sesja ma wewnętrzny kontekst token/tożsamość/lease, kontrolowany przed żądaniem i zastosowaniem odpowiedzi. Przycisk połączenia konta wykonuje trwały bodyless bootstrap E3. Utrata ACK zachowuje klucz, 401 odnawia najwyżej raz i wyłącznie przy potwierdzonym wyniku odnowienia, 409 zmiany kontekstu odnawia klucz najwyżej raz, 429/503 respektują Retry-After. Logout/nowa sesja/A→B→A odrzucają stary wynik; anulowanie zwalnia stan łączenia. requiresRecovery pozostaje trwałe. Żaden z tych przepływów nie wysyła dziennika, nie tworzy celu/profilu i nie importuje gościa.

## Weryfikacja

Końcowy pełny assemble/JVM/lint/device: PASS (4 min 33 s). 81 testów JVM, 76/76 testów urządzenia, 0 failure/error/skip. API35/Android15, 1080×2400, density420, font1, tryb samolotowy. Lint: 0 błędów, 28 ostrzeżeń i 1 informacja. Zestaw zawiera 8 nowych testów JVM transportu i 11 nowych testów urządzenia bootstrapu.

Nowe przypadki JVM obejmują ścisły adres HTTPS, przechwycone nagłówki, brak body/If-Match/X-Sync-Epoch, preflight blokujący wysyłkę, redirect/HTML/kompresję/limit 64 KiB, kształt błędów, Retry-After date/seconds, odrzucenie injection i redagowanie kontekstu. 429/503 z HTML proxy respektują opóźnienie bez odczytu body.

Nowe przypadki urządzenia łączą kontroler z prawdziwymi Room/Keystore oraz zastępczymi OIDC/HTTP: lost ACK i restart kontrolera, brak importu gościa/prywatnych mutacji, logout/A→B→A/double tap, 401 i ograniczenie retry, epoka/generacja/recovery/odrzucenie innego konta i cofniętej generacji, trwałe opóźnienie po restarcie, wadliwa odpowiedź/403/powtórny409, wygaśnięcie, brak sesji przy samym lokalnym ownerze, odnowienie podczas oczekiwania i dwa rodzaje anulowania. Nieudane odnowienie po401 nie ponawia żądania ze starym ani niepotwierdzonym tokenem.

Przebieg wcześniejszego zestawu: build/lint/JVM/device PASS, 80 JVM i 73/73 urządzenia, BUILD SUCCESSFUL w 6 min 12 s. W trakcie przeglądu dodano przypadki anulowania zadania/odnowienia, przeciążonego proxy i nieudanego odnowienia; wymagały ponownej walidacji finalnych źródeł. Bez pomijania testów, suppression/baseline lint i zwiększania timeoutów testów UI.

Nieudany pełny przebieg finalnych źródeł miał 66/76 PASS i 10 błędów ekranowych No compose hierarchies. Logcat potwierdził przejście Keyguard do DOZING i MainActivity do STOPPED, a dumpsys power: Wakefulness=Asleep, timeout ekranu 1800000 ms. Dłuższa przerwa w zadaniu wydłużyła wall time tego przebiegu; nie przypisujemy go wydajności aplikacji. Zachowano prywatny raport. Wybudzono emulator, włączono jego emulowane AC i svc power stayon, potwierdzając Awake/StayOn=true. Ponowny pełny zestaw 76/76 przeszedł bez zmian kodu/testów, automatycznego retry, skip lub wydłużania timeoutów UI. To korekta środowiska, nie poprawka aplikacji.

Komenda finalnej weryfikacji z `android/`:

```powershell
.\gradlew.bat :app:assembleDebug :app:testDebugUnitTest :app:lintDebug :app:connectedValidationAndroidTest --offline --console=plain
```

## Aktualizacja i próba ręczna

Aktualizacja przez adb install -r z 0.8.0 na 0.8.1 zachowała wszystkie kolumny 18 tabel Room6, dwa istniejące posiłki, profile/cele i całą kolejkę; foreign_key_check pusty. APK debug poza Git: output-apk/Racje-i-kalorie-0.8.1-debug.apk; SHA256 0985e14e66ed62046d49d0793617ef6d2ce6cab36806327a41ed3b2fe035b78a. Uruchomienie potwierdziło versionCode12/versionName0.8.1, status ok i widoczny Dziennik w emulatorze właściciela.

Scenariusze ręczne domyślnego APK: Dziennik → Profil → Konto i logowanie → powrót; dziennik, cel, wybór posiłku i Postępy pozostają dostępne offline. Logowanie/API są wyłączone przy pustych publicznych adresach. Po podłączeniu prawdziwego środowiska: przeglądarka/logowanie → osobny dziennik konta → Połącz konto z serwerem → widoczne mapowanie, bez oznaczenia kolejki jako wysłanej; następnie outage/retry/restart/logout i konta A/B.

## Granice dowodu i kolejny krok

Testy JVM używają zastępczego HttpsURLConnection, a urządzenie synthetic JWT/transportu. Nie są odbiorem prawdziwego TLS, podpisu JWT, Keycloak, przeglądarki lub zabicia procesu. Publiczny CA dla konkretnego hosta i osiągalne środowisko O3 nadal są potrzebne; Docker/uv nie były dostępne na komputerze O1. Domyślne adresy pozostają puste. Osobne zielone harnessy backendu/infrastruktury nie dowodzą integracji APK. KO-31/pełne E3/E5, odczyty API, WorkManager, zgoda/import gościa i synchronizacja nadal pozostają otwarte.

Na początku tego etapu odczytano main f551ecc i O2-018/019; brak nowego przekazania. Poprzedni head PR26 3b081c4 ma osiem kontroli success, w tym android-device i ci-required. Nowy opublikowany head wymaga oddzielnego odczytu CI; nie przenosimy wyniku poprzedniego commita na następny.

Przed publikacją odczytano nowy main75c4414: scalone retencja O3/PR21, odbiór sesji O3/PR27 i podział E8/PR29. [O3-011](../infra/integration/ANDROID_PKCE.md) potwierdza rzeczywisty odbiór sesji 0.8.0/3b081c4 i dostarcza overlay/scope helpers. Nie ma tam odbioru HTTP/bootstrapu 0.8.1. O1 uwzględnia raport i zachowuje wszystkie przekazania przy zwykłym merge. Nie rozpoczęto E8 ani nie przejęto niescalonego E7/PR28. Obserwację O3 o pojedynczym braku pola gramatury po checkboxie racji odczytano; nie odtworzyła się w udanych lokalnych pełnych przebiegach tego etapu.
