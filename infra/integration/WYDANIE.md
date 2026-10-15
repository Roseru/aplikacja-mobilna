# Pakiet wydania: zgodność artefaktów, migracja i powrót

`release.py` sprawdza lokalny komplet przed odbiorem wydania. Kod nie publikuje
obrazu, APK lub sekretów i nie wykonuje wdrożenia. Wynik `CANDIDATE_VALIDATED`
oznacza zgodne artefakty i komplet wskazanych dowodów; ich merytoryczny odbiór
nadal należy do autorów O1/O2/O3. `BLOCKED` zawiera osobne braki Androida,
backendu, katalogu i odbiorów, exit1. `deployment_authorized` pozostaje false.

## Uruchomienie

Użyj istniejącego środowiska backendu, Android build-tools i Java. Na Windows
wskaż `aapt.exe` i `lib/apksigner.jar`; nie uruchamiamy skryptu batch z argumentami
pochodzącymi z artefaktów. Przykład z własnymi lokalnymi ścieżkami:

```text
backend/.venv/Scripts/python.exe infra/integration/release.py --manifest <candidate/release.json> --output <candidate/check.json> --aapt <sdk/build-tools/35.0.0/aapt.exe> --java <jdk/bin/java.exe> --apksigner-jar <sdk/build-tools/35.0.0/lib/apksigner.jar>
```

Wszystkie pliki wejściowe są względne do katalogu release.json. Checker odrzuca
wyjście poza ten katalog, symlinki/junctions, zduplikowane pola JSON i duże JSON.
Pracuje na istniejącym lokalnie obrazie, bez pull. Sonda schematu uruchamia
jednorazowy kontener bez sieci, sekretów, mountów, writable root lub startu API.

## Format wejściowy

Poniższy schemat jest opisem pól do wypełnienia rzeczywistymi wynikami,
nie gotowym odbiorem. O3 składa manifest po otrzymaniu dostaw O1/O2.

| Pole release.json | Wartość |
|---|---|
| format | 1 |
| channel | integration albo production |
| commit | pełne40hex źródła wspólnego zestawu |
| android.manifest | względny plik manifestu buildu |
| android.apk | względny plik regularnego APK |
| android.signer_sha256 | oczekiwany publiczny SHA256 certyfikatu od O1 |
| android.catalog_reader_version | dodatnia wersja obsługi katalogu zadeklarowana i odebrana przez O1 |
| backend.image | lokalny immutable sha256 imageID lub repo@sha256 digest; production wymaga repo digest |
| backend.schema_revision | dokładny head Alembic |
| catalog.manifest / catalog.package | względne pliki istniejącego kontraktu katalogu |
| evidence | dokładnie pięć wpisów z tabeli poniżej, każdy `{path, sha256}` |

Manifest Androida używa istniejących pól CI: `application_id`, `version_name`,
`version_code`, `variant`, `commit`, `apk`, `sha256`. Checker porównuje wersję
z realnym `aapt dump badging` i kryptograficznie sprawdza podpis `apksigner`.
Wymagane regularne `pl.roseru.kalorie`; validation nie jest regularnym APK.
Production wymaga variant release i braku application-debuggable. Klucz podpisu
pozostaje u O1/w prywatnym magazynie; do pakietu trafia publiczny fingerprint.

Obraz musi mieć rzeczywisty `org.opencontainers.image.revision` zgodny z commit.
Dockerfile przyjmuje `VCS_REF`; CI przekazuje rzeczywisty github.sha i porównuje
label z checkoutem. Budowa operatora wymaga czystego, zatwierdzonego checkoutu:

```powershell
$releaseCommit = (git rev-parse HEAD).Trim()
docker build --build-arg "VCS_REF=$releaseCommit" -t "calorie-backend:$releaseCommit" backend
docker image inspect "calorie-backend:$releaseCommit" --format '{{.Id}}'
```

Do manifestu wpisz uzyskany immutable ID. Publikacja registry/digest jest osobnym
krokiem po konfiguracji uzgodnionego celu. Nie oznaczaj istniejącego starszego
obrazu nowszym commitem przez samą zmianę tagu. Katalog przechodzi rzeczywisty
import do osobnego tymczasowego SQLite: limity, gzip, hash, kontrakt, referencje
i aktywacja generacji. Production wymaga official; demo pozostaje jawnie demo.

## Dowody odbioru O1/O2/O3

Każdy receipt zawiera `result=PASS` i ten sam `commit`, wyłącznie po wykonaniu
opisanej próby. Hash receipt jest częścią manifestu. Prywatny backup lub Room/WAL
nie jest plikiem odbioru do publikacji; przygotuj neutralne podsumowanie i zachowaj
surowe dowody prywatnie. Brak odbioru oznacza brak receipt, nie wymyślone PASS.

| Wpis evidence | Właściciel i dodatkowe wymagane pola |
|---|---|
| android_acceptance | O1: apk_sha256, room_version, catalog_reader_version; dane z faktycznie odebranego APK |
| backend_acceptance | O2: image, schema_revision; zgodność API/30dni i testowane wersje opisać w receipt |
| migration | O2/O3: from_revision, to_revision, data_preserved=true po rzeczywistej migracji |
| rollback | O2/O3: for_revision, strategy=compatible_image albo restore; dla obrazu także image immutable i schema_compatible=true |
| restore | O3/O1/O2: rzeczywisty zakres restore; production dodatkowo offsite_verified=true i client_recovery=true |

Checker potwierdza spójność tych wejść i hash, nie pochodzenie ludzkiego podpisu
pod tekstem receipt ani samodzielne wykonanie opisanych scenariuszy. Linki do CI,
komend, zakresu i ograniczeń umieszczaj w receipt/PR; O1/O2 odbierają je niezależnie.

## Procedura migracji i wdrożenia

1. Odbierz końcowe CI tego commita, zgodność APK/API/katalogu i macierz O2.
   Nie wycofuj API obsługującego nadal ważne30dni checkpointy. Potwierdź
   działający cel, issuer/CA/SMTP i dostęp do poprzedniego obrazu/sekretów.
2. Wstrzymaj harmonogram backupu na okno operacyjne. Sprawdź zakończenie bieżącej
   operacji/recovery. Zatrzymaj dopływ zapisów i wykonaj spójną kopię obu baz,
   ról, konfiguracji i katalogu istniejącym backup.py capture. Dla lokalnej kopii
   verify/rehearse muszą przejść przed rolloutem. Offsite jest osobnym dowodem.
3. Migrację uruchom dokładnie raz osobnym migratorem na uzgodnionym zestawie;
   API/worker nie wykonują DDL. Polecenie na tym samym prywatnym Compose ma
   formę `docker compose --env-file <state/compose.env> --project-name <project>
   -f infra/integration/compose.yaml run --rm --no-deps migrate`. Nie podmieniaj
   istniejących sekretów lub epoki w ramach zwykłego upgrade.
4. Wdróż właściwy immutable obraz zgodnie z konfiguracją celu, sprawdź head,
   zachowanie danych według oracle O2, readiness/discovery/exact issuer/TLS,
   realne PKCE A/B i chronione GET, workery oraz odbiór APK O1. Otwórz ruch
   dopiero po tych kontrolach. Zachowaj version/digest/hash i wynik migracji.
5. Przywróć harmonogram i potwierdź świeże heartbeat/receipts monitoringu.
   Lokalny harmonogram nie jest CD na VPS. Cel produkcyjny wymaga rzeczywiście
   skonfigurowanych dostępów, zatwierdzenia wydania i własnego smoke.

## Powrót i awaria migracji

- **Zgodny obraz:** wyłącznie po jawnej ocenie O2 dla aktualnego schematu.
  Przełącz na wskazany immutable digest, sprawdź readiness/PKCE/API i workery.
  Nie zmieniaj sync_epoch przy samym restarcie lub zgodnym rollbacku obrazu.
- **Niezgodny schemat/błąd migracji:** zatrzymaj ruch i workery; nie wykonuj
  dowolnego Alembic downgrade. O2 wybiera naprawę naprzód lub przyjęty restore.
  O3 zachowuje kopię stanu awarii i wykonuje procedurę na uzgodnionym celu.
- **Restore starszej bazy:** przywróć spójne obie bazy/konfigurację/katalog,
  uzgodnij niezależny rejestr usunięć, nadaj nową epokę poza cofniętą kopią,
  unieważnij stare JWT/refresh/sesje i snapshoty oraz sprawdź spójność Keycloak.
  AI/Nemesis pozostają zamknięte do odbioru O2. Telefon O1 przechodzi KO32
  z zachowaniem potwierdzonych i niewysłanych operacji. Dopiero później ruch.

Lokalny backup.py rehearse sprawdza kopię w izolacji i celowo **nie otwiera ruchu**.
Nie jest poleceniem produkcyjnego restore. Wykonawcze wejścia deletion ledger,
unieważnienia tokenów i telefonu są zlecone O2/O1 we wspólnym dzienniku;
ich brak blokuje oznaczenie pełnego KO17/32 i produkcyjnego wydania.
