# Poczta i dostęp do lokalnego demo — O3

Właściciel ograniczył bieżący odbiór do demo lokalnego. Potrzebne są działający
APK, logowanie i próby funkcji z lokalnym API. VPS i domena pozostają poza tym
odbiorem. Zakres produkcyjny z wymagań nadal wymaga osobnego wykonania.

## Skrzynka do resetowania hasła

[`compose.demo-mail.yaml`](compose.demo-mail.yaml) dodaje Mailpit 1.32.0 do
**istniejącej** sieci integracyjnej. Obraz jest przypięty SHA256. Nie przebudowuje
API i nie uruchamia migracji. Przed użyciem sprawdź nazwę własnej sieci; poniżej
nazwa użytej instalacji O3, nie automatyczne wykrywanie dowolnego projektu:

```powershell
$env:DEMO_NETWORK = 'calorie-integration_default'
docker network inspect $env:DEMO_NETWORK --format '{{.Name}}'
docker compose --project-name calorie-o3-demo-mail --file infra/integration/compose.demo-mail.yaml config --quiet
docker compose --project-name calorie-o3-demo-mail --file infra/integration/compose.demo-mail.yaml pull
docker compose --project-name calorie-o3-demo-mail --file infra/integration/compose.demo-mail.yaml up --detach --no-build --pull never
```

Wiadomości czytaj na [http://127.0.0.1:18025](http://127.0.0.1:18025), wyłącznie
na komputerze gospodarza. SMTP jest dostępne wewnątrz sieci Docker jako
`calorie-demo-mailpit:1025`; nie ma portu SMTP opublikowanego na gospodarzu.
Dozwoleni są wyłącznie odbiorcy w domenach `invalid.example`, `example.test`
i `calorie-demo.test`. Usługa przechwytuje wiadomości i nie ma skonfigurowanego
przekazywania poczty do zewnętrznego dostawcy.

Rzeczywista próba SMTP RCPT TO potwierdziła `250` dla adresu testowego
i `550` dla adresu spoza tych domen; w tej próbie nie wysyłano treści wiadomości.

Kontener ma UID 10001, read-only rootfs, brak capabilities i tymczasową bazę
na tmpfs. Limit wynosi 100 wiadomości; restart kontenera usuwa skrzynkę.
Wiadomości zawierają aktywne linki resetowania hasła: nie publikuj ich ani
widoku skrzynki w GitHubie. Dane kont demonstracyjnych przechowuj prywatnie.

## Konfiguracja istniejącego Keycloak

Administrator ustawia w realm `calorie-dev` sekcję Email:

| Pole | Wartość lokalnego demo |
|---|---|
| Host | `calorie-demo-mailpit` |
| Port | `1025` |
| From | `noreply@calorie-demo.test` |
| From display name | `Kalorie demo lokalne` |
| Authentication, SSL, StartTLS | wyłączone, tylko prywatna sieć kontenerów |

W Login włącz **Forgot password** (`resetPasswordAllowed=true`). Konto do próby
ma mieć zweryfikowany adres z jednej z domen testowych i rolę API `user`.
Nie potrzebuje uprawnień administratora. Rejestracja publiczna pozostaje
wyłączona. Zmiana dotyczy działającego realm; ponowny start z plikiem importu
nie aktualizuje już istniejącego realm.

Zapisz te same ustawienia w prywatnym szablonie `realm/calorie-dev.json` stanu
instalacji, zachowując pozostałe pola. W prywatnym `demo-mail.env` zapisz
`DEMO_NETWORK`, dokładny `DEMO_MAIL_IMAGE` z Compose i SHA256 pliku Compose
jako `DEMO_MAIL_COMPOSE_SHA256`. Istniejący backup kopiuje pliki `*.env`,
`realm/`, TLS i obie bazy. Źródło Compose zachowaj na odebranym commicie.
Reguła `.gitattributes` zachowuje jego bajty LF również na Windows.
Po odtworzeniu uruchom osobny projekt poczty powyższymi poleceniami w tej
samej sieci; zawartość skrzynki jest celowo nietrwała.

## Powrót do demo po restarcie emulatora

Zachowaj dane własnego AVD i uruchom go ponownie bez `-wipe-data`.
Po pełnym starcie i `adb root` użyj `android_transport.py ensure` z tym samym
`--adb`, `--serial`, `--avd`, `--state` i prywatnym `--lease` co wcześniej.
Oryginalny adres HTTPS, issuer i CA pozostają takie same.

`ensure` sprawdza istniejące połączenie z bieżącego uruchomienia. Po restarcie
może odtworzyć transport, jeśli stary zapis ma dokładnie tę samą tożsamość
AVD i adresu, inny boot ID, a jego łańcuch NAT i mapowanie reverse już nie
istnieją. Najpierw zachowuje cały stary plik jako `*.stale-<sha256>.json`.
Istniejący plik archiwum, obce reguły lub inne dane właściciela zatrzymują
operację. Nie usuwa istniejących tras w celu wymuszenia połączenia.

Po pokazie użyj `disconnect` z tymi samymi argumentami, a potem zatrzymaj AVD.
`connect`, `status` i `disconnect` zachowują ścisłą kontrolę bieżącego boot ID;
`ensure` jest osobnym działaniem do wznowienia. Próba na własnym emulatorze
po restarcie komputera oraz 18 testów kontroli właściciela przeszły
24 października 2026. Sam transport nie potwierdza logowania ani synchronizacji.

## Wykonany odbiór O3, 23 października 2026

Na istniejącym API/schema `0024_e9_history_graph` wykonano prawdziwy formularz
**Forgot password**, dostarczenie jednej wiadomości przez SMTP, użycie linku
z oryginalnym TLS/issuer i logowanie nowym hasłem przez Code + PKCE S256.
Nonce i podpis JWT sprawdzone. Stare hasło odrzucone; stary refresh token
otrzymał `HTTP 400 invalid_grant`. Wynik **PASS**, 17:30:46 UTC, 2,032 s.
Własna jednorazowa tożsamość testowa została usunięta. Hasła wcześniejszych
kont pozostały zachowane. Osobne konto demo z rolą `user` ma sprawdzone PKCE;
jego dane początkowe są dostępne wyłącznie prywatnie u właściciela.

Po tych zmianach ręcznie uruchomiono zainstalowany, przypięty runtime backupu
0024, z pominięciem kontroli terminu kolejnej kopii. Nowa spójna kopia obu baz
i konfiguracji przeszła integralność oraz rzeczywiste odtworzenie offline
**PASS, 11,191 s**, 17:39:06 UTC. Usługi wznowione. To lokalna kopia nowego
stanu; nie jest potwierdzeniem jej nowego uploadu offsite ani przejścia na 0026.

Świeży własny AVD API35 przeszedł próbę HTTPS do API i discovery z właściwym
CA, hostname i issuer; błędne CA odrzucone, transport zamknięty po teście.
Ta próba sprawdza łączność Android VM. Końcowy skonfigurowany APK oraz
logowanie z aplikacji, synchronizacja i E4 wymagają odbioru właściwej wersji
Androida. Lokalna poczta nie potwierdza dostarczania email w produkcji.

## Odbiór lokalnego APK, 24 października 2026

Oryginalny pakiet A1 `5b283e4`, 0.8.29.validation/code1040/Room20, przeszedł
niezależną kontrolę czterech APK, podpisów oraz rzeczywistej konfiguracji CA,
issuer i API. [Manifest wejścia](../../android/KANDYDAT_E4_0_8_29.json) zachowuje
sumy dostarczonych plików. [Neutralne dowody operatora O3](https://github.com/Roseru/aplikacja-mobilna/releases/tag/untagged-d85ad9133083bfcca3ca)
są w roboczym wydaniu wymagającym dostępu do repozytorium.

Na własnym AVD i używanym API05/schema0024 wykonano Chrome/PKCE, bootstrap
i pełną kopię. Profil zapisano przed pierwszym celem; użytkownik jawnie podał
2300 kcal. Normalny interfejs utworzył offline profil, cel, wagę, produkt
prywatny, posiłek i kompletność dnia. Kolejka przetrwała restart. Jedna partia
otrzymała sześć `accepted`, revision1 i sześć trwałych lokalnych ACK.
Pełna treść w PostgreSQL odpowiada utrwalonym operacjom, w tym wartościom null.

Osobny E4 dotyczył jednej nowej operacji Meal. Po HTTP200 i niezależnym PG C1
rzeczywiście zatrzymano proces przed ACK. Restart wysłał identyczną partię,
otrzymał `already_applied`/revision1 i zapisał ACK; kontrola33tabel przeszła.
PG C2 zachował stan C1. Dopiero osobny późniejszy pełny PULL zmaterializował
nowy DiaryDay. Przed nim dnia nie było lokalnie; po nim payload i revision1
odpowiadały serwerowi, bez kolejnego POST lub duplikatu.

Te wyniki kwalifikują wskazane APK/Room20 do opisanych lokalnych prób.
Nie zastępują odbioru nowszego Room22, WorkManagera z docelową polityką sieci,
fizycznego telefonu, Gemini, pełnego KO32 lub wdrożenia produkcyjnego.
Historyczny FAIL E4 Room17 pozostaje osobnym wynikiem.

## Złożenie kolejnego pakietu po odbiorze APK, E4 i osobnego PULL

Poniższa procedura przygotowuje lokalny pakiet `channel=integration`,
`scope=localdemo`. Nie nadaje nowego PASS historycznemu Room20 ani nowszemu
Room23. Podstawą są rzeczywiste receipty z
[procedury E4](../../docs/integracja/PRZYGOTOWANIE_REPLAY_E4_O3.md).
Przed składaniem muszą istnieć niezależny STATIC_PASS dostawy czterech APK,
kwalifikowane `android_acceptance`, wynik E4 z niezależnymi PG C0/C1/C2
i trwałym ACK, oddzielny późniejszy PULL oraz uwierzytelniony wynik MRE119
z receiptem/SHA i closure. FAIL lub NOT_RUN któregokolwiek
wymaganego odbioru zatrzymuje składanie nowego finalnego pakietu.

Aktualna kolejność zatwierdzona przez właściciela: **rzeczywisty import118
i cleanup → actual acceptance108 → nowe E4/PG oraz osobny PULL110 i zwrot
operatorów → osobne wyłączne okno i rzeczywisty MRE push/replay/read119
z cleanupem oraz jawnym zwrotem → finalny pakiet111 oraz jedna końcowa kopia
z isolated restore**.
Wcześniejsze oczekiwanie na E4 przed importem jest historyczne. Techniczne
zwolnienie rezerwacji110 dla uzgodnionego slotu importu nadal jest wymagane;
może wynikać z decyzji o zmianie kolejności, bez fikcyjnych receiptów E4/PULL.
Zakończonych kwalifikacji117/PR189 i PR186 nie ponawia się dla pakowania.

Operator potwierdza zakończenie transportu poprzedniej próby i zwolnienie jej
dzierżawy. Następnie atomowo tworzy własny `runtime.lock`, bez odbierania
cudzego locka. Zachowuje go do końca kontrolowanej operacji, także podczas
kopii. Blokada koordynacji nie zastępuje OS locka istniejącego utrzymania.

### Manifest zachowujący tożsamość zestawu

W nowym, nieistniejącym wcześniej prywatnym folderze na uzgodnionym dysku
zachowaj dostawę czterech APK, jej oryginalny manifest i raport statyczny,
publiczny CA, katalog demo, neutralne receipty i instrukcję START.
Nie nadpisuj wcześniejszych pakietów. Manifest pakietu zapisuje osobno:

| Część | Wymagane powiązanie |
|---|---|
| Android | odrębne bindingi frozenRoom23 i skonfigurowanego MRE0.8.40/Room27: source/receipt commit, Android tree, Room, role/wersje/applicationId/podpisy/rozmiary/SHA256, manifest dostawy i rzeczywiste compiled API/issuer/CA |
| Uruchamiana aplikacja | dokładny APK z własnym zgodnym receiptem:108 dla frozenRoom23,119 dla configuredMRE27; wynik108 nie kwalifikuje Room27. validation-configured jest osobną aplikacją, regularny debug bez endpointów nie zastępuje jej |
| API | faktyczny immutable image, schema i rzeczywiste pochodzenie; brak OCI revision pozostaje jawny, archiwalna zgodność wybranych plików nie dowodzi commita całego obrazu |
| TLS | API base URL, dokładny issuer, publiczny PEM i jego SHA256, bez klucza prywatnego CA |
| Katalogi | osobna pozycja dla każdego package ID/kind/release/schema/reader, miejsca użycia, SHA256 i rozmiaru gzip/manifestu; asset APK i aktywna generacja Room są oddzielne od zapieczętowanego draftu serwera |
| Odbiory | źródła, hashe, rzeczywiste zakresy i ograniczenia android_acceptance/E4/PG/osobnego PULL oraz osobnego uwierzytelnionego119; zgodna instalacja, API/schema i epoka oraz oddzielny closure każdego okna |
| Kopia | hash manifestu nowej kopii, wynik integralności i izolowanego rehearsal, hash zaszyfrowanego pliku; zachowanie epoki i usług źródłowych |

Pełne tożsamości instalacji/konta, epoka, ścieżki prywatne i raw dowody pozostają
w prywatnym przekazaniu. Publiczny opis zawiera tylko zatwierdzoną projekcję.
Nie przepisuj receiptów w celu uzyskania wspólnego commita. Istniejący
[`release.py`](release.py) waliduje inny kontrakt: jeden wspólny commit APK,
OCI revision i pięciu odbiorów opisanych w [WYDANIE.md](WYDANIE.md).
Nie jest generatorem tego wieloźródłowego pakietu i nie kwalifikuje go przez
zmianę etykiet. Zachowaj jego dotychczasowe wymagania.

### Rzeczywisty kanał katalogu demo

Katalog startowy jest assetem APK `assets/catalog/e2/manifest.json` oraz
`assets/catalog/e2/base-pl.1.json.gz.bin`. Rozszerzenie `.bin` chroni gzip
przed automatycznym rozpakowaniem podczas budowania APK. Eksport referencyjny
leży w [`backend/data/demo/export`](../../backend/data/demo/export/manifest.json).
Reader sprawdza manifest i importuje tę generację do Room. Hashe plików w repo
sprawdź również wewnątrz faktycznie odebranego APK; same źródła nie dowodzą
instalacji lub importu. Pakiet `kind=demo` pozostaje oznaczony jako demo.

`GET /api/v1/offline-package/manifest` zwraca manifest opublikowanego **official**.
Przy braku official zwraca404; demo dostarczone w APK nie pochodzi z tej ścieżki.
Nie opisuj404 jako pobrania katalogu albo awarii całego API. Odbiór katalogu
demo wymaga jego rzeczywistych bajtów i aktywnej generacji. Jeżeli uzgodniony
scenariusz wymaga konkretnego official, brak przekazania zgłoś O2; nie publikuj
fikcyjnego katalogu w ramach pakowania.

### Zakres MRE po PR188

Zamrożone APK Room23 `2319357` zawierają tylko pierwotny pakiet E2
`47bdff67-e58b-5437-919b-ec00159afbc5`, bez assetów MRE. Nowy
[katalog MRE](../../android/MRE_2026.md) jest osobnym demo release1:
`3aa9b766-b01d-5111-8fd0-4c5b6257961b`, 111 produktów / 24 racje / 235 komponentów /
112 źródeł. Nie zmienia źródła APK23 ani nie ustala commita starszego obrazu API.

Manifest i START nazywają dokładny wariant. Dla pakietu uruchamiającego
odebrany Room23 zapisują jego własne wyniki i katalog E2. Jeżeli dołączamy
przygotowanie MRE na serwerze, jest ono osobnym zakresem danych, bez obietnicy
UI MRE w APK23. Wariant uruchamiający klienta MRE Room27 wymaga odrębnej
dostawy APK/source/tree/hashów i właściwego odbioru runtime tego klienta;
wyniki Room23 nie kwalifikują go automatycznie.

Serwerowy zakres MRE wymaga kwalifikowanego scratch O3-117 na dokładnym
image/schema i osobnego wyniku rzeczywistego importu O3-118. Sam scratch
nie jest odbiorem zmiany żywej instalacji. Import wykonuje wyłącznie jego
operator, po skutecznym technicznym przekazaniu rezerwacji przez109/110
i uzgodnieniu świeżego dokładnego okna. Zgoda właściciela na import przed E4
pozwala na takie przekazanie mimo E4/PG/PULL NOT_RUN; nie tworzy ich PASS.
Brak runtime.lock lub wygasły transport nie zastępują skutecznego przekazania.
Zakończone117 nie czeka na finalny pakiet lub kopię111 i nie wymaga ponowienia.
Operator118 bierze własne blokady wyłącznie dla swojego zaakceptowanego slotu;
operator111 nie zajmuje runtime.lock podczas oczekiwania.

Po rzeczywistym receipcie118, cleanupie i jawnym powrocie operatorów następuje
odbiór aplikacji108, a później nowa próba110. O1 rozlicza zastany stan swojego
profilu/fence, bez przejmowania stanowiska. Wymagane są świeży bootstrap,
odrębny pełny snapshot po imporcie, nowy trial/plan PG i rzeczywisty C0.
Stary baseline sprzed importu nie dowodzi zgodności nowego stanu katalogu.
Import118 obejmuje katalog; nie jest authenticated push/read ani odbiorem APK.
Pakowanie i kopia111 czekają również na końcowy E4/PG/osobny PULL110,
cleanup, zamknięcie lease i jawny zwrot wszystkich operatorów, a następnie
na osobny wynik119 opisany poniżej.

### Osobna bramka uwierzytelnionego MRE119

Po rzeczywistym108, E4/PG i osobnym PULL110 oraz cleanupie/jawnym zwrocie
operatorów wykonawca119 uzgadnia własne nowe wyłączne okno. Nie uruchamia
próby podczas frozen E4 ani na podstawie wygasłego slotu118. Przygotowanie
planu i odczyt istniejącej dostawy APK mogą odbywać się równolegle.

Finalny manifest wymaga receiptu119 z hashem i prawdziwym bindingiem
skonfigurowanego MRE0.8.40/Room27: APK/source/tree/SHA256/podpis/appId/wersja
oraz compiled API/issuer/CA. Binding Room23 i jego receipty pozostają osobne;
nie opisuj go jako klienta MRE. Rzeczywisty obraz OCI05/schema0024/PG17.11
zachowuje pełne źródło Git UNKNOWN. Aktualny main nie jest jego buildem.

Odbiór119 obejmuje rzeczywiste TLS/PKCE/logowanie z tego APK i nowy Meal na
zaimportowanych referencjach MRE: push, trwały wynik, replay tego samego wire
(UUID/body/fingerprint), `already_applied`, read/pull i brak duplikatów.
Receipt119 wiąże hash rzeczywistego importu118 oraz zakończoną próbę110/zwrot.
Syntetyczny serwerowy probe117 ani sam import118 nie zastępują tej próby.
Nie zmieniaj UUID utrwalonej odmowy `dependency_missing`, aby uzyskać PASS.
Wymagaj dowodu zachowania istniejących danych/epoki, cleanupu119, zamknięcia
lease i jawnego zwrotu jego operatora. Dopiero ten wynik zamyka bramkę119.

START wskazuje faktycznie odebrany końcowy APK/profil ze zgodnego receiptu,
zachowując artefakty i dowody Room23 oddzielnie. Nie zakładaj równoczesnej
instalacji obu wersji lub możliwości uruchomienia starszego Room23 na bazie27.
Nie twórz zastępczego profilu/konta ani nie przejmuj stanowiska O1 w celu
obejścia brakującego wejścia. Brak configured APK, operatora, rzeczywistego
konta lub receiptu119 pozostaje konkretnym brakiem finalnego pakietu.

Nowy pakiet otrzymuje `state=draft`, `sealed=true`. Import nie publikuje ani
nie aktywuje kanału. Dla nowego kanału `active_release=null`; istniejącego
wskaźnika import nie zeruje, a zgodny istniejący release może zostać zwrócony
bez nowego zapisu. Rzeczywisty stan potwierdza odbiór118, bez `publish`.
Nie oczekuj nowej aktywacji kanału serwera lub pliku gzip w wolumenie
publikacji. Właściwy dowód obejmuje identyczne wejście, membership i zawartość
rekordów, idempotentny ponowny import oraz rzeczywisty eksport/hash.
`catalog.tar` i official404 nie zastępują tych dowodów.
Aktywna generacja Room jest odrębnym wynikiem klienta korzystającego z MRE.

W manifeście zapisz także hashe reguł wyboru i materiału pochodzenia, jeżeli
pakiet je zawiera. `source.json` opisuje pochodzenie COMRAD; wejściem CLI
importu jest rozpakowany payload E2 z właściwego gzip. Dla zatwierdzonego
release1: manifest4769B/SHA256
`dc0a0b9b818dd7ea9f224424c6fe07b11d8af574dbb6109a9658c12297c149bf`,
gzip27924B/SHA256
`2c0a1ff730e408cc90ab1fcfcb2b9eef21ebce8fa2d935d429f296d225260880`,
payload246314B/SHA256
`0552172f59de3f71597074b88dcb99c22d8c227eba7cb3ce96ac30f3e0a9d967`.
Każdy receipt zachowuje własny zakres, rzeczywisty target i hashe dowodów;
nie przepisuj pinu API na commit katalogu z PR188.

### Jedna kopia zmienionego stanu i lokalny plik szyfrowany

Jedną końcową kopię wykonaj po wszystkich zaakceptowanych zmianach objętych
pakietem: imporcie118, acceptance108, nowym E4/PG/osobnym PULL110 i closure,
a potem uwierzytelnionej próbie119 i jej closure/zwrocie operatora.
Nie wykonuj kopii111 przed importem i drugiej po nim; już istniejąca kopia
harmonogramowa może stanowić odrębne zabezpieczenie operatora118.
Nową kopię uzasadnia zaakceptowana zmiana danych. Zdrowa wcześniejsza
kopia i startup nie wymagają ponawiania z powodu czasu spędzonego w czacie.
Użyj zainstalowanego, przypiętego runtime zgodnego ze schematem działającego
API, jego interpretera i oryginalnego prywatnego settings utrzymania. Bieżący
main może oczekiwać innego schematu; nie przeinstalowuj runtime dla tej kopii.

[`maintenance.py`](maintenance.py) `perform_backup` wykonuje capture,
integralność, wznowienie tych samych usług w finally, izolowany restore
i ponowną integralność. Wywołanie operatora używa `due_only=False`, dopiero
po wejściach odbioru. Sam `backup.py capture` pozostawia usługi zatrzymane
i nie bierze OS locka automatyzacji; nie uruchamiaj go równolegle.

Przy wymaganiu zachowania wszystkich starszych kopii standardowa retencja14
nie jest odpowiednia. Pod tym samym `maintenance.lock(directory)` odczytaj
oryginalne settings do kopii słownika w pamięci i ustaw jej `keep` na
`max(stored_keep, liczba_wszystkich_bezpośrednich_wpisów_root + 1)`.
Wywołaj istniejące `perform_backup` z tą kopią settings, bez zmiany zapisanego
pliku i bez podmiany funkcji retencji. Kandydaci usunięcia są podzbiorem tych
wpisów; jedna nowa kopia mieści się w tak dobranej granicy. Po wykonaniu
wymagaj `removed=0`, obecności wcześniejszych wpisów i niezmienionych settings.
Sprawdź też zgodne identyfikatory usług przed/po, `resume_pending=false`,
niezmieniony image/schema/CA i epokę żywej instalacji. Nieznany lub nieudany
stan kończy operację z rzeczywistym FAIL; nie wykonuj automatycznie drugiej kopii.

Próba odtworzenia używa wyłącznie nowego PG bez sieci i portów gospodarza.
Nowa epoka oraz fencing AI/Nemesis dotyczą wyłącznie tej izolowanej kopii.
Nie przywracaj jej na działające demo. Zachowaj wynik i cleanup własnego
kontenera zgodnie z [runbookiem utrzymania](UTRZYMANIE_LOKALNE.md).

Z tej samej, już sprawdzonej kopii przygotuj istniejącym
[`offsite_package.py`](offsite_package.py) jeden nowy plik szyfrowany:
`pack --backup <nowa-kopia> --output <nowy-plik.enc> --key <istniejący-klucz>`.
Następnie `verify --package <nowy-plik.enc> --key <istniejący-klucz>` potwierdza
uwierzytelnienie i sumy wszystkich członków. Użyj rzeczywiście zainstalowanej
pary interpreter/skrypt szyfrowania w osobnych procesach. Starszy runtime
utrzymania może nie zawierać tego modułu; nie mieszaj importów różnych runtime
w jednym procesie ani nie naprawiaj zdrowego środowiska. Klucz pozostaje osobno, prywatnie,
w już uzgodnionym miejscu. Nie twórz/nie rotuj go ani nie kopiuj do pakietu.
Ten lokalny eksport na dysk nie jest uploadem offsite; `offsite_verified=false`
pozostaje prawdziwą granicą wyniku i nie blokuje uzgodnionego lokalnego demo.

### Instrukcja START i końcowe przekazanie

START podaje rzeczywiście odebrany AVD/serial/applicationId, właściwy APK,
prywatną lokalizację danych konta i drogę wznowienia sesji. Zachowaj dane AVD,
bez wipe lub odinstalowania. Przed połączeniem operator sprawdza hash APK i CA,
image/API/issuer oraz tożsamość AVD; komendy i wyniki tego preflight zapisuje
w START i dowodach. Następnie używa istniejącego transportu `ensure` z własnym
lease; zakończenie używa `disconnect` z tym samym lease. Sam transport nie
sprawdza APK ani image i nie zastępuje tych odczytów operatora.
Nie otwieraj nowego transportu podczas aktywnego okna poprzedniego operatora.

Zapisz sumy i rozmiary dokładnego zbioru zwykłych plików pakietu (lista sum
wyłącza samą siebie), odmów symlinków/junctions i wyjścia poza nowy folder.
Zweryfikuj brak brakujących/dodatkowych plików i ponownie odczytaj sumy.
START, transport, konta i pliki wyników mają odpowiadać temu samemu zestawowi.
Przed zapisem potwierdź rzeczywistą dostępność uzgodnionego dysku D: i jego
istniejących prywatnych katalogów/klucza, bez odczytywania klucza do logu.
Jeżeli celu nie ma lub jest nieczytelny, zachowaj stan i wskaż konkretny brak;
nie wybieraj niejawnie innego dysku ani nie nadpisuj wcześniejszych kopii.
Końcowe prywatne przekazanie podaje faktyczny folder, hashe paczek i receiptów,
zakończenie lease/runtime oraz ograniczenia. Brak E4/PULL oznacza oczekiwanie,
bez nowego finalnego pakietu lub kopii. Wynik tego zakresu nie zamyka całego
v1, AI, telefonu fizycznego ani wdrożenia produkcyjnego.

Po stagingu jednego zestawu na D: wykonaj jedną kopię końcowego zmienionego
stanu, szyfrowany eksport i rzeczywisty izolowany restore. Dopiero następnie
domknij manifest/powiązania i przekaż je niezależnemu audytorowi O3-120.
Audyt120 nie zastępuje operatorstwa111 ani brakującego receiptu119.
Przed ostatecznym zamknięciem backlogu rozlicz kwalifikowane odbiory źródeł
PR185→PR184 i własnego funkcjonalnego PR/main. To osobna zgodność repozytorium;
nie oznacza rolloutu tych pinów ani zmiany pełnego źródła obrazu05 z UNKNOWN.

Źródła konfiguracji Mailpit: [Docker](https://mailpit.axllent.org/docs/install/docker/),
[API skrzynki](https://mailpit.axllent.org/docs/api-v1/),
[wydanie 1.32.0](https://github.com/axllent/mailpit/releases/tag/v1.32.0).
