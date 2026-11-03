# Lokalna instalacja: start, status, zatrzymanie i kopia

Decyzja właściciela z31.10.2026: dostarczamy MRE/DEMO, ręczne ścieżki i MOCK
na lokalnym komputerze. ARPOL dołączymy później. Brak VPS/domeny i kluczy
Gemini oznacza, że obecnie nie podłączamy publicznego hostingu, Google ani
billing. Docelowe historyczne wymagania pozostają w
[wymaganiach projektu](../../WYMAGANIA_PROJEKTOWE.md).

Po jednorazowym przygotowaniu przez operatora używaj prywatnego folderu:

- **START.ps1** — uruchom istniejące kontenery. W odebranym pakiecie nadrzędny
  **START.cmd** otwiera następnie zachowaną aplikację Androida; sam profil
  serwera nie instaluje APK i nie usuwa Room lub konta.
- **STATUS.ps1** — odczytaj API/HTTPS/issuer, procesy i rzeczywiste agregaty E8.
  Disabled, brak świeżego sukcesu lub brak healthcheck nie oznacza gotowości.
- **STOP.ps1** — zatrzymaj procesy, zachowując kontenery, wolumeny i klucze.
- **BACKUP.ps1** — zamknij ruch i wszystkich writerów; wykonaj sparowaną kopię
  PostgreSQL/Keycloak/katalogu/zdjęć oraz prywatnej konfiguracji. Po kopii
  instalacja pozostaje zatrzymana. Wznów ją zwykłym START.ps1.

Domyślne kopie powstają w podfolderze backups. Możesz wskazać nowy katalog
przez BACKUP.ps1 -Destination '<pełna-nowa-ścieżka>'. Archiwa zawierają dane,
hasła serwisowe i klucze — zachowaj je prywatnie. Osobny backup/eksport Androida
pozostaje obsługą klienta; serwerowa kopia nie zastępuje lokalnego Room/outbox.

## Jednorazowe przygotowanie operatora

To nowa obsługa już istniejącego zestawu. Dawne skrypty local_demo i verifier
PREPARATION_ONLY pozostają historycznymi bramkami przygotowania.
Nie zmieniamy ich na zgodę na uruchomienie.

Najpierw operator odbiera istniejący PostgreSQL/TLS, provider rejestracji,
katalog MRE/DEMO oraz obecne trzy workery E8. Używa istniejących
compose.e8.yaml, run_e8.py, provisionerów i e8_worker.py, z pełną chain.
Codzienne skrypty nie wykonują init/build/import/migrate/provision/activate.
Po restore nie powtarzają provisioningu LOGIN, związanego z databaseOID.
Zdrowy działający zestaw nie jest restartowany przy ponownym START.
Przy wznowieniu E8 wymagany jest świeży sukces z czasem nie wcześniejszym
niż start rzeczywistego procesu kontenera, zanim otworzy się gateway.

Z czystego, zapisanego źródła, kwalifikowanym Pythonem backendu, operator
tworzy NOWY prywatny folder z profilem:

~~~powershell
$BindArguments = @(
  'infra/integration/local_release.py', 'bind',
  '--profile', "$NewPrivateFolder/runtime.json",
  '--state', $ExistingState, '--project', $OwnedProject,
  '--docker-endpoint', $HeldLocalSocket, '--engine-id', $HeldEngineID,
  '--compose-file', "$Source/infra/integration/compose.yaml",
  '--compose-file', "$ExistingState/compose-ai-mock.yaml",
  '--compose-file', "$ExistingState/compose-spi-local.yaml",
  '--compose-file', "$Source/infra/integration/compose.e8.yaml"
)
& $Python @BindArguments
~~~

Binding odczytuje istniejące kontenery i zapisuje tylko prywatne pliki:
profil, launcher wskazujący ten interpreter i źródło oraz cztery skrypty.
Nie tworzy usług, wolumenów ani kont. Sprawdza lokalny socket/engineID,
loopback HTTPS, pełną listę usług, immutable imageId/containerId, projekty
wolumenów, konfigurację i SHA używanych plików. Pełna uporządkowana chain
obowiązuje także dla binarnych pg_dump i archiwizacji. Sekrety są haszowane
w konfiguracji i kopiowane wyłącznie do prywatnej kopii, nie do wynikowego JSON.

Zmiana przypiętego pliku źródłowego, obrazu, CA, ustawień lub kontenera
wymaga osobnego odbioru operatora i nowego bindingu; skrypt nie przyjmuje
zmiany automatycznie. source_commit zapisuje pochodzenie przy tworzeniu
profilu; codzienne operacje sprawdzają hashe używanych plików i konfigurację,
nie samą zmianę Git HEAD, na przykład po dopisaniu dokumentacji.
Blokada .operation.lock wyklucza nakładające się start/stop/backup.
Po awarii operator najpierw sprawdza zakończenie poprzedniego procesu i IO,
zanim ręcznie usuwa pozostałą blokadę.

## Sparowana kopia i odtworzenie

BACKUP zatrzymuje gateway, API, issuer, AI, retencję, SMTP i wszystkie E8.
Sprawdza fizyczne zakończenie procesów oraz brak innych klientów PostgreSQL.
Zachowuje obie bazy, globals/SCRAM, katalog, konfigurację/TLS, pełne overrides
i piny obrazów. Wynik sukcesu wymaga potwierdzonego zamknięcia; kod nie
wznawia ruchu lub writerów również wtedy, gdy kopia zakończy się błędem.

Katalog i zdjęcia czyta osobny jednorazowy helper z dokładnym, już istniejącym
backend imageId. Ma pull=never, network=none, UID10001, read-only i jeden
wskazany własny volume RO; nie dostaje migrate.env lub danych logowania DB.
Przesunięcie taga backend:local nie zmienia kodu archiwizacji. Po timeout
cleanup sprawdza dokładną losową nazwę, Image ID i własny label przed stop.
Żywy osierocony helper blokuje następną operację do wyjaśnienia fizycznego IO.
Stare bezpośrednie wywołanie backup.capture bez profilu zachowuje dawny
kontrakt; nowy pakiet nie uruchamia dla archiwizacji usługi migrate.

Opcjonalne photos.tar ma jawny marker optional_photos i hash/bytes w
tym samym manifest. Przechowuje tylko prywatne przygotowane JPG/staging,
z zachowaniem mtime dla retencji. Stary format1 bez markera pozostaje
obsługiwany bez domniemania, że zawiera zdjęcia. Dane i historia quota
pozostają w sparowanej bazie; archiwizacja nie zmienia limitów ani nie
wznawia pracy AI.

Odtworzenie prowadzi operator do NOWEGO własnego celu według odebranego
adaptera D2. Wymaga właściwych immutable obrazów, w tym Keycloak z providerem;
sam profil lub tag latest ich nie zastępuje. Zachowaj obrazy lub ich prywatny
eksport docker image save, źródła i kopię razem. Nie uruchamiaj ponownego
importu realm, Alembica lub provisionerów jako skrótu restore. Odtworzone
zdjęcia nie są zgodą na wznowienie jobów; dotychczasowe zamknięcie AI/Nemesis,
retencja, quota i fence epoki/sesji nadal obowiązują.

## Późniejsze Gemini

Teraz obowiązuje AI_PROVIDER=mock. [Template backendu](../../backend/.env.example)
zawiera zakomentowane GEMINI_API_KEY, AI_PROJECT_ID, AI_ENVIRONMENT_ID,
AI_MODEL i AI_LIVE_CONFIRMATION. Klucz należy wyłącznie do backendu,
nigdy do APK lub Git. Nie wpisuj demonstracyjnych limitów jako rzeczywistych.

Po przyszłej decyzji właściciela operator stosuje istniejące
[E7 — konfiguracja, datowane potwierdzenie i configure-pool](../../docs/e7/KONFIGURACJA_O3.md)
oraz [E9 — wspólna pula i energia](../../docs/e9/KONFIGURACJA_O3.md).
Dotychczasowe wymagania modelu, rzeczywistych limitów, historii i restore
pozostają. Zmiana konfiguracji ma osobne okno i odbiór; nowy binding
--provider gemini nie wykonuje połączenia z Google ani nie omija tych
warunków. Bez nich backend/worker nadal odmawia pracy.

## Odbiór tej obsługi

Testy źródeł obejmują konfigurację/ownership, odmowę driftu, pełną chain,
fizyczne zamknięcie writerów i prywatny opcjonalny photo archive.
Rzeczywisty odbiór 02.11.2026 obejmuje start/stop wszystkich dziesięciu usług,
sparowaną kopię z niepustym przygotowanym zdjęciem oraz jego odtworzenie do
nowego, izolowanego celu. Porównano bytes/SHA, uprawnienia i rzeczywistą
precyzję mtime; źródło zachowało kontenery, epokę, dane i historię limitów.
Po wznowieniu wymagano świeżych sukcesów wszystkich trzech E8. Osobny D2
Room27 zakończył uzgadnianie przez publiczny interfejs aplikacji1057,
z odczytem offline po restarcie. Dokładne granice i zachowane odmowy opisuje
[istniejący dziennik](../../docs/KOMUNIKACJA_AGENTOW.md).

Profil sprzed przerwy zachował odmowę pełnego fingerprintu konfiguracji.
Brak historycznego pełnego inspect nie pozwolił przypisać przyczyny różnicy.
Operator porównał aktualne kontenery z przypiętą pełną Compose chain,
konfiguracją immutable obrazów oraz dotychczasowymi danymi i utworzył NOWY
profil po zgodnym odbiorze. Nie edytowano starego profilu ani nie zmniejszono
kontroli. Także w przyszłości nie przyjmuj driftu automatycznie.
