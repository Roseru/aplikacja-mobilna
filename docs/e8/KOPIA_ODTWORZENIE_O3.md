# Spójna kopia i lokalna próba odtworzenia — O3

13 października 2026, Agent 3. Zakres: prywatna, spójna kopia aplikacji,
Keycloak, ról, konfiguracji/TLS i katalogu oraz faktyczne odtworzenie obu baz
w odizolowanym PostgreSQL 17. Próba nadaje nową epokę i odcina stare funkcje
przed jakimkolwiek ruchem. Nie otwiera API ani nie wykonuje produkcyjnego restore.

## Procedura

`infra/integration/backup.py` ma trzy jawne działania: capture, verify, rehearse.
Wymaga wskazania nowego prywatnego katalogu backupu; capture dodatkowo wymaga
konkretnego własnego lokalnego stanu. Nie nadpisuje istniejącej kopii.
Katalog pod Git może być wyłącznie pod ignorowanym `.tools`. Linux ma tryb0700,
Windows odcina dziedziczenie ACL i dopuszcza bieżącego użytkownika oraz SYSTEM.

Capture najpierw zatrzymuje gateway, API, retencję, opcjonalne trzy workery E8
i Keycloak. Sprawdza brak innych klientów bazy. Dopiero wtedy zapisuje dwa
custom archives PostgreSQL, globals/SCRAM, konfigurację/TLS i katalog. Brak
piszących procesów utrzymuje spójność pomiędzy bazami i plikami. Udany backup
pozostawia ruch zatrzymany; operator wznawia źródło osobną świadomą czynnością.
Nie zmienia jego epoki lub zgód i nie tworzy automatyzacji/harmonogramu.

Manifest wiąże pliki rozmiarem/SHA256, epoką, schematem, datą oraz prywatnymi
fingerprints kont i tożsamości. Verify odmawia niekompletnej, zmienionej lub
wychodzącej poza katalog kopii. Te hashe wykrywają zmianę danych; zaufanie do
kopii wynika z chronionego miejsca i właściciela. Kopie zawierają dane i sekrety,
więc manifest/config/logi/archiwa nie są publikowanym artefaktem CI lub Git.
Poza komputerem kopia wymaga chronionego, szyfrowanego magazynu i polityki O3.

Rehearse uruchamia nowy losowo nazwany, oznakowany PostgreSQL bez publicznych
portów. Nie przywraca danych do istniejącego serwera. Odtwarza globals i obie
bazy przez rzeczywiste pg_restore, sprawdza schemat, liczniki i fingerprints,
a następnie atomowo zamyka Nemesis, zmienia sync_epoch i usuwa stare snapshoty.
Istniejący trigger zamyka AI dispatch. Owner-only bounded cleanup anuluje stare
Nemesis i czyści stare odpowiedzi/kody/kursory do pending0. Nie przestawia
capability lub affirmation na nową epokę. Kontener finalizera nie dostaje
uprawnienia do aktywacji; jego rzeczywisty odtworzony SCRAM LOGIN zwraca readyfalse.

Katalog odtwarza się do nowego prywatnego scratch. Dopuszczone są tylko zwykłe
pliki/katalogi pod catalog, bez przejść `..`, symlinków, hardlinków lub devices.
Data filter i ponowne hashowanie sprawdzają zawartość. AI/photo transient storage
nie należy do tej kopii. W finally usuwany jest tylko własny oznakowany kontener
próby i jego anonimowe wolumeny; backup i prywatny receipt pozostają.

## Wykonany odbiór lokalny

Własne nowe środowisko HTTPS/Keycloak/PG17 z odbioru workerów PR44, immutable0021.
Cudzy zestaw integracyjny, źródła Random Data i checkouty pozostałych autorów
pozostały nietknięte. Finalny capture miał6 kont aplikacji i9 tożsamości;
**6,697s capture, 10,07s offline rehearsal**. To pomiary tego małego lokalnego
zestawu, nie RPO lub czas przywrócenia dostępności produkcyjnej.

Pięć wykonanych zakresów PASS: rzeczywisty restore obu baz/globals i pierwotnej
epoki, fingerprints kont/Keycloak, trwała nowa epoka i fence/snapshot cleanup,
bezpieczne odtworzenie katalogu z hashowaniem oraz rzeczywisty minimalny SCRAM
finalizer z zamkniętą bramką. Ruch nie został otwarty. Wcześniejszy prywatny
harness zatrzymał parsowanie JSON na tagu SET emitowanym przez psql; poprawiono
wyłącznie tryb quiet, zachowując pierwotny log. Wersjonowana procedura używa -qAt.

**44 testy infrastruktury PASS w7,39s**, w tym12 nowych dotyczących zmienionej
kopii, brakującej połowy zestawu, niezamkniętych writerów, istniejącego katalogu,
binary catalog i odrzucenia traversal/links/devices. Ruff/format/diff-check PASS.
CI wykonuje tę samą rzeczywistą capture/rehearse na własnym lokalnym zestawie
i publikuje tylko wynik bez sekretów. Lokalny wynik nie zastępuje finalnego CI/main.

## Warunki przed rzeczywistym reopen

Rehearse celowo kończy się przy zamkniętym ruchu. Do przywrócenia używanej
instalacji nadal wymagane są: niezależny od cofanej kopii aktualny rejestr
ukończonych usunięć/blokad, odcięcie issuance i starych JWT/refresh/sesji,
uzgodnienie kont z Keycloak, klient ze starą epoką i świadome recovery/KO-32,
kontrola ranking/sharing bez starego regrant oraz właściwy rollout O1/O2/O3.
Nie wolno przywrócić usuniętych po kopii kont przez samo odtworzenie obu baz.
Rzeczywiste AI pozostaje zamknięte według336h i fizycznego fencing E7;
procedura nie zmienia closed_at ani nie uruchamia starych zleceń dostawcy.

Produkcyjny magazyn kopii, retencja/schedule, RPO/RTO, public origin/VPS/domena/SMTP
i odbiór APK wymagają właściwego środowiska i danych konfiguracyjnych właściciela.
Te rzeczywiste odbiory pozostają WAITING_EXTERNAL. Narzędzie dostarcza lokalną
kopię i próbę z fencing; nie oznacza PASS całego E8 lub zgody na E9/Google/billing.

## Uzupełnienie lokalnego odbioru — 13 października 2026

Osobna [próba sesji, deletion i klienta](ODTWORZENIE_SESJE_I_KLIENT_O3.md)
wykonała rzeczywiste odtworzenie z HTTPS/PKCE, ponowne usunięcie konta na
podstawie nowszego lokalnego rejestru oraz odmowy starych JWT/refresh/epoki
i świadome recovery utraconego zapisu. Rejestr jest prywatnym niezależnym fixture;
nie stanowi wdrożenia produkcyjnego magazynu. Historyczna offline rehearsal
i jej pomiary zachowują swój zakres, a `rehearse` nadal nie otwiera ruchu.
