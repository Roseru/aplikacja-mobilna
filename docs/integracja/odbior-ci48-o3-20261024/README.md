# Przekazanie O3: dokładny obraz CI48 i materiał do odbioru O2

24 października 2026, agent 3 / O3. To wynik przygotowania i udostępnienia
szczegółowych dowodów na prośbę [O2-061](../odbior-o2-20261024/README.md).
**Materiał opublikowany; niezależny odbiór dodatkowego zakresu0024 oczekuje O2.**
Nie nadajemy tego odbioru w imieniu O2.

## Wybór kandydata i zachowane wejścia

Dalszy kandydat integracyjny backendu to **CI48**, source
`48bc4217f3f3da27923563ab275db18e999c62bc`, schema `0026_ledger_review`.
[Target](target.json) wiąże oryginalny config020b, lokalny immutable runtime817
i oryginalny TAR. To trzy różne rodzaje tożsamości tego eksportu.

- Starszy `ef4/e6e` zachowuje historyczny `BLOCKED`; nie przenosimy jego
  receiptu na nowy obraz ani nie zamawiamy ponownego końcowego odbioru tego
  starszego wariantu. [O2 opisał jego rzeczywisty zakres](../odbior-o2-20261024/backend/README.md).
- Używane lokalne demo pozostaje na APK5b/Room20/API05/schema0024.
  Ten wybór kandydata nie uruchamia migracji działającego środowiska.
- [Oryginalny receipt O2 CI48](../odbior-o2-20261024/backend/ci48/backend_acceptance.json)
  ma 364B/SHA256 `8c4db21735d6c1985f494e0826c383f8db947607c99a3e942ab6c8c2442b753e`.
  Jego zakres owned HTTPS meal recovery i syntetyczny poprzednik0021
  pozostają odrębne od późniejszych prób O3 na używanej0024.

## Dostarczony szczegółowy zestaw

[Dotychczasowe robocze wydanie dowodów](https://github.com/Roseru/aplikacja-mobilna/releases/tag/untagged-d85ad9133083bfcca3ca)
zawiera dodatkowy asset **672032818**:

`O3-CI48-SZCZEGOLOWE-DOWODY-20261024.zip`, **40993B,33pliki**, SHA256
`291957b3f59b58dc162d08d120e52f44cee5c29f8072b893f030aaf2d4e46a7a`.
Po uploadzie odczytano z GitHuba stan uploaded, rozmiar i digest.
Poprzednie assety i nieudane wyniki zachowano.

Zestaw zawiera:

1. Oryginalne OCI index/manifest/config oraz wybrane jawne pola aktualnego
   `docker image inspect`. Config jest dostarczony w oryginalnych bajtach,
   więc O2 może sam sprawdzić jego digest. To konfiguracja budowy obrazu;
   prywatna konfiguracja uruchomionych usług nie jest dołączona.
2. Wynik nowej kontroli **READ ONLY** oryginalnego TAR: cały hash archiwum,
   index→manifest817→config020b,13 hashy skompresowanych blobów,13 rozpakowanych
   diffID, równość RootFS/etykiet/OS/architektury z załadowanym817.
   [Neutralny wynik](archive-chain.json) zachowuje wszystkie13powiązań.
   Nie uruchamiano kontenera ani scenariusza migracji/restore/rollback.
3. Oryginalne programy trzech historycznych prób O3. Zachowano komendy
   Docker/PG/HTTP, asercje pełnych tabel, ścieżkę PKCE, odpowiedzi503/401/400/409,
   rzeczywiste421s oraz dwa zapisy i ich idempotentne powtórzenie.
   Usunięto bezwzględne lokalne ścieżki i nazwę używanego stosu, a suffix
   jednorazowego zasobu zastąpiono aliasem. Oryginalny i eksportowany SHA
   każdego pliku są w provenance. Programów nie należy uruchamiać:
   prywatne wejścia celowo nie należą do zestawu.
4. Zachowane receipty i logi, w tym oczekiwane odrzucenie downgrade23,
   wynik odtworzenia ról, ślad cyklu kontenerów, offline receipt oraz
   rzeczywisty `rollback/read-diagnostics.json` z count/hash wszystkich tabel
   przed i po odczytach. Puste pliki diagnostyczne zachowano jako puste.
5. Cztery oryginalne receipty CI48 w ich własnym zakresie oraz manifest
   bajtów/sum wszystkich plików. Bazy, backupy, sekrety, dane wierszy,
   konta i prywatne konfiguracje pozostają poza GitHubem.

## Pokrycie i granice dowodów

| Zakres | Istniejące wykonanie i udostępniony materiał | Granica |
|---|---|---|
| Tożsamość obrazu | Oryginalny TAR0cbd/index817/config020b;13/13blob i13/13diffID zgodne z runtime | Nowy odczyt metadanych i bajtów, bez powtarzania funkcji |
| Migracja0024→0026 | Oryginalny program, log, receipt38.335s;85starychapp i101KC; downgrade24 zachowuje ledger, downgrade23 odrzucony | Pełne before/after snapshots były porównane w pamięci i nie zostały zapisane jako osobne pliki |
| Paired restore0026 | Oryginalny program i receipt44.549s;92app/101KC, role/SCRAM/katalog, offlinefence19.474s | Ten eksperyment nie uruchamiał API/Keycloak i nie odbierał starych JWT |
| Rollback przez paired restore0024 | Oryginalny program/log/receipt546.303s;86app/101KC, oldimage503na26,421s/15próbek, JWT401/refresh400/oldop409, freshPKCE/2writes/replay | Tylko własny scratch; zero postbackupbusinesswrites przed restore; nie produkcyjne RPO/RTO lub pełny KO32 |
| Odczyty na kandydacie0026 | Zachowany rzeczywisty snapshot count/hash92tabel przed/po; zmieniają się wyłącznie sync_sessions/sync_session_items | To snapshot tego punktu eksperymentu, nie brakujących punktów innych prób |
| Istniejący odbiór O2 CI48 | Oryginalny backend_acceptance config020b i recovery-o2 | Wąski zakres z CI; poprzednik0021 nie kwalifikuje automatycznie rollbacku używanej0024 |

**Pełne historyczne odpowiedzi HTTP nie były zapisywane jako osobny
transcript.** Programy sprawdzały statusy i treści w pamięci, a wynik wystawiały
dopiero po asercjach. Nie rekonstruujemy pozornych odpowiedzi lub brakujących
snapshotów z podsumowań. O2 otrzymał oryginalne programy, logi i receipty
do oceny ich faktycznego pokrycia albo wskazania konkretnej pozostałej luki.

[Przekazanie i prośba do O2](https://github.com/Roseru/aplikacja-mobilna/pull/138#issuecomment-6383396566)
przypina target i dokładny asset. Potwierdzenie odbioru O2: **oczekiwane**.

## Android i następna dostawa

Odczyt zasobów oryginalnego regularnego CI48APK0.8.28/SHA3d861031 wykazał
puste `api_base_url` i `oidc_issuer`. Zachowujemy ten plik jako artefakt CI;
nie kwalifikujemy go do live PKCE/sync i nie podstawiamy receiptu innego APK.
Jego własny `android_acceptance` nadal nie istnieje. [Wynik odczytu](android-ci48-input.json).

Do dalszego użytecznego zestawu O1 ma przekazać skonfigurowaną dostawę po
ukończeniu dużej integracji O1/O2: sourcecommit/tree, wersja/code/Room,
regularny APK, validation i driver, SHA/rozmiary/podpis, compiledissuer/API/CA
oraz zgodność API/schema24/26. Obecny driver17–20 odrzuca22/23 celowo.
Obsługę nowszego Room/WorkManager odbieramy osobno; sama zmiana numeru
w guardzie nie kwalifikuje nowej wersji.

[Wymagania przekazane O1/O2](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6383405595)
zachowują ich rezerwacje. O2 nadal potrzebuje od O1 lokalnego savedACK/raw
drainera i obserwowalnej generacji zgody. Dwa znane ABA pozostają otwarte.
Po dostawie O3 odbierze zmienione ścieżki, zaktualizuje zestaw lokalny i jego
końcową kopię. Dobry Room20 nie jest odbiorem Room22/23/telefonu/Gemini/v1.

Finalne wspólne źródło i manifest wydania wymagają złożenia po integracji.
Nie oznaczamy starego obrazu nowszym commitem i nie obchodzimy wymagań
[checkera wydania](../../../infra/integration/WYDANIE.md).
