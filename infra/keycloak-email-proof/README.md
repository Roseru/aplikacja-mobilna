# Rejestracja z dowodem posiadania adresu e-mail

Osobny provider dla **Keycloak 26.8.1**, zgodnego z przypiętym obrazem
`infra/integration/Keycloak.Dockerfile`. Nie jest zainstalowany automatycznie
i nie zmienia istniejących realmów, danych, kluczy, klientów ani usług.

Standardowy formularz sprawdza unikalność przed `VERIFY_EMAIL`. Zmiana tekstu
`emailExistsMessage` nie zamyka tej ścieżki. Ten provider dodaje obowiązkowy
etap potwierdzenia przed jakimkolwiek wyszukiwaniem lub tworzeniem użytkownika:

1. Dla każdego poprawnego składniowo adresu wykonuje tę samą operację SMTP,
   bez `session.users()`. Publiczna odpowiedź i limit wysyłki nie zależą od
   istnienia konta. Wymagany jest ten sam oryginalny profil przeglądarki.
2. Wiadomość zawiera podpisany token akcji i standardowy adres odświeżenia
   wykonania flow rejestracji, bez jednorazowego formowego `session_code`.
   GET pokazuje formularz potwierdzenia; dopiero jego jawny POST
   sprawdza RS256, podpis, issuer/audience, czas, typ, klienta, root session,
   tab, execution oraz bieżący challenge. Token nie ma `sub` i nie tworzy
   tymczasowego użytkownika. Jednorazowość korzysta z atomowego
   `SingleUseObjectProvider.remove`, także przy równoległych żądaniach.
3. Dopiero po dowodzie działa standardowa walidacja profilu, unikalności i
   hasła. Guard blokuje bezpośredni POST, zmianę adresu, inny username oraz
   wielokrotne wartości pól; przed stock walidacją ustawia dokładnie jeden
   potwierdzony email/username. Brak dowodu nigdy nie wywołuje tej walidacji.
4. Stock `RegistrationUserCreation` nadal tworzy konto i nadaje domyślne role.
   Provider nie dodaje ról ani nie ustawia lub zmienia hasła istniejącego konta.
   Wskazany adres otrzymuje `emailVerified` dopiero po stockowym utworzeniu.
   Po dowodzie posiadania skrzynki jej właściciel może zobaczyć stockową
   informację o własnym istniejącym koncie i przejść do loginu/resetu.

Domyślny login i reset haseł pozostają standardowymi flow Keycloak.
Unikalność email pozostaje włączona (`duplicateEmailsAllowed=false`),
`registrationEmailAsUsername=true` i `loginWithEmailAllowed=true` są wymagane.
Guard odmawia, jeśli te ustawienia nie odpowiadają kontraktowi.
Link wygasa po 300 s; kolejną wiadomość na ten adres można zamówić po 60 s.
Nie ma logowania linków, tokenów, haseł ani wyjątków transportu przez moduł.
W konfiguracji serwera nadal należy wyłączyć logowanie pełnych URL zapytań.

## Budowanie

Z katalogu repozytorium, na JDK 21+ i Gradle 8.11.1:

```powershell
gradle -p infra/keycloak-email-proof test jar --no-daemon --console=plain
```

Można użyć istniejącej zweryfikowanej dystrybucji wrappera Androida zamiast
systemowego `gradle`. Moduł nie uruchamia Gradle Androida. Ma osobny build,
limit Gradle 384 MiB i pojedynczy worker testów 256 MiB. Na długich ścieżkach
Windows można dodać `-PcalorieBuildDir=C:\prywatny-krotki-build` oraz
`--project-cache-dir C:\prywatny-krotki-cache`. Nie używaj katalogu usług.

JAR: `build/libs/calorie-keycloak-email-proof-1.0.0.jar` (albo wybrany buildDir).
Zależności Keycloak są `compileOnly`; JAR nie pakuje serwera lub bibliotek.
Istniejący job `android-build` wykonuje testy/JAR tego modułu oraz testy odmów
harnessu i zachowuje raporty/JAR jako oddzielny artefakt. Nie dodano joba
ani wyjątku od `ci-required`; wynik zdalnego CI wymaga własnego odbioru.

## Powtarzalny odbiór opt-in

`live_acceptance.py` używa wyłącznie biblioteki standardowej Python 3.12+ oraz
lokalnego silnika Docker. Wymaga jawnej flagi i NOWEGO prywatnego katalogu
poza repozytorium. Nie przyjmuje adresu istniejącego serwera/realm ani danych
logowania. Sam tworzy syntetyczne konta, hasła, nowy realm, sieć i oznaczone
kontenery Keycloak26.8.1/Mailpit z przypiętych obrazów. Porty są publikowane
wyłącznie na `127.0.0.1`; nie wysyła poczty poza własny sink i nie używa proxy
ze zmiennych środowiska. Limity pamięci kontenerów to 768/64 MiB, heap384 MiB.

Po zbudowaniu JAR, z katalogu repozytorium:

```powershell
$TrialState = Join-Path $env:TEMP ('calorie-email-proof-' + [guid]::NewGuid())
python infra/keycloak-email-proof/live_acceptance.py --run-isolated-http-h2 --state $TrialState --jar infra/keycloak-email-proof/build/libs/calorie-keycloak-email-proof-1.0.0.jar
```

Próba trwa kilka minut, w tym rzeczywiste 300 s ważności linku. Sprawdza
neutralną inicjację, proof, tampering, jednorazowość, rejestrację, podstawową rolę,
Code/S256, podpis/nonce/issuer/audience, reset, prawdziwą awarię SMTP i expiry.
Domyślna sekwencja nie jest testem równoczesnego finalnego tworzenia konta.
Końcowe raporty mają zakres `ISOLATED_H2_HTTP_FUNCTIONAL_ONLY`, nigdy odbiór
produkcji/PG/TLS. Kontenery są zatrzymywane po sprawdzeniu właściciela obu;
ich dane i prywatne dowody pozostają do przeglądu. Nie publikuj katalogu stanu:
zawiera rzeczywiste efemeryczne tokeny, cookies, pocztę i hasła tej próby.

Testy odmów przed operacjami i dostępu do oracles bez Docker:

```powershell
python -m unittest discover -s infra/keycloak-email-proof/tests -p test_live_acceptance.py -v
```

## Izolowany odbiór i konfiguracja

Najpierw przegląd kodu i rzeczywista próba na przypiętym **26.8.1**, w nowym
realm i osobnym stanie. Unit testy nie są odbiorem strony, SMTP, bazy lub PKCE.

Skopiuj JAR wyłącznie do `providers/` własnej zatrzymanej dystrybucji i wykonaj
jej zwykły build/restart zgodny ze sposobem uruchomienia. Nie dodawaj go do
żywej historycznej instalacji i nie podmieniaj współdzielonego obrazu.
`realm-flow.json` jest fragmentem konfiguracji do złożenia z NOWYM realmem,
nie poleceniem importu/nadpisania istniejącej bazy. Zawiera dwa nowe flow,
ich binding, theme i flagi rejestracji. Standardowe flow browser/reset
i dokładne klienty Code/S256/redirectUri/audience pozostają bez zmian.
Domyślna rola API ma być wyłącznie `calorie-api/user`, bez kompozytu do
`admin`, `catalog_moderator` lub `realm-management`; moduł nie zmienia grafu ról.
Nie podłączaj samego pierwszego authenticatora bez guarded form action.

W nowym realm sprawdź i zachowaj rzeczywiste dowody:

- Istniejący i nowy adres: identyczny publiczny krok przed proof oraz po jednym
  jednakowym typie wiadomości; liczba użytkowników nie zmienia się przed proof.
- Bez linku, direct POST, zmieniony email/username, podwójne pola, obcy tab,
  klient lub sesja, zły podpis, expiry i replay nie tworzą konta i nie ujawniają
  informacji o innym użytkowniku. GET/HEAD skanera niczego nie zużywa.
- Nowy adres po jawnej weryfikacji: jedno konto z dokładnym adresem, poprawne
  hasło, `emailVerified=true`, wyłącznie podstawowe role; dwa równoczesne
  końcowe POST nie tworzą dwóch kont.
- Istniejący adres: bez nowego konta, zmiany hasła, ról lub subject. Po dowodzie
  można skorzystać ze standardowego loginu i resetu. Stare hasło po skutecznym
  resecie nie działa; subject i dane aplikacyjne są zachowane.
- Rzeczywisty Code/S256, audience i TTL, bootstrap/PULL oraz odmowa password
  grant są sprawdzane normalnym istniejącym harness/klientem.
- Niedostępny SMTP daje jawny błąd dostawy bez utworzenia użytkownika; po
  wznowieniu i okresie limitu działa nowe świadome wysłanie.

**Stan dostawy źródłowej:** testy komponentu są osobne od powyższego live
odbioru. Nie kwalifikują publicznej produkcji ani nie zamykają historycznego P2.
31.10.2026: lokalny JUnit15/15 oraz rzeczywisty powtarzalny odbiór nowego
H2/HTTP/SMTP/PKCE zakończono pozytywnie, łącznie z faktycznym 300 s expiry.
Podpis i jednorazowość sprawdzono także negatywnie. Hash JAR i prywatne
raw/receipty zachowano poza Git; nie podmieniono istniejącego środowiska.
Osobna próba dwóch niezależnie potwierdzonych flow tego samego adresu,
po rzeczywistym 61 s cooldown, dała nakładające się końcowe żądania HTTP:
jedno konto, odpowiedzi 302/400 i ukończony PKCE zwycięskiego flow. Równoległe
potwierdzenie tego samego formularza nie utworzyło konta. Nie przypisujemy tym
obserwacjom dwóch wejść do `consume` ani jednoczesnego wykonania SQL.
Odbiór istniejącego `calorie-final`/PostgreSQL/HTTPS i publikacja CI pozostają
odrębnymi krokami integracji.

## Oficjalne źródła API i ograniczenie stockowego action handlera

- [Authenticator SPI i adresy akcji](https://github.com/keycloak/keycloak/blob/26.8.1/server-spi-private/src/main/java/org/keycloak/authentication/Authenticator.java).
- [Stock tworzenie i walidacja użytkownika](https://github.com/keycloak/keycloak/blob/26.8.1/services/src/main/java/org/keycloak/authentication/forms/RegistrationUserCreation.java).
- [Obowiązkowy existing-user check standardowych action token handlerów](https://github.com/keycloak/keycloak/blob/26.8.1/services/src/main/java/org/keycloak/services/resources/LoginActionsServiceChecks.java).
- [Domyślne wykonania registration flow](https://github.com/keycloak/keycloak/blob/26.8.1/server-spi-private/src/main/java/org/keycloak/models/utils/DefaultAuthenticationFlows.java).
- [Atomowa jednorazowość w SPI](https://github.com/keycloak/keycloak/blob/26.8.1/server-spi/src/main/java/org/keycloak/models/SingleUseObjectProvider.java).

Zwykły `ActionTokenHandler` wymaga już istniejącego użytkownika. Dlatego token
bez użytkownika jest sprawdzany w wspieranym `Authenticator.action()` pod
standardową akcją rejestracji; nie omijamy checków istniejących handlerów,
nie tworzymy konta pozornego i nie dodajemy własnego endpointu przyjmującego hasła.
Keycloak oznacza SPI authenticator/form-action jako wewnętrzne i ostrzega o tym
przy rozruchu. Moduł jest przypięty do 26.8.1; aktualizacja serwera wymaga
ponownej kompilacji, przeglądu oraz odbioru rzeczywistych stron i wiadomości.
