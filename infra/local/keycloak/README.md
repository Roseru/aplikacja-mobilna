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

## Diagnostyka czasu tokenu offline — O3

`token_diagnostics.py` odczytuje wyłącznie jeden jawnie wskazany prywatny plik
z kompaktowym JWT. Przykład z katalogu głównego repozytorium:

```powershell
uv run --project backend --locked --offline python infra/local/keycloak/token_diagnostics.py --token-file C:\prywatne-dowody\access-token.txt
```

Token umieść w pliku poza checkoutem, w katalogu dostępnym tylko operatorowi.
Na Windows operator odpowiada za prywatny ACL katalogu i pliku; narzędzie nie
sprawdza ani nie zmienia DACL. Na POSIX plik musi należeć do bieżącego UID i nie
mieć żadnych uprawnień grupy/innych. Wejście musi być zwykłym plikiem z jednym
linkiem; symlinki, junctions/reparse points, katalogi i pliki wewnątrz tego
checkoutu są odrzucane. Limit **16 KiB obejmuje cały plik**, także opcjonalne
otaczające spacje/tab/CR/LF. Odczyt jest ograniczony do limitu+1 także po wzroście
pliku. W pliku ma być sam JWT: bez `Bearer`, JSON odpowiedzi lub BOM.
JWT, hasła i odpowiedzi HTTP nigdy nie są argumentami polecenia. Narzędzie nie
czyta stdin ani zmiennych środowiskowych jako źródła tokenu, nie wykonuje sieci,
retry, subprocessów ani zmian usług. Nie zapisuje raportu lub tokenu na dysku.

Każdy raport JSON ma znacznik **`UNVERIFIED_DIAGNOSTIC`**. Kod wyjścia 0 i
`status=DECODED` oznaczają wyłącznie zakończenie parsowania. Podpis, issuer,
audience, role i autentyczność danych pozostają **niezweryfikowane**; raport
nie podejmuje decyzji auth i nie wskazuje przyczyny odpowiedzi HTTP.
Również zmieniony podpis może dać te same pomiary. Stała allowlista wyjścia:

| Pole | Znaczenie |
|---|---|
| `kind`, `status`, `signature_verified` | Stały znacznik, `DECODED`, zawsze `false` |
| `iat_type`, `exp_type`, `nbf_type` | Tylko etykieta `missing/null/boolean/number/string/array/object` |
| `numeric_dates_finite` | Wymagane `iat/exp` i obecne `nbf` są skończonymi liczbami bez konwersji bool/string |
| `lifetime_seconds` | `exp-iat` |
| `age_seconds` | Jeden lokalny pomiar czasu minus `iat`; zegar operatora wpływa na wynik |
| `nbf_offset_seconds` | `nbf` minus ten sam lokalny pomiar; brak `nbf` daje `null` |
| `lifetime_exceeds_300` | Porównanie różnicy z 300; nie jest oceną ważności ani uprawnień |

Niepoprawny/brakujący typ i nieskończony wynik dają `null` w zależnym pomiarze.
Surowe czasy i wszystkie pozostałe pola/nagłówki są pomijane: także JWT, `sub`,
`iss`, `aud`, `kid`, role, credentials i response body. Błędy pliku, argumentów,
kodowania, base64url i JSON zwracają wyłącznie
`{"kind":"UNVERIFIED_DIAGNOSTIC","status":"INPUT_REJECTED"}` oraz kod 2, bez
ścieżek, wartości i treści wyjątków. Duplikaty kluczy, NaN/Infinity, przepełnienia
JSON float i niejednoznaczne kodowanie base64url są odrzucane. `--help` jest
statyczną instrukcją. Raport z prawdziwego tokenu nadal traktuj jako prywatny;
do publicznego PR wystarczą syntetyczne testy i zbiorcze metryki.

### Powtarzalny przypadek graniczny i granice wniosku

Sprawdzono oficjalne, przypięte źródło **Keycloak 26.8.0**:
[TokenManager.initToken/getTokenExpiration](https://github.com/keycloak/keycloak/blob/26.8.0/services/src/main/java/org/keycloak/protocol/oidc/TokenManager.java#L1011-L1088)
ustawia `iat` przez `issuedNow()`, a później oblicza `exp` z osobnego odczytu
milisekund, dodaje lifespan i przelicza na sekundy. Samo
[JsonWebToken.issuedNow](https://github.com/keycloak/keycloak/blob/26.8.0/core/src/main/java/org/keycloak/representations/JsonWebToken.java#L136-L138)
odczytuje bieżące sekundy. Jeśli pomiędzy odczytami przejdzie sekunda, przy
lifespan 300 i bez wcześniejszego ograniczenia przez koniec sesji możliwe jest
`exp-iat=301`. To wniosek o możliwości mechanizmu z kodu producenta.

Test `test_two_clock_reads_component_reproducer_with_real_signature_and_strict_verifier`
w [test_keycloak_diagnostics.py](../../integration/tests/test_keycloak_diagnostics.py)
ustawia pierwszy odczyt na 1000999 ms, drugi na 1000999 lub 1001000 ms. Otrzymuje
odpowiednio `iat=1000`, `exp=1300/1301`, podpisuje syntetyczny token RS256,
niezależnie potwierdza podpis i przepuszcza go przez istniejący `OIDCVerifier`
z syntetycznym JWKS w MockTransport. Dla tego samego issuer/audience/roli/zegara
300 s przechodzi, a 301 s daje 401 mimo `SKEW=60`. Limit backendu 300 i realm pozostają
bez zmian. Test nie uruchamia Keycloak i nie wykonuje rzeczywistego PKCE.

```powershell
uv run --project backend --locked --offline python -m pytest infra/integration/tests/test_keycloak_diagnostics.py -q
```

Testy korzystają wyłącznie z syntetycznych plików w standardowym prywatnym temp
poza checkoutem; w Windows nie ustawiaj `--basetemp` wewnątrz repozytorium.
Pokrywają formaty, typy/granice, neutralne błędy, canary prywatności, limit przed
parserem, wzrost pliku, odczyt tylko wskazanego pliku i brak sieci/subprocessów.

Historyczny [pierwszy main CI po PR171](https://github.com/Roseru/aplikacja-mobilna/actions/runs/40163266738/job/121079122750)
miał 27 PASS / 1 FAIL: pierwszy bootstrap konta właściciela w przypadku `[b]`
testu ACL zdjęcia dostał 401 przed uploadem i użyciem tokenu konta B.
[Jedyny retry](https://github.com/Roseru/aplikacja-mobilna/actions/runs/40163266738/job/121083093772)
przeszedł 28/0. **Przyczyna tamtego 401
pozostaje nieudowodniona**; tokenów/claimów nie publikowano i brak dowodu
wiążącego ten przypadek z konkretnym mechanizmem odmowy.
Nieznany `kid` po poprawnym JWKS, błędny podpis lub inne odrzucone claims także
mogą dawać 401; transport JWKS daje 503, a brak wymaganej roli 403. Ani retry,
ani reproducer nie dowodzi źródła historycznego błędu ani jego naprawy.
[Przekazanie do O2](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6393726228)
pozostaje osobnym etapem. Automatyczna integracja z `tokens()/boot`, harness E3
i ewentualna mitigacja producenta wymagają osobnego uzgodnienia i dowodów.
To narzędzie diagnostyczne i dowód komponentowy offline, bez odbioru nowego APK,
Room/fence, live E4 lub całego projektu.
