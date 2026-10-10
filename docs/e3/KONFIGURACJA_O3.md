# Konfiguracja i utrzymanie E3 - osoba 2

Backend Python 3.13 nadal korzysta wyłącznie z PostgreSQL 17, bazy
calorie_app i schematu app. Dane tożsamości dostawcy pozostają w oddzielnej
bazie Keycloak; backend nie ma do niej dostępu ani własnej bazy haseł.
Testowy harness H2 izoluje dane efemerycznego Keycloak i nie zastępuje
produkcyjnej konfiguracji PostgreSQL dostawcy.

## Konfiguracja API

| Zmienna | Znaczenie |
|---|---|
| DATABASE_URL | Rola calorie_app_api, sterownik postgresql+psycopg; bez DDL i praw do Keycloak |
| CATALOG_PAGE_TOKEN_SECRET | Trwałe 32 losowe bajty jako 64 znaki hex, wspólne dla replik i restartów; podpisuje także prywatne strony z oddzielnym prefiksem |
| OIDC_ISSUER | Dokładny issuer tokenu z zaufanej konfiguracji |
| OIDC_JWKS_URL | Dokładny zaufany adres JWKS; może być wewnętrzny, ale nie zmienia claimu iss |
| ENVIRONMENT | production domyślnie; development/test wyłącznie dla izolowanego środowiska |
| OIDC_ALLOW_LOCAL_HTTP | false domyślnie; true tylko development/test i loopback; produkcja odrzuca tę konfigurację |
| OIDC_JWKS_CACHE_SECONDS | Domyślnie i najwyżej 900 s |
| OIDC_JWKS_REFRESH_COOLDOWN_SECONDS | Domyślnie 5 s; ogranicza odświeżanie nieznanego kid |
| OIDC_JWKS_TIMEOUT_SECONDS | Domyślnie 3 s; całkowity limit fetchu, najwyżej 10 s |

Audience jest stałe calorie-api; algorytm RS256. Access token wymaga typ=Bearer,
iss/aud/sub/exp/iat, lifetime 0..300 s z dodatnią długością i skew 60 s.
nbf jest opcjonalne, obecne zawsze sprawdzane. Role pochodzą tylko z
resource_access.calorie-api.roles; normalny użytkownik potrzebuje user.
Moderator/admin nie omija własności danych.

JWKS ma limit 64 KiB i 32 kluczy, brak redirectów oraz koordynowane fetchowanie.
Świeży znany klucz działa podczas awarii; po TTL wymagane odświeżenie.
Brak niezbędnego dostawcy daje 503 z Retry-After; brak kid po poprawnym
odświeżeniu daje 401. jku/x5u i adresy z tokenów nie są fetchowane.

## Migracje i epoka

Uruchom `alembic -c backend/alembic.ini upgrade head` jako migrator przed
wdrożeniem nowego API. Nowe migracje 0006_e3_identity i 0007_e3_diary
rozszerzają 0005_ration_cursors; istniejące migracje i opublikowane bajty E2
pozostają niezmienione. Nowy readiness wymaga 0007_e3_diary.

0006 tworzy singleton app.installation_state z UUID sync_epoch jednokrotnie.
API i worker mają wyłącznie SELECT do tego zasobu; startup nie losuje epoki.
Przy zwykłym restarcie/zmianie repliki zachowaj DB i sekret paginacji.

Po restore operator przy zatrzymanym API/workerach musi nadać nową epokę
rolą migratora i unieważnić poprzedni kontekst klientów. Stary receipt
bootstrapu zwraca 409 sync_epoch_changed; nowy klucz zwraca ten sam account_id
i nową epokę, zachowując zgody. Pełne uzgodnienie snapshotów i danych po
restore jest zadaniem E4; samo przestawienie singletonu nie zamyka KO-32.

Downgrade nowych migracji odmawia zniszczenia istniejących danych prywatnych.
Nie usuwaj receipts ani historii, aby wymusić cofnięcie. Przy danych E3
wybierz kompatybilny rollback kodu albo sprawdzone odtworzenie.

## Retencja

Pełne odpowiedzi PUT zgód zachowujemy co najmniej 60 dni. Worker może
wywołać w swojej transakcji `SELECT app.prune_consent_responses()`; jedno
wywołanie czyści najwyżej 1000 pełnych odpowiedzi, a minimalne potwierdzenie
owner/operacja/klucz/hash/accepted_revision pozostaje. Wywołuj okresowo
aż wynik spadnie poniżej 1000. Replay po sprzątaniu daje
409 idempotency_result_expired i nie odtwarza mutacji. Małe wyniki bootstrapu
pozostają trwałe. Minimalne potwierdzenia usuwa dopiero skoordynowany
protokół usunięcia konta, zaplanowany osobno dla E4.

Strony E3 są podpisanymi tokenami stateless; produkty przypinają niezmienny
release E2, cele granicę rewizji niezmiennej osi. Nowe odczyty nie tworzą
rekordów snapshotów do sprzątania. TTL 60 minut nie jest przedłużany.

## Testowy Keycloak i CI

[Instrukcja Keycloak](../../infra/local/keycloak/README.md) i lockfile
opisują przypiętą dystrybucję, start/stop, generowanie efemerycznych kont A/B
oraz rzeczywisty test PKCE. Używa JDK 25; lokalny JBR 21 nie wystarcza
do najnowszej dystrybucji. Test nie wymaga produkcyjnych credentiali.

Testowy realm calorie-dev ma publiczny klient calorie-android z dokładnymi
redirectami O1. Audience mapper calorie-api dotyczy access tokenu i nie
dodaje tego audience do ID tokenu. Direct grants, implicit i wildcardy
są wyłączone. Osobny klient harnessu umożliwia loopback test bez handlera APK.

CI wymaga contracts, quality, postgres i keycloak-pkce; ci-required sprawdza
sukces wszystkich czterech. Brak usługi albo niewykonany test PKCE kończy
się błędem, bez zielonego skipu. Obraz/wheel zachowują zasoby runtime poza
checkoutem.

## Przekazanie środowiska mobilnego

O1 przekazał applicationId pl.roseru.kalorie i dokładne callbacki w
[INTEGRACJA_E3.md](../../android/INTEGRACJA_E3.md). Na emulatorze issuer
musi pozostać identycznym stringiem jak claim iss. Dla izolowanego serwera
hosta można uzgodnić adb reverse dla portu Keycloak/API, aby loopback był
osiągalny także z emulatora; alternatywą jest wspólny osiągalny host HTTPS.
Samo zastąpienie issuer przez 10.0.2.2 zmienia tożsamość i jest błędne.

Produkcyjna domena, HTTPS, SMTP, mobilny klient HTTP/OIDC i CI Androida
pozostają po stronie O1/O3. Backendowy test PKCE nie dowodzi wdrożenia
produkcji ani logowania APK. [Raport E3](RAPORT_E3.md) podaje wykonane dowody.
