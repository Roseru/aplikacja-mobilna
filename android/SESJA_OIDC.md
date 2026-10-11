# Sesja Androida 0.8.0 — przekazanie O1/O3

Aktualizacja 0.8.1 łączy ten klient z [bootstrapem HTTP](BOOTSTRAP_HTTP.md). Poniższy opis dokumentuje etap 0.8.0; jego brak HTTP był ówczesnym stanem. Nowy [raport O3](../infra/integration/ANDROID_PKCE.md) potwierdza rzeczywiste próby sesji APK 0.8.0/3b081c4 oraz udostępnia zewnętrzny overlay ograniczonego CA. Odczytano go na main75c4414; nie zastępuje odbioru nowego HTTP 0.8.1. Synchronizacja oraz import gościa nie są wykonywane przez bootstrap.

Implementacja klienta: AppAuth 0.11.1, systemowa przeglądarka, Authorization Code + PKCE S256, publiczny `calorie-android`, zakres `openid profile` i jawne `prompt=login`. Nie ma sekretu klienta ani formularza haseł w aplikacji. [Raport lokalny](RAPORT_0_8_0.md) rozdziela testy transportu zastępczego od przyszłego odbioru prawdziwego APK/Keycloak.

## Konfiguracja publicznego środowiska

Z katalogu `android/`:

```powershell
.\gradlew.bat :app:assembleDebug "-PCALORIE_OIDC_ISSUER=$env:CALORIE_OIDC_ISSUER"
```

Zmienna ma zawierać rzeczywisty, osiągalny z telefonu/emulatora issuer HTTPS środowiska O3, identyczny z discovery i konfiguracją API. Domyślnie jest pusty: logowanie jest wtedy wyłączone, a dziennik działa offline. Nie wpisujemy adresu demonstracyjnego ani tokenów. Wartość trafia do publicznego zasobu `oidc_issuer`, nie do sekretów. Konfiguracja jest przypięta do APK; jej zmiana nie przepisuje tożsamości i historii.

Dokładne allowlisty redirectów O3 pozostają:

- `pl.roseru.kalorie:/oauth2redirect`
- `pl.roseru.kalorie.validation:/oauth2redirect`

Android nie egzekwuje path filtra bez hosta. `OAuthRedirectActivity` ma filtr samego schematu, ale przed przekazaniem do AppAuth sprawdza dokładną postać scheme:/oauth2redirect, brak hosta/fragmentu, unikalność parametrów, state i rozłączność code/error. Opcjonalny `iss` musi odpowiadać konfiguracji. Kontroler dodatkowo porównuje odpowiedź z utrwalonym requestem, state, nonce, redirectem, klientem i przechwyconą generacją właściciela. Callback nie jest sam w sobie potwierdzeniem tożsamości.

Discovery wymaga dokładnego issuer; endpointy autoryzacji i tokenów muszą mieć HTTPS, ten sam host/port i znajdować się pod ścieżką realmu. To celowe ograniczenie klienta Keycloak. TLS i hostname pozostają weryfikowane, redirect HTTP nie jest śledzony. Aplikacja nie instaluje CA i nie ufa dowolnym certyfikatom użytkownika.

Lokalna instalacja O3 używa prywatnego CA. **Ten PR nie dostarcza jeszcze wariantu z ograniczonym zaufaniem temu CA ani próby prawdziwej przeglądarki/Keycloak.** Kolejny odbiór dodaje publiczny CA tylko dla konkretnego hosta i tylko do wydzielonego wariantu testowego, zgodnie z [Network Security Configuration](https://developer.android.com/privacy-and-security/security-config). Nie wyłączamy kontroli TLS, nie zmieniamy issuer tylko po stronie emulatora i nie kopiujemy klucza CA/credentials do APK lub Git. Instrukcja środowiska: [O3](../infra/integration/README.md).

## Zapis sesji i właściciel danych

`SessionVault` przechowuje jeden atomowy rekord AES/GCM, z losowym IV i kluczem Android Keystore, w `noBackupFilesDir`. Rekord zawiera AuthState i ewentualny request PKCE. Własny kod nie umieszcza tokenów/verifiera w Room, DataStore, SavedStateHandle ani logach. Biblioteka zarządza własnym prywatnym stanem aktywności przepływu. Backup/transfer aplikacji są wyłączone także jawnymi regułami Androida 12+.

Wymiana kodu odbywa się dopiero po sprawdzeniu utrwalonego requestu. Próba jest zużywana przed wymianą: po utracie odpowiedzi z tokenami wymagane jest nowe logowanie, a kod nie jest odtwarzany. TTL niezakończonej próby to 10 minut. Odtworzenie procesu zachowuje poprawną próbę; obca generacja, przekroczony czas, replay i anulowana próba nie zmieniają konta.

AppAuth najpierw waliduje code-flow ID token otrzymany bezpośrednio przez TLS z endpointu. Własne kontrole wymagają dodatkowo RS256, dokładnego issuer/sub, aud zawierającego calorie-android, poprawnego azp dla wielu odbiorców, nonce, exp i całkowitych iat/exp. Lokalnie korzystamy z dopuszczonej w code flow walidacji serwera TLS zamiast dodatkowego sprawdzania podpisu ID tokenu; nie przyjmujemy JWT dostarczonego przez ekran, deeplink lub użytkownika jako uwierzytelnienia. API nadal niezależnie weryfikuje podpis/aud/role access tokenu.

Potwierdzone `(issuer, sub)` wybiera właściciela bez przenoszenia danych gościa. Nowa generacja odbudowuje repozytorium i DiaryViewModel, kasuje poprzedni ViewModelStore oraz stan nawigacji/formularzy Compose. Lease chroni zapis w Room także podczas zmiany A→B→A. Mutex serializuje decyzje, ale nie blokuje wylogowania podczas oczekiwania na sieć. Spóźnione logowanie/refresh sprawdzają również identyfikator operacji.

Wygaśnięcie, brak sieci, uszkodzenie szyfrogramu lub utrata klucza zachowują aktywne konto lokalne oraz jego dziennik. Odnowienie nie może zmienić issuer/sub. Wylogowanie usuwa stan sesji i klucz, wybiera gościa, zachowuje oba dzienniki. To **wylogowanie lokalne**; sesja SSO w przeglądarce pozostaje. Kolejne logowanie żąda ponownego zalogowania.

## Następny odbiór

1. Uruchomić prawdziwe lokalne HTTPS/API/Keycloak O3 na osiągalnym wspólnym issuer, skonfigurować ograniczony publiczny CA dla wariantu testowego.
2. Wykonać rzeczywistym APK: przeglądarka/callback, konta A/B/gość, anulowanie, restart procesu, wygaśnięcie i odnowienie, logout oraz spóźniona odpowiedź. Nie zastępować tej próby wynikami osobnego harnessu Python lub fixture.
3. Dodać przechwycony, niezmienny kontekst token+identity+lease dla HTTP i trwały bootstrap E3. Brak body POST/me/bootstrap; istniejące AccountBootstrapStore/BootstrapProtocol pozostają podstawą. Zapisy i import gościa nadal wymagają odrębnego adaptera E4 i zgody.

Nie ma jeszcze HTTP bootstrapu, odczytów API, WorkManager ani wysyłania lokalnego outbox. Nie deklarujemy ukończenia sesji z integracją E3, KO-31 lub całego E5.

Źródła: [AppAuth](https://github.com/openid/AppAuth-Android), [walidacja ID tokenu 0.11.1](https://github.com/openid/AppAuth-Android/blob/0.11.1/library/java/net/openid/appauth/IdToken.java), [Android Keystore](https://developer.android.com/privacy-and-security/keystore), [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252).
