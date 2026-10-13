# Pełna lokalna próba odtworzenia: sesje, usunięcie i klient — O3

13 października 2026, Agent 3. **Lokalny HTTPS/Keycloak/PG17: PASS w sześciu
wykonanych zakresach. Produkcyjne odtworzenie i APK pozostają osobnym odbiorem.**
Ta próba uzupełnia [spójną kopię i offline restore](KOPIA_ODTWORZENIE_O3.md).
Nie zastępuje odebrania rzeczywistego rejestru usunięć, magazynu kopii i RPO/RTO
docelowego serwera.

## Źródło i izolacja

Narzędzie capture/verify i procedura fencing pochodzą z main `89be120`:
immutable head0021, dwa custom archives, globals/SCRAM, konfiguracja/TLS i katalog.
Odtworzony backend jest instalowanym obrazem własnego zestawu z PR44/a22;
`backend/src` i `backend/migrations` są identyczne pomiędzy a22 i89be120.
Aktualizacja PR47 dotyczy wyłącznie dokumentacji. Rzeczywisty Keycloak, zaufane
HTTPS i Authorization Code/PKCE pochodzą z tego samego własnego zestawu.

Każda próba tworzy nowy losowy projekt Compose, osobne wolumeny i chroniony
katalog poza Git. Ponownie używa własnego loopback origin, issuer, kluczy oraz
CA z kopii, po zatrzymaniu źródła. Cudzy działający zestaw integracyjny pozostaje
nietknięty. Nowe A/B są wyłącznie własnymi kontami fixture. Nie zmieniano zegara,
produkcyjnych funkcji czasu, migracji, aplikacji lub zasad synchronizacji.

Archiwa, konfiguracja, stare tokeny, hasła, identyfikatory, rejestr i raw logs
pozostają prywatne. Katalog próby ogranicza ACL do właściciela i SYSTEM na Windows;
nie jest publicznym artefaktem CI. Końcowy receipt zawiera zakres i ograniczenia.
Po próbie wszystkie własne API/Keycloak/workery/gateway są zatrzymane, a zasoby
odtworzenia zachowane do audytu. Nie usuwano cudzych kont, kontenerów lub danych.

## Wykonane sześć zakresów

1. Rzeczywiste PKCE utworzyło sesje A/B. API przyjęło bootstrap obu kont, pull
   i zapis wagi A. Spójny capture zatrzymał ruch i wszystkie writers; verify
   sprawdził archiwa i konfigurację. Stare access/refresh oraz epoka i checkpoint
   zostały zapisane wyłącznie w prywatnym stanie klienta poza kopią.
2. Po wykonaniu kopii źródło przyjęło drugi zapis A. Operator rozpoczął deletion B,
   faktycznie usunął użytkownika Keycloak, potwierdził404, zatwierdził confirm/purge
   przez istniejące DB entrypoints. Zakończony job zapisano w chronionym rejestrze
   poza cofanym zestawem. Nie konstruowano prywatnego `_deletion_context`.
3. Nowy PG został odtworzony przez prawdziwe globals i pg_restore obu baz.
   Odtworzył pierwotną epokę i konto B, ale nie zawierał późniejszego joba deletion.
   To reprodukcja przyczyny: sama dawna kopia przywraca usunięte później konto.
4. Przed ruchem zatwierdzono nową epokę, wyłączono Nemesis, usunięto snapshoty,
   wykonano bounded cleanup do pending0; AI dispatch pozostał fizycznie zamknięty.
   Katalog odtworzono z kontrolą zawartości. Gateway pozwalał wyłącznie na zaufany
   kanał operatora; API i user issuer zwracały503. Nowy rejestr uzgodniono z dokładnym
   issuer/subject/account/generation. Istniejący begin/confirm/purge oraz prawdziwe
   Keycloak DELETE/GET404 ponownie usunęły B. Permanent subject fence pozostał true,
   konto nie istnieje. Logout-all odciął odtworzone sesje całego user realm.
5. Ingress API oraz issuance użytkowników pozostały zamknięte do rzeczywistego
   `exp + 60s` obu uchwyconych access tokens, z dodatkową sekundą graniczną.
   Nie skracano lifetime lub verifier skew. Po lokalnym otwarciu każdy stary JWT
   dostał401, a każdy odtworzony refresh dostał400/invalid_grant. Sam upływ czasu
   nie jest dowodem: sprawdzono rzeczywiste odpowiedzi HTTP/TLS.
6. Świeże PKCE A zakończyło się sukcesem. Stary klucz bootstrap, stara epoka/pull
   checkpoint i stary push dostały409. Nowy bootstrap zachował account_id i zwrócił
   nową epokę. Recovery pull zwrócił receipt pierwszego zapisu, bez drugiego zapisu
   przyjętego po kopii. Dopiero jawne `recreate_missing`, nowa operacja i aktualna
   epoka odtworzyły utraconą wagę z nowym entity_id. AI/Nemesis pozostały zamknięte.

Sześć zakresów i końcowy runner exit0; nie są sumowane do zestawów pytest/CI.
Pierwsza pełna próba również wykonała powyższe asercje i exit0, ale jej prywatny
gateway maintenance miał początkowo błąd formatu Caddyfile, naprawiony podczas
zamkniętej próby. Zauważono też dodatkowy poziom katalogu w prywatnym mount.
Poprawiono wyłącznie harness; końcową procedurę wykonano ponownie od początku
na nowych własnych zasobach, z właściwym catalog root i bez napraw w trakcie.
Historyczne logi zachowano. Produkt i oczekiwania nie zostały dopasowane do wyniku.

Uzupełniająca próba rzeczywistego HTTPS sprawdziła również stary podpisany
checkpoint przy **aktualnej** epoce żądania i operacji: pull oraz push
odmówiły409/sync_epoch_changed, runner exit0. Pierwszy odczyt envelope w prywatnym harnessie
używał błędnego `error.code` zamiast kontraktowego top-level `code` i zakończył
się KeyError po właściwej odmowie409. Poprawiono wyłącznie odczyt wyniku i
ponowiono ten zakres; nie zmieniano backendu, checkpointu lub oczekiwanego kodu.

## Procedura przed rzeczywistym reopen

1. Zamknij ingress aplikacji, issuance użytkowników i wszystkie writers, również
   inne repliki lub niezależne wejścia. Odtwórz spójny zestaw; sprawdź jego pochodzenie,
   integralność, role, konfigurację i exact schema/package, zanim uruchomisz klienta.
2. Zatwierdź nową installation epoch i zamknięte capability, odetnij snapshoty,
   wykonaj bounded Nemesis cleanup. Zachowaj E7 closed_at/fencing; nie odmładzaj
   blokady AI ani nie odtwarzaj starych zleceń dostawcy.
3. Pobierz aktualny zaufany rejestr zakończonych usunięć i blokad z miejsca, które
   nie jest cofane razem z kopią. Uzgodnij dokładną tożsamość i generację poprzez
   istniejący protokół deletion. Każda niezgodność, brak lub niepewność utrzymuje
   zamknięty ruch. Nie importuj niesprawdzonego JSON jako autorytetu produkcji.
4. Zweryfikuj usunięcie/zablokowanie właściwych tożsamości i odetnij stare sesje
   Keycloak przez [realm logout-all](https://www.keycloak.org/docs-api/latest/rest-api/index.html).
   Access JWT jest stateless: samo logout-all nie daje natychmiastowego401 w API.
5. Zweryfikuj granice lifetime i zegary wszystkich issuer/API. Backend dopuszcza
   `exp - iat <= 300s` i skew60s. Dla nieznanych tokenów bezpieczny projektowy
   przedział po ostatnim możliwym issuance wynosi co najmniej420s, uwzględniając
   dopuszczony przyszły iat oraz leeway; dodatkowe źródła czasu wymagają własnej
   weryfikacji. Nie zastępuj tego krótszym czasem obserwowanego fixture JWT.
6. Odbierz odrzucenie starych JWT/refresh, brak odtworzenia usuniętego konta,
   świeże logowanie, stale epoch/checkpoint i świadome recovery klienta. Sprawdź
   brak regrant starego ranking/sharing. Dopiero wtedy jawny reopen danej instalacji.

## Granice tego odbioru

Rejestr w próbie jest chronionym, niezależnym **lokalnym fixture** zakończonej
rzeczywistej deletion. Nie wdraża magazynu/autentykacji/retencji ciągłego rejestru
produkcyjnego. Udowodniono zachowanie dwóch konkretnych realnych access/refresh
sessions, nie wszystkich możliwych tokenów/replik/offline sessions dostawcy.

HTTP recovery nie jest testem Room/UI telefonu lub pełnym KO-32. Potrzebne są
własne aktualne O1 API/APK/cache/Nemesis/zgody oraz produkcyjne O3 origin/VPS/
domena/SMTP, niezależny rejestr, szyfrowany magazyn kopii i pomiar RPO/RTO.
Brak tych wejść utrzymuje pełne E8 WAITING_EXTERNAL. Nie wykonano zakupów,
otwarcia produkcji, aktywacji AI/Google/E9 ani nowych automatyzacji Codex.
