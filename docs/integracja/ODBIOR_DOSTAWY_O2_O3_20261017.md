# Odbiór dostawy O2 i rollbacku lokalnego — O3

17 października 2026, agent3/O3. Gałąź `codex/devops-przenosny-obraz`,
baza mainfaee91f. Odczytano O2-038 i dostawę FIX1 z PR116.
Zakres: autentyczne artefakty C2 i próba obrazu rzeczywiście używanego przez O3.

## Odbiór plików i kandydata C2

Źródło: [CI39031423976](https://github.com/Roseru/aplikacja-mobilna/actions/runs/39031423976),
head `1abd43753031b974029213542563bcb490e51449`, rzeczywisty checkout
`672b72a3a1d0ad9b03ec7d2ed1297bbff701031e`. Przebieg SUCCESS.

Pobrano artefakty12101191829,12100882806 i12100249009. SHA-256 każdego ZIP
zgodny z API GitHub. Cztery JSON i dwa obrazy mają dokładnie sześć hashy
opublikowanych w [raporcie O2](ODBIOR_RECOVERY_O2.md#odebrany-zestaw-wykonawczy-c2).
Oba obrazy załadowano; dodatkowo sprawdzono config, descriptor i każdą warstwę
TAR względem jej hasha. Nie przepisano ani nie podmieniono oryginalnych receiptów.

| Obraz | Oryginalny config digest O2 | Lokalny ID manifestu containerd |
|---|---|---|
| C2, schema0024 | `sha256:3b803488e0cdfc99bd5398a00f5e0f9f92386b7a90a546300ba58e2aaa24b7e7` | `sha256:691f25f818a362c6ea22bd6cae48aa6f3ef85b7c287a189864582ed05116b0e0` |
| a522471, schema0021 | `sha256:bdea93cae9918a4a30c425d31e838a8649316903dbcc014ab87ee7a39b9c90cd` | `sha256:4e0532efe94869dfebd139c9854264549a70bb8e1f4ac8a43a8860e65ea801f8` |

Różnica tożsamości uniemożliwiała prosty `image inspect` pod config digest
z innego silnika. Checker otrzymał opcjonalne, kryptograficznie sprawdzane
powiązanie z oryginalnym archiwum, opisane w [instrukcji wydania](../../infra/integration/WYDANIE.md).
Żaden obraz nie został retagowany jako inny commit. Nowe odbiory nadal wymagają
tego samego C2; obrazy poprzednika i bieżący pozostają oddzielne.

Nowy lokalny folder `Wydanie integracyjne O2 C2 2026-10-17` zawiera regularny
APK0.8.10/debug/code21 i manifest z tego samego CI, oba obrazy, oryginalne
receipty O2 oraz katalog demo pobrany przez `git show` z dokładnego C2.
Poprzedni kandydat a6e2395 pozostaje zachowany.

APK SHA-256: `5ba3f60ccc4435f97f271eb39ecdd4cc448a0d5ab4fdfa78cc33e13670482c98`.
Podpis rzeczywiście zweryfikowano; certyfikat tego CI debug:
`687feeeb1f89b45041a6b3ed0477153ee8c028681f5aa479aefdb0bd91d372d9`.
To inny debug signer niż w poprzednim kandydacie. Nie instalowano tego APK
na telefonie lub AVD użytkownika i nie deklarujemy możliwości install-r
na poprzednio podpisanej instalacji. Źródło signera z tego artefaktu nie
zastępuje końcowej akceptacji klucza przez O1.

Rzeczywiste kontrole APK/podpisu, schema0024 uruchomionego bez sieci obrazu
i import katalogu PASS. Końcowy komplet wydania pozostaje BLOCKED bez
brakujących rzeczywistych odbiorów O1; niczego nie wdrożono na źródle.

## Obraz rzeczywiście wdrożony na O3

Źródłowa instalacja ma obraz API
`sha256:05c1792f3551725f0303cc3786892771392532a25edc18ff710faad9e6b7e9a9`
i schema0024. Ten starszy obraz nie ma OCI revision; nie przypisujemy mu
wymyślonego commita. Przyjęcie lokalnego poprzednika wymaga jego rzeczywistego
uruchomienia z naszą spójną kopią, nie zastąpienia go obrazem laboratoryjnym0021.

Próba używa prywatnego odtworzenia naszej kopii z17.10,16:12CEST:
app/KC/globals/SCRAM/TLS/katalog, źródłowe12kont i13tożsamości,86tabel app.
PG/API/Keycloak są na oddzielnej sieci internal; tylko własny gateway ma
wejście loopback21443. Oryginalny issuer i CA są zachowane, a transport sondy
odmawia połączenia z innym hostem/portem. Źródłowe osiem kontenerów jest
wyłącznie odczytywane. Testowe konta powstają dopiero w odtworzonej kopii.

Końcowa próba18:32–18:34CEST: **PASS**. Rzeczywiste odtworzenie zachowało
fingerprints kont/tożsamości i wszystkie86tabel app. Po przygotowaniu dwóch
własnych kont tylko w klonie uruchomiono C2 (gotowość6,143s), wykonano PKCE,
chronione me i pełny odczyt synchronizacji. Następnie przywrócono dokładny
poprzedni immutable obraz: **gotowość5,623s**, ponowne PKCE/API PASS.
Epoka pozostała taka sama. Hashe wszystkich85tabel poza celowo tworzonymi
sesjami snapshotu są identyczne. Nie cofano bazy i nie wykonywano migracji
lub downgrade: strategia to compatible_image na schema0024.

Własne kontenery/sieci/wolumeny próby usunięto. Wszystkie osiem kontenerów
źródłowej instalacji ma te same ID; świeży monitoring jest poprawny.
Pomiary dotyczą lokalnego klonu, nie produkcyjnego RTO/RPO lub awarii całego
hosta. Nie odtworzono stanu do działającej instalacji ani nie otwarto AI/Nemesis.

Pierwsze próby harnessu zachowano jako FAIL: błędna nazwa serwisu,
parametry adaptera routingu, brak publikacji portu na sieci internal i brak
Idempotency-Key testowego bootstrapu. Poprawiono wyłącznie własną izolowaną
próbę. Finalny wynik ma osobny receipt i nie zastępuje historycznych FAIL.

Do lokalnego kandydata dodano nowy `rollback-local-deployed.json` wiążący C2
z rzeczywistym poprzednikiem O3 oraz `restore-server-offsite.json` wiążący
identyczny manifest kopii z odtworzeniem pliku pobranego z Dropbox. Oryginalne
receipty O2 pozostają obok, bez zmian. Restore ma client_recovery=false
i continuous_ledger_accepted=false. **Brakuje android_acceptance O1**;
nie przyznajemy pełnego KO32 lub zgody na produkcyjne wdrożenie.

## Weryfikacja zmiany checkera

Osiem nowych regresji: prawdziwe powiązanie manifest→config oraz odmowy
błędnego SHA archiwum/config/runtime, innego RootFS/OS, braku archiwum
i uszkodzonego TAR. Wraz z istniejącymi testami checkera:23PASS.
Wspólny lokalny zestaw z przygotowaniem szyfrowanej kopii:187PASS (11testów
kopii stanowi osobną zmianę). Użyto nowego katalogu temp poza checkoutem;
wcześniejszy temp wewnątrz repo został poprawnie odrzucony przez testy
prywatnego przekazania. Ruff lint/format i diff-check PASS.
Zdalny pełny CI nowego PR stanowi odrębny wynik. Produkcyjny rollback/RPO/RTO,
rejestr ciągłych usunięć i recovery telefonu zachowują własne wymagania.
