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
oraz gate; ich domyślne wartości są zamknięte. **Tego roboczego źródła nie
należy traktować jako gotowego APK przed rzeczywistym wpięciem DI**.

SettingsScreen przyjmuje opcjonalne CatalogUpdateViewModel oraz
NetworkPolicyViewModel. Root/DI/nawigacja nadal czekają na uzgodnienie
własności trzech plików z O2. O1 [podał dokładny nowy zakres i typy](https://github.com/Roseru/aplikacja-mobilna/pull/146#issuecomment-6374865798),
nie nadpisując MainActivity/CalorieApplication/App ani Workera C.
B/C kontynuują niezależnie. Pełny WF-05 wymaga wszystkich konsumentów:
katalogu, API, logowania i wspólnego runtime/workera, w tym wybudzenia po
odblokowaniu. Sam CONNECTED ani sama gotowa preferencja nie są jego odbiorem.

Właściwe DI ma tworzyć **jeden** DeviceNetworkPolicy i jedną fabrykę
połączeń dla aplikacji; oba modele ekranów żyją poza kluczem właściciela.
CatalogUpdateFactory.repository otrzymuje ten sam provider co API/AppAuth
oraz runtime, bez stałego `true` i bez osobnego przełącznika.
Kompilacja portu jest osobnym zakresem; nie zastępuje testu gotowej funkcji.

## Odbiór po ukończeniu etapu

Jeden spójny build i celowane przypadki rzeczywistego Room/transportu/UI:
publiczne żądania bez sesji, niezgodny hash/rozmiar/identity,404 z zachowaniem
demo, Retry-After po restarcie, cancel/blokada w trakcie, atomowa aktywacja,
równoległy nowszy release, zachowanie dziennika/outbox i podgląd źródeł offline.
Bez seryjnego uruchamiania małych zestawów podczas pisania. Duży końcowy PR
dopiero po podłączeniu i odbiorze; te scenariusze nie mają jeszcze wyniku PASS.
