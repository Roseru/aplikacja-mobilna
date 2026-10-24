# Pobieranie bazy offline — implementacja O1 w toku

Gałąź `codex/android-katalog-do-pobrania`, baza main837343c.
To rozpoczęty kolejny etap; pełne wpięcie, odbiór, APK i PR pozostają otwarte.
Nie zmienia zamrożonej dostawy0.8.29/Room20 dla O2/O3.

## Zachowanie

Moduł korzysta z publicznych `GET /api/v1/offline-package/manifest` oraz
`GET /api/v1/offline-package/base-pl.<release>.json.gz`. Nie używa sesji,
tokenu ani logowania. Official ma stałe ID
`c12631e2-1a02-547c-a7f9-ebf87bb42e55`;404 oznacza brak opublikowanej bazy,
a nie polecenie zastąpienia jej demonstracyjnymi danymi.

Sprawdzenie wersji i pobranie wymagają osobnych działań użytkownika.
Wybrany manifest przypina release, ścieżkę, rozmiary i SHA256. Transport
nie przekierowuje, nie przyjmuje dodatkowego Content-Encoding i ogranicza
czas/rozmiar odpowiedzi. Blokada sieci albo anulowanie rozłącza także socket.
429/503 ma trwały Retry-After bez automatycznej pętli ponowień.

Sprawdzenie manifestu i pakietu korzysta z tego samego CatalogPackageReader
co osadzone demo: tożsamość, wersje czytnika/schematu, gzip/CRC, hash,
rozmiary, graf referencji i wymagane dane official. Stage i aktywacja
CatalogStore są objęte jedną zewnętrzną transakcją Room. Błąd nie podmienia
aktywnej generacji, a starszy równoległy download nie cofa nowszego release.
Tymczasowy plik leży w prywatnym cache aplikacji i jest usuwany w finally.
Nie ma nowej migracji ani zapisu do dziennika/kolejki użytkowników.

Panel pokazuje zapisane wydania, DEMO/official, datę, liczby produktów,
racji/składników i źródeł, dostępną aktualizację, postęp i jawne anulowanie.
Źródła konkretnego zapisanego release można przeglądać **bez sieci**:
paginacja po5, data weryfikacji, producent/rynek/wariant, jednostka odniesienia,
uwagi i braki danych. Długie listy są renderowane lazily. URL jest tekstem
do skopiowania; podgląd nie otwiera strony internetowej.

## Granica integracji z O2-C

O2 potwierdził [faktyczny brak portu w C](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6374626101).
O1 przejął jeden kontrakt i trwały provider w `core/network`: NetworkAccessGate,
NetworkAccessState.Unavailable/Blocked/Allowed(revision), NetworkPermit,
captureAllowed i requireCurrent. Nie powstaje niezależny drugi boolean.
Permit ma również tożsamość providera i lokalną generację, więc ponowne
Allowed po błędzie albo przejściu przez Blocked nie przywraca starego pozwolenia.

DeviceNetworkPolicy przechowuje jedno ustawienie urządzenia w DataStore,
oddzielone od motywu i konta. Domyślny standard jest dozwolony dopiero po
prawidłowym odczycie. Błąd zapisu/odczytu zamyka gate; jawna zmiana/naprawa
zwiększa rewizję. Polityka nie wyłącza Wi-Fi telefonu i nie kasuje dziennika.
Katalog przechwytuje permit dla operacji i ponownie sprawdza go w transporcie,
po walidacji oraz przed stage/activate. Podgląd źródeł nie wymaga pozwolenia.

PolicyConnectionFactory osłania HTTPS dla API/AppAuth z oryginalnym TLS,
zamykając połączenia przy zmianie polityki. AppAuthGateway przyjmuje builder
oraz gate; ich domyślne wartości są zamknięte. Faktyczny CalorieApplication
podaje wspólny provider i builder wszystkim jedenastu gatewayom API oraz
AppAuth. Kontrola obejmuje także zamknięcie strumieni odpowiedzi/żądania.
**Odbiór gotowej aplikacji i wpięcie tego gate do runtime nadal są wymagane**.

SettingsScreen przyjmuje opcjonalne CatalogUpdateViewModel oraz
NetworkPolicyViewModel. O2 zakończył A/B/C i [zwolnił root/DI na mainb245077](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6376449465).
O1 dołączył tę bazę zwykłym merge589e3c9. Addytywne wpięcie jest zapisane
w be2b91c i poprawione w1a6f9db; zakres O1 ma opisany niżej odbiór integracyjny.
O1 [podał dokładny nowy zakres i typy](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6374865798),
nie nadpisując MainActivity/CalorieApplication/App ani Workera C.
B/C kontynuują niezależnie. Pełny WF-05 wymaga wszystkich konsumentów:
katalogu, API, logowania i wspólnego runtime/workera, w tym wybudzenia po
odblokowaniu. Sam CONNECTED ani sama gotowa preferencja nie są jego odbiorem.

Właściwe DI ma tworzyć **jeden** DeviceNetworkPolicy i jedną fabrykę
połączeń dla aplikacji; oba modele ekranów żyją poza kluczem właściciela.
CatalogUpdateFactory.repository otrzymuje ten sam provider co API/AppAuth
oraz runtime, bez stałego `true` i bez osobnego przełącznika.
Kompilacja portu jest osobnym zakresem; nie zastępuje testu gotowej funkcji.

W kodzie O1 na C/Room22 istnieją po jednej instancji DeviceNetworkPolicy,
PolicyConnectionFactory oraz repozytorium katalogu w Application.
Modele ustawień/katalogu używają jawnego activity ViewModelStoreOwner poza
kluczem właściciela dziennika. Przed fizycznym otwarciem przeglądarki MainActivity
ponownie sprawdza permit; logout oraz lokalne zastosowanie kopii pozostają
oddzielnymi działaniami. Nawigacja zachowuje import i status synchronizacji C.
Ekrany serwerowe pokazują blokadę oraz skrót do Ustawień, z uwzględnieniem
obszaru paska systemu. Dziennik pokazuje faktyczny stan polityki i zapisane
wersje baz, liczbę zmian oraz odmowy serwera. Data ostatniej pełnej kopii
jest datą kopii; nie oznaczamy nią zakończenia całego cyklu PULL→PUSH→PULL.

Jedyny nowy scenariusz nawigacji używa rzeczywistych Application/MainActivity:
ustawienie poligonowe, źródła, odtworzenie activity, nowa generacja gościa,
skrót z konta, zapis posiłku i ponowne odtworzenie. Drugi wybrany przypadek
rozszerza istniejący test transportu o zamykanie odpowiedzi po ABA.
Pierwszy build be2b91c zatrzymał się przed Kotlin na brakującym w lokalnym
cache przypiętym WorkManager2.10.5 z C. Wynik jest zachowany, bez testów.
Nowy build1a6f9db pobrał brakującą zależność ze skonfigurowanych repozytoriów;
wyniki obu scenariuszy są poniżej. Nie zmieniono wersji zależności z C.

## Odbiór po ukończeniu etapu

Jeden spójny build i celowane przypadki rzeczywistego Room/transportu/UI:
publiczne żądania bez sesji, niezgodny hash/rozmiar/identity,404 z zachowaniem
demo, Retry-After po restarcie, cancel/blokada w trakcie, atomowa aktywacja,
równoległy nowszy release, zachowanie dziennika/outbox i podgląd źródeł offline.
Bez seryjnego uruchamiania małych zestawów podczas pisania. Duży końcowy PR
dopiero po podłączeniu i odbiorze. Poniższy odbiór komponentu nie zastępuje
odbioru gotowej aplikacji na Room22.

## Checkpoint kompilacji portu

Dokładny core ec75df971ab264016977470595e3866c25cd8c8e został wypchnięty
po jednej compileValidationKotlin PASS186,547s/15executed; logSHA256
`da2cfa8e83fa195712fda7759fd266a479eda6b24831980439559e9bda0ff229`.
Nie wykonano wtedy testów i nie powstało APK. Późniejsze lokalne helpery
modeli urządzenia i osiem nowych przypadków nie są objęte tym wynikiem.

[O2 potwierdził własność root dopiero po opublikowaniu C](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6375008028).
O1 zachowuje istniejące pliki i użyje wąskiej delty na rzeczywistym C,
a nie podmiany ze starszego checkoutu. rememberDeviceNetworkModels przyjmuje
jawny activity ViewModelStoreOwner, dzięki czemu modele urządzenia nie są
kasowane przy zmianie właściciela dziennika. Schemat katalogu jest ładowany
leniwie w jego operacjach IO, a nie podczas tworzenia modeli na wątku UI.

## Odbiór niezależnego komponentu — 24.10.2026

Dokładne źródło723cd920ac796056570ad63acadbf2bd05cc724c:
build aplikacji/pakietu testowego i lint PASS408,968s;0error/fatal,6warning,
1info. LogSHA256 `e7bce1e07162053e5742b245aea06280c0d2ed45334f8db8c05a5aa357d2b8df`.
Osiem nowych native API35 **8/8PASS,0fail/skip**, czas instrumentacji35,444s,
logSHA256 `ceae0afc5535e5fb8ced41bcbdc3f6045cb7123762d5296005476311004d5db4`.
Pięć CatalogUpdateStorageTest, dwa NetworkPolicyStorageTest i jeden
CatalogUpdateScreenTest. Realne Room/DataStore/Settings, syntetyczny publiczny
transport: trwałość, źródła offline, hash/cancel, ABA, nowszy release,
trwały Retry-After, blokada socketu/flush oraz wyścig AppAuth token request.
NetworkAccessDenied jest IOException zgodnym z obsługą błędów Java AppAuth.

Odbiór korzystał z odrębnego pakietu komponentu na własnym AVD, przy braku
aktywnej sieci przed/po. Dotychczasowe APK i pliki dziennika zachowały sumy
SHA256; usunięto jedynie zweryfikowane syntetyczne pakiety po próbie.
Nie uruchamiano JVM lub starych zestawów. Próba nowego AVD zatrzymała się
przed testami na braku miejsca, a pierwszy setup wykrywania pakietu wymagał
obsługi pustej odpowiedzi pm/exit1; nie były to wyniki testów aplikacji.
To komponent sprzed C/Room22, **bez odbioru root/DI, HTTP live, E4 lub WF-05**.
589e3c9 zachowuje ten core i dodaje odebrane C; nowa integracja ma osobny odbiór.

## Odbiór podłączenia O1 na Room22 — 24.10.2026

Dokładne źródło **1a6f9dbb200a4dad584aee1cff1bae73fe53fdf0**:
assembleValidation + assembleValidationAndroidTest + lintValidation
**PASS1075,813s**,42taski wykonane/31up-to-date. Lint0error/fatal,
46warning/1info;38ostrzeżeń to dostępność nowszych wersji AGP/zależności,
pozostałe wskazówki naming/DataExtractionRules/KTX/TOML. Nie aktualizowano
przy tym zależności lub konfiguracji C. LogSHA256
`000376dd0fbf133483d763bbc9db79435cf412225a5cfa0dd36e076b5206fd55`.

**2/2 celowane native API35 PASS,0fail/skip**, instrumentacja54,016s,
logSHA256 `726ca28c5d00842074277f09001f7ccc574ef3754404980cee520bb40c8e2909`.
Pierwszy to nowy NetworkPolicyNavigationTest na rzeczywistym root C/Room22:
ustawienia i źródła, rotacja, nowa generacja gościa, skrót z konta,
nowy zapis banana w Room/outbox mimo blokady i zachowanie po odtworzeniu.
Drugi to tylko rozszerzony istniejący przypadek transportu, w tym close
odpowiedzi po ABA. Nie sumujemy go z wcześniejszym odbiorem jako nowego testu.
Pozostałych siedmiu przypadków komponentu ani JVM/A/B/C nie powtarzano.

Izolowane APK aplikacji22005636B/SHA256
`5c2e9c711582094d519fa71969ab09558cd969fb465ffbbf78dc31ca97380997`
i testów4223838B/SHA256
`52422b4d7f0dcd618038e471551f29854e51fab30bc19d114c388b47545e994c`
zostały faktycznie zainstalowane i porównane. Offline przed/po, oryginalne
APK/pliki DB niezmienione także przy cleanup. Usunięto jedynie zweryfikowane
pakiety syntetyczne; własny AVD zatrzymany bezwipe. To nie dostawa normalnego
skonfigurowanego APK użytkownika/O3, liveHTTP, E4 lub całego WF-05.
Konsument runtime i jego rzeczywiste wybudzenie nadal pozostają otwarte.

## Następna dostawa O2 — konsument polityki w runtime

O1: core/network, DataStore/provider, katalog, API/AppAuth i addytywne
MainActivity/CalorieApplication/ui/App/Settings; nie modyfikuje równolegle
SyncWork.kt, SyncCoordinator.kt lub SyncWorkPresentation.kt.
O2: te trzy pliki runtime, konieczne własne testy oraz aktualizacja swojego
SYNCHRONIZACJA_W_TLE.md. Bez nowej preferencji albo innego providera.
Wspólny dziennik nadal jest jedynym dziennikiem przekazania.

- Konsument przyjmuje NetworkAccessGate z core/network. O1 poda tę samą
  instancję co katalog/API/AppAuth w DI; domyślny brak konfiguracji ma być
  zamknięty. Unavailable oraz Blocked nie pozwalają uruchamiać transportu.
- Zmiana rewizji unieważnia rozpoczęty permit, również Allowed→Blocked→Allowed.
  Runtime ma anulować własną trwającą pracę i unieważnić zaplanowane wysyłki,
  zachowując outbox, request/body/hash/operation_id, lease/context i Retry-After.
  Nie wolno ACK lub wywołań token refresh tylko z powodu włączenia trybu.
- Ręczny start, worker, watch i zdarzenie kolejki sprawdzają ten sam gate.
  Brak sieci ma czytelny stan oczekiwania, bez pętli retry/pollingu transportu.
- Po nowym Allowed runtime wybudza właściwy bieżący lease/context i kontynuuje
  jeden istniejący PULL→PUSH→PULL, honorując trwały termin ponowienia. Stary
  sygnał konta nie może wybudzać innego konta; blokady login/reconciliation/
  storage nie znikają wskutek samego odblokowania sieci.
- Nie blokować czysto lokalnego odczytu/zapisu ani zastosowania zapisanego
  zatwierdzenia/kopii; bariera dotyczy pracy wymagającej sieci.
- Odbiór po całej delcie: trwała blokada po odtworzeniu procesu, zero wywołań
  executora we wszystkich wejściach, anulowanie/ABA, właściwy automatyczny
  powrót i Retry-After oraz zachowanie kolejki/dowodów. Nie powtarzać lokalnie
  odebranych A/B/C w całości bez materialnej potrzeby. Końcowy duży PR/CI
  obejmie zintegrowaną funkcję; brak osobnego małego PR na ten konsument.

O2 zwraca przypięty commit oraz rzeczywistą sygnaturę DI i wynik całej delty.
O1 integruje ją zwykłym merge na tej samej gałęzi dużego etapu.
