# Odbiór APK 0.8.0 z lokalnym HTTPS — O3

11 października 2026 O3 wykonał rzeczywiste logowanie APK przez Chrome i lokalny
Keycloak. Kod O1 pochodził z `3b081c4a237c25183d6ec5d81317f9bd117160ea`
([draft PR #26](https://github.com/Roseru/aplikacja-mobilna/pull/26)); checkout był
odłączony od gałęzi, a jego śledzone pliki pozostały niezmienione. Narzędzia O3
powstały osobno z main `2a56682e2c4ee6c0456370af6fc64dcd87ba8979`.
O3 nie scalał ani nie aktualizował gałęzi, opisu, statusu lub kodu PR O1.

## Usunięta niezgodność środowiska

O1 żąda `openid profile`. Lokalny klient `calorie-android` miał jedynie domyślne
`basic` i `roles`, bez opcjonalnego `profile`. Pierwsze próby prawdziwego APK
zakończyły się odmową Keycloak `invalid_request / Invalid scopes: openid profile`.
Nie był to błąd TLS ani dowód uszkodzenia kontrolera Androida.

Nowe inicjalizacje O3 przypisują istniejący standardowy `profile` jako zakres
**opcjonalny wyłącznie klienta Androida**. Harness O2 pozostaje niezmieniony.
Próba HTTPS O3 wysyła teraz taki sam zakres jak APK dla obu redirectów Androida.
Już utworzonego realmu Keycloak nie nadpisuje podczas ponownego importu. Dlatego
istniejącą lokalną instalację aktualizuje się jawnie, bez ponownej inicjalizacji:

```powershell
uv run --project backend --locked python infra/integration/android_scope.py --state .tools/local-integration
```

Skrypt weryfikuje lokalny adres, publiczny CA, klienta publicznego, Code+S256,
wyłączone implicit/password grant i dokładne dwa redirecty. Przypisuje tylko
istniejący opcjonalny zakres przez administracyjne API; sprawdza zachowanie
reszty klienta i domyślnych zakresów. Ponowne wykonanie zwraca `changed=false`.
Nie wypisuje credentiali/tokenów, nie zmienia kont, ról, issuer, TTL ani kluczy.

## Wariant APK bez edycji źródeł O1

Wymagany jest działający zestaw [O3](README.md) z adresem LAN osiągalnym z urządzenia.
Nie zamieniaj issuer na `10.0.2.2` po jednej stronie. Użyj osobnego testowego AVD
i osobnego odłączonego checkoutu wskazanego commita O1. Polecenia przygotowania
wykonaj w checkoutcie O3 z tymi narzędziami, wskazując **istniejący** prywatny stan:

```powershell
$State = (Resolve-Path .tools/local-integration).Path
$Overlay = Join-Path $env:TEMP "calorie-o3-validation-overlay"
uv run --project backend --locked python infra/integration/android_overlay.py --state "$State" --output "$Overlay"
$Issuer = (Get-Content (Join-Path $Overlay overlay.json) -Raw | ConvertFrom-Json).issuer
```

Skrypt odmówi nadpisania istniejącego overlay. W katalogu `android/` odłączonego
checkoutu O1, w tej samej sesji PowerShell:

```powershell
.\gradlew.bat :app:assembleValidation :app:testDebugUnitTest :app:lintValidation --init-script "$Overlay/init.gradle" "-PCALORIE_OIDC_ISSUER=$Issuer"
```

Zewnętrzny init script dodaje zasoby i manifest tylko do istniejącego source set
`validation`. Wynik ma applicationId `pl.roseru.kalorie.validation`, dokładny
callback `pl.roseru.kalorie.validation:/oauth2redirect` oraz publiczny issuer.
Domyślne `debug` i `release` nie dostają CA nawet przy podaniu tego init scriptu.

Konfiguracja zaufania w APK dopuszcza jeden publiczny CA wyłącznie dla dokładnego
IPv4 z prywatnego stanu, bez subdomen. Pozostałe hosty mają systemowe CA.
Cleartext jest wyłączony; nie ma zaufania `user`, `debug-overrides`, trust-all,
klucza CA, credentiali ani tokenów. Network Security Configuration ogranicza host,
nie port; klient O1 dodatkowo sprawdza HTTPS, wspólny host/port endpointów i issuer.
Skrypt przyjmuje tylko loopback/RFC1918 i dokładnie jeden publiczny certyfikat CA.

Chrome ma własny magazyn zaufania. W odbiorze publiczny CA zainstalowano wyłącznie
w magazynie **użytkownika nowego testowego AVD**, dzięki czemu Chrome pokazał
bezpieczne połączenie. APK nadal nie ufa całemu magazynowi użytkownika.
Nie zmieniano zaufania Windows ani systemowych CA urządzenia, nie obchodzono
ostrzeżeń TLS. Ten publiczny certyfikat i APK pozostają poza Git; ich hash jest
identyfikatorem konkretnego lokalnego odbioru, nie pinem wszystkich instalacji.

## Wykonane próby

Własny nowy AVD: API35 Google APIs x86_64, 1080×2400, density420, font1.
Oryginalny emulator i checkout O1 nie były używane do tych prób. Test używał
wyłącznie istniejących technicznych kont A/B z lokalnego stanu O3.

| Próba rzeczywistego APK | Wynik |
|---|---|
| Discovery, Chrome, Code+PKCE i dokładny callback | A i B przyjęte, sesja dostępna; Chrome potwierdził HTTPS |
| Restart aplikacji po loginie A | A i jego lokalny posiłek/outbox zachowane |
| Zabicie procesu podczas otwartej przeglądarki, następnie login B | Potwierdzono brak procesu przed wysłaniem formularza; callback uruchomił nowy proces, wybrał B i pusty dziennik B |
| Odnowienie sesji B | Sesja odnowiona, bez zmiany właściciela |
| Lokalny logout B → gość | Wybrany gość; dane kont pozostały |
| Posiłek gościa → login A | A odzyskał własny dziennik; gość zachował swój, bez automatycznego importu |
| Zamknięcie custom tab przed loginem | Komunikat anulowania, A i jego sesja zachowane |
| Naturalne wygaśnięcie TTL300 i ponowne otwarcie aplikacji | Sesja wymaga odnowienia, właściciel/dziennik pozostają |
| Odnowienie bez sieci | Potwierdzone wyłączone Wi-Fi i brak aktywnej sieci; błąd odnowienia zachował A i dane |
| Powrót sieci i rzeczywisty refresh A | Sesja dostępna, komunikat odnowienia, właściciel zachowany |
| Opóźniona poprawna odpowiedź refresh po logout A | HTTP200 z prawdziwego Keycloak wstrzymano na7,9s; po potwierdzeniu logout odpowiedź przepuszczono, gość pozostał aktywny bez sesji A |
| Debug z tym samym issuer i init script, bez overlay validation | Brak zasobów CA/atrybutu NSC; discovery odrzucone z błędem ścieżki certyfikatu, gość pozostaje |

A zapisał przez UI banana120g/107kcal i jedną operację outbox. B pozostał pusty.
Gość zapisał przez UI baton40g/164kcal i jedną operację outbox. Po powrocie do A
generacja wynosiła5. Po dodatkowym loginie A i logout podczas opóźnionego refresh:
aktywny gość, generacja7, A1/1, B0/0, gość1/1 (posiłki/outbox).
Porównano całe wiersze siedmiu tabel `meals`, `meal_items`, `profiles`, `goals`,
`weights`, `diary_days`, `outbox`, osobno dla wszystkich trzech właścicieli:
przełączenie B zachowało A i gościa, powrót A/anulowanie/expiry/offline/refresh
zachowały wszystkie zapisane zbiory. `foreign_key_check` pusty.
To są kopie bazy **wraz z WAL** z nowego AVD, bez zapisu bezpośrednio do Room.
Jedną niepełną kopię bez WAL odrzucono jako nieważny dowód; ponowny pełny odczyt
potwierdził zachowanie danych. Kopie i ekranowe dowody pozostały prywatne.

Spóźniony refresh sprawdzono przez krótkotrwały proxy TLS na loopback gospodarza,
z istniejącym certyfikatem serwera i zaufanym CA także do upstreamu Keycloak.
Przekierowanie obejmowało tylko UID validation w nowym AVD; Chrome i wspólny serwer
pozostały bez zmian. Proxy nie zapisywał tokenów/credentiali i zatrzymał w pamięci
rzeczywistą odpowiedź200 dla refresh_token. Potwierdzono logout przez UI, zwolniono
odpowiedź przed upływem timeoutu klienta, następnie porównano DB+WAL: gość/generacja7
oraz wszystkie siedem zbiorów A/B/gościa zachowane. Usunięto własne przekierowanie,
adb reverse i proces proxy po próbie. Klucze certyfikatu nie opuściły prywatnego stanu.

Oddzielna próba minimalizacji i przywrócenia starej karty Chrome po anulowaniu
nie potwierdziła dostarczenia callbacku z poprawnym kodem; nie zaliczamy jej jako
spóźnionego code exchange. Fencing podczas równoczesnego A→B→A/code exchange
pozostaje objęty fixture O1, bez przypisywania mu wyniku próby refresh po logout.

## Identyfikacja i granice

- APK acceptance: `0.8.0`, versionCode11, Room6, applicationId validation,
  SHA256 `8ec8feaf56892deaf828a96ecafbb75138b6730c2c509d2baeea317cb16dd623`.
- Publiczny CA tej instalacji, SHA256 PEM:
  `01f120ef25f091a6413a535dcaa5e333575a8d08a016503c47998333eef3a6f6`.
- O3: build validation/debug PASS,73 JVM PASS; lint validation0błędów/40ostrzeżeń.
  To inny wariant niż debug lint28ostrzeżeń raportowany przez O1.
- Dodatkowa pełna regresja API35 z overlay i pustym issuer, przy potwierdzonym braku
  sieci: **końcowe65/65 PASS**, bez pominięć. Pierwszy pełny przebieg miał64/65:
  `DiaryFlowTest.choosePartialRationAndRestoreSelectionBeforeSaving`, linia100,
  nie znalazł `ration-grams-demo-a-crackers` po kliknięciu checkboxa.
  Bez zmian źródeł/testów ten przypadek przeszedł osobno1/1, następnie pełny65/65.
  Zachowano wszystkie trzy raporty; nie sumujemy ponowień ani nie ukrywamy odmowy.
  O1 otrzymuje obserwację do stabilizacji. Testowa aplikacja regression nie ma
  skonfigurowanego issuer; jej wynik nie zastępuje powyższej próby prawdziwego loginu.
- Narzędzia O3:21 testów infrastruktury PASS; Ruff lint/format PASS.
  Końcowe zdalne CI własnego PR i main potwierdza się oddzielnie w PR.

APK jest lokalnym artefaktem konkretnego niescalonego commita O1, z publicznym
issuer tej instalacji. Nie zastępuje domyślnego APK main z CI ani produkcyjnego wydania.
Nie ma HTTP/bootstrapu, odczytów API, WorkManager ani wysyłania outbox; nie odebrano
KO-31, pełnego E3/E5, publicznego wdrożenia ani restore/RPO/RTO. O1 może niezależnie
odebrać własny PR i rozpocząć następny adapter według istniejących kontraktów.
Nie deklarujemy wszystkich możliwych wyścigów sieciowych na podstawie tej próby.

Źródła mechanizmów: [Android Network Security Configuration](https://developer.android.com/privacy-and-security/security-config),
[Keycloak client scopes](https://www.keycloak.org/docs/latest/server_admin/#_client_scopes).
