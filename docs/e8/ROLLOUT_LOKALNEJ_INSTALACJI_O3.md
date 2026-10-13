# Aktualizacja rzeczywistej instalacji lokalnej do E8 — O3

13 października 2026, Agent 3. **Lokalna baza/API/workery:0021, odbiór wykonany.
Pełne E8/APK i produkcyjny rollout pozostają odrębne.** Aktualizacja zachowała
dane, account IDs, generacje, installation epoch, issuer, CA i certyfikat.
AI dispatch i capability Nemesis są zamknięte. Nie uruchamiano Google lub E9.

## Stan źródła i dowody kodu

Rzeczywiste dotychczasowe API i PostgreSQL miały `0014_catalog_search`.
Odczyt istniejących kontenerów i schematu nie zmieniał danych. Wcześniejszy
[odbiór upgrade E7→E8](AKTUALIZACJA_ISTNIEJACEJ_INSTALACJI_O3.md) dotyczył0015,
więc nie przypisano jego wyniku tej starszej instalacji.

Przyjęte źródło wdrożenia: main `0410ea5b46f512f2b693c7565030d42efde52c73`,
po [PR48](https://github.com/Roseru/aplikacja-mobilna/pull/48).
PR48/fdab/basebfb i osobny [push main38356363867](https://github.com/Roseru/aplikacja-mobilna/actions/runs/38356363867)
mają po8 completed/success; odczytano pełne logi wszystkich jobów. Main:
1658unit/44infra4,97s/1265PG811,77s/28Keycloak/126JVM/130device, installed
wheel/Docker-I i rzeczywisty HTTPS/PKCE/workers/paired offline restore.
Całe drzewo merge0410 i headfdab jest identyczne:460d01c062740d2eaf6c2e2a359f1d0bb42276e8.
Wynik CI nie jest odbiorem sieci LAN lub APK.

## Próba na kopii przed zmianą instalacji

Przy działającym źródle wykonano spójny **pojedynczy app snapshot** przez pg_dump,
z globals w chronionym katalogu. Nie nazywano tego paired backup lub RPO/RTO.
Nowy oznakowany PG17 odtworzył0014; nie zatrzymywano źródła w tej próbie.
Fingerprint wszystkich istniejących wartości wszystkich kolumn50 starych tabel
sprawdzono przed/po migracji; alembic_version jest osobną oczekiwaną zmianą.

Brak czterech bazowych ról AI/E8 odrzucił upgrade atomowo, nadal0014 i identyczne
stare dane. Zaufany administrator utworzył wyłącznie brakujące minimalne role.
Rzeczywisty upgrade0014→0021 zachował wszystkie50 zakresów danych i epokę.
Nemesis pozostaje disabled. E7 przy normalnej pierwszej migracji tworzy SQL
dispatch_open=true; owner jawnie zamknął AI przed jakimkolwiek startem API/IO.
Pierwsza asercja oczekująca samoistnego AI closed pozostała RED; poprawiono
procedurę wdrożenia, nie migrację lub oczekiwanie końcowe. Finalny runner exit0,
trzy zakresy PASS. Własny kontener próby usunięto po sprawdzeniu ownership label.

## Wykonany rollout istniejącej instalacji

1. Potwierdzono actual0014 API/DB i zatrzymano API, retencję oraz Keycloak.
   Bramka podczas kopii nie miała piszących upstreamów; wszystkie pozostałe
   client backends PG miały liczność0. Taki freeze odcinał API i issuance.
2. Wykonano nowy prywatny **paired backup obu baz** przez pg_dump, globals/SCRAM,
   konfigurację/TLS/realm i katalog. Manifest zapisuje prawdziwą source revision0014,
   epoch, konta/tożsamości, sizes/SHA256 i fingerprints. Nie udawano source0021.
3. Przed zmianą danych odtworzono oba rzeczywiste archiwa/globals w nowym
   oznakowanym PG bez publicznych portów. Oba fingerprints były zgodne;
   katalog bezpiecznie wyekstrahowano/sprawdzono. Nie otwierano tego scratch.
   Własny PG usunięto po ownership guard; kopia i dowody pozostały chronione.
4. Przy zamkniętych writers przygotowano cztery brakujące minimalne NOLOGIN/
   NOINHERIT role i przebudowano instalowany backend z przyjętego main.
   Migrator wykonał rzeczywisty upgrade0014→0021. Przed restartem wszystkie
   stare wartości/kolumny50 tabel były identyczne; konta obu baz, epoka i hashe
   oryginalnych CA/server.pem/server.key pozostały identyczne.
5. Owner jawnie zamknął nowe AI controls, zachowując istniejące closed_at,
   jeżeli byłoby już ustawione. Nie rotowano epoki jako zamiennika zwykłego upgrade,
   nie odmładzano blokady restore i nie włączano żadnego provider worker.
6. Nowe API/retencja i istniejący Keycloak wystartowały. Prawdziwe PKCE istniejącego
   diagnostycznego A oraz GET me/motivation dały200, przy zachowanym issuer/SNI/CA.
   Nie resetowano hasła, tożsamości, profilu, diariusza lub zgód.
7. Provisioner poprawnie odmówił nowym workerom, bo stary `calorie_test` dopuszczał
   PUBLIC CONNECT. Zachowano tę bazę i dane, cofnięto jej PUBLIC privileges,
   zachowując CONNECT dla trzech dotychczasowych technicznych ról API/worker/
   migrator. Pozostałe prywatne bazy są niedostępne dla nowych worker LOGINs.
   Nie pominięto effective ACL guard ani nie użyto konta API/retencji jako workera.
8. Odrębne trzy SCRAM LOGINy i installedCLI/UID10001 wykonały startup, naturalny
   drugi cykl minutowy, odmowy DDL/raw source/Keycloak/SET ROLE i restart bez
   zmiany epoki. Finalizer jest disabled/unhealthy, ponieważ gate jest zamknięty;
   taki stan nie jest udawaną pomyślną finalizacją. Motivation/lifecycle i retencja
   są healthy. Końcowy runner exit0; receipt w prywatnym stanie.

Dane po wznowieniu mogą być normalnie zmieniane przez użytkownika i retencję.
Dowód identyczności50 tabel dotyczy migracji przy zatrzymanych writers, nie
zakazu zwykłej pracy systemu. Nie sumujemy tych zakresów z testami pytest/CI.

## Zmiana sieci i granica rzeczywistego HTTPS

Dotychczasowy LAN origin wskazuje192.168.3.162:18443. Ten adres nie jest już
przypisany komputerowi. Pierwsza kontrola HTTPS z hosta zakończyła się timeout
**przed zatrzymaniem writers i przed migracją**. Pierwszy restart bramki też
odmówił powiązania portu z tym nieistniejącym adresem; nie był to błąd danych.

Bramka została związana wyłącznie z **127.0.0.1:18443**, przy niezmienionych
config.origin, Keycloak hostname/issuer, klientach, keys i certyfikatach.
Zmieniono tylko INTEGRATION_HOST w prywatnym compose.env; nie dodawano globalnych
adresów, tras, hosts entries lub wyjątków TLS na komputerze/telefonie.
Zmiana bind nie oznacza migracji tożsamości i nie tworzy nowego konta.

Próby kontenerowe kierowały wyłącznie socket docelowego host:port do własnego
gateway:8443, a osobna próba Windows do127.0.0.1:18443. URL, Host, SNI, issuer,
CA verification, realny Keycloak, podpis JWT, nonce i PKCE pozostały prawdziwe
i niezmienione. Obie próby zaliczyły fresh login i prywatne reads200.
Nie było syntetycznych JWT/JWKS, verify=false lub APK w tych próbach.
**To realne wewnętrzne i operatorskie HTTPS, nie PASS dostępu telefonu przez LAN.**

Zwykłe otwarcie https://127.0.0.1 nie jest konfiguracją klienta OIDC: hostname
certyfikatu i issuer pozostają dotychczasowe. Odbiór O1 wymaga osiągalnego,
stabilnego adresu i zgodnej konfiguracji/trust telefonu. Przy przywróceniu
dokładnego dawnego LAN IP operator może przywrócić bind do niego; zmiana issuer
wymaga odrębnej uzgodnionej migracji tożsamości i nie jest zwykłym rename URL.

## Historyczne odmowy i następny krok

Zachowano pierwotne prywatne logi: missing-role guard i początkowy AI-open RED,
timeout nieistniejącego LAN, odmowę PUBLIC dostępu do testDB, próbę startu starego
jednorazowego migratora0014 przy schemacie0021 i niepoprawny odczyt UTF-8 ścieżki
stanu w prywatnym harnessie. Po wymianie migrator container na aktualny image,
poprawieniu wyłącznie prywatnego UTF-8 odczytu, jawnej korekcie ACL i bind,
affected-only odbiór zakończył się exit0. Nie przepisywano immutable0001–0021,
nie dopasowano końcowych oczekiwań i nie kasowano danych lub historii.

Kopia sprzed upgrade, poprzedni image, chronione raw logs i receipts pozostają
poza Git. Ewentualny rollback danych jest restore i wymaga nowej epoki/rejestru/
sesji/recovery; nie traktuj archiwum0014 jako bieżącej kopii0021.
[Próba pełnego restore](ODTWORZENIE_SESJE_I_KLIENT_O3.md) ma własny source0021 i zakres.

Następne rzeczywiste wejścia: stabilny osiągalny LAN/public origin i O1 APK/UI/
Room/cache/świadome zgody/Nemesis. Produkcyjny VPS/domena/SMTP, niezależny rejestr
usunięć i szyfrowane kopie/retencja/RPO-RTO nadal wymagają właściwego środowiska.
Backend i local workers są dostarczone; pełne E8 pozostaje WAITING_EXTERNAL.
Nie wykonano zakupów, produkcyjnego reopen, Google/E9 lub automatyzacji Codex.
