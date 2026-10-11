# Izolowany Keycloak i PKCE E3 - osoba 2

Dystrybucja `26.8.0` pochodzi z oficjalnego wydania, jest przypięta wraz z SHA-256 w `distribution.lock.json` i wymaga JDK 25. Harness kopiuje dystrybucję do nowego katalogu stanu, generuje hasła A/B, importuje realm `calorie-dev` i uruchamia własny proces na `127.0.0.1:18080`. Tryb `start-dev` korzysta wyłącznie z własnej testowej bazy H2; nie łączy się z bazą aplikacji. PostgreSQL 17 dla testów backendu jest osobną usługą. Produkcyjny Keycloak, jego osobna baza PostgreSQL, HTTPS, kopie i osiągalność dla emulatora pozostają po stronie O3.

Przykładowe polecenia z głównego katalogu repozytorium; `JAVA_HOME` ma wskazywać rzeczywisty JDK 25:

```powershell
uv run --project backend --locked python infra/local/keycloak/harness.py download --home .tools/keycloak-distribution
uv run --project backend --locked python infra/local/keycloak/harness.py start --home .tools/keycloak-distribution/keycloak-26.8.0 --java-home $env:JAVA_HOME --state .tools/e3-keycloak
$env:E3_KEYCLOAK_ISSUER = 'http://127.0.0.1:18080/realms/calorie-dev'
$env:E3_KEYCLOAK_CREDENTIALS = (Resolve-Path .tools/e3-keycloak/credentials.json).Path
# TEST_DATABASE_URL: własna PostgreSQL 17 *_test, z rolami init-db.sh.
uv run --project backend --locked python -m pytest backend/tests/keycloak -q
uv run --project backend --locked python infra/local/keycloak/harness.py stop --state .tools/e3-keycloak
```

`harness.py test` wykonuje start, testy oraz zatrzymanie własnego procesu w `finally`. Brak usługi, credentiali lub dedykowanej PostgreSQL kończy test błędem. Job `keycloak-pkce` jest obowiązkową zależnością `ci-required`; brak/skipped/cancelled nie daje zielonego wyniku. Katalog stanu musi być nowy i znajduje się poza Git. Po zatrzymaniu można usunąć wyłącznie własny wskazany katalog; pozostawienie go zachowuje lokalne dowody, ale także efemeryczne hasła. Nigdy nie publikuj plików `credentials.json`, importu runtime ani `service.log`.

Publiczny klient `calorie-android` dopuszcza dokładne callbacki przekazane przez O1:

- `pl.roseru.kalorie:/oauth2redirect`
- `pl.roseru.kalorie.validation:/oauth2redirect`

Oddzielny publiczny klient `calorie-pkce-harness` dopuszcza tylko `http://127.0.0.1:8765/callback`. Test symuluje user-agent przez rzeczywistą stronę logowania/cookies i przechwytuje redirect bez uruchamiania callback servera. Używa profilu Safari: Keycloak 26.8 nadaje loopbackowi status secure context i emituje Secure cookies, których standardowy CookieJar HTTPX nie wysyła przez HTTP; oficjalny [SecureContextResolver](https://github.com/keycloak/keycloak/blob/26.8.0/services/src/main/java/org/keycloak/utils/SecureContextResolver.java) obsługuje profil Safari z cookies dopuszczalnymi w takim izolowanym kontekście. To symulacja user-agent, bez zmiany zabezpieczeń realm lub backendu. Weryfikuje `state`, `nonce`, code exchange z S256, błędny verifier, ponowne użycie code oraz odmowę password grant i niezatwierdzonych redirectów. Token ma TTL 300 s, audience `calorie-api` tylko w access tokenie i role `resource_access.calorie-api.roles`. Konta A/B mają rolę `user`; catalog_moderator/admin nadal nie omijają własności danych prywatnych. Dodatkowy testowy klient `calorie-pkce-android-only` emituje rzeczywisty access token wyłącznie dla audience Android, który backend odrzuca.

Klienci mobilny i harness mają domyślne client scopes `basic` i `roles`. Od Keycloak 25 claim `sub` access tokenu pochodzi z mappera Subject w `basic`; scope `roles` sam go nie dodaje. Testowy klient z audience Android ma `basic`, ale nie ma `roles` ani audience API. Nie wyłączaj walidacji `sub`, aby obejść brak mappera.

Issuer hosta to dokładnie `http://127.0.0.1:18080/realms/calorie-dev`, JWKS: `http://127.0.0.1:18080/realms/calorie-dev/protocol/openid-connect/certs`. Backendowe ustawienia `ENVIRONMENT=test`, `OIDC_ALLOW_LOCAL_HTTP=true`, `OIDC_ISSUER`, `OIDC_JWKS_URL` dopuszczają ten izolowany loopback. Domyślna produkcja nie dopuszcza HTTP. Publiczny issuer jest niezależny od zaufanego wewnętrznego adresu JWKS; claim `iss` musi pozostać dokładnie zgodny. Ten loopback nie jest osiągalnym adresem z emulatora/kontenera; O3 musi dostarczyć jeden osiągalny publiczny issuer i HTTPS. Test nie dowodzi gotowości handlera ani sesji APK.

Weryfikator backendu dopuszcza wyłącznie RS256 i claim `typ=Bearer`, sprawdza dokładny issuer, audience, niepusty subject i skończone numeryczne `iat`/`exp` oraz opcjonalne `nbf` (Keycloak nie musi emitować tego claimu). Skew wynosi 60 s, lifetime maksymalnie 300 s. JWKS ma limit 64 KiB / 32 klucze / 3 s całkowitego czasu, cache najwyżej 900 s oraz 5 s cooldownu i jedną współdzieloną blokadę odświeżania. Nieznane `kid` nie są zapamiętywane. Świeży klucz działa przy awarii dostawcy; po TTL nie zostaje użyty. Brak niezbędnego dostawcy daje 503 z Retry-After, brak klucza po udanym fetchu 401. Backend nie pobiera URL z JWT i nie utrzymuje transakcji DB podczas fetchu.

Źródła: [Keycloak OIDC](https://www.keycloak.org/securing-apps/oidc-layers), [Keycloak config](https://www.keycloak.org/server/all-config), [PyJWT API](https://pyjwt.readthedocs.io/en/stable/api.html), [oficjalne wydanie](https://github.com/keycloak/keycloak/releases/tag/26.8.0).
