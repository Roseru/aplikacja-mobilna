# Bootstrap HTTP Androida 0.8.1 — O1/O2/O3

Klient sesji z [0.8.0](SESJA_OIDC.md) ma teraz adapter `POST /api/v1/me/bootstrap` i przycisk **Połącz konto z serwerem** w ekranie konta. Potwierdzenie tworzy lokalne mapowanie konta aplikacyjnego. Posiłki, cele, profil, waga i outbox pozostają lokalne; bootstrap nie importuje gościa. Odczyty API, zgoda na przypisanie gościa i synchronizacja E4 są kolejnymi etapami.

## Konfiguracja APK

Z katalogu `android/`, po otrzymaniu rzeczywistych publicznych adresów O3:

```powershell
.\gradlew.bat :app:assembleDebug "-PCALORIE_OIDC_ISSUER=$env:CALORIE_OIDC_ISSUER" "-PCALORIE_API_BASE_URL=$env:CALORIE_API_BASE_URL"
```

Issuer ma być identyczny z discovery/JWT/API. Baza API musi mieć HTTPS, host, opcjonalny port i dokładną ścieżkę `/api/v1` z opcjonalnym końcowym `/`, bez userinfo, query lub fragmentu. Nie dodajemy adresów demonstracyjnych. Domyślne oba zasoby są puste; APK działa jako gość offline. Błędna konfiguracja API wyłącza adapter, zachowując dziennik. Są to publiczne adresy, bez haseł, tokenów i sekretu klienta w Gradle/APK.

`HttpsURLConnection` używa systemowej walidacji certyfikatu i hostname. Nie zmieniamy SSLSocketFactory ani HostnameVerifier, nie śledzimy redirectów, nie zapisujemy cache odpowiedzi. Lokalny CA O3 nadal wymaga osobnego wariantu testowego z zaufaniem ograniczonym do konkretnego hosta. Nie wyłączamy TLS ani nie ufamy wszystkim CA użytkownika. Przeglądarka ma własny magazyn zaufania; jej odbiór jest oddzielny.

## Tożsamość i trwałość próby

Kontekst HTTP jest wewnętrznym, przechwyconym `ApiSession`: potwierdzone issuer/sub, lease, access token oraz wersja zapisu sesji. Nie trafia do UI, Room, DataStore, SavedStateHandle ani logów; `toString()` redaguje zawartość. Wygaśnięcie sprawdzamy przed wysyłką, z marginesem 30 sekund. Token bliski wygaśnięcia odnawiamy tylko dla przechwyconego lease; odnowienie nie może podmienić osoby.

`AccountBootstrapStore.begin()` zapisuje UUID klucza przed POST. Request nie ma body, If-Match ani X-Sync-Epoch; bearer pochodzi z przechwyconej sesji. Brak ACK, błąd sieci/parsera i restart kontrolera zachowują niedokończony klucz dla tego samego lease. Zmiana właściciela lub nowa generacja nie kontynuuje starej próby.

Przed uruchomieniem żądania i przed zastosowaniem odpowiedzi ponownie sprawdzamy kontekst i ID zadania. Decyzje są pod mutexem i transakcją Room, oczekiwanie sieciowe poza nimi. Logout, zmiana konta A→B→A, nowe logowanie lub zmiana zapisu sesji odrzucają starą odpowiedź. Pakiet będący już w transmisji może dotrzeć do serwera po wylogowaniu, ale zawiera wyłącznie wcześniej przechwycony token; jego wynik nie jest przypisany nowej lokalnej sesji. Ponowienie po odnowieniu używa nowego ticketu tej samej osoby i tego samego klucza.

HTTP200 musi mieć ścisły `BootstrapProtocol` z czterema polami. `apply()` kontroluje klucz/lease, account_id, generację i epokę, zapisując mapowanie i receipt atomowo. Zmiana kontekstu ustawia trwałe requiresRecovery; kolejny bootstrap go nie usuwa. Nie kasujemy wcześniejszych wpisów, ACK lub kolejki.

## Błędy i limity

| Wynik | Zachowanie |
|---|---|
| 401 unauthorized | Najwyżej jedno odnowienie sesji i ponowienie z tym samym kluczem i lease; dalsza odmowa wymaga logowania |
| 403 | Brak odnowienia/nowego klucza; lokalny dziennik dostępny |
| 409 sync_epoch_changed lub account_generation_changed | Najwyżej jedno `renew()` i ponowienie z nowym kluczem; zachowanie mapowania i danych; dalszy konflikt kończy próbę |
| Inny 409 | Zachowanie niedokończonego klucza i danych; bez automatycznego odtwarzania mutacji |
| 429 lub 503 | Bez automatycznej pętli; Retry-After w sekundach lub jako HTTP date. Termin zapisany w szyfrowanej sesji przeżywa jej odnowienie i restart; ponowienie przed terminem nie wysyła żądania |
| Sieć/TLS/redirect/niepoprawna odpowiedź | Bez ACK; ręczne ponowienie zachowuje klucz |
| Anulowanie zadania | Zwolnienie stanu łączenia, zachowanie danych i istniejącego klucza |

Nieznany/brakujący Retry-After oznacza 30 sekund. Opóźnienie dotyczy bieżącej sesji; logout usuwa jej rekord. Dla 429/503 również proxy HTML respektujemy nagłówek bez pobierania lub wyświetlania body. Pozostałe odpowiedzi wymagają JSON, bez kompresji, maksymalnie 64 KiB również przy braku Content-Length; błędy mają kontrolowany kształt code/message/details/request_id. Swobodny tekst serwera nie trafia do UI ani nie steruje odnowieniem. Statusy 3xx nie przekazują bearer do kolejnego adresu. Timeout połączenia/pojedynczego odczytu to 15 sekund; odbiór ma dodatkowy termin 30 sekund kontrolowany między odczytami. Brak nowych bibliotek transportu.

## Odbiór

Aktualny odczyt O3-011 / main75c4414: O3 wykonał rzeczywiste logowanie **0.8.0/3b081c4** przez Chrome/HTTPS/Keycloak oraz A/B/gość, śmierć procesu w przeglądarce, expiry/refresh/offline/logout i spóźniony refresh po logout. [Raport i overlay validation-only](../infra/integration/ANDROID_PKCE.md) wskazują zakres i hash konkretnego APK. Standardowy opcjonalny scope profile jest poprawiony w lokalnej konfiguracji O3; istniejący realm wymaga jawnego helpera, bez reinit. Zewnętrzny overlay można wykorzystać również do nowego odbioru 0.8.1, dodając do komendy Gradle `-PCALORIE_API_BASE_URL` z rzeczywistą bazą API tego samego środowiska. Nie kopiujemy credentiali/CA private key i nie instalujemy testowego APK na dzienniku właściciela. Odczyt raportu nie jest samodzielnym odbiorem HTTP 0.8.1.

[Raport 0.8.1](RAPORT_0_8_1.md) podaje wyniki testów JVM, kontrolera/Room/Keystore i aktualizacji istniejącej instalacji. Zastępcze połączenie HTTPS w JVM i synthetic JWT w testach urządzenia nie dowodzą prawdziwego TLS, podpisu JWT, przeglądarki, Keycloak ani procesu zabitego przez system.

Kolejny odbiór O1/O3 używa [istniejącego lokalnego środowiska HTTPS](../infra/integration/README.md) i narzędzi O3, z osiągalnym wspólnym issuer i ograniczonym publicznym CA. APK 0.8.1 z kontami A/B ma przejść bootstrap, lost ACK, restart procesu, expiry/refresh/logout/A→B→A i zmianę epoki. Na komputerze tego zadania O1 Docker/uv nie były dostępne w PATH; nie deklarujemy uruchomienia jego własnego środowiska na podstawie raportu O3. Domyślne APK nie wysyła żądań do fikcyjnego serwera; pełny odbiór E3/KO-31 pozostaje otwarty.

Źródła: [kontrakt O2 E3](../docs/e3/INTEGRACJA_O1.md), [HttpsURLConnection](https://developer.android.com/reference/javax/net/ssl/HttpsURLConnection), [Network Security Configuration](https://developer.android.com/privacy-and-security/security-config).
